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

Dependency coverage:

- `requests` (HTTP requests) -> in `requirements.txt`
- `beautifulsoup4` (HTML parsing) -> in `requirements.txt`
- `python-whois` (WHOIS lookups) -> in `requirements-optional.txt`
- `ipaddress` (IP validation) -> Python standard library (no pip install needed)
- Python `3.10+` required (uses modern type-hint syntax)

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
- Adds a detailed Decision Summary explaining:
	- why the account can be approved,
	- why the account can be rejected,
	- why the final verdict was selected,
	- confidence score and confidence level.

### Advanced Fraud-Specific Checks (Optional)

You can enable real external checks individually:

- ScamAdviser API integration
- LinkedIn API professional verification
- SSL certificate validation
- Social media presence checking
- Business registry lookup (OpenCorporates)
- Machine-learning risk scoring (API or local joblib model)

Run all advanced checks:

```bash
python3 fraud_review_engine.py \
	--input sample_account_summary.json \
	--use-advanced-checks \
	--enable-scamadviser --enable-linkedin --enable-ssl --enable-social --enable-registry --enable-ml \
	--json
```

Environment variables for real integrations:

- `SCAMADVISER_API_URL`, `SCAMADVISER_API_KEY` (optional: `SCAMADVISER_URL_PARAM`)
- `LINKEDIN_API_URL`, `LINKEDIN_ACCESS_TOKEN`
- `OPENCORPORATES_API_TOKEN` (optional for higher limits)
- `ML_RISK_API_URL`, `ML_RISK_API_KEY` (or pass `--ml-model-path path/to/model.joblib`)

If these are not configured, the engine does not crash; it marks external intelligence as partial and routes uncertainty appropriately.

### New Mandatory Guardrails

- Strict time extraction: report Local Browser Time, Network IP Time, and exact math difference.
- If local vs network clock difference is greater than 1 hour, force location/proxy mismatch flag.
- If Item URL is missing, approval is blocked and verdict becomes:
	- `Conditional Approval - Hold for URL Verification`

### Fraud-Specific OSINT Reliability Controls

The engine explicitly handles common OSINT limitations so noisy signals do not create false positives:

- WHOIS data incomplete/privacy-protected:
	- Treated as uncertainty, not direct fraud proof.
	- AFOSINT scoring is softened when WHOIS status is unknown/protected.
- Web scraping depends on website structure:
	- Marks low-text pages as `scraping-limited`.
	- Avoids overconfident decisions from partial extraction.
- IP geolocation accuracy varies by provider:
	- IP mismatches are flagged but interpreted cautiously.
- Rate limits on external services:
	- HTTP `429` is detected as `rate-limited` and degrades confidence instead of forcing rejection.
- Dynamic JavaScript-rendered pages:
	- Script-heavy/low-visible-text pages are marked as dynamic content likely.
	- Positive approvals are downgraded to VIP/manual when uncertainty is high.
