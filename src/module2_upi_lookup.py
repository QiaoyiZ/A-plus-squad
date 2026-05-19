"""Module 2: ANNA-DSB UPI product lookup and attribute validation.

This module is intentionally parser-friendly: it accepts common trade field
spellings from JSON records and returns a stable dictionary that Module 1 and
Module 3 can consume.
"""

from __future__ import annotations

import argparse
import json
import re
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional quality enhancement
    jsonschema = None


EVENT_CONTRACT_TRADE_IDS = {"T026", "T027", "T028"}
EVENT_CONTRACT_EXPLANATION = (
    "EventContract / prediction market contracts are outside the current "
    "ANNA-DSB OTC product taxonomy. The DSB UPI library covers conventional "
    "Rates, Credit, Foreign_Exchange, Equity, Commodities, and Other OTC "
    "templates, but it does not provide an EventContract template for binary "
    "political, macro, or regulatory outcomes."
)
EVENT_CONTRACT_CLASSIFICATION_NOTE = (
    "Instrument type 'BinaryEventContract' under asset class 'EventContract' has "
    "no product definition in the ANNA-DSB UPI library. This reflects the current "
    "regulatory classification of prediction and event contracts as outside the "
    "OTC derivatives taxonomy in most jurisdictions. Refer to Module 4 for "
    "classification analysis."
)

ASSET_CLASS_ALIASES = {
    "rate": "Rates",
    "rates": "Rates",
    "interestrate": "Rates",
    "interest_rates": "Rates",
    "ir": "Rates",
    "credit": "Credit",
    "fx": "Foreign_Exchange",
    "forex": "Foreign_Exchange",
    "foreignexchange": "Foreign_Exchange",
    "foreign_exchange": "Foreign_Exchange",
    "equity": "Equity",
    "equities": "Equity",
    "commodity": "Commodities",
    "commodities": "Commodities",
    "other": "Other",
}

INSTRUMENT_TYPE_ALIASES = {
    "swap": "Swap",
    "swaps": "Swap",
    "option": "Option",
    "options": "Option",
    "forward": "Forward",
    "forwards": "Forward",
    "future": "Forward",
    "futures": "Forward",
    "fra": "Forward",
    "capfloor": "Option",
    "cap_floor": "Option",
    "other": "Other",
}

FIELD_ALIASES = {
    "trade_id": ["trade_id", "tradeId", "tradeID", "id", "TradeID"],
    "asset_class": ["asset_class", "assetClass", "AssetClass", "asset"],
    "instrument_type": [
        "instrument_type",
        "instrumentType",
        "InstrumentType",
        "product_type",
        "productType",
    ],
    "use_case": ["use_case", "useCase", "UseCase", "product", "product_name"],
    "attributes": [
        "attributes",
        "Attributes",
        "upi_attributes",
        "upiAttributes",
        "product_attributes",
        "productAttributes",
    ],
}

ATTRIBUTE_ALIASES = {
    "NotionalCurrency": [
        "notional_currency",
        "notionalCurrency",
        "notional_currency_leg1",
        "notionalCurrencyLeg1",
        "currency",
        "notional_ccy",
        "notionalCcy",
    ],
    "OtherNotionalCurrency": [
        "other_notional_currency",
        "otherNotionalCurrency",
        "notional_currency_leg2",
        "notionalCurrencyLeg2",
        "currency_2",
        "other_currency",
    ],
    "SettlementCurrency": [
        "settlement_currency",
        "settlementCurrency",
        "settlement_ccy",
    ],
    "ReferenceRate": [
        "reference_rate",
        "referenceRate",
        "reference_rate_leg1",
        "referenceRateLeg1",
        "floating_rate",
        "index",
    ],
    "ReferenceRateTermValue": [
        "reference_rate_term_value",
        "referenceRateTermValue",
        "reference_rate_term_leg1_value",
        "referenceRateTermLeg1Value",
        "tenor_value",
    ],
    "ReferenceRateTermUnit": [
        "reference_rate_term_unit",
        "referenceRateTermUnit",
        "reference_rate_term_leg1_unit",
        "referenceRateTermLeg1Unit",
        "tenor_unit",
    ],
    "OtherLegReferenceRate": [
        "other_leg_reference_rate",
        "otherLegReferenceRate",
        "reference_rate_leg2",
        "referenceRateLeg2",
    ],
    "OtherLegReferenceRateTermValue": [
        "other_leg_reference_rate_term_value",
        "otherLegReferenceRateTermValue",
        "reference_rate_term_leg2_value",
        "referenceRateTermLeg2Value",
    ],
    "OtherLegReferenceRateTermUnit": [
        "other_leg_reference_rate_term_unit",
        "otherLegReferenceRateTermUnit",
        "reference_rate_term_leg2_unit",
        "referenceRateTermLeg2Unit",
    ],
    "NotionalSchedule": ["notional_schedule", "notionalSchedule"],
    "DeliveryType": ["delivery_type", "deliveryType", "settlement_type"],
    "DebtSeniority": ["debt_seniority", "debtSeniority"],
    "OptionType": ["option_type", "optionType"],
    "UnderlyingInstrumentISIN": ["underlying_isin", "underlyingIsin"],
    "UnderlyingInstrumentIndex": [
        "underlying_index",
        "underlyingIndex",
        "index_name",
        "indexName",
    ],
    "UnderlyingInstrumentIndexTermValue": [
        "underlying_tenor_value",
        "underlyingTenorValue",
        "reference_rate_term_value",
    ],
    "UnderlyingInstrumentIndexTermUnit": [
        "underlying_tenor_unit",
        "underlyingTenorUnit",
        "reference_rate_term_unit",
    ],
}


def lookup_upi(trade: Mapping[str, Any], dsb_root: str | Path) -> dict[str, Any]:
    """Look up and validate the DSB UPI template for one trade.

    Args:
        trade: Parsed trade record. Expected classification fields are
            asset_class, instrument_type, and use_case, but common camel-case
            variants are accepted.
        dsb_root: Either the product_definitions root, the PROD root, or the
            OTC-Products root.

    Returns:
        A stable result dictionary:
        {
          "trade_id": "...",
          "status": "...",
          "template_path": "...",
          "matched_template": "...",
          "warnings": [...],
          "errors": [...],
          "explanation": "...",
          "classification_note": "...",  # populated only for NO_PRODUCT_DEFINITION
                                          # on novel instruments (T026-T028);
                                          # null for conventional derivatives.
          "derived_fields": [
            {"attribute": "...", "value": ..., "source": "default" |
             "inferred:<raw_field>" | "aliased:<original>" | "dropped"}
          ]
        }

        ``derived_fields`` is the audit trail for every value the engine
        inferred, defaulted, aliased, or removed during attribute enrichment.
        When the engine had to invent values for a *required* template
        attribute that the trade did not supply, a single summary warning is
        added to ``warnings``. The status remains ``FOUND`` because the product
        definition is still identified; the warning carries the data-quality
        caveat.
    """

    trade_id = _string_or_none(_get_field(trade, FIELD_ALIASES["trade_id"]))
    warnings: list[str] = []
    errors: list[str] = []

    raw_asset_class = _string_or_none(_get_field(trade, FIELD_ALIASES["asset_class"]))
    raw_instrument_type = _string_or_none(
        _get_field(trade, FIELD_ALIASES["instrument_type"])
    )
    raw_use_case = _string_or_none(_get_field(trade, FIELD_ALIASES["use_case"]))

    if _is_event_contract(trade, trade_id, raw_asset_class, raw_instrument_type, raw_use_case):
        return _result(
            trade_id=trade_id,
            status="NO_PRODUCT_DEFINITION",
            template_path=None,
            matched_template=None,
            warnings=[],
            errors=[],
            explanation=EVENT_CONTRACT_EXPLANATION,
            classification_note=EVENT_CONTRACT_CLASSIFICATION_NOTE,
            derived_fields=[],
        )

    asset_class = _normalize_asset_class(raw_asset_class)
    instrument_type = _normalize_instrument_type(raw_instrument_type)
    use_case = _normalize_use_case(raw_use_case, asset_class, instrument_type)

    if not asset_class:
        errors.append("Missing or unsupported asset_class for UPI lookup.")
    if not instrument_type:
        errors.append("Missing or unsupported instrument_type for UPI lookup.")
    if not use_case:
        errors.append("Missing use_case for UPI lookup.")

    if errors:
        return _result(
            trade_id=trade_id,
            status="BAD_INPUT",
            template_path=None,
            matched_template=None,
            warnings=warnings,
            errors=errors,
            explanation="The trade cannot be mapped to a DSB UPI template path.",
            derived_fields=[],
        )

    otc_root = _resolve_otc_root(dsb_root)
    template_path = _find_template_path(otc_root, asset_class, instrument_type, use_case)

    if template_path is None:
        expected_path = (
            otc_root
            / "UPI"
            / asset_class
            / f"{asset_class}.{instrument_type}.{use_case}.UPI.V1.json"
        )
        return _result(
            trade_id=trade_id,
            status="NOT_FOUND",
            template_path=str(expected_path),
            matched_template=None,
            warnings=warnings,
            errors=[],
            explanation=(
                "No ANNA-DSB UPI product template exists at the expected path "
                f"for {asset_class}.{instrument_type}.{use_case}."
            ),
            derived_fields=[],
        )

    template = _load_json(template_path)
    attr_values = _collect_trade_attributes(trade)
    attr_values, derived_fields = _enrich_attributes(attr_values, trade, template)
    validation = _validate_attributes(template_path, template, attr_values)
    warnings.extend(validation["warnings"])
    errors.extend(validation["errors"])

    # Audit-trail warning: when the engine invented values for required
    # template attributes that the trade itself did not provide, surface that
    # explicitly so the data-quality issue is not buried inside derived_fields.
    required = (
        template.get("properties", {})
        .get("Attributes", {})
        .get("required", [])
    )
    defaulted_required = [
        entry for entry in derived_fields
        if entry["source"] == "default" and entry["attribute"] in required
    ]
    if defaulted_required:
        names = ", ".join(entry["attribute"] for entry in defaulted_required)
        warnings.append(
            f"Applied default values for required template attributes ({names}); "
            "trade did not provide these. See derived_fields for the audit trail."
        )

    if errors:
        status = "INVALID_ATTRIBUTES"
        explanation = "Template matched, but one or more UPI attributes failed validation."
    else:
        status = "FOUND"
        if warnings:
            explanation = "Template matched and required attributes passed with warnings."
        else:
            explanation = "Template matched and required attributes passed validation."

    return _result(
        trade_id=trade_id,
        status=status,
        template_path=str(template_path),
        matched_template=template.get("title"),
        warnings=warnings,
        errors=errors,
        explanation=explanation,
        derived_fields=derived_fields,
    )


def lookup_portfolio(
    trades: list[Mapping[str, Any]], dsb_root: str | Path
) -> list[dict[str, Any]]:
    """Run Module 2 lookup for a list of trades."""

    return [lookup_upi(trade, dsb_root) for trade in trades]


def _result(
    *,
    trade_id: str | None,
    status: str,
    template_path: str | None,
    matched_template: str | None,
    warnings: list[str],
    errors: list[str],
    explanation: str,
    classification_note: str | None = None,
    derived_fields: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "trade_id": trade_id,
        "status": status,
        "template_path": template_path,
        "matched_template": matched_template,
        "upi_code": None,
        "warnings": warnings,
        "errors": errors,
        "validation_errors": errors,
        "explanation": explanation,
        "classification_note": classification_note,
        "derived_fields": derived_fields if derived_fields is not None else [],
    }


def _resolve_otc_root(dsb_root: str | Path) -> Path:
    root = Path(dsb_root)
    candidates = [
        root,
        root / "OTC-Products",
        root / "PROD" / "OTC-Products",
    ]
    for candidate in candidates:
        if (candidate / "UPI").is_dir() and (candidate / "codesets").is_dir():
            return candidate
    raise FileNotFoundError(
        "Could not find DSB OTC-Products root. Pass data/product_definitions, "
        "data/product_definitions/PROD, or data/product_definitions/PROD/OTC-Products."
    )


def _find_template_path(
    otc_root: Path, asset_class: str, instrument_type: str, use_case: str
) -> Path | None:
    product_dir = otc_root / "UPI" / asset_class
    exact = product_dir / f"{asset_class}.{instrument_type}.{use_case}.UPI.V1.json"
    if exact.exists():
        return exact

    # Fallback: pick the highest-versioned non-Request template. DSB ships
    # successive schema revisions (V1, V1M1, V2, V2M1) and the latest version
    # is the source of truth — e.g. Credit.Swap.Corporate.UPI.V2M1 supersedes
    # V1 once published.
    prefix = f"{asset_class}.{instrument_type}.{use_case}.UPI."
    matches = sorted(product_dir.glob(f"{prefix}*.json"))
    versioned = [path for path in matches if not path.name.startswith("Request.")]
    if versioned:
        return versioned[-1]
    return None


def _validate_attributes(
    template_path: Path, template: Mapping[str, Any], attr_values: Mapping[str, Any]
) -> dict[str, list[str]]:
    warnings: list[str] = []
    errors: list[str] = []
    attributes_schema = (
        template.get("properties", {})
        .get("Attributes", {})
    )
    attributes = (
        template.get("properties", {})
        .get("Attributes", {})
        .get("properties", {})
    )
    required = (
        template.get("properties", {})
        .get("Attributes", {})
        .get("required", [])
    )

    for attr_name in required:
        if attr_name not in attr_values or attr_values[attr_name] in (None, ""):
            errors.append(f"Missing required UPI attribute: {attr_name}.")

    for attr_name, value in attr_values.items():
        spec = attributes.get(attr_name)
        if spec is None or value in (None, ""):
            continue
        _validate_value(
            path=attr_name,
            value=value,
            spec=spec,
            template_path=template_path,
            warnings=warnings,
            errors=errors,
        )

    # JSON Schema layer is additive: it catches what the custom walker misses
    # (extra attributes, structural issues), but the custom walker already
    # produces a tighter message for codeset/enum failures. Dedupe by leading
    # field-name token so we do not double-report the same field.
    custom_fields = {error.split("=", 1)[0].split(":", 1)[0].split()[-1].rstrip(".")
                     for error in errors}
    schema_errors = _validate_attributes_with_jsonschema(
        template_path=template_path,
        attributes_schema=attributes_schema,
        attr_values=attr_values,
    )
    for schema_error in schema_errors:
        message_body = schema_error.removeprefix("JSON Schema: ")
        schema_field = message_body.split(":", 1)[0]
        if schema_field in custom_fields:
            continue
        if schema_error not in errors:
            errors.append(schema_error)

    return {"warnings": warnings, "errors": errors}


def _validate_attributes_with_jsonschema(
    *,
    template_path: Path,
    attributes_schema: Mapping[str, Any],
    attr_values: Mapping[str, Any],
) -> list[str]:
    """Run optional JSON Schema validation on the DSB Attributes fragment.

    Full DSB UPI records require Identifier and Derived sections that incoming
    trade records do not have, so Module 2 validates only the product attributes
    fragment against the official schema.
    """

    if jsonschema is None or not attributes_schema:
        return []

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning)
            resolver = jsonschema.RefResolver(
                base_uri=template_path.resolve().as_uri(),
                referrer=attributes_schema,
            )
            validator = jsonschema.Draft4Validator(
                attributes_schema,
                resolver=resolver,
            )
        return [
            f"JSON Schema: {_format_schema_error(error)}"
            for error in sorted(validator.iter_errors(attr_values), key=str)
        ]
    except Exception as exc:  # pragma: no cover - defensive, non-core path
        return [f"JSON Schema validation could not run: {exc}"]


def _format_schema_error(error: Any) -> str:
    path = ".".join(str(part) for part in error.absolute_path)
    location = path or "Attributes"
    return f"{location}: {error.message}"


def _validate_value(
    *,
    path: str,
    value: Any,
    spec: Mapping[str, Any],
    template_path: Path,
    warnings: list[str],
    errors: list[str],
) -> None:
    if "$ref" in spec:
        codeset_path = (template_path.parent / spec["$ref"]).resolve()
        codeset = _load_json(codeset_path)
        allowed = set(codeset.get("enum", []))
        value_text = str(value)
        if value_text not in allowed:
            if "LIBOR" in value_text.upper():
                warnings.append(
                    f"{path} uses legacy LIBOR reference rate {value_text}; "
                    "flagged as warning only."
                )
            else:
                errors.append(
                    f"{path}={value_text!r} is not in codeset {codeset_path.name}."
                )
        elif "LIBOR" in value_text.upper():
            warnings.append(
                f"{path} uses legacy LIBOR reference rate {value_text}; "
                "codeset match retained, warning only."
            )
        return

    if "enum" in spec:
        allowed_values = set(spec["enum"])
        if value not in allowed_values:
            errors.append(
                f"{path}={value!r} is not one of {sorted(allowed_values)!r}."
            )
        return

    expected_type = spec.get("type")
    if expected_type == "integer" and not _is_integer_like(value):
        errors.append(f"{path}={value!r} must be an integer.")
    elif expected_type == "number" and not _is_number_like(value):
        errors.append(f"{path}={value!r} must be numeric.")
    elif expected_type == "object":
        if not isinstance(value, Mapping):
            errors.append(f"{path} must be an object.")
            return
        nested_required = spec.get("required", [])
        nested_properties = spec.get("properties", {})
        for nested_name in nested_required:
            if nested_name not in value or value[nested_name] in (None, ""):
                errors.append(f"Missing required UPI attribute: {path}.{nested_name}.")
        for nested_name, nested_value in value.items():
            nested_spec = nested_properties.get(nested_name)
            if nested_spec:
                _validate_value(
                    path=f"{path}.{nested_name}",
                    value=nested_value,
                    spec=nested_spec,
                    template_path=template_path,
                    warnings=warnings,
                    errors=errors,
                )


def _collect_trade_attributes(trade: Mapping[str, Any]) -> dict[str, Any]:
    nested = _get_field(trade, FIELD_ALIASES["attributes"])
    sources: list[Mapping[str, Any]] = [trade]
    if isinstance(nested, Mapping):
        sources.insert(0, nested)

    collected: dict[str, Any] = {}
    candidate_names = set(ATTRIBUTE_ALIASES)
    for source in sources:
        for raw_key in source:
            canonical = _canonical_attribute_name(str(raw_key))
            if canonical:
                candidate_names.add(canonical)

    for canonical in candidate_names:
        aliases = [canonical, _camel_to_snake(canonical), *ATTRIBUTE_ALIASES.get(canonical, [])]
        value = _get_field_from_sources(sources, aliases)
        if value is not None:
            collected[canonical] = value
    return collected


def _enrich_attributes(
    attr_values: Mapping[str, Any], trade: Mapping[str, Any], template: Mapping[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fill missing DSB attributes from raw trade fields and template defaults.

    Returns a tuple of (enriched_attributes, derived_fields). Each entry in
    derived_fields is a dict with keys ``attribute``, ``value``, and ``source``.
    Sources are one of:
      - ``default`` — a value invented by the engine (e.g. NotionalSchedule=Constant).
      - ``inferred:<raw_field>`` — value derived from a real raw_trade field
        (e.g. OtherNotionalCurrency from underlying_currency_pair).
      - ``aliased:<original>`` — value renamed to a canonical DSB code
        (e.g. EUR-ESTR aliased to EUR-EuroSTR).
      - ``dropped`` — value removed from the enriched dict because the template
        does not declare the attribute.

    The audit trail lets the caller distinguish defensible inferences from
    silent fills, and lets ``lookup_upi`` raise a single warning when the engine
    has invented values for *required* template attributes.
    """

    enriched = dict(attr_values)
    derived: list[dict[str, Any]] = []
    attributes_schema = template.get("properties", {}).get("Attributes", {})
    properties = attributes_schema.get("properties", {})
    title = str(template.get("title", ""))

    _infer_other_currency(enriched, trade, derived)
    _infer_option_type(enriched, trade, derived)
    _infer_underlying(enriched, trade, properties, title, derived)
    _infer_rates_underlying(enriched, trade, properties, derived)
    _infer_base_product(enriched, trade, properties, derived)
    _infer_return_or_payout(enriched, properties, title, derived)

    for attr_name, spec in properties.items():
        if attr_name not in enriched and isinstance(spec, Mapping) and "default" in spec:
            enriched[attr_name] = spec["default"]
            derived.append({
                "attribute": attr_name,
                "value": spec["default"],
                "source": "default",
            })

    if "NotionalSchedule" in properties and "NotionalSchedule" not in enriched:
        enriched["NotionalSchedule"] = "Constant"
        derived.append({
            "attribute": "NotionalSchedule",
            "value": "Constant",
            "source": "default",
        })

    if "SettlementCurrency" in properties and "SettlementCurrency" not in enriched:
        if "NotionalCurrency" in enriched:
            enriched["SettlementCurrency"] = enriched["NotionalCurrency"]
            derived.append({
                "attribute": "SettlementCurrency",
                "value": enriched["NotionalCurrency"],
                "source": "default",
            })

    if "DeliveryType" in properties and "DeliveryType" not in enriched:
        delivery_enum = properties["DeliveryType"].get("enum", [])
        if "CASH" in delivery_enum:
            enriched["DeliveryType"] = "CASH"
            derived.append({
                "attribute": "DeliveryType",
                "value": "CASH",
                "source": "default",
            })
        elif "PHYS" in delivery_enum:
            enriched["DeliveryType"] = "PHYS"
            derived.append({
                "attribute": "DeliveryType",
                "value": "PHYS",
                "source": "default",
            })

    if "OptionExerciseStyle" in properties and "OptionExerciseStyle" not in enriched:
        enriched["OptionExerciseStyle"] = "EURO"
        derived.append({
            "attribute": "OptionExerciseStyle",
            "value": "EURO",
            "source": "default",
        })

    if (
        "ValuationMethodorTrigger" in properties
        and "ValuationMethodorTrigger" not in enriched
    ):
        enriched["ValuationMethodorTrigger"] = "Vanilla"
        derived.append({
            "attribute": "ValuationMethodorTrigger",
            "value": "Vanilla",
            "source": "default",
        })

    _normalize_known_reference_rates(enriched, derived)
    _drop_known_attributes_not_in_template(enriched, properties, derived)
    return enriched, derived


def _infer_other_currency(
    enriched: dict[str, Any], trade: Mapping[str, Any], derived: list[dict[str, Any]]
) -> None:
    if "OtherNotionalCurrency" in enriched:
        return
    pair = trade.get("underlying_currency_pair")
    if not isinstance(pair, str) or "/" not in pair:
        return
    left, right = [part.strip().upper() for part in pair.split("/", 1)]
    notional = str(enriched.get("NotionalCurrency", "")).upper()
    if notional == left:
        value = right
    elif notional == right:
        value = left
    else:
        value = right
    enriched["OtherNotionalCurrency"] = value
    derived.append({
        "attribute": "OtherNotionalCurrency",
        "value": value,
        "source": "inferred:underlying_currency_pair",
    })


def _infer_option_type(
    enriched: dict[str, Any], trade: Mapping[str, Any], derived: list[dict[str, Any]]
) -> None:
    raw_value = enriched.get("OptionType") or trade.get("option_type")
    source = None
    if raw_value:
        source = "inferred:option_type"
    else:
        use_case = str(trade.get("use_case", "")).lower()
        if "cap" in use_case:
            raw_value = "CALL"
            source = "inferred:use_case"
        elif "floor" in use_case:
            raw_value = "PUT"
            source = "inferred:use_case"
    if not raw_value:
        return
    normalized = str(raw_value).upper()
    if normalized == "PUT":
        normalized = "PUTO"
        if source:
            source += "+aliased:PUT"
    if enriched.get("OptionType") == normalized:
        return
    enriched["OptionType"] = normalized
    derived.append({
        "attribute": "OptionType",
        "value": normalized,
        "source": source or "inferred:option_type",
    })


def _infer_underlying(
    enriched: dict[str, Any],
    trade: Mapping[str, Any],
    properties: Mapping[str, Any],
    template_title: str,
    derived: list[dict[str, Any]],
) -> None:
    if "Underlying" not in properties or "Underlying" in enriched:
        return

    reference_entity_isin = trade.get("reference_entity_isin")
    reference_entity_lei = trade.get("reference_entity_lei")
    underlying_isin = trade.get("underlying_isin")
    underlying_index = trade.get("underlying_index") or trade.get("index_name")
    underlying_commodity = trade.get("underlying_commodity")

    source = None
    if reference_entity_isin:
        enriched["Underlying"] = {"InstrumentISIN": reference_entity_isin}
        source = "inferred:reference_entity_isin"
    elif reference_entity_lei:
        enriched["Underlying"] = {"InstrumentLEI": reference_entity_lei}
        source = "inferred:reference_entity_lei"
    elif underlying_isin:
        enriched["Underlying"] = {"UnderlyingInstrumentISIN": underlying_isin}
        source = "inferred:underlying_isin"
    elif underlying_index:
        enriched["Underlying"] = {"UnderlyingInstrumentIndexProp": underlying_index}
        source = "inferred:underlying_index"
    elif underlying_commodity:
        enriched["Underlying"] = {"UnderlyingInstrumentIndexProp": underlying_commodity}
        source = "inferred:underlying_commodity"

    if "Credit.Swap.Index" in template_title and underlying_index:
        enriched["Underlying"] = {
            "UnderlyingInstrumentIndexProp": underlying_index,
            "UnderlyingInstrumentIndexTermValue": 0,
            "UnderlyingInstrumentIndexTermUnit": "DAYS",
            "UnderlyingCreditIndexSeries": 0,
            "UnderlyingCreditIndexVersion": 0,
        }
        source = "inferred:underlying_index+default:credit_index_metadata"

    if source:
        derived.append({
            "attribute": "Underlying",
            "value": enriched["Underlying"],
            "source": source,
        })


def _infer_rates_underlying(
    enriched: dict[str, Any],
    trade: Mapping[str, Any],
    properties: Mapping[str, Any],
    derived: list[dict[str, Any]],
) -> None:
    if "UnderlyingInstrumentIndex" in properties and "UnderlyingInstrumentIndex" not in enriched:
        value = trade.get("reference_rate")
        if value:
            enriched["UnderlyingInstrumentIndex"] = value
            derived.append({
                "attribute": "UnderlyingInstrumentIndex",
                "value": value,
                "source": "inferred:reference_rate",
            })
    if (
        "UnderlyingInstrumentIndexTermValue" in properties
        and "UnderlyingInstrumentIndexTermValue" not in enriched
    ):
        value = trade.get("underlying_tenor_value") or trade.get("reference_rate_term_value")
        if value is not None:
            enriched["UnderlyingInstrumentIndexTermValue"] = value
            derived.append({
                "attribute": "UnderlyingInstrumentIndexTermValue",
                "value": value,
                "source": "inferred:underlying_tenor_value",
            })
    if (
        "UnderlyingInstrumentIndexTermUnit" in properties
        and "UnderlyingInstrumentIndexTermUnit" not in enriched
    ):
        value = trade.get("underlying_tenor_unit") or trade.get("reference_rate_term_unit")
        if value is not None:
            enriched["UnderlyingInstrumentIndexTermUnit"] = value
            derived.append({
                "attribute": "UnderlyingInstrumentIndexTermUnit",
                "value": value,
                "source": "inferred:underlying_tenor_unit",
            })


def _infer_base_product(
    enriched: dict[str, Any],
    trade: Mapping[str, Any],
    properties: Mapping[str, Any],
    derived: list[dict[str, Any]],
) -> None:
    if "BaseProduct" not in properties or "BaseProduct" in enriched:
        return
    commodity = str(trade.get("underlying_commodity", "")).upper()
    value: str | None = None
    if any(marker in commodity for marker in ("GOLD", "SILVER", "XAU", "METAL")):
        value = "METL"
    elif any(marker in commodity for marker in ("WTI", "BRENT", "OIL", "GAS", "POWER")):
        value = "NRGY"
    if value is None:
        return
    enriched["BaseProduct"] = value
    derived.append({
        "attribute": "BaseProduct",
        "value": value,
        "source": "inferred:underlying_commodity",
    })


def _infer_return_or_payout(
    enriched: dict[str, Any],
    properties: Mapping[str, Any],
    template_title: str,
    derived: list[dict[str, Any]],
) -> None:
    if "ReturnorPayoutTrigger" not in properties or "ReturnorPayoutTrigger" in enriched:
        return
    allowed = properties["ReturnorPayoutTrigger"].get("enum", [])
    value: str | None = None
    source = "default:template_title_heuristic"
    if "Total_Return" in template_title and "Total Return" in allowed:
        value = "Total Return"
    elif "Forward" in template_title and "Forward price of underlying instrument" in allowed:
        value = "Forward price of underlying instrument"
    elif "Contract for Difference (CFD)" in allowed:
        value = "Contract for Difference (CFD)"
    elif allowed:
        value = allowed[0]
    if value is None:
        return
    enriched["ReturnorPayoutTrigger"] = value
    derived.append({
        "attribute": "ReturnorPayoutTrigger",
        "value": value,
        "source": source,
    })


def _normalize_known_reference_rates(
    enriched: dict[str, Any], derived: list[dict[str, Any]]
) -> None:
    rate_aliases = {
        "EUR-ESTR": "EUR-EuroSTR",
        "GBP-RPI": "UK-RPI",
    }
    rate_fields = [
        "ReferenceRate",
        "OtherLegReferenceRate",
        "UnderlyingInstrumentIndex",
    ]
    for field in rate_fields:
        value = enriched.get(field)
        if isinstance(value, str) and value in rate_aliases:
            new_value = rate_aliases[value]
            enriched[field] = new_value
            derived.append({
                "attribute": field,
                "value": new_value,
                "source": f"aliased:{value}",
            })


def _drop_known_attributes_not_in_template(
    enriched: dict[str, Any],
    properties: Mapping[str, Any],
    derived: list[dict[str, Any]],
) -> None:
    known_attribute_names = set(ATTRIBUTE_ALIASES)
    for key in list(enriched):
        if key in known_attribute_names and key not in properties:
            removed_value = enriched.pop(key)
            derived.append({
                "attribute": key,
                "value": removed_value,
                "source": "dropped",
            })


def _canonical_attribute_name(raw_key: str) -> str | None:
    normalized = _key(raw_key)
    for canonical, aliases in ATTRIBUTE_ALIASES.items():
        if normalized in {_key(canonical), *(_key(alias) for alias in aliases)}:
            return canonical
    if raw_key and raw_key[0].isupper():
        return raw_key
    return None


def _get_field_from_sources(sources: list[Mapping[str, Any]], aliases: list[str]) -> Any:
    for source in sources:
        value = _get_field(source, aliases)
        if value is not None:
            return value
    return None


def _get_field(mapping: Mapping[str, Any], aliases: list[str]) -> Any:
    alias_keys = {_key(alias) for alias in aliases}
    for raw_key, value in mapping.items():
        if _key(str(raw_key)) in alias_keys:
            return value
    return None


def _normalize_asset_class(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _value_key(value)
    if normalized in ASSET_CLASS_ALIASES:
        return ASSET_CLASS_ALIASES[normalized]
    candidate = _normalize_token(value)
    return candidate if candidate in set(ASSET_CLASS_ALIASES.values()) else None


def _normalize_instrument_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _value_key(value)
    if normalized in INSTRUMENT_TYPE_ALIASES:
        return INSTRUMENT_TYPE_ALIASES[normalized]
    candidate = _normalize_token(value)
    return candidate if candidate in set(INSTRUMENT_TYPE_ALIASES.values()) else None


def _normalize_use_case(
    value: str | None, asset_class: str | None = None, instrument_type: str | None = None
) -> str | None:
    if value is None:
        return None
    cleaned = _normalize_token(value)
    compact = cleaned.replace("_", "")
    contextual_aliases = {
        ("Equity", "Option", "SingleNamePut"): "Single_Name",
        ("Equity", "Option", "SingleNameCall"): "Single_Name",
        ("Equity", "Option", "SingleName"): "Single_Name",
        ("Equity", "Forward", "SingleName"): "Price_Return_Basic_Performance_Single_Name",
        ("Equity", "Swap", "TotalReturnSingleIndex"): "Total_Return_Swap_Single_Index",
        ("Equity", "Swap", "Variance"): "Parameter_Return_Variance_Single_Index",
        ("Commodities", "Swap", "SingleName"): "Single_Index",
        ("Commodities", "Option", "SingleName"): "Single_Index",
        ("Foreign_Exchange", "Option", "Vanilla"): "Vanilla_Option",
        ("Foreign_Exchange", "Option", "Barrier"): "Barrier_Option",
        ("Foreign_Exchange", "Swap", "Standard"): "FX_Swap",
        ("Foreign_Exchange", "Forward", "Deliverable"): "Forward",
        ("Rates", "Swap", "CrossCurrency"): "Cross_Currency_Fixed_Float",
        ("Rates", "Swap", "Inflation"): "Inflation_Swap",
        ("Rates", "Swap", "OIS"): "Fixed_Float_OIS",
        ("Rates", "Option", "Cap"): "CapFloor",
        ("Rates", "Option", "Floor"): "CapFloor",
    }
    contextual = contextual_aliases.get((asset_class, instrument_type, compact))
    if contextual:
        return contextual

    aliases = {
        "FixedFloat": "Fixed_Float",
        "FixedFloating": "Fixed_Float",
        "Ndf": "NDF",
        "FxSwap": "FX_Swap",
        "Ois": "OIS",
        "Vanilla": "Vanilla_Option",
        "Barrier": "Barrier_Option",
        "CrossCurrency": "Cross_Currency_Fixed_Float",
        "Inflation": "Inflation_Swap",
        "Standard": "FX_Swap",
        "Deliverable": "Forward",
    }
    return aliases.get(compact, cleaned)


def _normalize_token(value: str) -> str:
    text = str(value).strip()
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if text.isupper():
        return text
    return "_".join(part[:1].upper() + part[1:] for part in text.split("_") if part)


def _is_event_contract(
    trade: Mapping[str, Any],
    trade_id: str | None,
    asset_class: str | None,
    instrument_type: str | None,
    use_case: str | None,
) -> bool:
    if trade_id in EVENT_CONTRACT_TRADE_IDS:
        return True
    joined = " ".join(
        str(value)
        for value in [asset_class, instrument_type, use_case, trade.get("platform")]
        if value is not None
    )
    normalized = _value_key(joined)
    event_markers = [
        "eventcontract",
        "event_contract",
        "predictionmarket",
        "prediction_market",
        "kalshi",
        "polymarket",
    ]
    return any(marker in normalized for marker in event_markers)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _value_key(value: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", value.lower().replace(" ", "_").replace("-", "_"))


def _camel_to_snake(value: str) -> str:
    text = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    return text.lower()


def _is_integer_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, str):
        return value.strip().isdigit()
    return False


def _is_number_like(value: Any) -> bool:
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


@lru_cache(maxsize=512)
def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_trades(path: Path) -> list[Mapping[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, Mapping):
        for key in ("trades", "Trades", "records"):
            if isinstance(data.get(key), list):
                return data[key]
    raise ValueError("Input JSON must be a list of trades or an object with a trades list.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Module 2 UPI lookup.")
    parser.add_argument("--input", required=True, help="Path to trades.json")
    parser.add_argument(
        "--dsb-root",
        default="data/product_definitions",
        help="Path to DSB product_definitions, PROD, or OTC-Products root.",
    )
    parser.add_argument("--output", help="Optional JSON output path.")
    # Accepted for CLI consistency with run_compliance_check.py. UPI lookup is
    # regime-independent (the same DSB template applies under CFTC, EMIR, MAS,
    # ASIC), so the value is recorded but does not change behaviour.
    parser.add_argument(
        "--regimes",
        default="CFTC,EMIR",
        help="Reporting regimes (recorded only; UPI lookup is regime-independent).",
    )
    args = parser.parse_args()

    trades = _load_trades(Path(args.input))
    results = lookup_portfolio(trades, args.dsb_root)
    payload = json.dumps(results, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
