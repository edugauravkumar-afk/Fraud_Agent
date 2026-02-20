from __future__ import annotations

import json
import importlib
from pathlib import Path
from typing import Any, cast

from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import SGDClassifier


LABEL_MAP = {
    "approve": 0,
    "route to human vip sales": 0,
    "conditional approval - hold for url verification": 0,
    "reject": 1,
}


def normalize_verdict_label(label: str) -> int:
    key = label.strip().lower()
    if key not in LABEL_MAP:
        raise ValueError(f"Unsupported verdict label: {label}")
    return LABEL_MAP[key]


def _joblib_module() -> Any:
    return importlib.import_module("joblib")


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

    return {
        "available": True,
        "error": None,
        "reject_probability": reject_prob,
    }


def train_from_feedback(feedback_jsonl: str, model_path: str) -> dict[str, Any]:
    feedback_file = Path(feedback_jsonl)
    if not feedback_file.exists():
        raise FileNotFoundError(f"Feedback file not found: {feedback_jsonl}")

    records: list[dict[str, Any]] = []
    for line in feedback_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj_any: Any = json.loads(line)
        obj = cast(dict[str, Any], obj_any if isinstance(obj_any, dict) else {})
        records.append(obj)

    if len(records) < 20:
        raise ValueError("Need at least 20 feedback records to train a stable self-learning model")

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

    if len(x_rows) < 20:
        raise ValueError("Not enough valid feedback rows after filtering")

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
    artifact: dict[str, Any] = {
        "vectorizer": vectorizer,
        "classifier": classifier,
        "training_samples": len(x_rows),
    }
    joblib = _joblib_module()
    joblib.dump(artifact, model_file)

    reject_rate = sum(y_rows) / len(y_rows)
    return {
        "model_path": str(model_file),
        "training_samples": len(x_rows),
        "reject_rate": round(reject_rate, 4),
    }


def append_feedback_record(
    feedback_jsonl: str,
    account: dict[str, Any],
    final_verdict: str,
    context: dict[str, Any] | None = None,
) -> None:
    record: dict[str, Any] = {
        "account": account,
        "final_verdict": final_verdict,
        "context": context or {},
    }
    path = Path(feedback_jsonl)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
