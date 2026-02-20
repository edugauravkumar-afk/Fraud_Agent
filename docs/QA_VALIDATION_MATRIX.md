# QA Validation Matrix

Date: 2026-02-20

This matrix validates critical fraud-policy behavior in the manual review engine.

## Cases

| Case | Scenario | Expected | Actual | Status |
|---|---|---|---|---|
| QA-01 | Midnight boundary timezone (23:50 vs 00:10 same offset) | No false mismatch flag; should not reject on time math | Approve, `clock delta=20 min`, mismatch rule clear | PASS |
| QA-02 | Large time mismatch + missing URL | Must not approve; enforce URL hold | Conditional Approval - Hold for URL Verification | PASS |
| QA-03 | Outsourced enterprise profile (US business + India +5:30) | No hard reject solely on outsourced pattern; route safely if mixed signals | Route to Human VIP Sales (outsourced exemption recognized, >1h mismatch flagged) | PASS |

## Evidence Files

- `qa_case_midnight_boundary.json`
- `qa_case_url_missing_time_mismatch.json`
- `qa_case_outsourced_enterprise.json`

## Repro Commands

```bash
source .venv/bin/activate
python fraud_review_engine.py --input qa_case_midnight_boundary.json --no-web-checks --json
python fraud_review_engine.py --input qa_case_url_missing_time_mismatch.json --no-web-checks --json
python fraud_review_engine.py --input qa_case_outsourced_enterprise.json --no-web-checks --json
```

## Notes

- Midnight-delta fix is verified (`clock delta` now uses circular 24-hour difference).
- Missing URL still enforces mandatory hold.
- Outsourced exemption avoids blind rejection while preserving manual review for major time mismatch.
