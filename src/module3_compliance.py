"""Module 3: multi-jurisdictional reporting compliance checks.

The checker consumes Module 1 parser output plus Module 2 UPI lookup output and
returns per-regime reporting statuses for CFTC and EMIR Refit.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.module1_parser import validate_date, validate_timestamp


BASE_DIR = Path(__file__).resolve().parents[1]
CURRENCY_CODESET = (
    BASE_DIR
    / "data"
    / "product_definitions"
    / "PROD"
    / "OTC-Products"
    / "codesets"
    / "ISOCurrencyCode.json"
)

UPI_SUCCESS_STATUSES = {"FOUND"}
EVENT_CLASSIFICATION = "NOVEL_INSTRUMENT_NO_TAXONOMY"
ACTION_TYPES = {
    "NEW",
    "MODIFY",
    "CORRECT",
    "CANCEL",
    "TERMINATE",
    "VALUATION",
    "POSITION",
    "ERROR",
    "REVIVE",
}


def compute_lei_check_digits(lei_body: str) -> str:
    """Compute ISO 7064 MOD 97-10 check digits for the first 18 LEI chars."""

    if not isinstance(lei_body, str) or not re.fullmatch(r"[A-Z0-9]{18}", lei_body):
        raise ValueError("LEI body must be 18 uppercase alphanumeric characters.")

    verification_number = "".join(_lei_char_to_number(char) for char in lei_body) + "00"
    return f"{98 - (int(verification_number) % 97):02d}"


def validate_lei(lei: str | None) -> tuple[bool, str]:
    """Validate LEI syntax and ISO 7064 MOD 97-10 check digits."""

    if _is_missing(lei):
        return False, "Missing LEI."
    if not isinstance(lei, str):
        return False, "LEI must be a string."

    value = lei.strip()
    if len(value) != 20:
        return False, "LEI must be exactly 20 characters."
    if not re.fullmatch(r"[A-Z0-9]{18}[0-9]{2}", value):
        return (
            False,
            "LEI must contain 18 uppercase alphanumeric characters followed by two digits.",
        )

    expected = compute_lei_check_digits(value[:18])
    actual = value[18:]
    if expected != actual:
        return False, f"Invalid LEI check digits: expected {expected}, got {actual}."

    return True, ""


def validate_uti(uti: str | None, reporting_lei: str | None) -> tuple[bool, str]:
    """Validate UTI format and namespace against the reporting counterparty LEI."""

    if _is_missing(uti):
        return False, "Missing UTI."
    if not isinstance(uti, str):
        return False, "UTI must be a string."

    value = uti.strip()
    if len(value) > 52:
        return False, "UTI must not exceed 52 characters."
    if len(value) < 21:
        return False, "UTI must contain a 20-character namespace LEI and a suffix."

    namespace = value[:20]
    suffix = value[20:]
    namespace_ok, namespace_error = validate_lei(namespace)
    if not namespace_ok:
        return False, f"UTI namespace LEI is invalid: {namespace_error}"

    if _is_missing(reporting_lei):
        return False, "Cannot compare UTI namespace because reporting counterparty LEI is missing."
    if namespace != str(reporting_lei).strip():
        return False, "UTI namespace LEI must equal reporting counterparty LEI."

    if not re.fullmatch(r"[A-Z0-9-]{1,32}", suffix):
        return False, "UTI suffix must be 1 to 32 uppercase letters, digits, or hyphens."

    return True, ""


def check_compliance(
    parsed_trade: Mapping[str, Any],
    upi_result: Mapping[str, Any],
    raw_trade: Mapping[str, Any],
    regimes: str | Iterable[str],
) -> dict[str, dict[str, Any]]:
    """Return per-regime compliance results for the requested regimes."""

    results: dict[str, dict[str, Any]] = {}
    for regime in _normalize_regimes(regimes):
        if regime == "CFTC":
            results[regime] = check_cftc_compliance(parsed_trade, upi_result, raw_trade)
        elif regime in {"EMIR", "EMIR_REFIT"}:
            results["EMIR"] = check_emir_compliance(parsed_trade, upi_result, raw_trade)
        else:
            results[regime] = _result(
                status="NOT_APPLICABLE",
                reporting_required=False,
                note=f"Regime {regime} is not implemented by Module 3.",
            )
    return results


def check_cftc_compliance(
    parsed_trade: Mapping[str, Any],
    upi_result: Mapping[str, Any],
    raw_trade: Mapping[str, Any],
) -> dict[str, Any]:
    """Check CFTC reporting requirements for one trade."""

    if _is_event_contract(parsed_trade, raw_trade):
        if _is_cftc_dcm_event_contract(raw_trade):
            return _result(
                status="CONDITIONAL",
                reporting_required=True,
                warnings=[
                    "upi: Event contract may be reportable on a CFTC-regulated DCM, "
                    "but no ANNA-DSB UPI product definition exists."
                ],
                note=(
                    "Kalshi/CFTC DCM event contract. Reporting may apply, but the "
                    "current UPI taxonomy does not support binary event contracts."
                ),
            )
        return _result(
            status="NOT_APPLICABLE",
            reporting_required=False,
            note=(
                "Event contract is not executed on a CFTC-regulated DCM; Module 3 "
                "treats it as outside CFTC OTC reporting scope."
            ),
        )

    return _check_conventional_trade(
        parsed_trade=parsed_trade,
        upi_result=upi_result,
        raw_trade=raw_trade,
        regime="CFTC",
        require_emir_margin_fields=False,
    )


def check_emir_compliance(
    parsed_trade: Mapping[str, Any],
    upi_result: Mapping[str, Any],
    raw_trade: Mapping[str, Any],
) -> dict[str, Any]:
    """Check EMIR Refit reporting requirements for one trade."""

    if _is_event_contract(parsed_trade, raw_trade):
        return _result(
            status="NOT_APPLICABLE",
            reporting_required=False,
            note=(
                "Event contracts are treated as outside EMIR OTC derivative reporting "
                "scope under the gambling/outside-taxonomy classification used here."
            ),
        )

    return _check_conventional_trade(
        parsed_trade=parsed_trade,
        upi_result=upi_result,
        raw_trade=raw_trade,
        regime="EMIR",
        require_emir_margin_fields=True,
    )


def _check_conventional_trade(
    *,
    parsed_trade: Mapping[str, Any],
    upi_result: Mapping[str, Any],
    raw_trade: Mapping[str, Any],
    regime: str,
    require_emir_margin_fields: bool,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    failed_fields: list[str] = []

    def add_error(field: str, message: str) -> None:
        errors.append(f"{field}: {message}")
        _append_unique(failed_fields, field)

    def add_warning(field: str, message: str) -> None:
        warnings.append(f"{field}: {message}")

    _validate_upi_requirement(upi_result, add_error, add_warning)
    _validate_counterparty_leis(raw_trade, add_error)
    _validate_uti_requirement(raw_trade, add_error)
    _validate_time_fields(raw_trade, add_error)
    _validate_currency(raw_trade, add_error)
    _validate_notional_amount(raw_trade, add_error)
    _validate_action_type(raw_trade, add_error)
    _validate_cleared_indicator(raw_trade, add_error)

    if parsed_trade.get("parse_status") == "FAILED":
        add_error("parse_status", "Parser failed for this trade.")

    if require_emir_margin_fields:
        _validate_emir_margin_fields(raw_trade, add_error)

    status = "NONCOMPLIANT" if errors else "COMPLIANT"
    if errors:
        note = f"{regime} reporting required; validation found {len(errors)} issue(s)."
    else:
        note = f"{regime} reporting requirements satisfied for this conventional derivative."

    return _result(
        status=status,
        reporting_required=True,
        errors=errors,
        warnings=warnings,
        failed_fields=failed_fields,
        note=note,
    )


def _validate_upi_requirement(upi_result: Mapping[str, Any], add_error, add_warning) -> None:
    status = upi_result.get("status")
    for warning in upi_result.get("warnings", []) or []:
        add_warning("upi", str(warning))

    if status in UPI_SUCCESS_STATUSES:
        return

    details = "; ".join(str(error) for error in upi_result.get("errors", []) or [])
    if not details:
        details = str(upi_result.get("explanation") or "UPI lookup did not produce a reportable product match.")
    add_error("upi", f"UPI lookup status {status}; {details}")


def _validate_counterparty_leis(raw_trade: Mapping[str, Any], add_error) -> None:
    for field in ("reporting_counterparty_lei", "other_counterparty_lei"):
        value = raw_trade.get(field)
        ok, message = validate_lei(value)
        if not ok:
            add_error(field, message)


def _validate_uti_requirement(raw_trade: Mapping[str, Any], add_error) -> None:
    ok, message = validate_uti(raw_trade.get("uti"), raw_trade.get("reporting_counterparty_lei"))
    if not ok:
        add_error("uti", message)


def _validate_time_fields(raw_trade: Mapping[str, Any], add_error) -> None:
    timestamp_status = validate_timestamp(raw_trade.get("execution_timestamp"))
    if timestamp_status != "OK":
        add_error(
            "execution_timestamp",
            _format_status_error(timestamp_status, "ISO 8601 UTC timestamp"),
        )

    for field in ("effective_date", "maturity_date"):
        date_status = validate_date(raw_trade.get(field))
        if date_status != "OK":
            add_error(field, _format_status_error(date_status, "YYYY-MM-DD date"))


def _validate_currency(raw_trade: Mapping[str, Any], add_error) -> None:
    currency = raw_trade.get("notional_currency")
    if _is_missing(currency):
        add_error("notional_currency", "Missing required notional currency.")
        return
    if not isinstance(currency, str):
        add_error("notional_currency", "Notional currency must be a string.")
        return
    if currency.strip().upper() not in _currency_codes():
        add_error("notional_currency", f"{currency!r} is not an ISO 4217 currency code.")


def _validate_notional_amount(raw_trade: Mapping[str, Any], add_error) -> None:
    value = raw_trade.get("notional_amount")
    if _is_missing(value):
        add_error("notional_amount", "Missing required notional amount.")
        return
    if not _is_number(value):
        add_error("notional_amount", "Notional amount must be numeric.")
        return
    if float(value) <= 0:
        add_error("notional_amount", "Notional amount must be positive.")


def _validate_action_type(raw_trade: Mapping[str, Any], add_error) -> None:
    value = raw_trade.get("action_type")
    if _is_missing(value):
        add_error("action_type", "Missing required action type.")
        return
    if not isinstance(value, str) or value.strip().upper() not in ACTION_TYPES:
        add_error("action_type", f"Unsupported action type {value!r}.")


def _validate_cleared_indicator(raw_trade: Mapping[str, Any], add_error) -> None:
    value = raw_trade.get("cleared")
    if _is_missing(value):
        add_error("cleared", "Missing required cleared indicator.")
    elif not isinstance(value, bool):
        add_error("cleared", "Cleared indicator must be boolean.")


def _validate_emir_margin_fields(raw_trade: Mapping[str, Any], add_error) -> None:
    if _is_missing(raw_trade.get("collateral_portfolio_code")):
        add_error("collateral_portfolio_code", "Missing required EMIR collateral portfolio code.")

    for field in ("initial_margin_posted", "variation_margin_posted"):
        value = raw_trade.get(field)
        if _is_missing(value):
            add_error(field, f"Missing required EMIR {field.replace('_', ' ')}.")
        elif not _is_number(value):
            add_error(field, f"{field.replace('_', ' ').title()} must be numeric.")


def _is_event_contract(
    parsed_trade: Mapping[str, Any],
    raw_trade: Mapping[str, Any],
) -> bool:
    if parsed_trade.get("classification_flag") == EVENT_CLASSIFICATION:
        return True
    asset_class = str(raw_trade.get("asset_class", "")).lower()
    instrument_type = str(raw_trade.get("instrument_type", "")).lower()
    return asset_class == "eventcontract" or "eventcontract" in instrument_type


CFTC_DCM_PLATFORM_NAMES = {"kalshi", "kalshiex", "kalshi inc", "kalshi llc"}
CFTC_DCM_PLATFORM_TYPES = {"CFTC_REGULATED_DCM", "CFTC_DCM", "DCM"}


def _is_cftc_dcm_event_contract(raw_trade: Mapping[str, Any]) -> bool:
    """Identify event contracts traded on a CFTC-regulated Designated Contract Market.

    The structural signal is `platform_type` (e.g. "CFTC_REGULATED_DCM"). The
    `platform` name is used as a fallback for trade records that only carry the
    venue name. Comparisons are case- and whitespace-insensitive so a Kalshi
    trade is recognised whether the source data writes "Kalshi", "KALSHI", or
    " kalshi ".
    """

    platform = str(raw_trade.get("platform", "")).strip().lower()
    platform_type = str(raw_trade.get("platform_type", "")).strip().upper()
    if platform_type in CFTC_DCM_PLATFORM_TYPES:
        return True
    return platform in CFTC_DCM_PLATFORM_NAMES


def _result(
    *,
    status: str,
    reporting_required: bool,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
    failed_fields: list[str] | None = None,
    note: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "reporting_required": reporting_required,
        "errors": errors or [],
        "warnings": warnings or [],
        "failed_fields": failed_fields or [],
        "note": note,
    }


def _normalize_regimes(regimes: str | Iterable[str]) -> list[str]:
    if isinstance(regimes, str):
        raw_regimes = regimes.split(",")
    else:
        raw_regimes = list(regimes)
    return [str(regime).strip().upper() for regime in raw_regimes if str(regime).strip()]


def _format_status_error(status: str, expected: str) -> str:
    if status == "MISSING":
        return f"Missing required {expected}."
    if status == "PARTIAL":
        return f"Partial value; expected {expected}."
    return f"Invalid value; expected {expected}."


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value.strip())
            return True
        except ValueError:
            return False
    return False


def _lei_char_to_number(char: str) -> str:
    if char.isdigit():
        return char
    return str(ord(char) - ord("A") + 10)


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


@lru_cache(maxsize=1)
def _currency_codes() -> set[str]:
    with CURRENCY_CODESET.open("r", encoding="utf-8") as file:
        codeset = json.load(file)
    return {str(value).upper() for value in codeset.get("enum", [])}
