from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from advanced_external_checks import run_advanced_checks
from afosint_integration import afosint_risk_points, normalize_ip_payload, run_comprehensive_check
from policy_config import PolicyConfig, load_policy_config


SHELL_ADDRESSES = {
    "1603 capitol ave, cheyenne, wy",
    "30 n gould st, sheridan, wy",
    "251 little falls dr, wilmington, de",
}

OUTSOURCED_NETWORK_OFFSETS_MINUTES = {330, 420, 480}
FREE_EMAIL_PROVIDERS = {
    "gmail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "icloud.com",
    "aol.com",
    "protonmail.com",
    "pm.me",
    "tutanota.com",
}
ENCRYPTED_EMAIL_PROVIDERS = {"protonmail.com", "pm.me", "tutanota.com"}

PARKED_KEYWORDS = [
    "domain for sale",
    "buy this domain",
    "this domain is parked",
    "sedo",
    "afternic",
]

SAFE_PAGE_PATTERNS = [
    "b2b solutions",
    "enterprise innovation",
    "digital transformation",
    "stock photo",
    "our mission is to empower",
]


@dataclass
class AccountSummary:
    name: str
    email: str
    ml_score: float
    company_name: str
    cc_owner: str
    cc_country: str
    address: str
    local_time: str
    network_time: str
    item_urls: list[str] = field(default_factory=list)
    ip_addresses: list[dict[str, str]] = field(default_factory=list)
    email_first_seen: str | None = None
    email_invalid_flag: bool = False
    network_country: str | None = None

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "AccountSummary":
        return AccountSummary(
            name=data.get("name", "").strip(),
            email=data.get("email", "").strip().lower(),
            ml_score=float(data.get("ml_score", 50)),
            company_name=data.get("company_name", "").strip(),
            cc_owner=data.get("cc_owner", "").strip(),
            cc_country=data.get("cc_country", "").strip(),
            address=data.get("address", "").strip(),
            local_time=data.get("local_time", "").strip(),
            network_time=data.get("network_time", "").strip(),
            item_urls=data.get("item_urls", []) or [],
            ip_addresses=data.get("ip_addresses", []) or [],
            email_first_seen=data.get("email_first_seen"),
            email_invalid_flag=bool(data.get("email_invalid_flag", False)),
            network_country=data.get("network_country"),
        )


def parse_iso_with_tz(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def timezone_offset_minutes(dt: datetime) -> int:
    tz = dt.utcoffset()
    return int(tz.total_seconds() // 60) if tz else 0


def clock_time_difference_minutes(local_dt: datetime, network_dt: datetime) -> int:
    local_minutes = local_dt.hour * 60 + local_dt.minute
    network_minutes = network_dt.hour * 60 + network_dt.minute
    diff = abs(local_minutes - network_minutes)
    return min(diff, 1440 - diff)


def last_name(full_name: str) -> str:
    tokens = [token for token in re.split(r"\s+", full_name.strip()) if token]
    return tokens[-1].lower() if tokens else ""


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def is_gibberish_domain(domain: str) -> bool:
    root = domain.split(".")[0]
    if len(root) < 7:
        return False
    vowels = sum(ch in "aeiou" for ch in root)
    return vowels <= 1 and any(ch.isdigit() for ch in root)


def looks_enterprise_domain(email_domain: str, company_name: str) -> bool:
    if email_domain in FREE_EMAIL_PROVIDERS:
        return False
    company_tokens = [t for t in re.findall(r"[a-z0-9]+", company_name.lower()) if len(t) > 2]
    if not company_tokens:
        return True
    return any(token in email_domain for token in company_tokens)


def is_western_business_profile(company_name: str, address: str, email_domain: str) -> bool:
    address_l = address.lower()
    western_terms = [
        "usa",
        "united states",
        "uk",
        "united kingdom",
        "canada",
        "australia",
        "new zealand",
        "germany",
        "france",
        "netherlands",
    ]
    has_western_address = any(term in address_l for term in western_terms)
    enterprise_domain = looks_enterprise_domain(email_domain, company_name)
    return has_western_address and enterprise_domain


def inspect_url(url: str, timeout: int = 6) -> dict[str, Any]:
    result: dict[str, Any] = {
        "url": url,
        "reachable": False,
        "status_code": None,
        "final_url": None,
        "title": "",
        "parked": False,
        "safe_page_template": False,
        "bait_switch": False,
        "rate_limited": False,
        "dynamic_content_likely": False,
        "scraping_limited": False,
        "error": None,
    }
    try:
        response = requests.get(url, timeout=timeout, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        result["status_code"] = response.status_code
        if response.status_code == 429:
            result["rate_limited"] = True
            result["error"] = "Rate limit encountered (HTTP 429)"
            return result

        body = response.text[:25000].lower()
        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.title.get_text(strip=True).lower() if soup.title else ""
        start_domain = urlparse(url).netloc.replace("www.", "")
        end_domain = urlparse(response.url).netloc.replace("www.", "")
        visible_text = " ".join(soup.stripped_strings)[:25000].lower()
        script_tags = len(soup.find_all("script"))
        body_len = len(body)
        text_len = len(visible_text)
        result["dynamic_content_likely"] = script_tags >= 8 and text_len < 400 and body_len > 3000
        result["scraping_limited"] = text_len < 120

        result["reachable"] = response.status_code < 500
        result["final_url"] = response.url
        result["title"] = title
        result["parked"] = any(key in body or key in title for key in PARKED_KEYWORDS)
        safe_source = visible_text if visible_text else body
        result["safe_page_template"] = sum(1 for key in SAFE_PAGE_PATTERNS if key in safe_source) >= 2
        result["bait_switch"] = start_domain != end_domain and end_domain != ""
    except Exception as exc:
        result["error"] = str(exc)

    return result


def review_account(
    account: AccountSummary,
    enable_web_checks: bool = True,
    use_afosint: bool = False,
    afosint_web_searches: bool = False,
    afosint_mock_mode: bool = False,
    use_advanced_checks: bool = False,
    enable_scamadviser: bool = False,
    enable_linkedin: bool = False,
    enable_ssl: bool = False,
    enable_social: bool = False,
    enable_registry: bool = False,
    enable_ml: bool = False,
    ml_model_path: str | None = None,
    policy: PolicyConfig | None = None,
) -> dict[str, Any]:
    policy = policy or PolicyConfig()
    verdict = "Route to Human VIP Sales"

    if account.ml_score < policy.ml_auto_approve_threshold:
        return {
            "verdict": "Approve",
            "analysis": {
                "timezone_geo": "ML score below 30 threshold: auto-approved by policy before manual queue.",
                "identity_payment": "Manual identity checks are bypassed by threshold policy.",
                "domain_policy": "Manual content checks are bypassed by threshold policy.",
            },
            "false_positive": "This is not a false positive case because policy routes sub-30 scores directly to approval.",
            "internal_note": "Auto-approved by ML threshold policy (<30). No manual review required unless a post-approval alert is triggered.",
            "tags": ["APPROVE", "ML_LOW_RISK", "AUTO", "N/A"],
        }

    if account.ml_score > policy.ml_auto_reject_threshold:
        return {
            "verdict": "Reject",
            "analysis": {
                "timezone_geo": "ML score above 85 threshold: auto-rejected by policy before manual queue.",
                "identity_payment": "Manual identity checks are bypassed by threshold policy.",
                "domain_policy": "Manual content checks are bypassed by threshold policy.",
            },
            "false_positive": "This is not treated as a manual false-positive case because policy routes >85 scores directly to rejection.",
            "internal_note": "Auto-rejected by ML threshold policy (>85). Escalate only if commercial owner requests override.",
            "tags": ["REJECT", "ML_HIGH_RISK", "AUTO", "N/A"],
        }

    risk_score = 0
    positive_signals = 0
    reasons: list[str] = []

    local_dt = parse_iso_with_tz(account.local_time)
    network_dt = parse_iso_with_tz(account.network_time)
    local_offset = timezone_offset_minutes(local_dt)
    network_offset = timezone_offset_minutes(network_dt)
    offset_diff_minutes = abs(local_offset - network_offset)
    clock_diff_minutes = clock_time_difference_minutes(local_dt, network_dt)

    email_domain = account.email.split("@")[-1] if "@" in account.email else ""
    natural_offset_diff = offset_diff_minutes % 30 == 0
    outsourced_exemption = (
        network_offset in OUTSOURCED_NETWORK_OFFSETS_MINUTES
        and is_western_business_profile(account.company_name, account.address, email_domain)
    )

    if clock_diff_minutes > policy.clock_mismatch_minutes_threshold:
        risk_score += 30
        reasons.append("Local vs network clock difference is greater than 1 hour (mandatory proxy/location mismatch flag).")

    if not natural_offset_diff and not outsourced_exemption:
        risk_score += 35
        reasons.append("Chaotic timezone delta suggests anti-detect manipulation.")
    elif outsourced_exemption:
        positive_signals += 2
        reasons.append("Timezone mismatch fits outsourced agency pattern (allowed false-positive exemption).")
    else:
        positive_signals += 1
        reasons.append("Timezone offset relationship appears natural.")

    first_seen_zero = (account.email_first_seen or "").startswith("1970")
    enterprise_domain = looks_enterprise_domain(email_domain, account.company_name)

    if email_domain in ENCRYPTED_EMAIL_PROVIDERS:
        risk_score += 20
        reasons.append("Encrypted/burner-style mail provider raises account trust risk.")

    if is_gibberish_domain(email_domain):
        risk_score += 20
        reasons.append("Email domain looks synthetic/gibberish.")

    if first_seen_zero or account.email_invalid_flag:
        if enterprise_domain:
            positive_signals += 1
            reasons.append("Email API flag ignored due to plausible enterprise domain/firewall behavior.")
        else:
            risk_score += 20
            reasons.append("Zero-history/invalid email with non-enterprise domain.")
    else:
        positive_signals += 1

    address_normalized = normalize_text(account.address)
    shell_hit = any(shell in address_normalized for shell in SHELL_ADDRESSES)

    user_last = last_name(account.name)
    card_last = last_name(account.cc_owner)
    last_name_match = user_last != "" and user_last == card_last
    card_company_match = normalize_text(account.cc_owner) == normalize_text(account.company_name)

    if last_name_match or card_company_match:
        positive_signals += 2
        reasons.append("Card ownership is logically connected (family/corporate pattern).")
    else:
        risk_score += 20
        reasons.append("Card owner not logically connected to applicant identity/company.")

    is_foreign_card = (
        account.network_country is not None
        and account.cc_country != ""
        and account.network_country.lower() not in account.cc_country.lower()
    )
    if shell_hit and is_foreign_card:
        risk_score += 35
        reasons.append("Known shell address with foreign card profile.")
    elif shell_hit:
        risk_score += 20
        reasons.append("Known shell address detected.")
    else:
        positive_signals += 1

    url_findings = []
    if enable_web_checks:
        for url in account.item_urls[:5]:
            finding = inspect_url(url)
            url_findings.append(finding)

    parked_hits = sum(1 for item in url_findings if item.get("parked"))
    safe_page_hits = sum(1 for item in url_findings if item.get("safe_page_template"))
    bait_hits = sum(1 for item in url_findings if item.get("bait_switch"))
    rate_limited_hits = sum(1 for item in url_findings if item.get("rate_limited"))
    dynamic_hits = sum(1 for item in url_findings if item.get("dynamic_content_likely"))
    scraping_limited_hits = sum(1 for item in url_findings if item.get("scraping_limited"))

    if parked_hits > 0:
        risk_score += 25
        reasons.append("One or more item URLs appear parked/for-sale.")
    if safe_page_hits > 0:
        risk_score += 20
        reasons.append("Generic safe-page pattern detected in landing content.")
    if bait_hits > 0:
        risk_score += 25
        reasons.append("Domain bait-and-switch/redirect mismatch detected.")

    uncertainty_signals = 0
    if rate_limited_hits > 0:
        uncertainty_signals += 1
        reasons.append("External URL intelligence encountered API/site rate limits; content confidence reduced.")
    if dynamic_hits > 0:
        uncertainty_signals += 1
        reasons.append("Dynamic JavaScript-rendered pages detected; static scraping may miss true content.")
    if scraping_limited_hits > 0:
        uncertainty_signals += 1
        reasons.append("Website structure yielded low extractable content; scraping evidence is partial.")

    advanced_summary = "Advanced external checks not requested."
    advanced_debug: dict[str, Any] = {
        "enabled": use_advanced_checks,
        "risk_points_applied": 0,
        "uncertainty_signals": 0,
        "tags": [],
        "details": {},
    }
    advanced_tags: list[str] = []
    if use_advanced_checks:
        advanced_result = run_advanced_checks(
            account_owner=account.name,
            company_name=account.company_name,
            email=account.email,
            urls=account.item_urls,
            base_risk_signals={
                "clock_diff_minutes": clock_diff_minutes,
                "offset_diff_minutes": offset_diff_minutes,
                "base_risk_score": risk_score,
                "positive_signals": positive_signals,
            },
            enable_scamadviser=enable_scamadviser,
            enable_linkedin=enable_linkedin,
            enable_ssl=enable_ssl,
            enable_social=enable_social,
            enable_registry=enable_registry,
            enable_ml=enable_ml,
            ml_model_path=ml_model_path,
        )
        risk_score += int(advanced_result.get("risk_points", 0))
        uncertainty_signals += int(advanced_result.get("uncertainty_signals", 0))
        advanced_notes = advanced_result.get("notes", []) or []
        reasons.extend([str(note) for note in advanced_notes])
        advanced_tags = [str(tag) for tag in (advanced_result.get("tags", []) or [])]

        advanced_debug["risk_points_applied"] = int(advanced_result.get("risk_points", 0))
        advanced_debug["uncertainty_signals"] = int(advanced_result.get("uncertainty_signals", 0))
        advanced_debug["tags"] = advanced_tags
        advanced_debug["details"] = advanced_result.get("debug", {}) or {}
        advanced_summary = (
            f"Advanced checks integrated: +{advanced_debug['risk_points_applied']} risk points, "
            f"+{advanced_debug['uncertainty_signals']} uncertainty signals."
        )

    if parked_hits == 0 and safe_page_hits == 0 and bait_hits == 0 and account.item_urls:
        positive_signals += 1
        reasons.append("No cloaking or parked-domain indicators in sampled URLs.")

    afosint_summary = "AFOSINT not requested."
    afosint_debug: dict[str, Any] = {
        "enabled": False,
        "available": None,
        "error": None,
        "result": None,
        "risk_points_applied": 0,
        "tags": [],
    }
    afosint_extra_tags: list[str] = []
    if use_afosint:
        ip_payload = normalize_ip_payload(account.ip_addresses, fallback_country=account.network_country)
        afosint_check = run_comprehensive_check(
            account_owner=account.name,
            cc_holder=account.cc_owner,
            company_name=account.company_name,
            email=account.email,
            urls=account.item_urls,
            ip_addresses=ip_payload,
            perform_web_searches=afosint_web_searches,
            mock_mode=afosint_mock_mode,
        )
        afosint_debug.update(afosint_check)

        if afosint_check.get("result"):
            af_points, af_notes, afosint_extra_tags = afosint_risk_points(afosint_check["result"])
            risk_score += af_points
            reasons.extend(af_notes)
            afosint_debug["risk_points_applied"] = af_points
            afosint_debug["tags"] = afosint_extra_tags
            afosint_summary = f"AFOSINT integrated: +{af_points} risk points."
        elif afosint_check.get("error"):
            afosint_summary = f"AFOSINT requested but unavailable/failed: {afosint_check['error']}."
        else:
            afosint_summary = "AFOSINT requested but no result returned."

    missing_urls = len(account.item_urls) == 0
    if missing_urls:
        reasons.append("Item URL is missing; account cannot be fully approved before landing-page verification.")

    if uncertainty_signals > 0 and risk_score < 70:
        reasons.append("Uncertainty signals present; avoid hard decision from incomplete OSINT and escalate to manual/VIP when needed.")

    hard_reject = (not natural_offset_diff and not outsourced_exemption and shell_hit) or (parked_hits > 0 and bait_hits > 0)

    if hard_reject or risk_score >= policy.reject_risk_threshold:
        verdict = "Reject"
        status_tag = "REJECT"
    elif risk_score <= policy.approve_risk_threshold and positive_signals >= policy.approve_positive_signals_threshold:
        verdict = "Approve"
        status_tag = "APPROVE"
    else:
        verdict = "Route to Human VIP Sales"
        status_tag = "VIP_REVIEW"

    if missing_urls and verdict != "Reject":
        verdict = "Conditional Approval - Hold for URL Verification"
        status_tag = "HOLD_URL_VERIFICATION"

    if uncertainty_signals > 0 and verdict == "Approve":
        verdict = "Route to Human VIP Sales"
        status_tag = "VIP_REVIEW"

    confidence_score = int(
        clamp(
            55
            + (positive_signals * 6)
            - (risk_score * 0.45)
            - (uncertainty_signals * 12)
            - (10 if missing_urls else 0),
            10,
            95,
        )
    )

    if confidence_score >= 75:
        confidence_level = "High"
    elif confidence_score >= 50:
        confidence_level = "Medium"
    else:
        confidence_level = "Low"

    timezone_geo = (
        f"Local Browser Time: {account.local_time}; Network IP Time: {account.network_time}. "
        f"Calculation: |clock delta|={clock_diff_minutes} min, |offset delta|={offset_diff_minutes} min. "
        f"Rule check (>{policy.clock_mismatch_minutes_threshold} min clock mismatch)={'flagged' if clock_diff_minutes > policy.clock_mismatch_minutes_threshold else 'clear'}. "
        f"Natural offset delta={'yes' if natural_offset_diff else 'no'}; outsourced exemption={'yes' if outsourced_exemption else 'no'}."
    )

    identity_payment = (
        f"Name/card relation={'match' if (last_name_match or card_company_match) else 'mismatch'}; "
        f"shell address={'yes' if shell_hit else 'no'}; foreign card risk={'yes' if is_foreign_card else 'no'}."
    )

    domain_policy = (
        f"URL provided={'yes' if not missing_urls else 'no'}; URL checks: parked={parked_hits}, safe-template={safe_page_hits}, bait-switch={bait_hits}. "
        f"Limitations: rate-limited={rate_limited_hits}, dynamic-content={dynamic_hits}, scraping-limited={scraping_limited_hits}. "
        f"{afosint_summary} {advanced_summary} Total risk score={risk_score}, positive signals={positive_signals}."
    )

    approve_factors = []
    if last_name_match or card_company_match:
        approve_factors.append("identity and payment owner are logically linked")
    if not shell_hit:
        approve_factors.append("address does not match known shell-address patterns")
    if natural_offset_diff or outsourced_exemption:
        approve_factors.append("timezone profile has a legitimate interpretation")
    if parked_hits == 0 and bait_hits == 0:
        approve_factors.append("no direct parked/bait-switch signal in checked URLs")

    reject_factors = []
    if clock_diff_minutes > policy.clock_mismatch_minutes_threshold:
        reject_factors.append(
            f"local vs network time mismatch exceeds {policy.clock_mismatch_minutes_threshold} minutes"
        )
    if not natural_offset_diff and not outsourced_exemption:
        reject_factors.append("chaotic timezone offset suggests spoofing")
    if shell_hit and is_foreign_card:
        reject_factors.append("known shell address combined with foreign card profile")
    if parked_hits > 0:
        reject_factors.append("parked-domain behavior detected")
    if bait_hits > 0:
        reject_factors.append("bait-and-switch redirect behavior detected")
    if missing_urls:
        reject_factors.append("item URL missing so compliance destination cannot be verified")

    approve_side = (
        "; ".join(approve_factors[:4])
        if approve_factors
        else "no strong positive trust signals were found"
    )
    reject_side = (
        "; ".join(reject_factors[:4])
        if reject_factors
        else "no hard-fraud signal was strong enough on its own"
    )

    if verdict == "Approve":
        final_reason = (
            "Approved because positive identity/GEO/content signals outweighed risk indicators, "
            "and no mandatory hold/reject gate was triggered."
        )
    elif verdict == "Reject":
        final_reason = (
            "Rejected because independent fraud indicators converged strongly enough to pass rejection thresholds."
        )
    elif verdict == "Conditional Approval - Hold for URL Verification":
        final_reason = (
            "Conditionally approved on identity/business coherence, but held because URL verification is mandatory before full approval."
        )
    else:
        final_reason = (
            "Routed to Human VIP Sales because mixed signals or OSINT uncertainty require senior manual judgment."
        )

    confidence_statement = (
        f"{confidence_level} confidence ({confidence_score}/100): based on risk score, positive corroboration, "
        f"and uncertainty penalties from data quality limitations."
    )

    false_positive = (
        "False-positive risk is controlled because enterprise/outsourcing and family/corporate payment patterns are explicitly exempted "
        "before rejection. The account is only rejected when multi-signal fraud evidence is present."
        if verdict != "Reject"
        else "This is not a false positive because multiple independent fraud indicators align (identity/geo/content), not a single noisy flag."
    )

    internal_note = (
        f"Manual-band review completed for ML score {account.ml_score}. "
        f"Decision={verdict}; key factors: {'; '.join(reasons[:4])}. "
        "Decision is evidence-based with false-positive exemptions evaluated first."
    )

    risk_type = "MULTI_SIGNAL" if risk_score >= 40 else "LOW_SIGNAL"
    location = account.network_country or "UNKNOWN"
    content = "CLOAKING_RISK" if (parked_hits or bait_hits or safe_page_hits) else "CLEAN_CONTENT"
    if missing_urls:
        content = "URL_MISSING"
    elif uncertainty_signals > 0:
        content = "CONTENT_UNCERTAIN"

    tags = [status_tag, risk_type, location, content]
    for af_tag in afosint_extra_tags:
        if af_tag not in tags:
            tags.append(af_tag)
    for advanced_tag in advanced_tags:
        if advanced_tag not in tags:
            tags.append(advanced_tag)

    return {
        "verdict": verdict,
        "analysis": {
            "timezone_geo": timezone_geo,
            "identity_payment": identity_payment,
            "domain_policy": domain_policy,
        },
        "false_positive": false_positive,
        "decision_summary": {
            "approve_case": approve_side,
            "reject_case": reject_side,
            "final_reason": final_reason,
            "confidence": confidence_statement,
            "confidence_score": confidence_score,
            "confidence_level": confidence_level,
        },
        "internal_note": internal_note,
        "tags": tags,
        "debug": {
            "risk_score": risk_score,
            "positive_signals": positive_signals,
            "uncertainty_signals": uncertainty_signals,
            "reasons": reasons,
            "url_findings": url_findings,
            "afosint": afosint_debug,
            "advanced_checks": advanced_debug,
        },
    }


def format_report(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"### Verdict: {result['verdict']}",
            "",
            "### Deep Analysis:",
            "",
            "**Timezone & GEO Logic:**",
            result["analysis"]["timezone_geo"],
            "",
            "**Identity & Payment Logic:**",
            result["analysis"]["identity_payment"],
            "",
            "**Domain & Policy Risk:**",
            result["analysis"]["domain_policy"],
            "",
            "### False Positive Check:",
            result["false_positive"],
            "",
            "### Decision Summary:",
            "**Why this can be approved:**",
            result["decision_summary"]["approve_case"],
            "",
            "**Why this can be rejected:**",
            result["decision_summary"]["reject_case"],
            "",
            "**Why final verdict was chosen:**",
            result["decision_summary"]["final_reason"],
            "",
            "**Confidence Statement:**",
            result["decision_summary"]["confidence"],
            "",
            "### Internal Note Summary:",
            result["internal_note"],
            "",
            "### Tags:",
            " ".join(f"`{tag}`" for tag in result["tags"]),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fraud Review Agent Decision Engine")
    parser.add_argument("--input", required=True, help="Path to account summary JSON file")
    parser.add_argument(
        "--no-web-checks",
        action="store_true",
        help="Disable live URL inspection if network access is restricted",
    )
    parser.add_argument(
        "--use-afosint",
        action="store_true",
        help="Run AFOSINT comprehensive fraud check and blend result into manual-band scoring",
    )
    parser.add_argument(
        "--afosint-web-searches",
        action="store_true",
        help="Allow AFOSINT to perform web searches (slower, better intelligence)",
    )
    parser.add_argument(
        "--afosint-mock-mode",
        action="store_true",
        help="Run AFOSINT in mock mode for local testing",
    )
    parser.add_argument(
        "--use-advanced-checks",
        action="store_true",
        help="Enable advanced external checks (ScamAdviser, LinkedIn, SSL, social, registry, ML)",
    )
    parser.add_argument("--enable-scamadviser", action="store_true", help="Enable ScamAdviser API check")
    parser.add_argument("--enable-linkedin", action="store_true", help="Enable LinkedIn professional verification")
    parser.add_argument("--enable-ssl", action="store_true", help="Enable SSL certificate validation")
    parser.add_argument("--enable-social", action="store_true", help="Enable social media presence check")
    parser.add_argument("--enable-registry", action="store_true", help="Enable business registry lookup")
    parser.add_argument("--enable-ml", action="store_true", help="Enable external/local ML risk scoring")
    parser.add_argument(
        "--ml-model-path",
        default=None,
        help="Path to a local serialized ML model (joblib) for risk scoring",
    )
    parser.add_argument(
        "--policy",
        default="fraud_policy.json",
        help="Path to policy config JSON",
    )
    parser.add_argument("--json", action="store_true", help="Print raw JSON result")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    account = AccountSummary.from_dict(payload)
    policy = load_policy_config(args.policy)
    result = review_account(
        account,
        enable_web_checks=not args.no_web_checks,
        use_afosint=args.use_afosint,
        afosint_web_searches=args.afosint_web_searches,
        afosint_mock_mode=args.afosint_mock_mode,
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

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_report(result))


if __name__ == "__main__":
    main()
