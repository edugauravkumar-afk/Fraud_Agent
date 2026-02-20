from __future__ import annotations

import os
import socket
import ssl
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


SOCIAL_DOMAINS = [
    "linkedin.com",
    "facebook.com",
    "x.com",
    "twitter.com",
    "instagram.com",
    "youtube.com",
    "tiktok.com",
]


def _host_from_url(url: str) -> str:
    return urlparse(url).hostname or ""


def _safe_json(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {}


def _score_from_payload(payload: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def check_ssl_certificate(url: str, timeout: int = 5) -> dict[str, Any]:
    host = _host_from_url(url)
    result: dict[str, Any] = {
        "url": url,
        "host": host,
        "checked": False,
        "valid": None,
        "expires_in_days": None,
        "issuer": None,
        "error": None,
    }
    if not host or not url.lower().startswith("https://"):
        result["error"] = "SSL check requires HTTPS URL"
        return result

    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=host) as secure_sock:
                cert = secure_sock.getpeercert()
                result["checked"] = True
                issuer = cert.get("issuer", [])
                issuer_parts = [item[0][1] for item in issuer if item and item[0]]
                result["issuer"] = ", ".join(issuer_parts) if issuer_parts else None

                not_after = cert.get("notAfter")
                if not_after:
                    expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                    now = datetime.now(tz=timezone.utc)
                    expires_in = int((expiry - now).total_seconds() // 86400)
                    result["expires_in_days"] = expires_in
                    result["valid"] = expires_in >= 0
                else:
                    result["valid"] = True
    except Exception as exc:
        result["error"] = str(exc)

    return result


def check_social_presence(url: str, timeout: int = 6) -> dict[str, Any]:
    result: dict[str, Any] = {
        "url": url,
        "checked": False,
        "social_links_found": [],
        "count": 0,
        "error": None,
    }
    try:
        response = requests.get(url, timeout=timeout, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(response.text, "html.parser")
        found: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].lower()
            if any(domain in href for domain in SOCIAL_DOMAINS):
                found.append(href)

        deduped = sorted(set(found))
        result["checked"] = True
        result["social_links_found"] = deduped
        result["count"] = len(deduped)
    except Exception as exc:
        result["error"] = str(exc)
    return result


def run_advanced_checks(
    *,
    account_owner: str,
    company_name: str,
    email: str,
    urls: list[str],
    base_risk_signals: dict[str, Any] | None = None,
    enable_scamadviser: bool = False,
    enable_linkedin: bool = False,
    enable_ssl: bool = False,
    enable_social: bool = False,
    enable_registry: bool = False,
    enable_ml: bool = False,
    ml_model_path: str | None = None,
) -> dict[str, Any]:
    risk_points = 0
    notes: list[str] = []
    tags: list[str] = []
    uncertainty_signals = 0
    debug: dict[str, Any] = {}

    primary_url = urls[0] if urls else ""

    if enable_scamadviser and primary_url:
        scam_url = os.getenv("SCAMADVISER_API_URL", "").strip()
        scam_key = os.getenv("SCAMADVISER_API_KEY", "").strip()
        scam_url_param = os.getenv("SCAMADVISER_URL_PARAM", "url").strip() or "url"
        if scam_url and scam_key:
            try:
                response = requests.get(
                    scam_url,
                    params={scam_url_param: primary_url},
                    headers={"Authorization": f"Bearer {scam_key}"},
                    timeout=8,
                )
                payload = _safe_json(response)
                debug["scamadviser"] = payload

                trust_score = _score_from_payload(payload, ["trust_score", "score", "trustScore"])
                risk_score = _score_from_payload(payload, ["risk_score", "riskScore"])
                unsafe_flag = bool(payload.get("unsafe") or payload.get("is_unsafe"))

                if unsafe_flag:
                    risk_points += 25
                    tags.append("SCAMADVISER_UNSAFE")
                    notes.append("ScamAdviser API marked URL as unsafe.")
                elif trust_score is not None and trust_score < 40:
                    risk_points += 20
                    tags.append("SCAMADVISER_LOW_TRUST")
                    notes.append(f"ScamAdviser trust score is low ({trust_score:.0f}/100).")
                elif risk_score is not None and risk_score >= 60:
                    risk_points += 20
                    tags.append("SCAMADVISER_HIGH_RISK")
                    notes.append(f"ScamAdviser risk score is high ({risk_score:.0f}/100).")
                else:
                    notes.append("ScamAdviser check returned no high-risk signal.")
            except Exception as exc:
                uncertainty_signals += 1
                notes.append(f"ScamAdviser API check failed: {exc}.")
        else:
            uncertainty_signals += 1
            notes.append("ScamAdviser API not configured (set SCAMADVISER_API_URL and SCAMADVISER_API_KEY).")

    if enable_linkedin:
        linkedin_url = os.getenv("LINKEDIN_API_URL", "").strip()
        linkedin_token = os.getenv("LINKEDIN_ACCESS_TOKEN", "").strip()
        if linkedin_url and linkedin_token:
            payload = {
                "person_name": account_owner,
                "company_name": company_name,
                "email": email,
            }
            try:
                response = requests.post(
                    linkedin_url,
                    json=payload,
                    headers={"Authorization": f"Bearer {linkedin_token}"},
                    timeout=8,
                )
                data = _safe_json(response)
                debug["linkedin"] = data
                verified = bool(data.get("verified") or data.get("professional_match"))
                confidence = _score_from_payload(data, ["confidence", "confidence_score", "score"])
                if verified or (confidence is not None and confidence >= 70):
                    notes.append("LinkedIn professional verification indicates likely real professional identity.")
                else:
                    risk_points += 12
                    tags.append("LINKEDIN_UNVERIFIED")
                    notes.append("LinkedIn professional verification did not confirm person/business linkage.")
            except Exception as exc:
                uncertainty_signals += 1
                notes.append(f"LinkedIn API verification failed: {exc}.")
        else:
            uncertainty_signals += 1
            notes.append("LinkedIn API not configured (set LINKEDIN_API_URL and LINKEDIN_ACCESS_TOKEN).")

    if enable_ssl and primary_url:
        ssl_result = check_ssl_certificate(primary_url)
        debug["ssl"] = ssl_result
        if ssl_result.get("error"):
            uncertainty_signals += 1
            notes.append(f"SSL validation could not complete: {ssl_result['error']}.")
        elif ssl_result.get("valid") is False:
            risk_points += 20
            tags.append("SSL_INVALID")
            notes.append("SSL certificate is expired/invalid.")
        else:
            expires = ssl_result.get("expires_in_days")
            if isinstance(expires, int) and expires < 15:
                risk_points += 8
                tags.append("SSL_EXPIRING")
                notes.append(f"SSL certificate expires soon ({expires} days).")

    if enable_social and primary_url:
        social_result = check_social_presence(primary_url)
        debug["social"] = social_result
        if social_result.get("error"):
            uncertainty_signals += 1
            notes.append(f"Social media presence check failed: {social_result['error']}.")
        else:
            social_count = int(social_result.get("count", 0))
            if social_count == 0:
                risk_points += 6
                tags.append("NO_SOCIAL_PRESENCE")
                notes.append("No social media links found on primary website.")
            else:
                notes.append(f"Social presence found ({social_count} linked profile(s)).")

    if enable_registry and company_name:
        oc_token = os.getenv("OPENCORPORATES_API_TOKEN", "").strip()
        try:
            params = {"q": company_name}
            if oc_token:
                params["api_token"] = oc_token
            response = requests.get(
                "https://api.opencorporates.com/v0.4/companies/search",
                params=params,
                timeout=8,
            )
            payload = _safe_json(response)
            debug["business_registry"] = payload

            if payload.get("error"):
                uncertainty_signals += 1
                notes.append("Business registry lookup returned provider error; treated as uncertainty.")
                payload = {}

            results = (
                payload.get("results", {})
                .get("companies", [])
                if isinstance(payload.get("results"), dict)
                else []
            )
            if payload and not results:
                risk_points += 15
                tags.append("REGISTRY_NOT_FOUND")
                notes.append("Business registry lookup found no matching entity (OpenCorporates).")
            elif results:
                notes.append("Business registry lookup found matching company records.")
        except Exception as exc:
            uncertainty_signals += 1
            notes.append(f"Business registry lookup failed: {exc}.")

    if enable_ml:
        ml_api_url = os.getenv("ML_RISK_API_URL", "").strip()
        ml_api_key = os.getenv("ML_RISK_API_KEY", "").strip()
        features = {
            "owner_name": account_owner,
            "company_name": company_name,
            "email": email,
            "url_count": len(urls),
            **(base_risk_signals or {}),
        }

        ml_score: float | None = None
        if ml_api_url:
            try:
                response = requests.post(
                    ml_api_url,
                    json={"features": features},
                    headers={"Authorization": f"Bearer {ml_api_key}"} if ml_api_key else None,
                    timeout=8,
                )
                payload = _safe_json(response)
                debug["ml_api"] = payload
                ml_score = _score_from_payload(payload, ["risk_score", "score", "ml_risk_score"])
            except Exception as exc:
                uncertainty_signals += 1
                notes.append(f"ML risk API call failed: {exc}.")
        elif ml_model_path:
            try:
                import joblib  # type: ignore

                model = joblib.load(ml_model_path)
                model_input = [[
                    float(features.get("clock_diff_minutes", 0)),
                    float(features.get("offset_diff_minutes", 0)),
                    float(features.get("url_count", 0)),
                    float(features.get("base_risk_score", 0)),
                    float(features.get("positive_signals", 0)),
                ]]

                if hasattr(model, "predict_proba"):
                    probability = float(model.predict_proba(model_input)[0][1])
                    ml_score = probability * 100
                elif hasattr(model, "predict"):
                    prediction = float(model.predict(model_input)[0])
                    ml_score = max(0.0, min(100.0, prediction))
            except Exception as exc:
                uncertainty_signals += 1
                notes.append(f"Local ML model scoring failed: {exc}.")
        else:
            uncertainty_signals += 1
            notes.append("ML scoring not configured (set ML_RISK_API_URL or provide --ml-model-path).")

        if ml_score is not None:
            debug["ml_score"] = ml_score
            if ml_score >= 85:
                risk_points += 25
                tags.append("ML_EXTREME_RISK")
                notes.append(f"External ML risk scoring is very high ({ml_score:.1f}/100).")
            elif ml_score >= 60:
                risk_points += 12
                tags.append("ML_HIGH_RISK")
                notes.append(f"External ML risk scoring is elevated ({ml_score:.1f}/100).")
            elif ml_score <= 25:
                notes.append(f"External ML risk scoring is low ({ml_score:.1f}/100).")

    if uncertainty_signals > 0:
        tags.append("EXTERNAL_INTEL_PARTIAL")

    return {
        "risk_points": risk_points,
        "notes": notes,
        "tags": sorted(set(tags)),
        "uncertainty_signals": uncertainty_signals,
        "debug": debug,
    }
