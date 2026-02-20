# Fraud_Agent

Revenue protection prompt and workflow for ad network compliance review.

## Prompt Spec

Use the full operating prompt in:

- `docs/FRAUD_REVIEW_AGENT_PROMPT.md`

## Intended Use

- Paste the prompt into your review agent system message.
- Feed each case as an `Account Summary` block.
- Require strict output format:
	- Verdict
	- Deep Analysis (Timezone/GEO, Identity/Payment, Domain/Policy)
	- False Positive Check
	- Internal Note Summary
	- Tags

## Goal

Maximize legitimate approvals while minimizing fraud losses and avoiding false positives.

## Manual Review Decision Engine (ML Band 30-85)

This repo now includes a Python decision engine for the critical manual-review range:

- `ML < 30` => Auto Approve
- `ML > 85` => Auto Reject
- `30 <= ML <= 85` => Deep contextual analysis with false-positive exemptions

### Files

- `fraud_review_engine.py` - main decision engine + strict report formatter
- `afosint_integration.py` - optional AFOSINT adapter with graceful fallback
- `sample_account_summary.json` - sample account payload
- `requirements.txt` - required Python packages
- `requirements-optional.txt` - optional AFOSINT package list

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### Run

```bash
python3 fraud_review_engine.py --input sample_account_summary.json
```

Optional (skip live URL fetch checks):

```bash
python3 fraud_review_engine.py --input sample_account_summary.json --no-web-checks
```

Raw JSON output:

```bash
python3 fraud_review_engine.py --input sample_account_summary.json --json
```

### AFOSINT Integration (Optional)

Install optional package(s):

```bash
python -m pip install -r requirements-optional.txt
```

Run with AFOSINT comprehensive check enabled:

```bash
python3 fraud_review_engine.py --input sample_account_summary.json --use-afosint --json
```

Enable AFOSINT web searches (deeper checks, slower):

```bash
python3 fraud_review_engine.py --input sample_account_summary.json --use-afosint --afosint-web-searches
```

Run AFOSINT in mock mode for tests:

```bash
python3 fraud_review_engine.py --input sample_account_summary.json --use-afosint --afosint-mock-mode
```

### Why this helps

- Adds structured checks for timezone/GEO, email trust, identity-payment linkage, and content-cloaking patterns.
- Explicitly enforces false-positive exemptions (outsourced agencies, enterprise domains, family/corporate cards).
- Produces consistent analyst-ready output for CRM logging and audits.

### New Mandatory Guardrails

- Strict time extraction: report Local Browser Time, Network IP Time, and exact math difference.
- If local vs network clock difference is greater than 1 hour, force location/proxy mismatch flag.
- If Item URL is missing, approval is blocked and verdict becomes:
	- `Conditional Approval - Hold for URL Verification`
