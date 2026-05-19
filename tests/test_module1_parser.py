"""Stress tests for the Module 1 trade parser.

These tests exercise the error paths that the rest of the suite assumes work:
missing fields, wrong types, malformed dates, unknown asset classes, garbage
payloads. The parser is required to produce one output record per input row
and never to raise.
"""

import unittest

from src.module1_parser import (
    classify_instrument,
    parse_trade,
    parse_trades,
    validate_date,
    validate_timestamp,
)


def conventional_trade(**overrides):
    trade = {
        "trade_id": "T999",
        "asset_class": "Rates",
        "instrument_type": "Swap",
        "use_case": "Fixed_Float",
        "execution_timestamp": "2026-07-01T10:30:00Z",
        "effective_date": "2026-07-03",
        "maturity_date": "2031-07-03",
        "notional_currency": "USD",
        "notional_amount": 10_000_000,
        "reporting_counterparty_lei": "5493001KJTIIGC8Y1R12",
        "other_counterparty_lei": "1VUV7VQFKUOQSJ21A208",
        "uti": "5493001KJTIIGC8Y1R1220260701IRS00099",
    }
    trade.update(overrides)
    return trade


class ClassifyInstrumentTests(unittest.TestCase):
    def test_conventional_asset_class_is_conventional(self):
        self.assertEqual(
            classify_instrument("S001", "Rates", "Swap"),
            "CONVENTIONAL_DERIVATIVE",
        )

    def test_event_contract_asset_class_is_novel(self):
        self.assertEqual(
            classify_instrument("S002", "EventContract", "BinaryEventContract"),
            "NOVEL_INSTRUMENT_NO_TAXONOMY",
        )

    def test_hardcoded_event_trade_ids_are_novel_even_without_event_asset_class(self):
        for trade_id in ("T026", "T027", "T028"):
            with self.subTest(trade_id=trade_id):
                self.assertEqual(
                    classify_instrument(trade_id, None, None),
                    "NOVEL_INSTRUMENT_NO_TAXONOMY",
                )

    def test_missing_asset_class_is_ambiguous(self):
        self.assertEqual(
            classify_instrument("S003", None, "Swap"),
            "CLASSIFICATION_AMBIGUOUS",
        )

    def test_unknown_asset_class_is_ambiguous(self):
        self.assertEqual(
            classify_instrument("S004", "QuantumWeather", "Swap"),
            "CLASSIFICATION_AMBIGUOUS",
        )


class ParseTradeStressTests(unittest.TestCase):
    def test_clean_trade_is_success(self):
        result = parse_trade(conventional_trade())

        self.assertEqual(result["parse_status"], "SUCCESS")
        self.assertEqual(result["classification_flag"], "CONVENTIONAL_DERIVATIVE")
        self.assertEqual(result["parse_errors"], [])

    def test_missing_top_level_fields_become_partial_with_errors(self):
        result = parse_trade({"trade_id": "T_NOFIELDS"})

        self.assertEqual(result["parse_status"], "PARTIAL")
        self.assertIn("Missing asset_class", result["parse_errors"])
        self.assertIn("Missing instrument_type", result["parse_errors"])
        self.assertIn("Missing use_case", result["parse_errors"])
        self.assertIn("Missing execution_timestamp", result["parse_errors"])
        self.assertEqual(result["classification_flag"], "CLASSIFICATION_AMBIGUOUS")

    def test_unknown_asset_class_is_classification_ambiguous(self):
        result = parse_trade(
            conventional_trade(asset_class="QuantumWeather", trade_id="T_UNK")
        )

        self.assertEqual(result["classification_flag"], "CLASSIFICATION_AMBIGUOUS")
        # Still a valid row — clean fields elsewhere keep parse_status SUCCESS.
        self.assertEqual(result["parse_status"], "SUCCESS")

    def test_garbage_timestamp_is_invalid(self):
        result = parse_trade(
            conventional_trade(execution_timestamp="not-a-timestamp")
        )

        self.assertEqual(result["parse_status"], "PARTIAL")
        self.assertIn(
            "Invalid execution_timestamp format",
            result["parse_errors"],
        )

    def test_date_only_timestamp_is_partial(self):
        result = parse_trade(conventional_trade(execution_timestamp="2026-07-01"))

        self.assertEqual(result["parse_status"], "PARTIAL")
        self.assertTrue(
            any("date-only" in error for error in result["parse_errors"])
        )

    def test_malformed_maturity_date_is_partial(self):
        result = parse_trade(conventional_trade(maturity_date="9999-99-99"))

        self.assertEqual(result["parse_status"], "PARTIAL")
        self.assertIn("Invalid maturity_date format", result["parse_errors"])

    def test_event_contract_trade_classifies_as_novel(self):
        result = parse_trade(
            conventional_trade(
                trade_id="T026",
                asset_class="EventContract",
                instrument_type="BinaryEventContract",
                use_case="PoliticalOutcome",
            )
        )

        self.assertEqual(result["classification_flag"], "NOVEL_INSTRUMENT_NO_TAXONOMY")

    def test_non_string_timestamp_is_invalid(self):
        self.assertEqual(validate_timestamp(12345), "INVALID")
        self.assertEqual(validate_timestamp(None), "MISSING")

    def test_non_string_date_is_invalid(self):
        self.assertEqual(validate_date(20260701), "INVALID")
        self.assertEqual(validate_date(None), "MISSING")


class ParseTradesBulkResilienceTests(unittest.TestCase):
    def test_parse_trades_emits_one_record_per_input_even_for_garbage(self):
        raw_trades = [
            conventional_trade(trade_id="T_SUCCESS"),
            {"trade_id": "T_MISSING_FIELDS"},
            None,                                       # garbage row
            "not a dict at all",                        # garbage row
            {"trade_id": "T_UNK_ASSET", "asset_class": "QuantumWeather"},
        ]

        results = parse_trades(raw_trades)

        self.assertEqual(len(results), len(raw_trades))

        statuses = [r["parse_status"] for r in results]
        # First row is clean.
        self.assertEqual(statuses[0], "SUCCESS")
        # The two garbage rows (None and a bare string) must come back as FAILED.
        self.assertEqual(statuses[2], "FAILED")
        self.assertEqual(statuses[3], "FAILED")

        for row in results:
            if row["parse_status"] == "FAILED":
                self.assertEqual(row["classification_flag"], "CLASSIFICATION_AMBIGUOUS")
                self.assertEqual(row["trade_id"], "UNKNOWN")

    def test_parse_trades_handles_empty_list(self):
        self.assertEqual(parse_trades([]), [])


if __name__ == "__main__":
    unittest.main()
