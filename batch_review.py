from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, cast

from fraud_review_engine import AccountSummary, review_account
from policy_config import load_policy_config


def _read_accounts(path: str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    suffix = p.suffix.lower()
    if suffix == ".json":
        payload = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return [cast(dict[str, Any], payload)]
        if isinstance(payload, list):
            payload_items = cast(list[Any], payload)
            rows: list[dict[str, Any]] = []
            for item in payload_items:
                if isinstance(item, dict):
                    rows.append(cast(dict[str, Any], item))
            return rows
        raise ValueError("JSON input must be an object or array of objects")

    if suffix == ".jsonl":
        rows: list[dict[str, Any]] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(cast(dict[str, Any], obj))
        return rows

    if suffix == ".csv":
        with p.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = []
            for row in reader:
                clean: dict[str, Any] = {k: v for k, v in row.items()}
                if clean.get("item_urls"):
                    clean["item_urls"] = [url.strip() for url in clean["item_urls"].split("|") if url.strip()]
                else:
                    clean["item_urls"] = []
                if clean.get("ip_addresses"):
                    ips = [value.strip() for value in clean["ip_addresses"].split("|") if value.strip()]
                    clean["ip_addresses"] = [{"ip": ip, "country": clean.get("network_country", "")} for ip in ips]
                else:
                    clean["ip_addresses"] = []
                rows.append(clean)
            return rows

    raise ValueError("Supported input formats: .json, .jsonl, .csv")


def _to_queue_row(idx: int, source: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    summary_any: Any = result.get("decision_summary", {}) or {}
    summary = cast(dict[str, Any], summary_any if isinstance(summary_any, dict) else {})
    return {
        "row_id": idx,
        "name": source.get("name", ""),
        "email": source.get("email", ""),
        "company_name": source.get("company_name", ""),
        "ml_score": source.get("ml_score", ""),
        "verdict": result.get("verdict", ""),
        "confidence_score": summary.get("confidence_score", ""),
        "confidence_level": summary.get("confidence_level", ""),
        "tags": "|".join(result.get("tags", [])),
        "final_reason": summary.get("final_reason", ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch fraud review queue generator")
    parser.add_argument("--input", required=True, help="Path to .json, .jsonl, or .csv account file")
    parser.add_argument("--output", required=True, help="Path to output .csv queue file")
    parser.add_argument("--policy", default="fraud_policy.json", help="Path to policy config JSON")
    parser.add_argument("--no-web-checks", action="store_true", help="Disable URL content fetching")
    parser.add_argument("--use-afosint", action="store_true", help="Enable AFOSINT checks")
    parser.add_argument("--use-advanced-checks", action="store_true", help="Enable advanced external checks")
    parser.add_argument("--enable-scamadviser", action="store_true")
    parser.add_argument("--enable-linkedin", action="store_true")
    parser.add_argument("--enable-ssl", action="store_true")
    parser.add_argument("--enable-social", action="store_true")
    parser.add_argument("--enable-registry", action="store_true")
    parser.add_argument("--enable-ml", action="store_true")
    parser.add_argument("--ml-model-path", default=None)
    args = parser.parse_args()

    policy = load_policy_config(args.policy)
    accounts = _read_accounts(args.input)

    queue_rows: list[dict[str, Any]] = []
    for idx, payload in enumerate(accounts, start=1):
        account = AccountSummary.from_dict(payload)
        result = review_account(
            account,
            enable_web_checks=not args.no_web_checks,
            use_afosint=args.use_afosint,
            use_advanced_checks=args.use_advanced_checks,
            enable_scamadviser=args.enable_scamadviser,
            enable_linkedin=args.enable_linkedin,
            enable_ssl=args.enable_ssl,
            enable_social=args.enable_social,
            enable_registry=args.enable_registry,
            enable_ml=args.enable_ml,
            ml_model_path=args.ml_model_path,
            policy=policy,
        )
        queue_rows.append(_to_queue_row(idx, payload, result))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "row_id",
        "name",
        "email",
        "company_name",
        "ml_score",
        "verdict",
        "confidence_score",
        "confidence_level",
        "tags",
        "final_reason",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(queue_rows)

    print(f"Processed {len(queue_rows)} account(s) -> {output_path}")


if __name__ == "__main__":
    main()
