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
