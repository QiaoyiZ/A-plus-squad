import unittest
from pathlib import Path

from src.module2_upi_lookup import lookup_portfolio, lookup_upi


DSB_ROOT = Path(__file__).resolve().parents[1] / "data" / "product_definitions"


class Module2UpiLookupTests(unittest.TestCase):
    def test_rates_fixed_float_template_matches(self):
        result = lookup_upi(
            {
                "trade_id": "S001",
                "asset_class": "Rates",
                "instrument_type": "Swap",
                "use_case": "Fixed_Float",
                "attributes": {
                    "NotionalCurrency": "USD",
                    "ReferenceRate": "USD-SOFR",
                    "ReferenceRateTermValue": 3,
                    "ReferenceRateTermUnit": "MNTH",
                    "NotionalSchedule": "Constant",
                    "DeliveryType": "CASH",
                },
            },
            DSB_ROOT,
        )

        self.assertEqual(result["status"], "FOUND")
        self.assertTrue(result["template_path"].endswith("Rates.Swap.Fixed_Float.UPI.V1.json"))
        self.assertEqual(result["errors"], [])

    def test_xau_is_valid_currency_for_fx_ndf(self):
        result = lookup_upi(
            {
                "trade_id": "S004",
                "asset_class": "FX",
                "instrument_type": "Forward",
                "use_case": "NDF",
                "attributes": {
                    "NotionalCurrency": "XAU",
                    "OtherNotionalCurrency": "USD",
                    "SettlementCurrency": "USD",
                },
            },
            DSB_ROOT,
        )

        self.assertEqual(result["status"], "FOUND")
        self.assertEqual(result["errors"], [])

    def test_invalid_currency_and_enum_fail_validation(self):
        result = lookup_upi(
            {
                "trade_id": "S003",
                "asset_class": "Rates",
                "instrument_type": "Swap",
                "use_case": "Fixed_Float",
                "attributes": {
                    "NotionalCurrency": "ZZZ",
                    "ReferenceRate": "USD-SOFR",
                    "ReferenceRateTermValue": 3,
                    "ReferenceRateTermUnit": "MONTH",
                    "NotionalSchedule": "Constant",
                    "DeliveryType": "CASH",
                },
            },
            DSB_ROOT,
        )

        self.assertEqual(result["status"], "INVALID_ATTRIBUTES")
        self.assertGreaterEqual(len(result["errors"]), 2)

    def test_libor_is_warning_not_error(self):
        result = lookup_upi(
            {
                "trade_id": "S002",
                "asset_class": "Rates",
                "instrument_type": "Swap",
                "use_case": "Fixed_Float",
                "attributes": {
                    "NotionalCurrency": "GBP",
                    "ReferenceRate": "GBP-LIBOR-BBA",
                    "ReferenceRateTermValue": 6,
                    "ReferenceRateTermUnit": "MNTH",
                    "NotionalSchedule": "Constant",
                    "DeliveryType": "CASH",
                },
            },
            DSB_ROOT,
        )

        self.assertEqual(result["status"], "FOUND")
        self.assertEqual(result["errors"], [])
        self.assertTrue(any("LIBOR" in warning for warning in result["warnings"]))

    def test_event_contracts_return_no_product_definition(self):
        for trade_id in ("T026", "T027", "T028"):
            result = lookup_upi(
                {
                    "trade_id": trade_id,
                    "asset_class": "Event",
                    "instrument_type": "EventContract",
                    "use_case": "Prediction_Market",
                    "platform": "Kalshi",
                },
                DSB_ROOT,
            )

            self.assertEqual(result["status"], "NO_PRODUCT_DEFINITION")
            self.assertIsNone(result["template_path"])
            self.assertIn("EventContract", result["explanation"])

    def test_missing_template_fails_gracefully(self):
        result = lookup_upi(
            {
                "trade_id": "S005",
                "asset_class": "Rates",
                "instrument_type": "Swap",
                "use_case": "Climate_Event_Swap",
                "attributes": {},
            },
            DSB_ROOT,
        )

        self.assertEqual(result["status"], "NOT_FOUND")
        self.assertEqual(result["errors"], [])

    def test_member1_parser_camel_case_fields_are_supported(self):
        result = lookup_upi(
            {
                "tradeId": "S006",
                "assetClass": "Rates",
                "instrumentType": "Swap",
                "useCase": "Fixed Float",
                "upiAttributes": {
                    "notionalCurrency": "USD",
                    "referenceRate": "USD-SOFR",
                    "referenceRateTermValue": 1,
                    "referenceRateTermUnit": "YEAR",
                    "notionalSchedule": "Constant",
                    "deliveryType": "PHYS",
                },
            },
            DSB_ROOT,
        )

        self.assertEqual(result["status"], "FOUND")
        self.assertEqual(result["trade_id"], "S006")

    def test_json_schema_flags_extra_attributes(self):
        result = lookup_upi(
            {
                "trade_id": "S007",
                "asset_class": "Rates",
                "instrument_type": "Swap",
                "use_case": "Fixed_Float",
                "attributes": {
                    "NotionalCurrency": "USD",
                    "ReferenceRate": "USD-SOFR",
                    "ReferenceRateTermValue": 3,
                    "ReferenceRateTermUnit": "MNTH",
                    "NotionalSchedule": "Constant",
                    "DeliveryType": "CASH",
                    "UnexpectedProductField": "not allowed by DSB template",
                },
            },
            DSB_ROOT,
        )

        self.assertEqual(result["status"], "INVALID_ATTRIBUTES")
        self.assertTrue(any("JSON Schema" in error for error in result["errors"]))

    def test_missing_classification_fields_return_bad_input(self):
        result = lookup_upi({"trade_id": "S008", "attributes": {}}, DSB_ROOT)

        self.assertEqual(result["status"], "BAD_INPUT")
        self.assertGreaterEqual(len(result["errors"]), 3)

    def test_portfolio_lookup_preserves_trade_count(self):
        trades = [
            {
                "trade_id": "S009",
                "asset_class": "Rates",
                "instrument_type": "Swap",
                "use_case": "Fixed_Float",
                "attributes": {
                    "NotionalCurrency": "USD",
                    "ReferenceRate": "USD-SOFR",
                    "ReferenceRateTermValue": 3,
                    "ReferenceRateTermUnit": "MNTH",
                    "NotionalSchedule": "Constant",
                    "DeliveryType": "CASH",
                },
            },
            {
                "trade_id": "T028",
                "asset_class": "Event",
                "instrument_type": "EventContract",
                "use_case": "ESMA_AI_Act_Decision",
            },
        ]

        results = lookup_portfolio(trades, DSB_ROOT)

        self.assertEqual(len(results), 2)
        self.assertEqual([result["trade_id"] for result in results], ["S009", "T028"])

    def test_event_contract_detected_by_platform_name_alone(self):
        result = lookup_upi(
            {
                "trade_id": "N005",
                "asset_class": "Credit",
                "instrument_type": "EventContract",
                "use_case": "Sovereign_Restructuring_Binary",
                "platform": "Kalshi",
            },
            DSB_ROOT,
        )

        self.assertEqual(result["status"], "NO_PRODUCT_DEFINITION")
        self.assertIsNone(result["template_path"])
        self.assertIn("EventContract", result["explanation"])

    def test_default_values_for_required_attributes_warn(self):
        """A trade missing required template attributes should still match,
        but with a single audit-trail warning naming the defaulted fields and
        a derived_fields entry per fill. Required attributes for
        Rates.Swap.Fixed_Float include NotionalSchedule and DeliveryType — this
        trade omits both."""

        result = lookup_upi(
            {
                "trade_id": "S100",
                "asset_class": "Rates",
                "instrument_type": "Swap",
                "use_case": "Fixed_Float",
                "attributes": {
                    "NotionalCurrency": "USD",
                    "ReferenceRate": "USD-SOFR",
                    "ReferenceRateTermValue": 3,
                    "ReferenceRateTermUnit": "MNTH",
                },
            },
            DSB_ROOT,
        )

        self.assertEqual(result["status"], "FOUND")
        self.assertEqual(result["errors"], [])

        defaulted_attrs = {
            entry["attribute"]
            for entry in result["derived_fields"]
            if entry["source"] == "default"
        }
        self.assertIn("NotionalSchedule", defaulted_attrs)
        self.assertIn("DeliveryType", defaulted_attrs)

        self.assertTrue(
            any(
                "default values for required template attributes" in warning
                for warning in result["warnings"]
            )
        )

    def test_audit_trail_records_aliased_reference_rate(self):
        """A trade using EUR-ESTR should auto-alias to EUR-EuroSTR and the
        change must appear in derived_fields with source='aliased:EUR-ESTR'."""

        result = lookup_upi(
            {
                "trade_id": "S101",
                "asset_class": "Rates",
                "instrument_type": "Swap",
                "use_case": "OIS",
                "attributes": {
                    "NotionalCurrency": "EUR",
                    "ReferenceRate": "EUR-ESTR",
                    "ReferenceRateTermValue": 1,
                    "ReferenceRateTermUnit": "DAYS",
                    "NotionalSchedule": "Constant",
                    "DeliveryType": "CASH",
                },
            },
            DSB_ROOT,
        )

        aliased = [
            entry for entry in result["derived_fields"]
            if entry["source"] == "aliased:EUR-ESTR"
        ]
        self.assertTrue(
            aliased,
            "Expected at least one derived_fields entry with source 'aliased:EUR-ESTR', "
            f"got {result['derived_fields']!r}",
        )


if __name__ == "__main__":
    unittest.main()
