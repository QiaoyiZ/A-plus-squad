import json
import unittest
from pathlib import Path

from src.module1_parser import parse_trade
from src.module2_upi_lookup import lookup_upi
from src.module3_compliance import (
    check_cftc_compliance,
    check_emir_compliance,
    validate_lei,
    validate_uti,
)


BASE_DIR = Path(__file__).resolve().parents[1]
DSB_ROOT = BASE_DIR / "data" / "product_definitions"


def fixed_float_trade(**overrides):
    trade = {
        "trade_id": "S300",
        "asset_class": "Rates",
        "instrument_type": "Swap",
        "use_case": "Fixed_Float",
        "execution_timestamp": "2026-07-01T10:30:00Z",
        "effective_date": "2026-07-03",
        "maturity_date": "2031-07-03",
        "notional_currency": "USD",
        "notional_amount": 40000000,
        "reference_rate": "USD-SOFR",
        "reference_rate_term_value": 3,
        "reference_rate_term_unit": "MNTH",
        "notional_schedule": "Constant",
        "delivery_type": "CASH",
        "reporting_counterparty_lei": "5493001KJTIIGC8Y1R12",
        "other_counterparty_lei": "1VUV7VQFKUOQSJ21A208",
        "uti": "5493001KJTIIGC8Y1R1220260701IRS00030",
        "action_type": "NEW",
        "cleared": False,
        "collateral_portfolio_code": "PORT-Z999",
        "initial_margin_posted": 0,
        "variation_margin_posted": 0,
    }
    trade.update(overrides)
    return trade


class Module3IdentifierValidationTests(unittest.TestCase):
    def test_valid_lei_passes(self):
        valid, message = validate_lei("5493001KJTIIGC8Y1R12")

        self.assertTrue(valid)
        self.assertEqual(message, "")

    def test_invalid_lei_check_digit_fails(self):
        valid, message = validate_lei("2138002TXD6KSZ3V5X27")

        self.assertFalse(valid)
        self.assertIn("check digits", message)

    def test_valid_uti_passes(self):
        valid, message = validate_uti(
            "5493001KJTIIGC8Y1R1220260701IRS00030",
            "5493001KJTIIGC8Y1R12",
        )

        self.assertTrue(valid)
        self.assertEqual(message, "")

    def test_invalid_uti_cases_fail(self):
        cases = [
            (None, "5493001KJTIIGC8Y1R12", "Missing"),
            (
                "5299000J2N45DDNE4Y2820260701IRS00030",
                "5493001KJTIIGC8Y1R12",
                "must equal",
            ),
            (
                "WRONGNAMESPACE123456720260701IRS00031",
                "5493001KJTIIGC8Y1R12",
                "namespace LEI",
            ),
            (
                "5493001KJTIIGC8Y1R12" + "A" * 33,
                "5493001KJTIIGC8Y1R12",
                "52",
            ),
            (
                "5493001KJTIIGC8Y1R1220260701irs00030",
                "5493001KJTIIGC8Y1R12",
                "suffix",
            ),
        ]

        for uti, reporting_lei, expected in cases:
            with self.subTest(uti=uti):
                valid, message = validate_uti(uti, reporting_lei)
                self.assertFalse(valid)
                self.assertIn(expected, message)


class Module3ComplianceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.portfolio = json.loads((BASE_DIR / "trades.json").read_text(encoding="utf-8"))

    def trade_by_id(self, trade_id):
        return next(trade for trade in self.portfolio if trade["trade_id"] == trade_id)

    def check_trade(self, trade, checker):
        parsed = parse_trade(trade)
        upi = lookup_upi(trade, DSB_ROOT)
        return checker(parsed, upi, trade)

    def test_cftc_event_contract_asymmetry(self):
        self.assertEqual(
            self.check_trade(self.trade_by_id("T026"), check_cftc_compliance)["status"],
            "CONDITIONAL",
        )
        self.assertEqual(
            self.check_trade(self.trade_by_id("T027"), check_cftc_compliance)["status"],
            "NOT_APPLICABLE",
        )
        self.assertEqual(
            self.check_trade(self.trade_by_id("T028"), check_cftc_compliance)["status"],
            "CONDITIONAL",
        )

    def test_emir_event_contracts_are_not_applicable(self):
        for trade_id in ("T026", "T027", "T028"):
            with self.subTest(trade_id=trade_id):
                result = self.check_trade(self.trade_by_id(trade_id), check_emir_compliance)
                self.assertEqual(result["status"], "NOT_APPLICABLE")
                self.assertFalse(result["reporting_required"])

    def test_conventional_trade_can_be_cftc_compliant(self):
        trade = fixed_float_trade()

        result = self.check_trade(trade, check_cftc_compliance)

        self.assertEqual(result["status"], "COMPLIANT")
        self.assertEqual(result["errors"], [])

    def test_emir_missing_collateral_and_margin_fields_fails(self):
        trade = fixed_float_trade(
            collateral_portfolio_code=None,
            initial_margin_posted=None,
            variation_margin_posted=None,
        )

        result = self.check_trade(trade, check_emir_compliance)

        self.assertEqual(result["status"], "NONCOMPLIANT")
        self.assertIn("collateral_portfolio_code", result["failed_fields"])
        self.assertIn("initial_margin_posted", result["failed_fields"])
        self.assertIn("variation_margin_posted", result["failed_fields"])

    def test_emir_accepts_zero_margin_values(self):
        trade = fixed_float_trade(
            collateral_portfolio_code="PORT-Z999",
            initial_margin_posted=0,
            variation_margin_posted=0,
        )

        result = self.check_trade(trade, check_emir_compliance)

        self.assertNotIn("initial_margin_posted", result["failed_fields"])
        self.assertNotIn("variation_margin_posted", result["failed_fields"])

    def test_upi_validation_failure_makes_conventional_trade_noncompliant(self):
        trade = fixed_float_trade(notional_currency="INVALID_CCY")

        result = self.check_trade(trade, check_cftc_compliance)

        self.assertEqual(result["status"], "NONCOMPLIANT")
        self.assertIn("upi", result["failed_fields"])


if __name__ == "__main__":
    unittest.main()
