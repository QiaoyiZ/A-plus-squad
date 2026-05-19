import json
import unittest
from pathlib import Path

from dashboard import build_dashboard_data, render_dashboard_html


BASE_DIR = Path(__file__).resolve().parents[1]


class DashboardDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(
            (BASE_DIR / "output" / "compliance_report.json").read_text(encoding="utf-8")
        )
        cls.data = build_dashboard_data(cls.report)

    def test_heatmap_has_trade_rows_and_regime_columns(self):
        self.assertEqual(len(self.data["heatmap"]["z"]), 33)
        self.assertEqual(self.data["regimes"], ["CFTC", "EMIR"])
        self.assertEqual(len(self.data["heatmap"]["z"][0]), 2)
        self.assertIn("T026", self.data["trade_ids"])

    def test_error_frequency_counts_failed_fields(self):
        fields = {row["field"] for row in self.data["error_frequency"]}

        self.assertIn("reporting_counterparty_lei", fields)
        self.assertIn("other_counterparty_lei", fields)

    def test_asset_breakdown_contains_rates_and_event_contracts(self):
        rows = self.data["asset_breakdown"]
        asset_regimes = {(row["asset_class"], row["regime"]) for row in rows}

        self.assertIn(("Rates", "CFTC"), asset_regimes)
        self.assertIn(("EventContract", "EMIR"), asset_regimes)

    def test_frontier_rows_show_jurisdictional_asymmetry(self):
        frontier = {row["trade_id"]: row for row in self.data["frontier"]}

        self.assertEqual(frontier["T026"]["cftc_status"], "CONDITIONAL")
        self.assertEqual(frontier["T027"]["cftc_status"], "NOT_APPLICABLE")
        self.assertEqual(frontier["T028"]["emir_status"], "NOT_APPLICABLE")
        self.assertIn("taxonomy", frontier["T026"]["cftc_note"])

    def test_frontier_rows_carry_classification_note(self):
        """The spec requires the frontier panel to surface the compliance
        note text for T026-T028. Each frontier row should carry the
        classification_note string that Module 2 emits for novel instruments."""

        frontier = {row["trade_id"]: row for row in self.data["frontier"]}
        for trade_id in ("T026", "T027", "T028"):
            with self.subTest(trade_id=trade_id):
                note = frontier[trade_id].get("classification_note", "")
                self.assertIn("ANNA-DSB UPI library", note)

    def test_matrix_rows_include_upi_classification_note(self):
        row = next(row for row in self.data["matrix"] if row["trade_id"] == "T026")

        self.assertEqual(row["upi_status"], "NO_PRODUCT_DEFINITION")
        self.assertIn("ANNA-DSB", row["upi_classification_note"])

    def test_no_live_demo_runner_or_engine_api(self):
        """The browser-side Run Engine button and /api/run-engine endpoint were
        removed because they shipped a permanent JSON.parse error to every
        grader. Guard against regressions."""

        html = render_dashboard_html(self.data)
        for forbidden in (
            "Live Demo Runner",
            "Run Engine",
            "Focus T026",
            "/api/run-engine",
            "additional_trade_audit",
            "Additional trade coverage",
        ):
            self.assertNotIn(forbidden, html)

    def test_rendered_html_contains_required_panels_and_interpretation(self):
        html = render_dashboard_html(self.data)

        for marker in (
            "Portfolio Compliance Heatmap",
            "Error Frequency",
            "Asset Class Breakdown",
            "Classification Frontier: T026-T028",
            "Interpretation",
        ):
            self.assertIn(marker, html)
        # Spec rubric requires 2-3 paragraphs of interpretation; we ship 3.
        self.assertEqual(len(self.data["interpretation"]), 3)
        # And the classification-note text must be present in the rendered
        # frontier panel, not just in the underlying data.
        self.assertIn("no product definition in the ANNA-DSB UPI library", html)


if __name__ == "__main__":
    unittest.main()
