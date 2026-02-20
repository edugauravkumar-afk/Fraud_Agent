#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -d ".venv" ]]; then
  echo "[ERROR] .venv not found. Create it first:"
  echo "  python3 -m venv .venv && source .venv/bin/activate && python -m pip install -r requirements.txt"
  exit 1
fi

source .venv/bin/activate

CASES=(
  "qa_case_midnight_boundary.json"
  "qa_case_url_missing_time_mismatch.json"
  "qa_case_outsourced_enterprise.json"
)

EXPECTED=(
  "Approve"
  "Conditional Approval - Hold for URL Verification"
  "Route to Human VIP Sales"
)

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

printf "\nFraud Agent QA Run\n"
printf "===================\n\n"
printf "%-4s | %-42s | %-45s | %-45s | %-5s\n" "ID" "CASE" "EXPECTED" "ACTUAL" "PASS?"
printf "%.0s-" {1..154}
printf "\n"

all_pass=true
for i in "${!CASES[@]}"; do
  case_file="${CASES[$i]}"
  expected="${EXPECTED[$i]}"
  out_json="$TMP_DIR/case_$i.json"

  python fraud_review_engine.py --input "$case_file" --no-web-checks --json > "$out_json"

  actual="$(python - <<'PY' "$out_json"
import json,sys
with open(sys.argv[1], 'r', encoding='utf-8') as f:
    d=json.load(f)
print(d.get('verdict',''))
PY
)"

  pass="YES"
  if [[ "$actual" != "$expected" ]]; then
    pass="NO"
    all_pass=false
  fi

  printf "%-4s | %-42s | %-45s | %-45s | %-5s\n" "Q$((i+1))" "$case_file" "$expected" "$actual" "$pass"
done

printf "\n"
if [[ "$all_pass" == true ]]; then
  echo "RESULT: PASS (all QA fixtures matched expected verdicts)"
  exit 0
else
  echo "RESULT: FAIL (one or more fixtures diverged)"
  exit 2
fi
