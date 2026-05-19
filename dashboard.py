"""Interactive compliance dashboard for the HW2 output report.

Running ``python dashboard.py`` regenerates ``output/dashboard.html`` from
``output/compliance_report.json`` and serves it locally. The dashboard uses
browser-side Plotly for charts, so no additional Python dashboard dependencies
are required.

The dashboard is a read-only renderer: it consumes the existing
``output/compliance_report.json`` and produces a static HTML page. To refresh
the underlying data, re-run ``python run_compliance_check.py`` separately.
"""

from __future__ import annotations

import argparse
import html
import json
import webbrowser
from collections import Counter, defaultdict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_REPORT = BASE_DIR / "output" / "compliance_report.json"
DEFAULT_OUTPUT = BASE_DIR / "output" / "dashboard.html"

STATUS_ORDER = ["COMPLIANT", "NONCOMPLIANT", "CONDITIONAL", "NOT_APPLICABLE"]
STATUS_SCORE = {
    "COMPLIANT": 0,
    "NONCOMPLIANT": 1,
    "CONDITIONAL": 2,
    "NOT_APPLICABLE": 3,
}
STATUS_COLORS = {
    "COMPLIANT": "#2fbf71",
    "NONCOMPLIANT": "#ef5b5b",
    "CONDITIONAL": "#e5a82e",
    "NOT_APPLICABLE": "#8d98aa",
}


def load_report(path: Path = DEFAULT_REPORT) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Report file not found: {path}. Run "
            "`python run_compliance_check.py --input trades.json --regimes CFTC,EMIR` "
            "first."
        )
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def build_dashboard_data(report: dict[str, Any]) -> dict[str, Any]:
    trades = report.get("trades", [])
    regimes = report.get("regimes") or _discover_regimes(trades)
    trade_ids = [trade.get("trade_id", "UNKNOWN") for trade in trades]
    matrix = _build_matrix_rows(trades, regimes)
    heatmap = _build_heatmap_compat(matrix, regimes)
    error_frequency = _build_error_frequency(matrix)
    asset_breakdown = _build_asset_breakdown(matrix, regimes)
    frontier = _build_frontier_rows(matrix)
    interpretation = _build_interpretation(
        report=report,
        error_frequency=error_frequency,
        asset_breakdown=asset_breakdown,
        frontier=frontier,
    )

    return {
        "input_file": report.get("input_file", ""),
        "summary": report.get("summary", {}),
        "regimes": regimes,
        "trade_ids": trade_ids,
        "trade_meta": [
            {
                "trade_id": row["trade_id"],
                "asset_class": row["asset_class"],
                "classification_flag": row["classification_flag"],
            }
            for row in matrix
        ],
        "asset_classes": sorted({row["asset_class"] for row in matrix}),
        "status_order": STATUS_ORDER,
        "status_colors": STATUS_COLORS,
        "matrix": matrix,
        "heatmap": heatmap,
        "error_frequency": error_frequency,
        "asset_breakdown": asset_breakdown,
        "frontier": frontier,
        "interpretation": interpretation,
    }


def render_dashboard_html(data: dict[str, Any]) -> str:
    data_json = json.dumps(data, ensure_ascii=False)
    return _DASHBOARD_TEMPLATE.replace("__DASHBOARD_DATA__", data_json)


def write_dashboard(
    report_path: Path = DEFAULT_REPORT,
    output_path: Path = DEFAULT_OUTPUT,
) -> Path:
    report = load_report(report_path)
    data = build_dashboard_data(report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_dashboard_html(data), encoding="utf-8")
    return output_path


def serve_dashboard(
    output_path: Path,
    port: int,
    report_path: Path = DEFAULT_REPORT,
    open_browser: bool = True,
) -> None:
    class DashboardHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(BASE_DIR), **kwargs)

        def do_GET(self):  # noqa: N802 - inherited API
            if self.path in {"/", "", "/dashboard.html"}:
                return self._send_dashboard()
            return super().do_GET()

        def _send_dashboard(self):
            data = build_dashboard_data(load_report(report_path))
            body = render_dashboard_html(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = None
    actual_port = port
    for candidate in range(port, port + 10):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), DashboardHandler)
            actual_port = candidate
            break
        except OSError:
            continue
    if server is None:
        raise OSError(f"Could not bind dashboard server on ports {port}-{port + 9}.")

    url = f"http://127.0.0.1:{actual_port}/"
    print(f"Dashboard written to {output_path}")
    print(f"Serving dashboard at {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard server stopped.")
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and serve the compliance dashboard.")
    parser.add_argument("--report", default=str(DEFAULT_REPORT), help="Path to compliance_report.json.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Path for generated dashboard HTML.")
    parser.add_argument("--port", type=int, default=8050, help="Local server port.")
    parser.add_argument("--no-serve", action="store_true", help="Generate HTML and exit.")
    parser.add_argument("--no-browser", action="store_true", help="Serve without opening a browser window.")
    args = parser.parse_args()

    report_path = Path(args.report)
    output_path = write_dashboard(report_path, Path(args.output))
    if args.no_serve:
        print(f"Dashboard written to {output_path}")
        return 0

    serve_dashboard(output_path, args.port, report_path, open_browser=not args.no_browser)
    return 0


def _build_matrix_rows(
    trades: list[dict[str, Any]],
    regimes: list[str],
) -> list[dict[str, Any]]:
    rows = []
    for trade in trades:
        parse_result = trade.get("parse_result", {})
        upi_result = trade.get("upi_result", {})
        raw_trade = parse_result.get("raw_trade", {})
        compliance = trade.get("compliance_result", {})
        regime_results = {}
        for regime in regimes:
            result = compliance.get(regime, {})
            regime_results[regime] = {
                "status": result.get("status", "UNKNOWN"),
                "reporting_required": bool(result.get("reporting_required")),
                "errors": result.get("errors", []) or [],
                "warnings": result.get("warnings", []) or [],
                "failed_fields": result.get("failed_fields", []) or [],
                "note": result.get("note", ""),
            }
        rows.append(
            {
                "trade_id": trade.get("trade_id", "UNKNOWN"),
                "parse_status": parse_result.get("parse_status") or "UNKNOWN",
                "asset_class": parse_result.get("asset_class") or "Unknown",
                "instrument_type": parse_result.get("instrument_type") or "Unknown",
                "use_case": parse_result.get("use_case") or "Unknown",
                "classification_flag": parse_result.get("classification_flag") or "Unknown",
                "upi_status": upi_result.get("status") or "UNKNOWN",
                "upi_product": (
                    upi_result.get("matched_template")
                    or upi_result.get("product")
                    or upi_result.get("template")
                    or ""
                ),
                "upi_classification_note": upi_result.get("classification_note") or "",
                "upi_errors": upi_result.get("errors", []) or [],
                "upi_warnings": upi_result.get("warnings", []) or [],
                "platform": raw_trade.get("platform") or "",
                "event_type": raw_trade.get("event_type") or "",
                "description": raw_trade.get("description") or "",
                "design_intent": raw_trade.get("_design_intent") or "",
                "regimes": regime_results,
            }
        )
    return rows


def _build_heatmap_compat(
    matrix: list[dict[str, Any]],
    regimes: list[str],
) -> dict[str, Any]:
    z = []
    text = []
    hover = []
    details = []
    for row in matrix:
        z_row = []
        text_row = []
        hover_row = []
        details_row = []
        for regime in regimes:
            result = row["regimes"][regime]
            status = result["status"]
            z_row.append(STATUS_SCORE.get(status, 4))
            text_row.append(status)
            hover_bits = []
            if result["failed_fields"]:
                hover_bits.append("Failed fields: " + ", ".join(result["failed_fields"]))
            if result["errors"]:
                hover_bits.append(f"Errors: {len(result['errors'])}")
            if result["warnings"]:
                hover_bits.append(f"Warnings: {len(result['warnings'])}")
            if result["note"]:
                hover_bits.append("Note: " + result["note"])
            hover_row.append("<br>".join(html.escape(bit) for bit in hover_bits) or "No findings")
            details_row.append(
                {
                    "trade_id": row["trade_id"],
                    "regime": regime,
                    "status": status,
                    "asset_class": row["asset_class"],
                    "failed_fields": result["failed_fields"],
                    "errors": result["errors"],
                    "warnings": result["warnings"],
                    "note": result["note"],
                }
            )
        z.append(z_row)
        text.append(text_row)
        hover.append(hover_row)
        details.append(details_row)
    return {
        "z": z,
        "text": text,
        "hover": hover,
        "details": details,
        "trade_ids": [row["trade_id"] for row in matrix],
    }


def _build_error_frequency(matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for row in matrix:
        for result in row["regimes"].values():
            fields = result.get("failed_fields", []) or []
            if fields:
                counter.update(fields)
            else:
                for error in result.get("errors", []) or []:
                    counter.update([str(error).split(":", 1)[0]])
    return [
        {"field": field, "count": count}
        for field, count in counter.most_common(12)
    ] or [{"field": "No failing fields", "count": 0}]


def _build_asset_breakdown(
    matrix: list[dict[str, Any]],
    regimes: list[str],
) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"compliant": 0, "required": 0}
    )
    asset_classes = sorted({row["asset_class"] for row in matrix})

    for row in matrix:
        for regime in regimes:
            result = row["regimes"].get(regime, {})
            key = (row["asset_class"], regime)
            if result.get("reporting_required"):
                buckets[key]["required"] += 1
                if result.get("status") == "COMPLIANT":
                    buckets[key]["compliant"] += 1

    rows = []
    for asset_class in asset_classes:
        for regime in regimes:
            counts = buckets[(asset_class, regime)]
            required = counts["required"]
            compliant = counts["compliant"]
            rate = compliant / required if required else None
            rows.append(
                {
                    "asset_class": asset_class,
                    "regime": regime,
                    "compliance_rate": rate,
                    "compliant": compliant,
                    "required": required,
                    "label": (
                        f"{compliant}/{required} reportable trades compliant"
                        if required
                        else "No reportable trades"
                    ),
                }
            )
    return rows


def _build_frontier_rows(matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in matrix:
        if row["trade_id"] not in {"T026", "T027", "T028"}:
            continue
        cftc = row["regimes"].get("CFTC", {})
        emir = row["regimes"].get("EMIR", {})
        rows.append(
            {
                "trade_id": row["trade_id"],
                "platform": row["platform"],
                "event_type": row["event_type"],
                "cftc_status": cftc.get("status"),
                "cftc_note": cftc.get("note"),
                "emir_status": emir.get("status"),
                "emir_note": emir.get("note"),
                "classification_note": row.get("upi_classification_note", ""),
            }
        )
    return rows


def _build_interpretation(
    *,
    report: dict[str, Any],
    error_frequency: list[dict[str, Any]],
    asset_breakdown: list[dict[str, Any]],
    frontier: list[dict[str, Any]],
) -> list[str]:
    summary = report.get("summary", {})
    total = summary.get("total_trades", 0)
    compliance = summary.get("compliance", {})
    cftc = compliance.get("CFTC", {})
    emir = compliance.get("EMIR", {})
    top_error = error_frequency[0] if error_frequency else {"field": "none", "count": 0}

    best_rates = [
        row for row in asset_breakdown
        if row["compliance_rate"] is not None
    ]
    best = max(best_rates, key=lambda row: row["compliance_rate"], default=None)
    cftc_frontier = {
        row["trade_id"]: row["cftc_status"]
        for row in frontier
    }

    first = (
        f"The report covers {total} trades across CFTC and EMIR. CFTC produces "
        f"{cftc.get('COMPLIANT', 0)} compliant, {cftc.get('NONCOMPLIANT', 0)} "
        f"noncompliant, {cftc.get('CONDITIONAL', 0)} conditional, and "
        f"{cftc.get('NOT_APPLICABLE', 0)} not-applicable outcomes; EMIR produces "
        f"{emir.get('COMPLIANT', 0)} compliant, {emir.get('NONCOMPLIANT', 0)} "
        f"noncompliant, and {emir.get('NOT_APPLICABLE', 0)} not-applicable outcomes."
    )
    second = (
        f"The most frequent failing field is {top_error['field']}, appearing "
        f"{top_error['count']} times across regime-level checks. The pattern shows "
        "that identifier quality, margin data, and UPI validation are the practical "
        "control points a compliance team would investigate first."
    )
    if best:
        third_prefix = (
            f"The strongest asset-class/regime compliance rate is {best['asset_class']} "
            f"under {best['regime']} at {best['compliance_rate']:.0%} "
            f"({best['label']}). "
        )
    else:
        third_prefix = "No reportable asset-class bucket has a compliant trade. "
    third = (
        third_prefix
        + "The frontier trades make the taxonomy gap explicit: "
        + ", ".join(f"{trade_id} is {status} under CFTC" for trade_id, status in cftc_frontier.items())
        + ", while all three are outside EMIR reporting scope in this model."
    )
    return [first, second, third]


def _discover_regimes(trades: list[dict[str, Any]]) -> list[str]:
    regimes: list[str] = []
    for trade in trades:
        for regime in trade.get("compliance_result", {}):
            if regime not in regimes:
                regimes.append(regime)
    return regimes


_DASHBOARD_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Compliance Dashboard</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    :root {
      --bg: #0d1117;
      --panel: #161b22;
      --panel-2: #1f2633;
      --panel-3: #0f141c;
      --line: #303846;
      --line-strong: #465064;
      --ink: #eef2f7;
      --muted: #aab4c5;
      --soft: #d7deea;
      --accent: #4cc9a7;
      --accent-2: #8ab4ff;
      --green: #2fbf71;
      --red: #ef5b5b;
      --amber: #e5a82e;
      --gray: #8d98aa;
      --shadow: rgba(0, 0, 0, 0.35);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background:
        radial-gradient(circle at top left, rgba(76, 201, 167, 0.14), transparent 32rem),
        linear-gradient(180deg, #0d1117 0%, #10141d 100%);
      color: var(--ink);
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.45;
    }
    header {
      padding: 26px 34px 22px;
      border-bottom: 1px solid var(--line);
      background: rgba(13, 17, 23, 0.92);
    }
    header h1 {
      margin: 0 0 8px;
      font-size: 32px;
      letter-spacing: 0;
    }
    header p {
      margin: 0;
      color: var(--muted);
      max-width: 900px;
    }
    main {
      width: min(1480px, calc(100vw - 28px));
      margin: 18px auto 40px;
    }
    .summary {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }
    .metric {
      background: linear-gradient(180deg, #1a202c, #141922);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 16px;
      box-shadow: 0 10px 24px var(--shadow);
    }
    .metric strong {
      display: block;
      font-size: 30px;
      margin-bottom: 3px;
    }
    .metric span {
      color: var(--muted);
      font-size: 13px;
    }
    section {
      background: rgba(22, 27, 34, 0.96);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 18px;
      margin-bottom: 16px;
      box-shadow: 0 12px 28px var(--shadow);
    }
    .section-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      margin-bottom: 12px;
    }
    section h2 {
      margin: 0;
      font-size: 22px;
      letter-spacing: 0;
    }
    .section-note {
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 13px;
    }
    .controls {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
      padding: 12px;
      margin-bottom: 14px;
      background: var(--panel-3);
      border: 1px solid var(--line);
      border-radius: 10px;
    }
    .control-label {
      color: var(--soft);
      font-size: 13px;
      font-weight: 700;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 32px;
      padding: 5px 10px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--panel-2);
      color: var(--ink);
      font-size: 13px;
      white-space: nowrap;
      cursor: pointer;
    }
    .chip input { margin: 0; accent-color: var(--accent); }
    .dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      display: inline-block;
      flex: 0 0 auto;
    }
    select, input[type="search"], button {
      min-height: 34px;
      border: 1px solid var(--line-strong);
      border-radius: 8px;
      background: #0f141c;
      color: var(--ink);
      font: inherit;
      font-size: 13px;
      padding: 6px 10px;
    }
    input[type="search"]::placeholder { color: #7f8a9d; }
    button {
      background: linear-gradient(180deg, #2d6cdf, #1c4aa8);
      border-color: #2d6cdf;
      cursor: pointer;
      font-weight: 700;
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 10px 16px;
      margin-bottom: 12px;
      color: var(--muted);
      font-size: 13px;
    }
    .legend span {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      white-space: nowrap;
    }
    .matrix-layout {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(320px, 420px);
      gap: 14px;
      align-items: start;
    }
    .matrix-wrap {
      overflow: auto;
      max-height: 720px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #0f141c;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 10px;
      text-align: left;
      vertical-align: middle;
    }
    th {
      position: sticky;
      top: 0;
      z-index: 2;
      background: #202838;
      color: var(--soft);
      font-size: 12px;
      letter-spacing: 0.02em;
      text-transform: uppercase;
    }
    .matrix-table td:first-child,
    .matrix-table th:first-child {
      position: sticky;
      left: 0;
      z-index: 3;
      background: #131923;
      min-width: 86px;
    }
    .matrix-table th:first-child { background: #202838; }
    .trade-id {
      color: var(--ink);
      font-weight: 700;
    }
    .asset {
      color: var(--muted);
      white-space: nowrap;
    }
    .status-cell {
      width: 100%;
      min-width: 150px;
      border: 0;
      border-radius: 8px;
      color: #fff;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-size: 13px;
      font-weight: 800;
      padding: 9px 10px;
      text-align: left;
    }
    .status-cell small {
      font-size: 11px;
      font-weight: 700;
      opacity: 0.9;
      white-space: nowrap;
    }
    .status-COMPLIANT { background: linear-gradient(135deg, #178f52, #2fbf71); }
    .status-NONCOMPLIANT { background: linear-gradient(135deg, #b9363d, #ef5b5b); }
    .status-CONDITIONAL { background: linear-gradient(135deg, #b77610, #e5a82e); color: #191100; }
    .status-NOT_APPLICABLE { background: linear-gradient(135deg, #667386, #8d98aa); }
    .detail-panel {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #0f141c;
      padding: 14px;
      min-height: 260px;
      position: sticky;
      top: 12px;
    }
    .detail-panel h3 {
      margin: 0 0 10px;
      font-size: 18px;
    }
    .detail-panel p {
      margin: 8px 0;
      color: var(--soft);
    }
    .detail-panel ul {
      margin: 8px 0 12px 18px;
      padding: 0;
      color: var(--soft);
    }
    .detail-panel li { margin-bottom: 5px; }
    .muted { color: var(--muted); }
    .status-pill {
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      color: #fff;
      font-size: 12px;
      font-weight: 800;
      padding: 5px 9px;
      white-space: nowrap;
    }
    .status-pill.status-CONDITIONAL { color: #191100; }
    .status-pill.status-FOUND { background: linear-gradient(135deg, #178f52, #2fbf71); }
    .status-pill.status-INVALID_ATTRIBUTES { background: linear-gradient(135deg, #b9363d, #ef5b5b); }
    .status-pill.status-NOT_FOUND { background: linear-gradient(135deg, #667386, #8d98aa); }
    .status-pill.status-NO_PRODUCT_DEFINITION { background: linear-gradient(135deg, #667386, #8d98aa); }
    .status-pill.status-FOUND { background: linear-gradient(135deg, #178f52, #2fbf71); }
    .status-pill.status-INVALID_ATTRIBUTES { background: linear-gradient(135deg, #b9363d, #ef5b5b); }
    .chart {
      width: 100%;
      min-height: 460px;
    }
    .table-scroll {
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 10px;
    }
    .frontier-table th,
    .frontier-table td {
      min-width: 110px;
    }
    .frontier-note-row td {
      background: #131923;
      color: var(--soft);
      font-size: 13px;
      line-height: 1.55;
      padding: 12px 14px;
      border-top: 0;
      border-bottom: 2px solid var(--line-strong);
      min-width: 0;
    }
    .frontier-note-row td strong {
      color: var(--accent);
    }
    .note {
      color: var(--soft);
      min-width: 320px;
    }
    .interpretation {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
    }
    .interpretation p {
      margin: 0;
      padding: 15px;
      color: var(--soft);
      background: #0f141c;
      border: 1px solid var(--line);
      border-left: 4px solid var(--accent);
      border-radius: 10px;
    }
    .hidden { display: none; }
    footer {
      color: var(--muted);
      font-size: 12px;
      margin-top: 14px;
      text-align: right;
    }
    @media (max-width: 980px) {
      header { padding: 22px 18px; }
      .summary, .interpretation, .matrix-layout { grid-template-columns: 1fr; }
      .detail-panel { position: static; }
      section { padding: 14px; }
      .matrix-wrap { max-height: 620px; }
      .status-cell { min-width: 132px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>OTC Derivatives Compliance Dashboard</h1>
    <p>A read-only view of <code>output/compliance_report.json</code>: every trade across CFTC and EMIR Refit, the most common errors, asset-class compliance rates, and the prediction-market classification gap. Click any status cell for the full per-trade story.</p>
  </header>
  <main>
    <div class="summary" id="summaryMetrics"></div>

    <section>
      <div class="section-head">
        <div>
          <h2>Portfolio Compliance Heatmap</h2>
          <p class="section-note">Rows are trade IDs, columns are regimes, and each status cell is clickable. Colours: green = COMPLIANT, red = NONCOMPLIANT, amber = CONDITIONAL, grey = NOT_APPLICABLE.</p>
        </div>
      </div>
      <div class="controls" id="matrixControls"></div>
      <div class="legend" id="statusLegend"></div>
      <div class="matrix-layout">
        <div class="matrix-wrap">
          <table class="matrix-table" id="matrixTable"></table>
        </div>
        <aside id="selectedTradeDetails" class="detail-panel muted">
          Select any status cell to inspect errors, warnings, and compliance notes for that trade-regime pair.
        </aside>
      </div>
    </section>

    <section>
      <div class="section-head">
        <div>
          <h2>Error Frequency</h2>
          <p class="section-note">Horizontal bar chart of the most commonly failing fields across all trades.</p>
        </div>
      </div>
      <div id="errorChart" class="chart"></div>
    </section>

    <section>
      <div class="section-head">
        <div>
          <h2>Asset Class Breakdown</h2>
          <p class="section-note">Compliance rate grouped by asset class and regime, using reportable trades as the denominator.</p>
        </div>
      </div>
      <div id="assetChart" class="chart"></div>
    </section>

    <section>
      <div class="section-head">
        <div>
          <h2>Classification Frontier: T026-T028</h2>
          <p class="section-note">Jurisdictional asymmetry for the prediction/event contracts, including compliance note text.</p>
        </div>
      </div>
      <div id="frontierTable"></div>
    </section>

    <section>
      <h2>Interpretation</h2>
      <div class="interpretation" id="interpretation"></div>
    </section>

    <footer>Regenerated by dashboard.py</footer>
  </main>
  <script>
    let DATA = __DASHBOARD_DATA__;
    let statusOrder = DATA.status_order;
    let statusColors = DATA.status_colors;
    let activeStatuses = new Set(statusOrder);
    let activeAsset = "ALL";
    let tradeSearch = "";

    renderAll();

    function renderAll() {
      renderSummary();
      renderControls();
      renderLegend();
      renderMatrix();
      renderErrorChart();
      renderAssetChart();
      renderFrontierTable();
      renderInterpretation();
    }

    function renderSummary() {
      const summary = DATA.summary || {};
      const cftc = summary.compliance?.CFTC || {};
      const emir = summary.compliance?.EMIR || {};
      const metrics = [
        [summary.total_trades ?? DATA.matrix.length, "Trades in report"],
        [summary.novel_instruments ?? 0, "Novel instruments"],
        [cftc.CONDITIONAL ?? 0, "CFTC conditional"],
        [emir.NOT_APPLICABLE ?? 0, "EMIR not applicable"]
      ];
      document.getElementById("summaryMetrics").innerHTML = metrics.map(([value, label]) =>
        `<div class="metric"><strong>${escapeHtml(String(value))}</strong><span>${escapeHtml(label)}</span></div>`
      ).join("");
    }

    function renderControls() {
      const statusControls = statusOrder.map(status => `
        <label class="chip">
          <input type="checkbox" data-status="${escapeHtml(status)}" ${activeStatuses.has(status) ? "checked" : ""}>
          <span class="dot" style="background:${statusColors[status]}"></span>
          <span>${escapeHtml(status)}</span>
        </label>
      `).join("");
      const assetOptions = ["ALL", ...DATA.asset_classes].map(asset =>
        `<option value="${escapeHtml(asset)}" ${asset === activeAsset ? "selected" : ""}>${asset === "ALL" ? "All asset classes" : escapeHtml(asset)}</option>`
      ).join("");
      document.getElementById("matrixControls").innerHTML = `
        <span class="control-label">Status</span>
        ${statusControls}
        <span class="control-label">Asset</span>
        <select id="assetFilter" aria-label="Filter by asset class">${assetOptions}</select>
        <span class="control-label">Trade</span>
        <input id="tradeSearch" type="search" placeholder="Search T026" aria-label="Search trade ID" value="${escapeHtml(tradeSearch)}">
        <button id="resetFilters" type="button">Reset</button>
      `;
      document.querySelectorAll("#matrixControls input[data-status]").forEach(input => {
        input.addEventListener("change", () => {
          const status = input.getAttribute("data-status");
          input.checked ? activeStatuses.add(status) : activeStatuses.delete(status);
          renderMatrix();
        });
      });
      document.getElementById("assetFilter").addEventListener("change", event => {
        activeAsset = event.target.value;
        renderMatrix();
      });
      document.getElementById("tradeSearch").addEventListener("input", event => {
        tradeSearch = event.target.value.trim().toUpperCase();
        renderMatrix();
      });
      document.getElementById("resetFilters").addEventListener("click", () => {
        activeStatuses = new Set(statusOrder);
        activeAsset = "ALL";
        tradeSearch = "";
        renderControls();
        renderMatrix();
      });
    }

    function renderLegend() {
      document.getElementById("statusLegend").innerHTML = statusOrder.map(status => `
        <span><span class="dot" style="background:${statusColors[status]}"></span>${escapeHtml(status)}</span>
      `).join("");
    }

    function renderMatrix() {
      const rows = filteredRows();
      const header = `
        <thead>
          <tr>
            <th>Trade</th>
            <th>Asset Class</th>
            ${DATA.regimes.map(regime => `<th>${escapeHtml(regime)}</th>`).join("")}
          </tr>
        </thead>
      `;
      const body = rows.length
        ? rows.map(row => `
          <tr>
            <td class="trade-id">${escapeHtml(row.trade_id)}</td>
            <td class="asset">${escapeHtml(row.asset_class)}</td>
            ${DATA.regimes.map(regime => statusCell(row, regime)).join("")}
          </tr>
        `).join("")
        : `<tr><td colspan="${DATA.regimes.length + 2}" class="muted">No trades match the current filters.</td></tr>`;
      document.getElementById("matrixTable").innerHTML = `${header}<tbody>${body}</tbody>`;
      document.querySelectorAll(".status-cell").forEach(button => {
        button.addEventListener("click", () => {
          const row = DATA.matrix[Number(button.dataset.rowIndex)];
          const result = row.regimes[button.dataset.regime];
          renderSelectedTrade(row, button.dataset.regime, result);
        });
      });
    }

    function statusCell(row, regime) {
      const result = row.regimes[regime];
      const status = result.status || "UNKNOWN";
      const issueCount = (result.errors?.length || 0) + (result.warnings?.length || 0);
      const issueText = issueCount ? `${issueCount} note${issueCount === 1 ? "" : "s"}` : "clear";
      return `
        <td>
          <button class="status-cell status-${escapeHtml(status)}" data-row-index="${DATA.matrix.indexOf(row)}" data-regime="${escapeHtml(regime)}">
            <span>${escapeHtml(status)}</span>
            <small>${escapeHtml(issueText)}</small>
          </button>
        </td>
      `;
    }

    function filteredRows() {
      return DATA.matrix.filter(row => {
        const assetMatches = activeAsset === "ALL" || row.asset_class === activeAsset;
        const searchMatches = !tradeSearch || row.trade_id.toUpperCase().includes(tradeSearch);
        const statusMatches = Object.values(row.regimes).some(result => activeStatuses.has(result.status));
        return assetMatches && searchMatches && statusMatches;
      });
    }

    function renderSelectedTrade(row, regime, result) {
      const errors = listBlock("Errors", result.errors);
      const warnings = listBlock("Warnings", result.warnings);
      const failed = result.failed_fields?.length ? result.failed_fields.join(", ") : "None";
      const panel = document.getElementById("selectedTradeDetails");
      panel.classList.remove("muted");
      panel.innerHTML = `
        <h3>${escapeHtml(row.trade_id)} / ${escapeHtml(regime)} ${statusPill(result.status)}</h3>
        <p><strong>Asset class:</strong> ${escapeHtml(row.asset_class)}</p>
        <p><strong>Instrument:</strong> ${escapeHtml(row.instrument_type)} / ${escapeHtml(row.use_case)}</p>
        <p><strong>UPI lookup:</strong> ${statusPill(row.upi_status)}</p>
        <p><strong>Classification flag:</strong> ${escapeHtml(row.classification_flag)}</p>
        <p><strong>Event description:</strong> ${escapeHtml(row.description || "None")}</p>
        <p><strong>Failed fields:</strong> ${escapeHtml(failed)}</p>
        <p><strong>Note:</strong> ${escapeHtml(result.note || "No note.")}</p>
        ${row.upi_classification_note ? `<p><strong>UPI note:</strong> ${escapeHtml(row.upi_classification_note)}</p>` : ""}
        ${errors}
        ${warnings}
      `;
    }

    function listBlock(title, items) {
      if (!items || !items.length) {
        return `<p class="muted">No ${title.toLowerCase()}.</p>`;
      }
      return `<h3>${escapeHtml(title)}</h3><ul>${items.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
    }

    function renderErrorChart() {
      const rows = DATA.error_frequency;
      const trace = {
        type: "bar",
        orientation: "h",
        x: rows.map(row => row.count),
        y: rows.map(row => row.field),
        text: rows.map(row => String(row.count)),
        textposition: "outside",
        cliponaxis: false,
        marker: {color: "#ef5b5b"},
        hovertemplate: "%{y}<br>Failures: %{x}<extra></extra>"
      };
      const layout = darkLayout({
        margin: {l: 230, r: 70, t: 16, b: 48},
        height: Math.max(430, rows.length * 42 + 110),
        xaxis: {title: "Failure count", rangemode: "tozero", fixedrange: true},
        yaxis: {autorange: "reversed", automargin: true}
      });
      Plotly.newPlot("errorChart", [trace], layout, {responsive: true, displayModeBar: false});
    }

    function renderAssetChart() {
      const rows = DATA.asset_breakdown;
      const assets = [...new Set(rows.map(row => row.asset_class))];
      const traces = DATA.regimes.map(regime => {
        const byAsset = Object.fromEntries(rows.filter(row => row.regime === regime).map(row => [row.asset_class, row]));
        return {
          type: "bar",
          orientation: "h",
          name: regime,
          y: assets,
          x: assets.map(asset => byAsset[asset]?.compliance_rate ?? 0),
          text: assets.map(asset => {
            const rate = byAsset[asset]?.compliance_rate;
            return rate === null || rate === undefined ? "N/A" : `${Math.round(rate * 100)}%`;
          }),
          textposition: "outside",
          cliponaxis: false,
          customdata: assets.map(asset => byAsset[asset] || {}),
          hovertemplate: "%{y} / " + regime + "<br>Compliance rate: %{x:.1%}<br>%{customdata.label}<extra></extra>"
        };
      });
      const layout = darkLayout({
        barmode: "group",
        margin: {l: 150, r: 90, t: 56, b: 60},
        height: 500,
        xaxis: {title: "Compliance rate", tickformat: ".0%", range: [0, 1.15], fixedrange: true},
        yaxis: {automargin: true},
        legend: {orientation: "h", x: 0, y: 1.12}
      });
      Plotly.newPlot("assetChart", traces, layout, {responsive: true, displayModeBar: false});
    }

    function darkLayout(extra) {
      return {
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        font: {color: "#d7deea", family: "Arial, Helvetica, sans-serif"},
        hoverlabel: {align: "left", bgcolor: "#111827", bordercolor: "#4cc9a7", font: {color: "#eef2f7"}},
        xaxis: {gridcolor: "#303846", zerolinecolor: "#303846", tickfont: {color: "#d7deea"}, titlefont: {color: "#d7deea"}},
        yaxis: {gridcolor: "#303846", zerolinecolor: "#303846", tickfont: {color: "#d7deea"}, titlefont: {color: "#d7deea"}},
        ...extra,
        xaxis: {...{gridcolor: "#303846", zerolinecolor: "#303846", tickfont: {color: "#d7deea"}, titlefont: {color: "#d7deea"}}, ...(extra.xaxis || {})},
        yaxis: {...{gridcolor: "#303846", zerolinecolor: "#303846", tickfont: {color: "#d7deea"}, titlefont: {color: "#d7deea"}}, ...(extra.yaxis || {})}
      };
    }

    function renderFrontierTable() {
      const rows = DATA.frontier;
      const htmlRows = rows.map(row => {
        const note = row.classification_note
          ? `<tr class="frontier-note-row">
               <td colspan="7"><strong>UPI classification note:</strong> ${escapeHtml(row.classification_note)}</td>
             </tr>`
          : "";
        return `
          <tr>
            <td><strong>${escapeHtml(row.trade_id)}</strong></td>
            <td>${escapeHtml(row.platform || "")}</td>
            <td>${escapeHtml(row.event_type || "")}</td>
            <td>${statusPill(row.cftc_status)}</td>
            <td class="note">${escapeHtml(row.cftc_note || "")}</td>
            <td>${statusPill(row.emir_status)}</td>
            <td class="note">${escapeHtml(row.emir_note || "")}</td>
          </tr>
          ${note}
        `;
      }).join("");
      document.getElementById("frontierTable").innerHTML = `
        <div class="table-scroll">
          <table class="frontier-table">
            <thead>
              <tr>
                <th>Trade</th>
                <th>Platform</th>
                <th>Event Type</th>
                <th>CFTC</th>
                <th>CFTC Note</th>
                <th>EMIR</th>
                <th>EMIR Note</th>
              </tr>
            </thead>
            <tbody>${htmlRows}</tbody>
          </table>
        </div>
      `;
    }

    function renderInterpretation() {
      document.getElementById("interpretation").innerHTML = DATA.interpretation.map(text =>
        `<p>${escapeHtml(text)}</p>`
      ).join("");
    }

    function statusPill(status) {
      return `<span class="status-pill status-${escapeHtml(status || "UNKNOWN")}">${escapeHtml(status || "UNKNOWN")}</span>`;
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
