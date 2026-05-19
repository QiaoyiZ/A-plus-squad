"""End-to-end pipeline snapshot for the four diagnostic trades.

T001 is a conventional Rates Fixed/Float swap with a real-looking but
invalid-check-digit other-counterparty LEI — it should match a UPI template
yet fail compliance.

T026, T027, T028 are the three event-contract trades that drive the
classification-frontier story:

  T026 — Kalshi / CFTC-regulated DCM political outcome.
  T027 — Polymarket / offshore decentralised platform.
  T028 — Kalshi / CFTC-regulated DCM regulatory decision outcome.

Per the homework specification the expected reporting statuses are:

  +--------+------------------------+--------------------+--------------------+
  | trade  | UPI                    | CFTC               | EMIR               |
  +========+========================+====================+====================+
  | T001   | FOUND                  | NONCOMPLIANT       | NONCOMPLIANT       |
  | T026   | NO_PRODUCT_DEFINITION  | CONDITIONAL        | NOT_APPLICABLE     |
  | T027   | NO_PRODUCT_DEFINITION  | NOT_APPLICABLE     | NOT_APPLICABLE     |
  | T028   | NO_PRODUCT_DEFINITION  | CONDITIONAL        | NOT_APPLICABLE     |
  +--------+------------------------+--------------------+--------------------+

This file pins those outcomes so any regression in Modules 1-3 is caught the
moment it is introduced.
"""

import json
import unittest
from pathlib import Path

from src.module1_parser import parse_trade
from src.module2_upi_lookup import lookup_upi
from src.module3_compliance import check_compliance


BASE_DIR = Path(__file__).resolve().parents[1]
DSB_ROOT = BASE_DIR / "data" / "product_definitions"
TRADES_PATH = BASE_DIR / "trades.json"
ADDITIONAL_TRADES_PATH = BASE_DIR / "additional_trades.json"


EXPECTED = {
    "T001": {
        "upi_status": "FOUND",
        "CFTC": "NONCOMPLIANT",
        "EMIR": "NONCOMPLIANT",
        "classification_flag": "CONVENTIONAL_DERIVATIVE",
    },
    "T026": {
        "upi_status": "NO_PRODUCT_DEFINITION",
        "CFTC": "CONDITIONAL",
        "EMIR": "NOT_APPLICABLE",
        "classification_flag": "NOVEL_INSTRUMENT_NO_TAXONOMY",
    },
    "T027": {
        "upi_status": "NO_PRODUCT_DEFINITION",
        "CFTC": "NOT_APPLICABLE",
        "EMIR": "NOT_APPLICABLE",
        "classification_flag": "NOVEL_INSTRUMENT_NO_TAXONOMY",
    },
    "T028": {
        "upi_status": "NO_PRODUCT_DEFINITION",
        "CFTC": "CONDITIONAL",
        "EMIR": "NOT_APPLICABLE",
        "classification_flag": "NOVEL_INSTRUMENT_NO_TAXONOMY",
    },
}


class PipelineSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        portfolio = json.loads(TRADES_PATH.read_text(encoding="utf-8"))
        cls.by_id = {trade["trade_id"]: trade for trade in portfolio}
        additional = json.loads(ADDITIONAL_TRADES_PATH.read_text(encoding="utf-8"))
        cls.additional_by_id = {trade["trade_id"]: trade for trade in additional}

    def _run_pipeline(self, trade):
        parsed = parse_trade(trade)
        upi = lookup_upi(trade, DSB_ROOT)
        compliance = check_compliance(parsed, upi, trade, "CFTC,EMIR")
        return parsed, upi, compliance

    def test_diagnostic_trades_match_expected_pipeline_outcome(self):
        for trade_id, expected in EXPECTED.items():
            with self.subTest(trade_id=trade_id):
                trade = self.by_id[trade_id]
                parsed, upi, compliance = self._run_pipeline(trade)

                self.assertEqual(
                    parsed["classification_flag"],
                    expected["classification_flag"],
                    f"{trade_id} classification flag drifted",
                )
                self.assertEqual(
                    upi["status"],
                    expected["upi_status"],
                    f"{trade_id} UPI status drifted",
                )
                self.assertEqual(
                    compliance["CFTC"]["status"],
                    expected["CFTC"],
                    f"{trade_id} CFTC verdict drifted",
                )
                self.assertEqual(
                    compliance["EMIR"]["status"],
                    expected["EMIR"],
                    f"{trade_id} EMIR verdict drifted",
                )

    def test_event_contracts_carry_classification_note(self):
        """T026-T028 must emit the spec-conformant classification_note text."""
        for trade_id in ("T026", "T027", "T028"):
            with self.subTest(trade_id=trade_id):
                _, upi, _ = self._run_pipeline(self.by_id[trade_id])
                self.assertIsNotNone(upi.get("classification_note"))
                self.assertIn("EventContract", upi["classification_note"])
                self.assertIn(
                    "ANNA-DSB",
                    upi["classification_note"],
                )

    def test_conventional_trade_has_null_classification_note(self):
        _, upi, _ = self._run_pipeline(self.by_id["T001"])
        self.assertIsNone(upi.get("classification_note"))

    def test_additional_trades_cover_required_design_cases(self):
        additional = self.additional_by_id

        self.assertEqual(len(additional), 5)
        asset_classes = {trade["asset_class"] for trade in additional.values()}
        self.assertGreaterEqual(
            asset_classes,
            {"EventContract", "Rates", "Credit", "FX"},
        )
        event_variants = [
            trade
            for trade in additional.values()
            if trade["asset_class"] == "EventContract"
        ]
        self.assertGreaterEqual(len(event_variants), 2)

        parsed_030, upi_030, _ = self._run_pipeline(additional["T030"])
        self.assertEqual(parsed_030["parse_status"], "PARTIAL")
        self.assertEqual(upi_030["status"], "NO_PRODUCT_DEFINITION")

        _, _, compliance_031 = self._run_pipeline(additional["T031"])
        self.assertEqual(compliance_031["CFTC"]["status"], "NONCOMPLIANT")
        self.assertIn(
            "uti",
            compliance_031["CFTC"]["failed_fields"],
        )

        _, _, compliance_032 = self._run_pipeline(additional["T032"])
        self.assertEqual(compliance_032["CFTC"]["status"], "COMPLIANT")
        self.assertEqual(compliance_032["EMIR"]["status"], "NONCOMPLIANT")
        self.assertIn(
            "initial_margin_posted",
            compliance_032["EMIR"]["failed_fields"],
        )

        _, _, compliance_033 = self._run_pipeline(additional["T033"])
        self.assertEqual(compliance_033["CFTC"]["status"], "COMPLIANT")
        self.assertEqual(compliance_033["EMIR"]["status"], "COMPLIANT")


if __name__ == "__main__":
    unittest.main()
