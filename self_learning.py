from __future__ import annotations

import json
import importlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, cast

from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import SGDClassifier


LABEL_MAP = {
    "approve": 0,
    "route to human vip sales": 0,
    "conditional approval - hold for url verification": 0,
    "reject": 1,
}

MIN_TRAINING_ROWS = 20
MIN_CLASS_ROWS = 5


def normalize_verdict_label(label: str) -> int:
    key = label.strip().lower()
    if key not in LABEL_MAP:
        raise ValueError(f"Unsupported verdict label: {label}")
    return LABEL_MAP[key]


def _joblib_module() -> Any:
    return importlib.import_module("joblib")


def _iter_feedback_records(feedback_file: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in feedback_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj_any: Any = json.loads(line)
        obj = cast(dict[str, Any], obj_any if isinstance(obj_any, dict) else {})
        records.append(obj)
    return records


def _count_feedback_lines(feedback_file: Path) -> int:
    return len([line for line in feedback_file.read_text(encoding="utf-8").splitlines() if line.strip()])


def build_feature_dict(account: dict[str, Any], context: dict[str, Any]) -> dict[str, float]:
    email = str(account.get("email", ""))
    email_domain = email.split("@")[-1] if "@" in email else ""
    item_urls_any = account.get("item_urls", [])
    item_urls: list[Any] = cast(list[Any], item_urls_any if isinstance(item_urls_any, list) else [])

    return {
        "ml_score": float(account.get("ml_score", 0.0) or 0.0),
        "has_urls": 1.0 if len(item_urls) > 0 else 0.0,
        "url_count": float(len(item_urls)),
        "clock_diff_minutes": float(context.get("clock_diff_minutes", 0.0)),
        "offset_diff_minutes": float(context.get("offset_diff_minutes", 0.0)),
        "risk_score_before_learning": float(context.get("risk_score", 0.0)),
        "positive_signals": float(context.get("positive_signals", 0.0)),
        "uncertainty_signals": float(context.get("uncertainty_signals", 0.0)),
        "email_domain_free_provider": 1.0 if email_domain in {
            "gmail.com",
            "yahoo.com",
            "outlook.com",
            "hotmail.com",
            "icloud.com",
            "aol.com",
            "protonmail.com",
            "pm.me",
            "tutanota.com",
        } else 0.0,
    }


def predict_reject_probability(model_path: str, features: dict[str, float]) -> dict[str, Any]:
    model_file = Path(model_path)
    if not model_file.exists():
        return {
            "available": False,
            "error": f"model not found: {model_path}",
            "reject_probability": None,
        }
    joblib = _joblib_module()
    artifact_any: Any = joblib.load(model_file)
    artifact = cast(dict[str, Any], artifact_any if isinstance(artifact_any, dict) else {})
    vectorizer: Any = artifact["vectorizer"]
    classifier: Any = artifact["classifier"]

    x: Any = vectorizer.transform(cast(Any, [features]))
    if hasattr(classifier, "predict_proba"):
        reject_prob = float(classifier.predict_proba(x)[0][1])
    else:
        score = float(classifier.decision_function(x)[0])
        reject_prob = 1.0 / (1.0 + pow(2.718281828, -score))

    model_meta_any = artifact.get("metadata", {})
    model_meta = cast(dict[str, Any], model_meta_any if isinstance(model_meta_any, dict) else {})

    return {
        "available": True,
        "error": None,
        "reject_probability": reject_prob,
        "model_metadata": model_meta,
    }


def train_from_feedback(feedback_jsonl: str, model_path: str) -> dict[str, Any]:
    feedback_file = Path(feedback_jsonl)
    if not feedback_file.exists():
        raise FileNotFoundError(f"Feedback file not found: {feedback_jsonl}")

    records = _iter_feedback_records(feedback_file)

    if len(records) < MIN_TRAINING_ROWS:
        raise ValueError(f"Need at least {MIN_TRAINING_ROWS} feedback records to train a stable self-learning model")

    x_rows: list[dict[str, float]] = []
    y_rows: list[int] = []
    for rec in records:
        account_data_any = rec.get("account", {})
        account_data = cast(dict[str, Any], account_data_any if isinstance(account_data_any, dict) else {})
        outcome = str(rec.get("final_verdict", "")).strip()
        if not outcome:
            continue
        context_any = rec.get("context", {})
        context = cast(dict[str, Any], context_any if isinstance(context_any, dict) else {})
        x_rows.append(build_feature_dict(account_data, context))
        y_rows.append(normalize_verdict_label(outcome))

    if len(x_rows) < MIN_TRAINING_ROWS:
        raise ValueError("Not enough valid feedback rows after filtering")

    reject_rows = sum(y_rows)
    approve_rows = len(y_rows) - reject_rows
    if reject_rows < MIN_CLASS_ROWS or approve_rows < MIN_CLASS_ROWS:
        raise ValueError(
            "Training set is imbalanced for robust learning. "
            f"Need at least {MIN_CLASS_ROWS} rows per class; got approve={approve_rows}, reject={reject_rows}."
        )

    vectorizer: Any = DictVectorizer(sparse=True)
    x: Any = vectorizer.fit_transform(cast(Any, x_rows))

    classifier = SGDClassifier(
        loss="log_loss",
        alpha=1e-4,
        max_iter=2000,
        tol=1e-3,
        random_state=42,
    )
    classifier.fit(x, y_rows)

    model_file = Path(model_path)
    model_file.parent.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, Any] = {
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "training_samples": len(x_rows),
        "approve_samples": approve_rows,
        "reject_samples": reject_rows,
        "feedback_line_count": len(records),
        "feature_count": len(vectorizer.feature_names_),
    }
    artifact: dict[str, Any] = {
        "vectorizer": vectorizer,
        "classifier": classifier,
        "training_samples": len(x_rows),
        "metadata": metadata,
    }
    joblib = _joblib_module()
    joblib.dump(artifact, model_file)

    reject_rate = sum(y_rows) / len(y_rows)
    return {
        "model_path": str(model_file),
        "training_samples": len(x_rows),
        "reject_rate": round(reject_rate, 4),
        "approve_samples": approve_rows,
        "reject_samples": reject_rows,
        "metadata": metadata,
    }


def should_retrain(feedback_jsonl: str, model_path: str, min_new_records: int = 25) -> dict[str, Any]:
    feedback_file = Path(feedback_jsonl)
    if not feedback_file.exists():
        return {
            "should_retrain": False,
            "reason": f"feedback file not found: {feedback_jsonl}",
            "new_records": 0,
            "feedback_line_count": 0,
        }

    line_count = _count_feedback_lines(feedback_file)
    model_file = Path(model_path)
    if not model_file.exists():
        return {
            "should_retrain": line_count >= MIN_TRAINING_ROWS,
            "reason": "model not found",
            "new_records": line_count,
            "feedback_line_count": line_count,
        }

    joblib = _joblib_module()
    artifact_any: Any = joblib.load(model_file)
    artifact = cast(dict[str, Any], artifact_any if isinstance(artifact_any, dict) else {})
    metadata_any = artifact.get("metadata", {})
    metadata = cast(dict[str, Any], metadata_any if isinstance(metadata_any, dict) else {})
    last_seen = int(metadata.get("feedback_line_count", 0) or 0)
    new_records = max(0, line_count - last_seen)

    return {
        "should_retrain": new_records >= min_new_records,
        "reason": "threshold met" if new_records >= min_new_records else "not enough new feedback",
        "new_records": new_records,
        "feedback_line_count": line_count,
        "last_trained_feedback_count": last_seen,
        "min_new_records": min_new_records,
    }


def append_feedback_record(
    feedback_jsonl: str,
    account: dict[str, Any],
    final_verdict: str,
    context: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    record: dict[str, Any] = {
        "account": account,
        "final_verdict": final_verdict,
        "context": context or {},
        "metadata": metadata or {},
        "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    path = Path(feedback_jsonl)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
