# app/views.py
from __future__ import annotations

import os
import re
import io
import zipfile
import base64
import random
import tempfile
import hashlib
import json
import socket
from typing import Dict, Any, List, Tuple
from xml.etree import ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests
import requests
from requests.exceptions import RequestException, SSLError, Timeout, ConnectionError as ReqConnError

try:
    response = requests.get("https://example.com", timeout=5)
    response.raise_for_status()  # Raise HTTPError for bad responses (4xx, 5xx)
except ReqConnError as e:
    print(f"Connection error occurred: {e}")
except Timeout as e:
    print(f"Request timed out: {e}")
except SSLError as e:
    print(f"SSL error occurred: {e}")
except RequestException as e:
    print(f"An error occurred: {e}")
else:
    print("Request was successful!")


from django.shortcuts import render, redirect
from django.template.loader import get_template
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_POST
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest

from dotenv import load_dotenv
load_dotenv()

# PDF export
from xhtml2pdf import pisa

# Matplotlib (headless)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ===== Utils (your modules) =====
from .utils import (
    extract_applicant_name,
    extract_github_username,
    extract_leetcode_username,
    calculate_dynamic_ats_score,
    derive_resume_metrics,
    ats_resume_scoring,
    extract_links_combined,
    extract_text_from_docx,
    generate_pie_chart_v2,
    calculate_screening_emphasis,
    get_grade_tag,
    # NEW ↓↓↓
    count_only_certifications,
    suggest_role_certifications,
    score_linkedin_public_html,
)

from .profile_scoring import *
from .ats_score_non_tech import ats_scoring_non_tech_v2

# ========= In-memory OTP / user stores (demo only) =========
registered_users: Dict[str, str] = {}
OTP_TTL_SECONDS = 300  # 5 min

def norm_email(email: str) -> str:
    return (email or "").strip().lower()

def norm_mobile(mobile: str) -> str:
    return re.sub(r"\D+", "", (mobile or "").strip())

# -------------------------------------------------------------------
# Microsoft Graph email helpers (INLINE as requested)
# Uses OUTLOOK_* from environment
# -------------------------------------------------------------------
from django.conf import settings

OUTLOOK_TENANT_ID     = os.getenv("OUTLOOK_TENANT_ID", "")
OUTLOOK_CLIENT_ID     = os.getenv("OUTLOOK_CLIENT_ID", "")
OUTLOOK_CLIENT_SECRET = os.getenv("OUTLOOK_CLIENT_SECRET", "")
OUTLOOK_SENDER_EMAIL  = os.getenv("OUTLOOK_SENDER_EMAIL", "")
EMAIL_TIMEOUT         = int(os.getenv("EMAIL_TIMEOUT", "30"))

def _graph_get_token() -> str | None:
    """Client-credentials flow for Microsoft Graph."""
    if not (OUTLOOK_TENANT_ID and OUTLOOK_CLIENT_ID and OUTLOOK_CLIENT_SECRET):
        return None
    token_url = f"https://login.microsoftonline.com/{OUTLOOK_TENANT_ID}/oauth2/v2.0/token"
    data = {
        "client_id": OUTLOOK_CLIENT_ID,
        "client_secret": OUTLOOK_CLIENT_SECRET,
        "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default",
    }
    try:
        r = requests.post(token_url, data=data, timeout=EMAIL_TIMEOUT)
        if r.ok:
            return r.json().get("access_token")
    except requests.RequestException:
        pass
    return None

def _graph_send_mail(sender_email: str, to_email: str, subject: str, body_text: str) -> tuple[bool, str]:
    """
    Sends mail via Graph: POST /v1.0/users/{sender}/sendMail
    Requires: Application permission 'Mail.Send' + admin consent, and a real mailbox for sender_email.
    """
    token = _graph_get_token()
    if not token:
        return False, "No Graph access token"

    url = f"https://graph.microsoft.com/v1.0/users/{sender_email}/sendMail"
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body_text},
            "toRecipients": [{"emailAddress": {"address": to_email}}],
        },
        "saveToSentItems": False,
    }
    try:
        r = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=EMAIL_TIMEOUT,
        )
        # 202 is expected on success
        if 200 <= r.status_code < 300:
            return True, "sent"
        return False, f"Graph sendMail failed ({r.status_code}): {r.text[:300]}"
    except requests.RequestException as e:
        return False, f"Graph request error: {e}"

def send_otp_email(to_email: str, otp: str, subject: str):
    """
    First try Microsoft Graph using your client credentials.
    If that fails, fall back to Django email backend (console or SMTP depending on settings).
    """
    sender = OUTLOOK_SENDER_EMAIL or getattr(settings, "DEFAULT_FROM_EMAIL", "") or getattr(settings, "EMAIL_HOST_USER", "")
    if not sender:
        sender = "webmaster@localhost"

    body = f"Your OTP is {otp}. It will expire in {OTP_TTL_SECONDS // 60} minutes."

    # 1) Try Graph (ideal with your provided credentials)
    ok, info = _graph_send_mail(sender, to_email, subject, body)
    if ok:
        return

    # 2) Fallback to Django backend
    from django.core.mail import send_mail as dj_send_mail
    dj_send_mail(
        subject=subject,
        message=body,
        from_email=sender,
        recipient_list=[to_email],
        fail_silently=False,
    )

# ========= Basic pages =========
def landing(request): return render(request, "landing.html")
def signin(request): return render(request, "login.html")
def login_view(request): return render(request, "login.html")
def signup(request): return render(request, "login.html")
def about_us(request): return render(request, "about_us.html")
def upload_resume(request): return render(request, "upload_resume.html")

# ------------------------
# Dedupers
# ------------------------
def _dedupe_preserve_order_strings(seq: List[str]) -> List[str]:
    seen, out = set(), []
    for item in seq:
        if not isinstance(item, str):
            continue
        k = item.strip()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out

def _dedupe_preserve_order_link_dicts(seq: List[dict]) -> List[dict]:
    seen, out = set(), []
    for item in seq:
        if not isinstance(item, dict):
            continue
        url = (item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(item)
    return out

# ------------------------
# Link extraction & helpers
# ------------------------
def _normalize_text(s: str) -> str:
    if not s:
        return ""
    return (
        s.replace("\u200b", "")  # zero-width space
        .replace("\ufeff", "")   # BOM
        .replace("\u00a0", " ")  # NBSP -> space
    )

_PORTFOLIO_HOSTS = (
    "vercel.app","netlify.app","github.io","read.cv","notion.site","notion.so",
    "about.me","carrd.co","wixsite.com","wix.com","wordpress.com","square.site",
    "webflow.io","pages.dev","framer.website","framer.ai","format.com","cargo.site",
    "showwcase.co","behance.net","dribbble.com","super.site",
)

_SOCIAL_HOSTS = (
    "linkedin.com","github.com","leetcode.com","x.com","twitter.com",
    "medium.com","dev.to","kaggle.com","gitlab.com","bitbucket.org",
    "lnkd.in","linktr.ee",
)

_PERSONAL_TLDS = (
    ".me",".dev",".app",".io",".sh",".xyz",".site",".page",".studio",".design",".works",
    ".tech",".codes",".space",".digital",
)

_GH_USER_RE = re.compile(r"https?://(?:[\w\-]+\.)?github\.com/([A-Za-z0-9\-]+)(?:/|$)", re.I)
_LI_ANY_RE  = re.compile(r"https?://(?:[\w\-]+\.)?(?:linkedin\.com|lnkd\.in)(?:/|$)", re.I)
_LI_SLUG_RE = re.compile(r"https?://(?:[\w\-]+\.)?linkedin\.com/(?:in|pub|profile)/([A-Za-z0-9\-_\.]+)/?", re.I)
_LC_USER_RE = re.compile(r"https?://(?:www\.)?leetcode\.com/(?:u|profile)/([A-Za-z0-9\-_]+)/?", re.I)

_URL_RE = re.compile(
    r"""(?ix)
    (?:\b
        (?:https?://|www\.)                           # scheme or www
        [\w\-]+(?:\.[\w\-\u00a1-\uffff]+)+            # domain.tld
        (?::\d{2,5})?                                 # optional port
        (?:/[^\s<>()\[\]{}"']*)?                      # optional path
    )
    |
    (?:\b
        (?:linkedin\.com|lnkd\.in|github\.com|leetcode\.com|notion\.so|notion\.site|
           vercel\.app|netlify\.app|github\.io|webflow\.io|pages\.dev|
           read\.cv|about\.me|carrd\.co|wixsite\.com|wix\.com|wordpress\.com|
           square\.site|framer\.website|framer\.ai|format\.com|cargo\.site|
           showwcase\.co|behance\.net|dribbble\.com|super\.site|gitlab\.com|
           bitbucket\.org|kaggle\.com|medium\.com|dev\.to|linktr\.ee)
        [^\s<>()\[\]{}"']*
    )
    """,
    re.UNICODE,
)

_PUNCT_END = re.compile(r"[),.;:!?]+$")

def _fix_obfuscations(text: str) -> str:
    t = text or ""
    t = re.sub(r"\b(dot|\[dot\]|\(dot\))\b", ".", t, flags=re.I)
    t = re.sub(r"\b(slash|\[slash\]|\(slash\))\b", "/", t, flags=re.I)
    t = re.sub(r"\b(at|\[at\]|\(at\))\b", "@", t, flags=re.I)
    t = t.replace(" :// ", "://").replace(" / ", "/")
    return t

def _ensure_scheme(u: str) -> str:
    if not u:
        return u
    if u.startswith(("http://", "https://")):
        return u
    if u.startswith("www."):
        return "https://" + u
    return "https://" + u

def _strip_trailing_punct(u: str) -> str:
    return _PUNCT_END.sub("", u).strip("()[]{}<>\"' ")

def extract_urls_from_text(text: str) -> List[str]:
    if not text:
        return []
    t = _normalize_text(_fix_obfuscations(text))
    found: List[str] = []
    for m in _URL_RE.finditer(t):
        u = _ensure_scheme(_strip_trailing_punct(m.group(0)))
        if u:
            found.append(u)
    return _dedupe_preserve_order_strings(found)

def extract_links_from_docx(path: str) -> List[str]:
    urls: List[str] = []
    try:
        with zipfile.ZipFile(path) as zf:
            rels_target = "word/_rels/document.xml.rels"
            if rels_target not in zf.namelist():
                return []
            rels_xml = ET.fromstring(zf.read(rels_target))
            rels = {}
            for rel in rels_xml.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
                rId = rel.attrib.get("Id")
                tgt = rel.attrib.get("Target")
                mode = rel.attrib.get("TargetMode", "")
                if rId and tgt and (mode == "External" or tgt.startswith("http")):
                    rels[rId] = tgt
            doc_xml = ET.fromstring(zf.read("word/document.xml"))
            NS = {
                "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
                "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
            }
            for hl in doc_xml.findall(".//w:hyperlink", NS):
                rId = hl.attrib.get("{%s}id" % NS["r"])
                if rId and rId in rels:
                    urls.append(_ensure_scheme(_strip_trailing_punct(rels[rId])))
    except Exception:
        pass
    return _dedupe_preserve_order_strings(urls)

def _domain_of(u: str) -> str:
    try:
        return urlparse(u).netloc.lower()
    except Exception:
        return ""

def classify_link(url: str, title_hint: str = "", path_hint: str = "") -> str:
    u = url or ""
    dom = _domain_of(u)
    if "linkedin.com" in dom or dom == "lnkd.in":
        return "linkedin"
    if "github.com" in dom:
        return "github"
    if "leetcode.com" in dom:
        return "leetcode"
    for h in _PORTFOLIO_HOSTS:
        if h in dom:
            return "portfolio"
    if any(dom.endswith(tld) for tld in _PERSONAL_TLDS):
        return "portfolio"
    hint = f"{title_hint or ''} {path_hint or ''}".lower()
    if any(k in hint for k in ["portfolio", "projects", "work", "case study", "case-studies", "showcase"]):
        return "portfolio"
    if dom and "." in dom and not any(s in dom for s in _SOCIAL_HOSTS):
        return "portfolio"
    return "other"

def infer_github_username(urls: List[str], text: str) -> str:
    for u in urls:
        m = _GH_USER_RE.search(u)
        if m:
            return m.group(1)
    m2 = _GH_USER_RE.search(text or "")
    return m2.group(1) if m2 else ""

def infer_linkedin_slug(urls: List[str], text: str) -> str:
    for u in urls:
        m = _LI_SLUG_RE.search(u)
        if m:
            return m.group(1)
    m2 = _LI_SLUG_RE.search(text or "")
    return m2.group(1) if m2 else ""

def infer_leetcode_username(urls: List[str], text: str) -> str:
    for u in urls:
        m = _LC_USER_RE.search(u)
        if m:
            return m.group(1)
    m2 = _LC_USER_RE.search(text or "")
    return m2.group(1) if m2 else ""

def _detect_contact(resume_text: str) -> bool:
    email = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", resume_text or "")
    phone = re.search(r"(\+?\d[\d\s\-()]{8,})", resume_text or "")
    return bool(email or phone)

def _grade_pct_label(pct: float) -> str:
    if pct >= 85:
        return "Excellent"
    if pct >= 70:
        return "Good"
    if pct >= 50:
        return "Average"
    return "Poor"

# ------------------------
# URL validation (only valid links influence scoring)
# ------------------------
_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ApplyWizzBot/1.3)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en",
    "Connection": "close",
}
_session = requests.Session()
_session.headers.update(_DEFAULT_HEADERS)

def _extract_title(html: str) -> str:
    if not html:
        return ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip()[:200] if m else ""

def fetch_url_status(url: str, timeout: float = 7.5) -> Dict[str, Any]:
    """
    HEAD -> GET with redirects. Returns final_url, status, ok (200), title, path_hint, html.
    Also treats LinkedIn public profile URL patterns as 'present' even if behind a login wall,
    but scoring from HTML will only happen if we actually get a 200 and real HTML.
    """
    result = {"url": url, "final_url": url, "status": None, "ok": False, "title": "", "path_hint": "", "html": ""}

    if not url:
        return result

    try:
        r = _session.head(url, allow_redirects=True, timeout=timeout)
        result.update({"status": r.status_code, "final_url": r.url, "path_hint": urlparse(r.url).path})
        if r.status_code == 200:
            result["ok"] = True

        # Always try GET to capture HTML/title when publicly available
        r = _session.get(result["final_url"], allow_redirects=True, timeout=timeout)
        result.update({"status": r.status_code, "final_url": r.url, "path_hint": urlparse(r.url).path})
        if r.status_code == 200:
            result["ok"] = True
            result["html"] = r.text or ""
            result["title"] = _extract_title(r.text or "")

        # Soft fallback: mark *pattern* as present (ok) for presence UI,
        # but note we still won't have HTML for scoring unless status==200 above.
        host = (urlparse(result["final_url"]).netloc or "").lower()
        path = (urlparse(result["final_url"]).path or "")
        if not result["ok"] and ("linkedin.com" in host or host == "lnkd.in") and re.match(r"^/(in|pub|profile)/", path, flags=re.I):
            result["ok"] = True
            result["title"] = result["title"] or "LinkedIn Profile"

    except (RequestException, SSLError, Timeout, ReqConnError, socket.error):
        pass

    return result

def validate_links_enrich(links: List[Dict[str, Any]], max_workers: int = 6) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    futures = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for item in links:
            if not isinstance(item, dict):
                continue
            url = (item.get("url") or "").strip()
            if not url:
                continue
            futures[ex.submit(fetch_url_status, url)] = item
        for fut in as_completed(futures):
            base = futures[fut]
            info = fut.result() if fut else {}
            final_url = info.get("final_url") or base.get("url")
            new_type  = classify_link(final_url, info.get("title") or "", info.get("path_hint") or "")
            enriched.append({**base, **info, "type": new_type})
    by_url = {e.get("url"): e for e in enriched if e.get("url")}
    ordered, seen = [], set()
    for item in links:
        u = (item.get("url") or "").strip()
        if not u or u in seen:
            continue
        ordered.append(by_url.get(u, item))
        seen.add(u)
    return ordered

def only_ok_links(links: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [l for l in links if l.get("ok")]

# ------------------------
# Certifications – extraction + dynamic scoring helpers
# ------------------------
_CERT_HEAD_RE = re.compile(r"^\s*(licenses?\s*&?\s*certifications?|certifications?|licenses?)\s*$", re.I)
_BULLET_RE = re.compile(r"^\s*(?:[-*•■●]|[0-9]+\.)\s*(.+)$")
_CERT_LINE_HINT = re.compile(r"(certif|license|licen[sc]e|credential|badge|certificate|exam|id:|license:)", re.I)

_CERT_PROVIDERS = (
    "aws","amazon web services","azure","microsoft","google cloud","gcp",
    "coursera","udemy","udacity","datacamp","databricks","snowflake","tableau",
    "power bi","oracle","salesforce","trailhead","cisco","red hat","linux foundation",
    "ibm","pmi","prince2","itil","scrum","comptia","kubernetes","ckad","cka","ckad/cka",
    "sap","okta","hashicorp","terraform","mongodb","redis","elastic","neo4j",
)

_CERT_LINK_HOSTS = (
    "credly.com","youracclaim.com","accredible.com","badgr.com","openbadgepassport.com",
    "coursera.org","udemy.com","trailhead.salesforce.com","trailhead.salesforce",
    "aws.amazon.com","cloud.google.com","learn.microsoft.com","docs.microsoft.com",
    "oracle.com","education.oracle.com","datacamp.com","academy.databricks.com",
    "udacity.com","learn.udacity.com","tableau.com","certificates.tableau.com",
    "cisco.com","comptia.org","redhat.com","training.linuxfoundation.org",
)

_CERT_LEVELS = ("associate","professional","expert","specialty","advanced","foundational","practitioner")
_CERT_RELEVANCE_HINTS = (
    "aws","azure","gcp","google cloud","cloud practitioner","solutions architect",
    "devops","kubernetes","k8s","docker","security",
    "data","ml","machine learning","ai","analytics","etl","elt",
    "spark","hadoop","dbt","airflow","snowflake","bigquery","redshift",
    "sql","database","dba","data engineer","data scientist","python","pyspark",
    "tableau","power bi","salesforce","oracle","terraform",
)

def _split_lines_keep(text: str) -> List[str]:
    raw = (text or "")
    parts: List[str] = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln:
            parts.append("")
            continue
        # Split common inline bullet/sep chars
        for chunk in re.split(r"[•·\u2022\|;/,]+", ln):
            c = (chunk or "").strip(" -\t")
            if c:
                parts.append(c)
    return parts

def _looks_like_cert_line(s: str) -> bool:
    if not s:
        return False
    s = s.strip()
    if _CERT_LINE_HINT.search(s):
        return True
    if re.search(r"\b(certified|certificate|credential)\b", s, re.I) and any(p in s.lower() for p in _CERT_PROVIDERS):
        return True
    if re.search(r"\b(AZ|DP|AI|PL|SC|MS)-\d{3}\b", s):
        return True
    if re.search(r"\b(CCA|CKA|CKAD|CKS|PCSAE|PCDRA|PCA)\b", s):
        return True
    if any(k in s.lower() for k in ["digital leader","data engineer","solutions architect","cloud practitioner","desktop specialist"]):
        return True
    return False

def _normalize_cert_name(s: str) -> str:
    s = re.sub(r"\b(license|licen[sc]e|credential\s*id|id|no\.?)\b.*$", "", s, flags=re.I)
    s = re.sub(r"\s{2,}", " ", s).strip(" -–—")
    return s[:180]

def extract_certifications_block(resume_text: str) -> List[str]:
    lines = _split_lines_keep(resume_text)
    out: List[str] = []
    in_block = False
    for line in lines:
        if _CERT_HEAD_RE.match(line):
            in_block = True
            continue
        if in_block:
            if not line.strip():
                continue
            if re.match(r"^(experience|education|projects?|skills?|profile|summary|achievements?)\s*:?\s*$", line, re.I) \
               or re.match(r"^[A-Z][A-Z \-/&]{2,}$", line):
                in_block = False
                continue
            m = _BULLET_RE.match(line)
            candidate = (m.group(1) if m else line).strip()
            if _looks_like_cert_line(candidate):
                out.append(_normalize_cert_name(candidate))
    return out

def extract_certifications_anywhere(resume_text: str) -> List[str]:
    segs = _split_lines_keep(resume_text)
    hits = []
    for s in segs:
        if _looks_like_cert_line(s):
            hits.append(_normalize_cert_name(s))
    norm_map = {}
    for h in hits:
        key = re.sub(r"[\s\-–—]+", " ", h.lower())
        norm_map.setdefault(key, h)
    return list(norm_map.values())

def extract_certifications_from_links(links: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    certs = []
    for l in links or []:
        u = (l.get("final_url") or l.get("url") or "")
        t = (l.get("title") or "")
        dom = (urlparse(u).netloc or "").lower()
        if any(h in dom for h in _CERT_LINK_HOSTS) or "verify" in u.lower() or "badge" in u.lower():
            certs.append({"name": _normalize_cert_name(t or u), "link": u, "ok": bool(l.get("ok"))})
    return certs

def score_certifications(resume_text: str, enriched_links: List[Dict[str, Any]]) -> Tuple[int, List[str], List[str]]:
    from_section = extract_certifications_block(resume_text)
    from_anywhere = extract_certifications_anywhere(resume_text)
    link_items = extract_certifications_from_links(enriched_links)

    text_names = _dedupe_preserve_order_strings(from_section + from_anywhere)
    evidence = []
    verifiable_count = 0
    for it in link_items:
        link = it.get("link")
        if link and link not in evidence:
            evidence.append(link)
        if it.get("ok"):
            verifiable_count += 1

    joined_text = " ".join(text_names + [it.get("name","") for it in link_items]).lower()
    relevant = any(h in joined_text for h in _CERT_RELEVANCE_HINTS)
    level_hit = any(lvl in joined_text for lvl in _CERT_LEVELS)

    unique_cert_count = len(text_names) + len([1 for _ in link_items if not text_names])
    score = 0
    rats: List[str] = []

    if unique_cert_count > 0:
        score += min(4, unique_cert_count)
        rats.append(f"{unique_cert_count} certification(s) identified.")
    if relevant:
        score += 2; rats.append("Certifications relevant to role (cloud/data/devops/analytics/etc.).")
    if verifiable_count >= 1:
        score += 2; rats.append("Verifiable credential link detected.")
    if level_hit:
        score += 1; rats.append("Higher-level credential (Associate/Professional/Expert) mentioned.")
    score = min(9, score)

    if unique_cert_count == 0 and verifiable_count == 0:
        rats = ["No certifications found."]

    return score, rats, evidence

# ========= OTP SIGNUP / LOGIN =========
@csrf_exempt
def send_signup_otp(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Invalid request"}, status=405)
    email = norm_email(request.POST.get("email", ""))
    mobile = norm_mobile(request.POST.get("mobile", ""))
    if not email or not mobile:
        return JsonResponse({"status": "error", "message": "Email and mobile required"}, status=400)
    otp = f"{random.randint(100000, 999999)}"
    cache_key = f"signup_otp:{email}:{mobile}"
    from django.core.cache import cache
    cache.set(cache_key, otp, timeout=OTP_TTL_SECONDS)
    try:
        send_otp_email(email, otp, subject="Your ApplyWizz Signup OTP")
        return JsonResponse({"status": "success", "message": "OTP sent to your email"})
    except Exception as e:
        return JsonResponse({"status": "error", "message": f"Failed to send OTP: {e}"}, status=500)

@csrf_exempt
def verify_signup_otp(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Invalid request"}, status=405)
    email = norm_email(request.POST.get("email", ""))
    mobile = norm_mobile(request.POST.get("mobile", ""))
    otp = (request.POST.get("otp", "") or "").strip()
    from django.core.cache import cache
    cache_key = f"signup_otp:{email}:{mobile}"
    stored_otp = cache.get(cache_key)
    if stored_otp and stored_otp == otp:
        registered_users[mobile] = email
        cache.delete(cache_key)
        return JsonResponse({"status": "success", "redirect_url": "/login"})
    else:
        return JsonResponse({"status": "error", "message": "Invalid or expired OTP"}, status=400)

@csrf_exempt
def send_login_otp(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Invalid request"}, status=405)
    email = norm_email(request.POST.get("email", ""))
    if not email:
        return JsonResponse({"status": "error", "message": "Email required"}, status=400)
    otp = f"{random.randint(100000, 999999)}"
    from django.core.cache import cache
    cache_key = f"login_otp:{email}"
    cache.set(cache_key, otp, timeout=OTP_TTL_SECONDS)
    try:
        send_otp_email(email, otp, subject="Your ApplyWizz Login OTP")
        return JsonResponse({"status": "success", "message": "OTP sent to your email"})
    except Exception as e:
        return JsonResponse({"status": "error", "message": f"Failed to send OTP: {e}"}, status=500)

@csrf_exempt
def verify_login_otp(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Invalid request"}, status=405)
    email = norm_email(request.POST.get("email", ""))
    otp = (request.POST.get("otp", "") or "").strip()
    from django.core.cache import cache
    cache_key = f"login_otp:{email}"
    stored_otp = cache.get(cache_key)
    if stored_otp and stored_otp == otp:
        cache.delete(cache_key)
        return JsonResponse({"status": "success", "redirect_url": "/upload_resume"})
    else:
        return JsonResponse({"status": "error", "message": "Invalid or expired OTP"}, status=400)

# ========= PDF Download =========
def download_resume_pdf(request):
    # pull either key (tech/non-tech)
    context = request.session.get("resume_context_tech") or \
              request.session.get("resume_context_nontech") or \
              request.session.get("resume_context", {})
    template_path = "resume_result.html"
    # simple heuristic switcher
    if context and context.get("github_detection") == "NO" and context.get("role") in ["Human Resources","Marketing","Sales","Finance","Customer Service"]:
        template_path = "score_of_non_tech.html"
    template = get_template(template_path)
    html = template.render(context)
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="resume_report.pdf"'
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse("We had some errors <pre>" + html + "</pre>")
    return response

# ========= Technical analyzer =========
@require_POST
def analyze_resume(request):
    role = request.POST.get('tech_role')  # Check for the technical role
    if role:
        # If the selected role is 'technical', call the technical analyzer
        return analyze_resume(request)

    role = request.POST.get('nontech_role')  # Check for the non-technical role
    if role:
        # If the selected role is 'non-technical', call the non-tech analyzer
        return analyze_resume_v2(request)

    resume_file = request.FILES["resume"]
    ext = os.path.splitext(resume_file.name)[1].lower()

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        for chunk in resume_file.chunks():
            tmp.write(chunk)
        temp_path = tmp.name

    try:
        # 1) Extract text & anchors
        if ext == ".pdf":
            legacy_links, resume_text_raw = extract_links_combined(temp_path)
            resume_text = _normalize_text(resume_text_raw or "")
        elif ext == ".docx":
            resume_text_raw = extract_text_from_docx(temp_path) or ""
            resume_text = _normalize_text(resume_text_raw)
            legacy_links = extract_links_from_docx(temp_path)
        elif ext in (".txt",):
            with open(temp_path, "r", encoding="utf-8", errors="ignore") as f:
                resume_text_raw = f.read()
            resume_text = _normalize_text(resume_text_raw or "")
            legacy_links = []
        else:
            return HttpResponseBadRequest("Unsupported file format.")

        # 2) Metadata enrich + URLs from text
        resume_links_full = (
            process_resume_links(
                temp_path,
                mime_type=resume_file.content_type,
                fetch_metadata=True,
                limit=120,
            ) or []
        )

        text_urls = extract_urls_from_text(resume_text)
        existing = {i.get("url") for i in resume_links_full if i.get("url")}
        extra_pool = []
        for u in (legacy_links + text_urls):
            if not u or u in existing:
                continue
            extra_pool.append({
                "url": u,
                "domain": _domain_of(u),
                "type": "other",
                "title": "",
                "description": "",
            })
        merged_links = _dedupe_preserve_order_link_dicts(resume_links_full + extra_pool)

        # 3) Validate links
        enriched_links = validate_links_enrich(merged_links)
        ok_links = only_ok_links(enriched_links)
        link_urls_ok  = [i.get("final_url") or i.get("url") for i in ok_links if i.get("url")]
        link_urls_all = [i.get("final_url") or i.get("url") for i in enriched_links if i.get("url")]

        # 4) Inputs / usernames
        applicant_name    = extract_applicant_name(resume_text) or "Candidate"
        github_username   = (request.POST.get("github_username", "") or "").strip() \
                            or extract_github_username(resume_text) \
                            or infer_github_username(link_urls_ok or link_urls_all, resume_text) \
                            or ""
        leetcode_username = (request.POST.get("leetcode_username", "") or "").strip() \
                            or extract_leetcode_username(resume_text) \
                            or infer_leetcode_username(link_urls_ok or link_urls_all, resume_text) \
                            or ""
        role_slug         = request.POST.get("tech_role", "software_engineer")
        job_description   = (request.POST.get("job_description", "") or "").strip()

        # 5) Dynamic ATS
        dyn = calculate_dynamic_ats_score(
            resume_text=resume_text,
            github_username=github_username if any("github.com" in (u or "") for u in link_urls_ok) else "",
            leetcode_username=leetcode_username if any("leetcode." in (u or "") for u in link_urls_ok) else "",
            extracted_links=ok_links,
        )

        # 6) Optional GitHub API score if token + reachable profile
        github_token = os.getenv("GITHUB_TOKEN")
        if github_username and github_token and any(l for l in ok_links if l.get("type") == "github"):
            try:
                gh_score, gh_rationales, gh_evidence, _ = score_github_via_api(github_username, github_token)
                if "sections" in dyn and "GitHub Profile" in dyn["sections"]:
                    dyn["sections"]["GitHub Profile"]["score"] = gh_score
                    dyn["sections"]["GitHub Profile"].setdefault("sub_criteria", []).append(
                        {"name": "API Evaluation", "score": gh_score, "weight": 27, "insight": "GitHub API assessment"}
                    )
            except Exception as e:
                print(f"GitHub API error (fallback to heuristic): {e}")

        # 6b) LinkedIn public HTML (only if 200 OK page captured)
        ok_linkedin = next((l for l in ok_links if l.get("type") == "linkedin"), None)
        if ok_linkedin:
            li_html = ok_linkedin.get("html", "") or ""
            li_url  = ok_linkedin.get("final_url") or ok_linkedin.get("url") or ""
            li_score_pub, li_rats_pub, li_evidence_pub = score_linkedin_public_html(li_html, li_url, resume_text)
            if "sections" in dyn and "LinkedIn" in dyn["sections"] and isinstance(li_score_pub, (int, float)):
                base_score = int(dyn["sections"]["LinkedIn"].get("score", 0) or 0)
                dyn["sections"]["LinkedIn"]["score"] = max(base_score, int(li_score_pub))
                dyn["sections"]["LinkedIn"].setdefault("sub_criteria", []).append(
                    {"name": "Public Profile Parse", "score": int(li_score_pub), "weight": 18, "insight": " ; ".join(li_rats_pub)}
                )

        # 7) Presence notes for UI rows
        linkedin_present_any  = any(_LI_ANY_RE.search((l.get("final_url") or l.get("url") or "")) for l in enriched_links)
        portfolio_present_any = any(l for l in enriched_links if l.get("type") == "portfolio")
        ok_portfolio          = [l for l in ok_links if l.get("type") == "portfolio"]

        def _ensure_presence_row(subrows, label_prefix, text, score_val=0):
            updated = False
            for r in subrows:
                name = (r.get("name","") or "").lower().strip()
                if name.startswith(label_prefix):
                    r["insight"] = text
                    r.setdefault("weight", 2)
                    r["score"] = score_val
                    updated = True
                    break
            if not updated:
                subrows.insert(0, {"name": label_prefix.title(), "score": score_val, "weight": 2, "insight": text})

        li_sec = dyn["sections"].get("LinkedIn", {"score": 0, "sub_criteria": []})
        li_sub = li_sec.get("sub_criteria") or []
        if linkedin_present_any and not ok_linkedin:
            _ensure_presence_row(li_sub, "profile presence", "Profile link present but unreachable (login/blocked).", 0)
        elif ok_linkedin:
            _ensure_presence_row(li_sub, "profile presence", "Profile link present and reachable (public).", 2)
        li_sec["sub_criteria"] = li_sub
        dyn["sections"]["LinkedIn"] = li_sec

        pf_sec = dyn["sections"].get("Portfolio Website", {"score": 0, "sub_criteria": []})
        pf_sub = pf_sec.get("sub_criteria") or []
        if portfolio_present_any and not ok_portfolio:
            _ensure_presence_row(pf_sub, "portfolio presence", "Portfolio link present but unreachable.", 0)
        elif ok_portfolio:
            _ensure_presence_row(pf_sub, "portfolio presence", "Portfolio link(s) present and reachable.", 2)
        pf_sec["sub_criteria"] = pf_sub
        dyn["sections"]["Portfolio Website"] = pf_sec

        # 8) Certifications count-in (show only count, no names)
        cert_count, cert_names_found = count_only_certifications(resume_text, enriched_links)

        cert_sec_key = "Certifications & Branding"
        cert_sec = dyn["sections"].get(cert_sec_key, {"score": 0, "sub_criteria": []})
        cert_sub = cert_sec.get("sub_criteria") or []

        cert_score_by_count = min(9, max(0, int(cert_count)))
        cert_sec["score"] = max(int(cert_sec.get("score", 0) or 0), cert_score_by_count)

        # remove any prior auto rows
        cert_sub = [r for r in cert_sub if not (isinstance(r, dict) and str(r.get("name","")).startswith("[Auto]"))]

        # NOTE: We do NOT list certificate names anymore — only the count.
        cert_sub.insert(0, {
            "name": "[Auto] Certifications Found",
            "score": cert_score_by_count,
            "weight": 9,
            "insight": f"Detected {cert_count} certification(s).",
        })

        cert_sec["sub_criteria"] = cert_sub
        dyn["sections"][cert_sec_key] = cert_sec

        # 9) Suggest role-aware certs to top-up to 6 (kept as suggestions)
        suggested_certs = []
        if cert_count < 6:
            needed = 6 - cert_count
            suggested_certs = suggest_role_certifications(
                role_text=role_slug,
                job_description=job_description,
                resume_text=resume_text,
                existing_cert_lines=cert_names_found,
                max_items=needed,
            )

        # 10) Build report sections (DYNAMIC — no hard-coded maxima)
        map_to_dyn = {
            "GitHub":         "GitHub Profile",
            "LinkedIn":       "LinkedIn",
            "Portfolio":      "Portfolio Website",
            "Resume (ATS)":   "Resume (ATS Score)",
            "Certifications": "Certifications & Branding",
        }

        DEFAULT_SECTION_MAX = {
            "GitHub": 27,
            "LinkedIn": 18,
            "Portfolio": 23,
            "Resume (ATS)": 23,
            "Certifications": 9,
        }

        dyn_weights = dyn.get("weights") or {}

        def dyn_max_for(tpl_name: str) -> int:
            dyn_key = map_to_dyn[tpl_name]
            sec = dyn["sections"].get(dyn_key, {})
            if isinstance(sec, dict) and isinstance(sec.get("max"), (int, float)):
                return int(sec["max"])
            if dyn_key in dyn_weights and isinstance(dyn_weights[dyn_key], (int, float)):
                return int(dyn_weights[dyn_key])
            if tpl_name in dyn_weights and isinstance(dyn_weights[tpl_name], (int, float)):
                return int(dyn_weights[tpl_name])
            return DEFAULT_SECTION_MAX[tpl_name]

        SECTION_MAX = {name: dyn_max_for(name) for name in map_to_dyn.keys()}
        TOTAL_MAX = sum(SECTION_MAX.values())

        def _safe_sec(name):
            return dyn["sections"].get(name, {"score": 0, "grade": "Poor", "sub_criteria": []})

        github_sec    = _safe_sec(map_to_dyn["GitHub"])
        linkedin_sec  = _safe_sec(map_to_dyn["LinkedIn"])
        portfolio_sec = _safe_sec(map_to_dyn["Portfolio"])
        resume_sec    = _safe_sec(map_to_dyn["Resume (ATS)"])
        certs_sec     = _safe_sec(map_to_dyn["Certifications"])

        section_scores = {
            "GitHub":         int(github_sec.get("score", 0) or 0),
            "LinkedIn":       int(linkedin_sec.get("score", 0) or 0),
            "Portfolio":      int(portfolio_sec.get("score", 0) or 0),
            "Resume (ATS)":   int(resume_sec.get("score", 0) or 0),
            "Certifications": int(certs_sec.get("score", 0) or 0),
        }

        weights_pct = {
            k: int(round((SECTION_MAX[k] / float(TOTAL_MAX)) * 100)) if TOTAL_MAX else 0
            for k in SECTION_MAX
        }

        def _grade_pct(pct: float) -> str:
            if pct >= 85:
                return "Excellent"
            if pct >= 70:
                return "Good"
            if pct >= 50:
                return "Average"
            return "Poor"

        score_breakdown, score_breakdown_ordered = {}, []
        for tpl_name in ["GitHub","LinkedIn","Portfolio","Resume (ATS)","Certifications"]:
            score  = section_scores[tpl_name]
            maxpts = SECTION_MAX[tpl_name]
            grade  = _grade_pct((score / maxpts) * 100 if maxpts else 0)
            score_breakdown[tpl_name] = {"score": score, "max": maxpts, "grade": grade, "weight": weights_pct[tpl_name]}
            score_breakdown_ordered.append((tpl_name, {
                "score": score,
                "grade": grade,
                "sub_criteria": (_safe_sec(map_to_dyn[tpl_name]).get("sub_criteria") or []),
            }))

        total_score     = sum(section_scores.values())
        profile_percent = int(round((total_score / float(TOTAL_MAX)) * 100)) if TOTAL_MAX else 0

        def _color_class(pct: int) -> str:
            if pct > 80: return "score-box"
            if pct >= 50: return "score-box-orange"
            return "score-box-red"

        # DYNAMIC ATS percent
        ats_score_val = int(resume_sec.get("score", 0) or 0)
        ats_max_val   = SECTION_MAX["Resume (ATS)"] or 1
        ats_percent   = int(round((ats_score_val / float(ats_max_val)) * 100))
        ats_score_class     = _color_class(ats_percent)
        profile_score_class = _color_class(profile_percent)

        # 11) Charts — dynamic maxima in legend
        def _build_pie_base64_local(scores: Dict[str, int]) -> str:
            if not scores or sum(scores.values()) == 0:
                return ""
            labels, values = list(scores.keys()), list(scores.values())
            fig, ax = plt.subplots(figsize=(4.6, 4.6), facecolor="#121212")
            ax.set_facecolor("#121212")
            def _autopct(p): return f"{p:.0f}%" if p >= 5 else ""
            wedges, _, _ = ax.pie(values, labels=None, autopct=_autopct, startangle=140,
                                  textprops={"color": "white", "fontsize": 10})
            ax.axis("equal")
            legend_labels = [
                f"{lbl}: {val}/{SECTION_MAX[lbl]} ({(val/SECTION_MAX[lbl])*100:.0f}%)"
                for lbl, val in zip(labels, values)
            ]
            ax.legend(wedges, legend_labels, loc="lower center", bbox_to_anchor=(0.5, -0.22),
                      fontsize=9, frameon=False, labelcolor="white", ncol=2, columnspacing=1.2,
                      handlelength=1.2, borderpad=0.2)
            buf = io.BytesIO()
            plt.tight_layout()
            plt.savefig(buf, format="png", dpi=160, facecolor="#121212", bbox_inches="tight")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            buf.close(); plt.close(fig)
            return b64

        pie_chart_image = _build_pie_base64_local(section_scores)

        # 12) Reweighted Screening Emphasis (Initial Screen)
        REWEIGHTED = {
            "MAANG":       {"GitHub": 22, "LinkedIn": 22, "Portfolio": 20, "Resume": 31, "Certifications": 5},
            "Startups":    {"GitHub": 30, "LinkedIn": 18, "Portfolio": 28, "Resume": 20, "Certifications": 4},
            "Mid-sized":   {"GitHub": 25, "LinkedIn": 22, "Portfolio": 23, "Resume": 24, "Certifications": 6},
            "Fortune 500": {"GitHub": 18, "LinkedIn": 25, "Portfolio": 17, "Resume": 30, "Certifications": 10},
        }

        gh_pct = (section_scores["GitHub"]       / float(SECTION_MAX["GitHub"]))       * 100.0 if SECTION_MAX["GitHub"] else 0.0
        li_pct = (section_scores["LinkedIn"]     / float(SECTION_MAX["LinkedIn"]))     * 100.0 if SECTION_MAX["LinkedIn"] else 0.0
        pf_pct = (section_scores["Portfolio"]    / float(SECTION_MAX["Portfolio"]))    * 100.0 if SECTION_MAX["Portfolio"] else 0.0
        rs_pct = (section_scores["Resume (ATS)"] / float(SECTION_MAX["Resume (ATS)"])) * 100.0 if SECTION_MAX["Resume (ATS)"] else 0.0
        ce_pct = (section_scores["Certifications"]/ float(SECTION_MAX["Certifications"])) * 100.0 if SECTION_MAX["Certifications"] else 0.0

        def compute_company_emphasis(gh, li, pf, rs, ce):
            scores = {}
            for company, w in REWEIGHTED.items():
                total = (gh * w["GitHub"] + li * w["LinkedIn"] + pf * w["Portfolio"]
                         + rs * w["Resume"] + ce * w["Certifications"]) / 100.0
                scores[company] = round(total, 1)
            return scores

        screening_scores = compute_company_emphasis(gh_pct, li_pct, pf_pct, rs_pct, ce_pct)

        def _build_company_screening_bar(scores_dict: Dict[str, float]) -> str:
            if not scores_dict:
                return ""
            import matplotlib as mpl
            import matplotlib.pyplot as plt
            mpl.rcParams.update({
                "font.family": "DejaVu Sans",
                "font.sans-serif": ["DejaVu Sans"],
                "axes.titleweight": "bold",
            })
            order = ["MAANG", "Startups", "Mid-sized", "Fortune 500"]
            vals = [float(scores_dict.get(k, 0.0)) for k in order]
            fig, ax = plt.subplots(figsize=(7.2, 3.9), facecolor="#121212")
            ax.set_facecolor("#121212")
            bars = ax.bar(order, vals, linewidth=0.6, edgecolor="#e6e6e6", alpha=0.95)
            ax.set_ylim(0, 100)
            ax.set_ylabel("Weighted score (0–100)", color="white", fontsize=10, fontweight="bold", labelpad=8)
            ax.set_title("Screening Emphasis by Company Type (Initial Screen)",
                        color="white", fontsize=8, fontweight="bold", pad=5)
            ax.tick_params(axis="x", colors="white", labelsize=8)
            ax.tick_params(axis="y", colors="white", labelsize=8)
            ax.spines["bottom"].set_color("#444"); ax.spines["left"].set_color("#444")
            ax.spines["top"].set_visible(False);   ax.spines["right"].set_visible(False)
            ax.grid(axis="y", color="#333", alpha=0.35, linewidth=0.7)
            for rect, v in zip(bars, vals):
                ax.text(rect.get_x() + rect.get_width()/2.0, rect.get_height() + 2, f"{v:.0f}",
                        ha="center", va="bottom", color="white", fontsize=10, fontweight="bold")
            buf = io.BytesIO(); plt.tight_layout()
            plt.savefig(buf, format="png", dpi=170, facecolor="#121212", bbox_inches="tight")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            buf.close(); plt.close(fig); return b64

        screening_chart_image = _build_company_screening_bar(screening_scores)

        # 13) Final context
        context = {
            "result_key": hashlib.sha256(json.dumps({
                "role_type": "technical",
                "role_slug": role_slug,
                "resume_hash": hashlib.sha256((resume_text or "").encode("utf-8")).hexdigest(),
                "github": github_username or "",
                "leetcode": leetcode_username or "",
            }, sort_keys=True).encode("utf-8")).hexdigest(),

            "applicant_name": applicant_name,

            # Header badges
            "ats_score": ats_percent,
            "ats_score_class": ats_score_class,
            "overall_score_average": profile_percent,
            "profile_score_class": profile_score_class,

            # Detections (presence)
            "contact_detection": "YES" if _detect_contact(resume_text) else "NO",
            "linkedin_detection": "YES" if linkedin_present_any else "NO",
            "github_detection": "YES" if (any(l for l in ok_links if l.get("type") == "github") or bool(github_username)) else "NO",

            # Table & cards
            "score_breakdown": score_breakdown,
            "score_breakdown_ordered": score_breakdown_ordered,
            "total_score": total_score,
            "total_grade": _grade_pct_label(profile_percent),

            # Charts
            "pie_chart_image": pie_chart_image,
            "screening_chart_image": screening_chart_image,
            "screening_scores": screening_scores,

            # Suggestions / misc
            "role": role_slug,
            "suggestions": (dyn.get("suggestions") or [])[:8],

            # Certifications: suggestions (no listing of found names)
            "missing_certifications": suggested_certs,
            "missing_certifications_block": (
                ("CERTIFICATIONS\n" + "\n".join(suggested_certs)) if suggested_certs else ""
            ),

            # Rich links for UI
            "extracted_links": enriched_links,
        }

        request.session["resume_context_tech"] = context
        request.session.modified = True
        return render(request, "resume_result.html", context)

    finally:
        try:
            os.unlink(temp_path)
        except Exception:
            pass

# ========= Non-tech analyzer =========
@require_POST
def analyze_resume_v2(request):
    context = {
        "applicant_name": "N/A",
        "ats_score": 0,
        "overall_score_average": 0,
        "overall_grade": "N/A",
        "score_breakdown": {},
        "suggestions": [],
        "pie_chart_image": None,
        "detected_links": [],
        "error": None,
        "contact_detection": "NO",
        "github_detection": "NO",
        "linkedin_detection": "NO",
    }
    if request.method == "POST" and request.FILES.get("resume"):
        resume_file = request.FILES["resume"]
        ext = os.path.splitext(resume_file.name)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            for chunk in resume_file.chunks():
                tmp.write(chunk)
            temp_path = tmp.name
        try:
            if ext == ".pdf":
                extracted_links, resume_text_raw = extract_links_combined(temp_path)
                resume_text = _normalize_text(resume_text_raw or "")
            elif ext == ".docx":
                resume_text_raw = extract_text_from_docx(temp_path) or ""
                resume_text = _normalize_text(resume_text_raw)
                extracted_links = extract_links_from_docx(temp_path)
            elif ext in (".txt",):
                with open(temp_path, "r", encoding="utf-8", errors="ignore") as f:
                    resume_text_raw = f.read()
                resume_text = _normalize_text(resume_text_raw or "")
                extracted_links = []
            else:
                context["error"] = "Unsupported file format."
                return render(request, "score_of_non_tech.html", context)

            text_urls = extract_urls_from_text(resume_text)
            merged = _dedupe_preserve_order_strings((extracted_links or []) + text_urls)

            display_links = [{"url": u, "type": "other"} for u in merged]
            display_links = validate_links_enrich(display_links)

            contact_detection = "YES" if _detect_contact(resume_text) else "NO"
            github_detection = "YES" if any(l for l in display_links if l.get("ok") and l.get("type") == "github") else "NO"
            linkedin_detection = "YES" if any(_LI_ANY_RE.search((l.get("final_url") or l.get("url") or "")) for l in display_links) else "NO"
            applicant_name = extract_applicant_name(resume_text) or "N/A"

            ats_result = ats_scoring_non_tech_v2(temp_path)

            context.update({
                "applicant_name": applicant_name,
                "ats_score": ats_result.get("ats_score", 0),
                "overall_score_average": ats_result.get("overall_score_average", 0),
                "overall_grade": ats_result.get("overall_grade", "N/A"),
                "score_breakdown": ats_result.get("score_breakdown", {}),
                "pie_chart_image": ats_result.get("pie_chart_image"),
                "suggestions": ats_result.get("suggestions", []),
                "detected_links": display_links,
                "contact_detection": contact_detection,
                "github_detection": github_detection,
                "linkedin_detection": linkedin_detection,
            })
        finally:
            try:
                os.unlink(temp_path)
            except Exception:
                pass

    request.session["resume_context_nontech"] = context
    request.session.modified = True
    return render(request, "score_of_non_tech.html", context)

# ========= Show reports =========
def show_report_technical(request):
    ctx = request.session.get("resume_context_tech")
    if not ctx:
        return redirect("upload_resume")
    return render(request, "resume_result.html", ctx)

def show_report_nontechnical(request):
    ctx = request.session.get("resume_context_nontech")
    if not ctx:
        return redirect("upload_resume")
    return render(request, "score_of_non_tech.html", ctx)

def why(request): return render(request, "why.html")
def who(request): return render(request, "who.html")

@csrf_protect
def ats_report_view(request):
    if request.method == "GET":
        ctx = {
            "applicant_name": "",
            "contact_detection": "NO",
            "linkedin_detection": "NO",
            "github_detection": "NO",
            "ats_score": 0,
            "overall_score_average": 0,
            "score_breakdown": {},
            "score_breakdown_ordered": [],
            "total_score": 0,
            "total_grade": "Poor",
            "pie_chart_image": "",
            "missing_certifications": [],
            "suggestions": [],
            "role": "",
        }
        return render(request, "ats_report.html", ctx)
    return HttpResponseBadRequest("Use the upload endpoint to submit a resume.")

