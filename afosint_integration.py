from __future__ import annotations

from typing import Any


def _import_toolkit() -> Any:
    try:
        from afosint_toolkit import AFOSINTToolkit  # type: ignore

        return AFOSINTToolkit
    except Exception:
        return None


def toolkit_available() -> bool:
    return _import_toolkit() is not None


def run_comprehensive_check(
    *,
    account_owner: str,
    cc_holder: str,
    company_name: str,
    email: str,
    urls: list[str],
    ip_addresses: list[dict[str, str]],
    perform_web_searches: bool = False,
    mock_mode: bool = False,
) -> dict[str, Any]:
    toolkit_class = _import_toolkit()
    if toolkit_class is None:
        return {
            "enabled": False,
            "available": False,
            "error": "afosint_toolkit is not installed",
            "result": None,
        }

    try:
        toolkit = toolkit_class(mock_mode=mock_mode)
    except TypeError:
        toolkit = toolkit_class()

    payload = {
        "account_owner": account_owner,
        "cc_holder": cc_holder,
        "company_name": company_name,
        "email": email,
        "urls": urls,
        "ip_addresses": ip_addresses,
    }

    try:
        result = toolkit.comprehensive_fraud_check(payload, perform_web_searches=perform_web_searches)
        return {
            "enabled": True,
            "available": True,
            "error": None,
            "result": result,
        }
    except Exception as exc:
        return {
            "enabled": True,
            "available": True,
            "error": str(exc),
            "result": None,
        }


def normalize_ip_payload(ip_addresses: list[Any], fallback_country: str | None = None) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for ip_data in ip_addresses:
        if isinstance(ip_data, str):
            normalized.append({"ip": ip_data, "country": fallback_country or ""})
            continue
        if isinstance(ip_data, dict):
            ip = str(ip_data.get("ip", "")).strip()
            if ip:
                country = str(ip_data.get("country", fallback_country or "")).strip()
                normalized.append({"ip": ip, "country": country})
    return normalized


def afosint_risk_points(afosint_result: dict[str, Any] | None) -> tuple[int, list[str], list[str]]:
    if not afosint_result:
        return 0, [], []

    risk_score = int(afosint_result.get("overall_risk_score", 0) or 0)
    risk_level = str(afosint_result.get("risk_level", "")).upper()

    points = 0
    notes: list[str] = []
    tags: list[str] = []

    if risk_level == "HIGH" or risk_score >= 60:
        points = 30
        tags.append("AFOSINT_HIGH")
    elif risk_level == "MEDIUM" or risk_score >= 30:
        points = 15
        tags.append("AFOSINT_MEDIUM")
    else:
        tags.append("AFOSINT_LOW")

    red_flags = afosint_result.get("red_flags", []) or []
    if red_flags:
        notes.append(f"AFOSINT red flags: {', '.join(str(flag) for flag in red_flags[:3])}.")

    green_flags = afosint_result.get("green_flags", []) or []
    if green_flags:
        notes.append(f"AFOSINT green flags: {', '.join(str(flag) for flag in green_flags[:2])}.")

    notes.append(f"AFOSINT overall risk score={risk_score}/100, level={risk_level or 'UNKNOWN'}.")
    return points, notes, tags
