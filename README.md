# Fraud_Agent

Revenue protection prompt and workflow for ad network compliance review.

## Prompt Spec

Use the full operating prompt in:

- `docs/FRAUD_REVIEW_AGENT_PROMPT.md`
- `docs/QA_VALIDATION_MATRIX.md` (alignment test cases + expected outcomes)

## One-Command QA Runner

Run all alignment fixtures and print pass/fail:

```bash
./qa_run.sh
```

This validates expected verdict behavior for:

- Midnight boundary time math
- Missing URL mandatory hold
- Outsourced enterprise exemption routing

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
- `advanced_external_checks.py` - optional advanced external intelligence checks
- `policy_config.py` - policy thresholds loader
- `fraud_policy.json` - default policy thresholds
- `batch_review.py` - batch queue generator for multi-account review
- `self_learning.py` - self-learning feature extraction, inference, and training helpers
- `self_learning_pipeline.py` - feedback append + model training CLI
- `.env.example` - external API configuration template
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
python3 fraud_review_engine.py --input sample_account_summary.json --policy fraud_policy.json
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

### Policy Configuration

Tune thresholds in `fraud_policy.json` without changing code:

- `ml_auto_approve_threshold`
- `ml_auto_reject_threshold`
- `clock_mismatch_minutes_threshold`
- `reject_risk_threshold`
- `approve_risk_threshold`
- `approve_positive_signals_threshold`

Use custom policy file:

```bash
python3 fraud_review_engine.py --input sample_account_summary.json --policy fraud_policy.json
```

### Batch Review Queue

Process many accounts from `.json`, `.jsonl`, or `.csv` and generate a reviewer queue CSV:

```bash
python3 batch_review.py \
	--input accounts.jsonl \
	--output out/review_queue.csv \
	--policy fraud_policy.json \
	--no-web-checks
```

CSV input notes:

- `item_urls`: separate multiple URLs with `|`
- `ip_addresses`: separate multiple IPs with `|`

### Self-Learning Decision Model (Human Feedback Loop)

The agent supports controlled self-learning from reviewed outcomes:

1) Append reviewed outcomes to feedback store:

```bash
python3 self_learning_pipeline.py add-feedback \
	--account sample_account_summary.json \
	--final-verdict "Route to Human VIP Sales" \
	--source "analyst-review" \
	--review-id "BS-1995001" \
	--feedback-data data/review_feedback.jsonl
```

2) Train/retrain model from feedback:

```bash
python3 self_learning_pipeline.py train \
	--feedback-data data/review_feedback.jsonl \
	--model-path models/self_learning_model.joblib
```

Optional auto-train (retrain only when enough new feedback accumulates):

```bash
python3 self_learning_pipeline.py auto-train \
	--feedback-data data/review_feedback.jsonl \
	--model-path models/self_learning_model.joblib \
	--min-new-records 25
```

3) Use model during review (conservative risk adjustment):

```bash
python3 fraud_review_engine.py \
	--input sample_account_summary.json \
	--use-self-learning \
	--self-learning-model-path models/self_learning_model.joblib \
	--json
```

Safety design:

- Hard guardrails (URL missing hold, shell/geo rules, thresholds) remain active.
- Self-learning only adjusts risk score conservatively; it does not bypass mandatory checks.
- Training now enforces minimum sample count and class balance to reduce overfitting.
- Model artifacts store metadata (`trained_at`, class counts, feedback line count) for controlled retraining.

### CI Automation

QA alignment runs automatically on every push/PR via:

- `.github/workflows/qa.yml`

### New Mandatory Guardrails

- Strict time extraction: report Local Browser Time, Network IP Time, and exact math difference.
- If local vs network clock difference is greater than 1 hour, force location/proxy mismatch flag.
- If Item URL is missing, approval is blocked and verdict becomes:
	- `Conditional Approval - Hold for URL Verification`
- If URL resolves to dead HTTP status (`4xx/5xx`), account is treated as high-risk and cannot be approved.

Additional decision signals integrated:

- `cc_type` weighting:
	- `credit` lowers risk slightly (stronger KYC profile)
	- `debit/prepaid` increases risk
- Landing-page thematic mismatch detection:
	- URL intent (e.g., investment) vs page content intent (e.g., dating/scholarship)
	- mismatch contributes cloaking/bait-switch risk

- Fuzzy identity validation (Account Name vs Card Owner):
	- exact match => normal scoring
	- complete mismatch => hard reject (unless explicit regional corporate-card exemption)
	- fuzzy match (typo/transliteration/nickname, e.g. Olga/Olha, Jon/John):
		- with missing/invalid URL or email-age score <= 3 => hard reject
		- with valid URL and aged email => route to manual VIP review (never blind auto-approve)

- Verified legal-director override:
	- If `legal_director_verified=true` and account/card names exactly match and card network is tier-1 (`visa/mastercard/amex`) and URL/email domain are coherent,
	- then a single noisy email-validation anomaly can be overridden conservatively,
	- and parent/subsidiary company-vs-domain mismatch penalties are softened.

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
