import argparse
import json
from pathlib import Path

from src.module1_parser import parse_trades
from src.module2_upi_lookup import lookup_upi
from src.module3_compliance import check_compliance


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DSB_ROOT = BASE_DIR / "data" / "product_definitions"
DEFAULT_OUTPUT = BASE_DIR / "output" / "compliance_report.json"


def main():
    args = parse_args()

    report = run_compliance(
        input_path=args.input,
        additional_input=args.additional_input,
        regimes=args.regimes,
        dsb_root=args.dsb_root,
        output_path=DEFAULT_OUTPUT,
    )

    for line in format_console_summary(report, DEFAULT_OUTPUT):
        print(line)


def run_compliance(
    input_path,
    additional_input="additional_trades.json",
    regimes="CFTC,EMIR",
    dsb_root=DEFAULT_DSB_ROOT,
    output_path=DEFAULT_OUTPUT,
):
    input_path = resolve_project_path(input_path)
    dsb_root = resolve_project_path(dsb_root)
    output_path = resolve_project_path(output_path) if output_path else None

    raw_trades = load_json(input_path)
    provided_trade_count = len(raw_trades)
    additional_input_path = resolve_optional_project_path(additional_input)
    additional_trades = []
    if additional_input_path is not None and additional_input_path.exists():
        additional_trades = load_json(additional_input_path)
        raw_trades = raw_trades + additional_trades

    regimes = parse_regimes(regimes)
    parsed_trades = parse_trades(raw_trades)
    upi_results = [lookup_upi(trade["raw_trade"], dsb_root) for trade in parsed_trades]
    compliance_results = [
        check_compliance(trade, upi_result, trade["raw_trade"], regimes)
        for trade, upi_result in zip(parsed_trades, upi_results)
    ]

    report = {
        "input_file": str(input_path),
        "additional_input_file": (
            str(additional_input_path)
            if additional_input_path is not None and additional_input_path.exists()
            else None
        ),
        "regimes": regimes,
        "summary": {
            "total_trades": len(parsed_trades),
            "provided_trades": provided_trade_count,
            "additional_trades": len(additional_trades),
            "success": count_by_status(parsed_trades, "SUCCESS"),
            "partial": count_by_status(parsed_trades, "PARTIAL"),
            "failed": count_by_status(parsed_trades, "FAILED"),
            "novel_instruments": count_by_classification(
                parsed_trades,
                "NOVEL_INSTRUMENT_NO_TAXONOMY",
            ),
            "upi": count_upi_statuses(upi_results),
            "compliance": count_compliance_statuses(compliance_results),
        },
        "trades": [
            {
                "trade_id": trade["trade_id"],
                "parse_result": trade,
                "upi_result": upi_result,
                "compliance_result": compliance_result,
            }
            for trade, upi_result, compliance_result in zip(
                parsed_trades,
                upi_results,
                compliance_results,
            )
        ],
    }

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        save_json(output_path, report)

    return report


def format_console_summary(report, output_path=DEFAULT_OUTPUT):
    lines = [
        f"Parsed {report['summary']['total_trades']} trades",
        f"UPI summary: {report['summary']['upi']}",
        f"Compliance summary: {report['summary']['compliance']}",
    ]
    additional_trades = report["summary"].get("additional_trades", 0)
    if additional_trades:
        lines.insert(1, f"Included {additional_trades} additional trades")
    if output_path:
        lines.append(f"Output written to {resolve_project_path(output_path)}")
    return lines


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run OTC derivatives compliance checks for HW2."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to input trades JSON file.",
    )
    parser.add_argument(
        "--regimes",
        default="CFTC,EMIR",
        help="Comma-separated reporting regimes, e.g. CFTC,EMIR.",
    )
    parser.add_argument(
        "--dsb-root",
        default=str(DEFAULT_DSB_ROOT),
        help="Path to ANNA-DSB product_definitions folder.",
    )
    parser.add_argument(
        "--additional-input",
        default="additional_trades.json",
        help=(
            "Optional JSON file of additional trades to append. Defaults to "
            "additional_trades.json when that file is present."
        ),
    )
    return parser.parse_args()


def load_json(path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path, data):
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def resolve_project_path(path):
    path = Path(path)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


def resolve_optional_project_path(path):
    if path is None or str(path).strip() == "":
        return None
    return resolve_project_path(path)


def parse_regimes(regimes):
    if not isinstance(regimes, str):
        return [str(regime).strip().upper() for regime in regimes if str(regime).strip()]
    return [
        regime.strip().upper()
        for regime in regimes.split(",")
        if regime.strip()
    ]


def count_by_status(parsed_trades, status):
    return sum(1 for trade in parsed_trades if trade["parse_status"] == status)


def count_by_classification(parsed_trades, classification):
    return sum(
        1
        for trade in parsed_trades
        if trade["classification_flag"] == classification
    )


def count_upi_statuses(upi_results):
    statuses = {}
    for result in upi_results:
        status = result["status"]
        statuses[status] = statuses.get(status, 0) + 1
    return statuses


def count_compliance_statuses(compliance_results):
    regimes = {}
    for result in compliance_results:
        for regime, regime_result in result.items():
            regime_counts = regimes.setdefault(regime, {})
            status = regime_result["status"]
            regime_counts[status] = regime_counts.get(status, 0) + 1
    return regimes


if __name__ == "__main__":
    main()
