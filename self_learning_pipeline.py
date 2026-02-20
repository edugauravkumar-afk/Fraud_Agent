from __future__ import annotations

import argparse
import json
from typing import Any, cast

from self_learning import append_feedback_record, should_retrain, train_from_feedback


def cmd_add_feedback(args: argparse.Namespace) -> None:
    with open(args.account, "r", encoding="utf-8") as handle:
        account_payload_any: Any = json.load(handle)
    account_payload = cast(dict[str, Any], account_payload_any if isinstance(account_payload_any, dict) else {})

    context: dict[str, Any] = {}
    if args.context:
        with open(args.context, "r", encoding="utf-8") as handle:
            payload_any: Any = json.load(handle)
            payload = cast(dict[str, Any], payload_any if isinstance(payload_any, dict) else {})
            context = payload

    append_feedback_record(
        feedback_jsonl=args.feedback_data,
        account=account_payload,
        final_verdict=args.final_verdict,
        context=context,
        metadata={
            "source": args.source,
            "review_id": args.review_id,
        },
    )
    print(f"Feedback appended to {args.feedback_data}")


def cmd_auto_train(args: argparse.Namespace) -> None:
    decision = should_retrain(
        feedback_jsonl=args.feedback_data,
        model_path=args.model_path,
        min_new_records=args.min_new_records,
    )
    if not decision.get("should_retrain"):
        print(json.dumps({"trained": False, "decision": decision}, indent=2, ensure_ascii=False))
        return

    trained = train_from_feedback(
        feedback_jsonl=args.feedback_data,
        model_path=args.model_path,
    )
    print(json.dumps({"trained": True, "decision": decision, "result": trained}, indent=2, ensure_ascii=False))


def cmd_train(args: argparse.Namespace) -> None:
    result = train_from_feedback(
        feedback_jsonl=args.feedback_data,
        model_path=args.model_path,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Self-learning fraud model pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_feedback = subparsers.add_parser("add-feedback", help="Append one reviewed account outcome")
    add_feedback.add_argument("--account", required=True, help="Path to account JSON used during review")
    add_feedback.add_argument(
        "--final-verdict",
        required=True,
        choices=[
            "Approve",
            "Reject",
            "Route to Human VIP Sales",
            "Conditional Approval - Hold for URL Verification",
        ],
        help="Final human-reviewed verdict",
    )
    add_feedback.add_argument(
        "--feedback-data",
        default="data/review_feedback.jsonl",
        help="Feedback JSONL store path",
    )
    add_feedback.add_argument(
        "--context",
        default=None,
        help="Optional JSON file with numeric context fields used for training features",
    )
    add_feedback.add_argument(
        "--source",
        default="manual-review",
        help="Origin of the feedback record",
    )
    add_feedback.add_argument(
        "--review-id",
        default=None,
        help="Optional external review/audit identifier",
    )
    add_feedback.set_defaults(func=cmd_add_feedback)

    train = subparsers.add_parser("train", help="Train/retrain model from accumulated feedback")
    train.add_argument(
        "--feedback-data",
        default="data/review_feedback.jsonl",
        help="Feedback JSONL store path",
    )
    train.add_argument(
        "--model-path",
        default="models/self_learning_model.joblib",
        help="Output model artifact path",
    )
    train.set_defaults(func=cmd_train)

    auto_train = subparsers.add_parser("auto-train", help="Train only when enough new feedback has accumulated")
    auto_train.add_argument(
        "--feedback-data",
        default="data/review_feedback.jsonl",
        help="Feedback JSONL store path",
    )
    auto_train.add_argument(
        "--model-path",
        default="models/self_learning_model.joblib",
        help="Model artifact path",
    )
    auto_train.add_argument(
        "--min-new-records",
        type=int,
        default=25,
        help="Minimum new feedback records since last training to trigger retrain",
    )
    auto_train.set_defaults(func=cmd_auto_train)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
