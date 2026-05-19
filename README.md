# OTC Derivatives Compliance Engine

This repository implements the MH6822 Homework 2 compliance engine for OTC
derivatives reporting and prediction-market classification. The runner parses
the provided trade portfolio, appends the five additional designed trades,
matches conventional derivatives against the ANNA-DSB UPI product definition
library, and checks reporting obligations under CFTC and EMIR Refit.

## Included Work

- Module 1: trade parser and instrument classifier.
- Module 2: ANNA-DSB UPI lookup and product-attribute validation.
- Module 3: CFTC and EMIR Refit compliance checker.
- Module 4: written classification analysis in `Final_Report.docx`, with a
  proposed EventContract schema in `EventContract_UPI_Schema.json`.
- Module 5 bonus: browser dashboard generated from the compliance report.
- Tests for parser resilience, UPI lookup, compliance checks, dashboard data,
  and pipeline snapshot outcomes.

## How To Run

From this directory:

```powershell
pip install -r requirements.txt
python run_compliance_check.py --input trades.json --regimes CFTC,EMIR
```

By default, the runner appends `additional_trades.json` when that file is
present. The output therefore covers:

- 28 provided trades from `trades.json`
- 5 additional designed trades from `additional_trades.json`
- 33 total trades in `output/compliance_report.json`

To run only the provided portfolio, pass an empty additional input:

```powershell
python run_compliance_check.py --input trades.json --regimes CFTC,EMIR --additional-input ""
```

The runner writes:

```text
output/compliance_report.json
```

## Current Integrated Result

Default full-run output when `additional_trades.json` is included:

```text
Parsed 33 trades
Included 5 additional trades
UPI summary: {'FOUND': 23, 'INVALID_ATTRIBUTES': 5, 'NO_PRODUCT_DEFINITION': 5}
Compliance summary: {'CFTC': {'NONCOMPLIANT': 25, 'COMPLIANT': 3, 'CONDITIONAL': 3, 'NOT_APPLICABLE': 2}, 'EMIR': {'NONCOMPLIANT': 27, 'NOT_APPLICABLE': 5, 'COMPLIANT': 1}}
```

Module 1 surfaces:

- Parser status counts: `SUCCESS / PARTIAL / FAILED`.
- Novel-instrument count: T026-T028 plus additional event contracts T029-T030.
- Per-trade `effective_date_status` and `maturity_date_status`; for example,
  T021's `9999-99-99` maturity date is flagged as `PARTIAL`.

Module 2 surfaces:

- UPI status counts across `FOUND / INVALID_ATTRIBUTES / NOT_FOUND /
  NO_PRODUCT_DEFINITION / BAD_INPUT`.
- A `derived_fields` audit trail on every matched trade naming values inferred
  from raw fields, defaulted, aliased, or dropped.
- Warning messages when the engine has to default required template attributes
  or when a legacy LIBOR reference rate appears.

Key findings:

- T005 matches a DSB template but raises a LIBOR warning.
- T009 fails because `INVALID_CCY` is not an ISO 4217 currency code.
- T008, T011, T013, and T021 fail because of missing or out-of-enum UPI
  product attributes.
- T026-T030 event contracts return `NO_PRODUCT_DEFINITION`, showing the
  classification gap for prediction/event contracts.
- T026, T028, and T029 are `CONDITIONAL` under CFTC because they are modelled
  as CFTC-regulated DCM event contracts; T027 and T030 are not applicable under
  CFTC. All five event contracts are not applicable under EMIR in this model.

## Tests

From this directory:

```powershell
python -m unittest discover -s tests -v
```

## One-Shot Verify

To install dependencies, run tests, and regenerate the compliance report:

```powershell
verify.bat
```

On macOS / Linux:

```bash
bash verify.sh
```

## Dashboard

Module 5 is implemented as a browser dashboard generated from
`output/compliance_report.json`. The dashboard is a read-only renderer of
that file: it produces the four required visualisations (compliance heatmap,
error-frequency bar, asset-class breakdown, classification frontier for
T026-T028 with the full UPI classification-note text) plus three paragraphs
of written interpretation. To refresh the underlying data, re-run
`run_compliance_check.py` first.

Windows:

```text
START_DASHBOARD.bat
```

This installs dependencies, regenerates the 33-trade compliance report, writes
`output/dashboard.html`, starts a local server, and opens the dashboard in the
browser.

Command line:

```powershell
python dashboard.py
```

To regenerate the HTML without starting the local server:

```powershell
python dashboard.py --no-serve
```

This writes:

```text
output/dashboard.html
```

## Submission Note

The report, source code, DSB product definitions, test suite, regenerated
compliance report, additional trade file, proposed EventContract schema, and
dashboard are included in this repository. The recorded-presentation link
should be added separately before submission.
