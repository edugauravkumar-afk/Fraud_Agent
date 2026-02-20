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
            email_first_seen=data.get("email_first_seen"),
            email_invalid_flag=bool(data.get("email_invalid_flag", False)),
            network_country=data.get("network_country"),
        )


def parse_iso_with_tz(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def timezone_offset_minutes(dt: datetime) -> int:
    tz = dt.utcoffset()
    return int(tz.total_seconds() // 60) if tz else 0


def last_name(full_name: str) -> str:
    tokens = [token for token in re.split(r"\s+", full_name.strip()) if token]
    return tokens[-1].lower() if tokens else ""


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


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
        "final_url": None,
        "title": "",
        "parked": False,
        "safe_page_template": False,
        "bait_switch": False,
        "error": None,
    }
    try:
        response = requests.get(url, timeout=timeout, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        body = response.text[:25000].lower()
        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.title.get_text(strip=True).lower() if soup.title else ""
        start_domain = urlparse(url).netloc.replace("www.", "")
        end_domain = urlparse(response.url).netloc.replace("www.", "")

        result["reachable"] = response.status_code < 500
        result["final_url"] = response.url
        result["title"] = title
        result["parked"] = any(key in body or key in title for key in PARKED_KEYWORDS)
        result["safe_page_template"] = sum(1 for key in SAFE_PAGE_PATTERNS if key in body) >= 2
        result["bait_switch"] = start_domain != end_domain and end_domain != ""
    except Exception as exc:
        result["error"] = str(exc)

    return result


def review_account(account: AccountSummary, enable_web_checks: bool = True) -> dict[str, Any]:
    verdict = "Route to Human VIP Sales"

    if account.ml_score < 30:
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

    if account.ml_score > 85:
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
    diff_minutes = abs(local_offset - network_offset)

    email_domain = account.email.split("@")[-1] if "@" in account.email else ""
    natural_diff = diff_minutes % 30 == 0
    outsourced_exemption = (
        network_offset in OUTSOURCED_NETWORK_OFFSETS_MINUTES
        and is_western_business_profile(account.company_name, account.address, email_domain)
    )

    if not natural_diff and not outsourced_exemption:
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

    if parked_hits > 0:
        risk_score += 25
        reasons.append("One or more item URLs appear parked/for-sale.")
    if safe_page_hits > 0:
        risk_score += 20
        reasons.append("Generic safe-page pattern detected in landing content.")
    if bait_hits > 0:
        risk_score += 25
        reasons.append("Domain bait-and-switch/redirect mismatch detected.")

    if parked_hits == 0 and safe_page_hits == 0 and bait_hits == 0 and account.item_urls:
        positive_signals += 1
        reasons.append("No cloaking or parked-domain indicators in sampled URLs.")

    hard_reject = (not natural_diff and not outsourced_exemption and shell_hit) or (parked_hits > 0 and bait_hits > 0)

    if hard_reject or risk_score >= 70:
        verdict = "Reject"
        status_tag = "REJECT"
    elif risk_score <= 25 and positive_signals >= 4:
        verdict = "Approve"
        status_tag = "APPROVE"
    else:
        verdict = "Route to Human VIP Sales"
        status_tag = "VIP_REVIEW"

    timezone_geo = (
        f"Local offset={local_offset} min, network offset={network_offset} min, delta={diff_minutes} min. "
        f"Natural delta={'yes' if natural_diff else 'no'}; outsourced exemption={'yes' if outsourced_exemption else 'no'}."
    )

    identity_payment = (
        f"Name/card relation={'match' if (last_name_match or card_company_match) else 'mismatch'}; "
        f"shell address={'yes' if shell_hit else 'no'}; foreign card risk={'yes' if is_foreign_card else 'no'}."
    )

    domain_policy = (
        f"URL checks: parked={parked_hits}, safe-template={safe_page_hits}, bait-switch={bait_hits}. "
        f"Total risk score={risk_score}, positive signals={positive_signals}."
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

    return {
        "verdict": verdict,
        "analysis": {
            "timezone_geo": timezone_geo,
            "identity_payment": identity_payment,
            "domain_policy": domain_policy,
        },
        "false_positive": false_positive,
        "internal_note": internal_note,
        "tags": [status_tag, risk_type, location, content],
        "debug": {
            "risk_score": risk_score,
            "positive_signals": positive_signals,
            "reasons": reasons,
            "url_findings": url_findings,
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
    parser.add_argument("--json", action="store_true", help="Print raw JSON result")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    account = AccountSummary.from_dict(payload)
    result = review_account(account, enable_web_checks=not args.no_web_checks)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_report(result))


if __name__ == "__main__":
    main()
