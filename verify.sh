#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "============================================================"
echo " MH6822 Verify - install + tests + engine"
echo "============================================================"

python_cmd="${PYTHON:-python3}"
if ! command -v "$python_cmd" >/dev/null 2>&1; then
    if command -v python >/dev/null 2>&1; then
        python_cmd=python
    else
        echo "Python 3.11+ not found on PATH." >&2
        exit 1
    fi
fi

echo "Step 1 of 3: Installing dependencies..."
"$python_cmd" -m pip install -r requirements.txt

echo
echo "Step 2 of 3: Running unit tests..."
"$python_cmd" -m unittest discover -s tests -v

echo
echo "Step 3 of 3: Running the compliance engine on trades.json..."
"$python_cmd" run_compliance_check.py --input trades.json --regimes CFTC,EMIR

echo
echo "Verify completed successfully. See output/compliance_report.json."
