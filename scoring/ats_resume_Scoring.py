# ats_resume_scoring.py
# ------------------------------------------------------------
# ATS Resume Scoring (max 23) using Gemini parsing + heuristics
# ------------------------------------------------------------
# pip install google-generativeai python-dotenv
# export GEMINI_API_KEY=your_key  (or use .env with python-dotenv)

from __future__ import annotations
import os, re, json, math
from dataclasses import dataclass
from typing import Dict, List, Tuple, Any, Optional

# Optional: load API key from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ---- Gemini setup (safe placeholder; no keys printed) ----
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
USE_GEMINI = bool(GEMINI_API_KEY)

if USE_GEMINI:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    # Use a fast model for extraction; upgrade to pro if you prefer.
    _GEMINI_MODEL = genai.GenerativeModel("gemini-1.5-flash")

# ------------ Weights (total = 23) ------------
W_KEYWORD = 5
W_IMPACT  = 7
W_ATS     = 4
W_CLARITY = 4
W_ROLE    = 3

# ------------ Helpers ------------

ACTION_VERBS = {
    "achieved","analyzed","architected","automated","built","configured","created","designed",
    "developed","deployed","delivered","drove","enhanced","engineered","executed","implemented",
    "improved","increased","led","migrated","optimized","reduced","refactored","scaled","shipped"
}

SECTION_HINTS = [
    "summary","about","experience","work experience","employment","projects",
    "skills","technical skills","education","certifications","awards","publications"
]

PERC_RE = re.compile(r"\b\d{1,3}(?:\.\d+)?\s?%")
# Numbers with contextual units (users, requests, ms, minutes, dollars, etc.)
NUM_UNIT_RE = re.compile(
    r"\b\d{2,}(?:\.\d+)?\s?(?:users?|reqs?|requests|rows|records|events|clients|datasets?|"
    r"ms|s|sec|seconds|mins?|minutes|hours?|days?|GB|TB|MB|k|K|m|M|million|bn|billion|₹|\$)\b"
)

def _lower_words(text: str) -> List[str]:
    text = text.lower()
    # strip punctuation to basic tokens
    words = re.findall(r"[a-zA-Z0-9\+\#\.\-]+", text)
    return words

def _unique_order(seq: List[str]) -> List[str]:
    seen, out = set(), []
    for s in seq:
        if s and s not in seen:
            seen.add(s); out.append(s)
    return out

def _normalize_skill(s: str) -> str:
    s = s.strip().lower()
    return {"py": "python", "js": "javascript", "ts": "typescript"}.get(s, s)

def _extract_columns_signals(text: str) -> Dict[str, Any]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    # Heuristic: many lines with 3+ consecutive spaces can indicate multi-column layout exported to text
    multicol_hits = sum(1 for ln in lines if re.search(r"\s{3,}\S+\s{3,}\S+", ln))
    ascii_table_hits = sum(1 for ln in lines if any(ch in ln for ch in ["|", "│", "─", "┼", "┌", "┐", "└", "┘"]))
    graphics_hits = sum(1 for ln in lines if re.search(r"(jpg|png|svg|qr)", ln, re.I))
    return {
        "multicol_hits": multicol_hits,
        "ascii_table_hits": ascii_table_hits,
        "graphics_hits": graphics_hits,
        "ratio_multicol": multicol_hits / max(1, len(lines)),
    }

def _presence_of_sections(text: str) -> float:
    t = text.lower()
    hits = sum(1 for s in SECTION_HINTS if s in t)
    return hits / len(SECTION_HINTS)

def _count_action_verb_bullets(text: str) -> Tuple[int, int]:
    bullets = [ln.strip(" -•\t") for ln in text.splitlines() if re.match(r"^\s*[-•\u2022]", ln) or ln.strip().startswith(("-", "•"))]
    if not bullets:
        # fallback: treat each line as a pseudo-bullet if short-ish
        bullets = [ln.strip() for ln in text.splitlines() if 0 < len(ln.strip()) <= 180]
    total = len(bullets)
    good = 0
    for b in bullets:
        # first word as verb?
        m = re.match(r"^([A-Za-z]+)", b)
        if m and m.group(1).lower() in ACTION_VERBS:
            good += 1
    return good, total

def _safe_json_loads(s: str, fallback: Any) -> Any:
    try:
        return json.loads(s)
    except Exception:
        return fallback

# ------------ Gemini-assisted parsing ------------

def _gemini_extract(job_description: str, resume_text: str) -> Dict[str, Any]:
    """
    Ask Gemini to extract normalized skills, role titles, and domain cues from JD and Resume.
    Returns a dict with keys:
      jd_skills, jd_titles, resume_skills, resume_titles, resume_summary
    """
    if not USE_GEMINI:
        raise RuntimeError("Gemini not configured")

    prompt = (
        "You are an ATS parsing assistant. Extract normalized tokens as JSON.\n"
        "Return strictly this schema:\n"
        "{\n"
        '  "jd_skills": [string],\n'
        '  "jd_titles": [string],\n'
        '  "resume_skills": [string],\n'
        '  "resume_titles": [string],\n'
        '  "resume_summary": string\n'
        "}\n\n"
        f"JOB_DESCRIPTION:\n{job_description}\n\n"
        f"RESUME_TEXT:\n{resume_text}\n\n"
        "Normalization rules: lowercase; split stacks (e.g., python, pandas, spark); expand acronyms if clear; "
        "dedupe; keep role titles simple (e.g., 'data engineer', 'ml engineer')."
    )

    resp = _GEMINI_MODEL.generate_content(prompt)
    text = resp.text or ""
    # Try to locate JSON in the response
    m = re.search(r"\{[\s\S]+\}", text)
    payload = _safe_json_loads(m.group(0) if m else text, {})
    # sanitize payload
    for k in ["jd_skills","jd_titles","resume_skills","resume_titles"]:
        payload[k] = [_normalize_skill(x) for x in payload.get(k, []) if isinstance(x, str)]
    payload["resume_summary"] = payload.get("resume_summary", "") or ""
    return payload

# ------------ Fallback parsing (no Gemini) ------------

TECH_HINTS = {
    # lightweight list; extend as needed
    "python","pandas","numpy","scikit-learn","sklearn","tensorflow","pytorch","sql","postgres","mysql",
    "spark","airflow","dbt","databricks","aws","gcp","azure","docker","kubernetes","terraform",
    "java","scala","javascript","typescript","react","node","flask","fastapi","django","rest","graphql",
    "hadoop","kafka","rabbitmq","snowflake","bigquery","redshift","lakehouse","mlflow","huggingface"
}
TITLE_HINTS = {
    "data engineer","ml engineer","machine learning engineer","data scientist","software engineer",
    "backend engineer","analytics engineer","mle","de","swe"
}

def _fallback_extract(job_description: str, resume_text: str) -> Dict[str, Any]:
    jd_words = set(_lower_words(job_description))
    res_words = set(_lower_words(resume_text))
    jd_skills = sorted(set(w for w in jd_words if w in TECH_HINTS))
    resume_skills = sorted(set(w for w in res_words if w in TECH_HINTS))
    jd_titles = sorted(t for t in TITLE_HINTS if t in job_description.lower())
    resume_titles = sorted(t for t in TITLE_HINTS if t in resume_text.lower())
    return {
        "jd_skills": jd_skills,
        "jd_titles": jd_titles,
        "resume_skills": resume_skills,
        "resume_titles": resume_titles,
        "resume_summary": ""
    }

# ------------ Scoring primitives ------------

def _score_keyword_alignment(jd_skills: List[str], resume_skills: List[str]) -> int:
    if not jd_skills:
        # No JD skills — award neutral mid since alignment can't be measured
        return math.ceil(W_KEYWORD * 0.6)
    overlap = len(set(jd_skills) & set(resume_skills))
    coverage = overlap / max(1, len(set(jd_skills)))
    # ≥70% coverage gets full points
    score = round(W_KEYWORD * min(1.0, coverage / 0.70))
    # guard against tiny overlaps
    return max(0, min(W_KEYWORD, score))

def _score_quantified_impact(resume_text: str) -> int:
    perc = len(PERC_RE.findall(resume_text))
    units = len(NUM_UNIT_RE.findall(resume_text))
    # Simple saturation curve: more signals ⇒ more points, with diminishing returns
    raw = perc * 1.5 + units * 1.0
    # thresholds tuned to common resumes
    if raw >= 12:
        return W_IMPACT
    elif raw >= 8:
        return W_IMPACT - 1
    elif raw >= 5:
        return W_IMPACT - 2
    elif raw >= 3:
        return max(1, W_IMPACT - 3)
    return 0

def _score_structure_ats(resume_text: str) -> int:
    sec_ratio = _presence_of_sections(resume_text)  # 0..1
    sig = _extract_columns_signals(resume_text)
    penalties = 0
    # penalize strong signs of tables/graphics/multicol
    if sig["ascii_table_hits"] > 3: penalties += 1
    if sig["multicol_hits"] > 6 or sig["ratio_multicol"] > 0.12: penalties += 1
    if sig["graphics_hits"] > 0: penalties += 1
    # base from section presence; full points if ≥0.6 of sections present
    base = round(W_ATS * min(1.0, sec_ratio / 0.6))
    return max(0, min(W_ATS, base - penalties))

def _score_clarity_action(resume_text: str) -> int:
    good, total = _count_action_verb_bullets(resume_text)
    if total == 0:
        return 0
    ratio = good / total
    if ratio >= 0.8:   return W_CLARITY
    if ratio >= 0.6:   return W_CLARITY - 1
    if ratio >= 0.4:   return W_CLARITY - 2
    if ratio >= 0.25:  return 1
    return 0

def _score_role_relevance(jd_titles: List[str], resume_titles: List[str]) -> int:
    if not jd_titles and not resume_titles:
        # No titles to compare — award conservative mid
        return 1
    overlap = len(set(jd_titles) & set(resume_titles))
    if overlap >= 1: return W_ROLE
    # partial match via token overlap
    jd_tokens = set(" ".join(jd_titles).split())
    rs_tokens = set(" ".join(resume_titles).split())
    token_overlap = len(jd_tokens & rs_tokens) / max(1, len(jd_tokens))
    if token_overlap >= 0.5: return W_ROLE - 1
    if token_overlap >= 0.25: return 1
    return 0

def _band_guard(score: int, resume_text: str) -> int:
    """
    Enforce rubric bands:
      - Empty resume_text: allow 0.
      - Otherwise clamp to [4,23] by band logic (generic minimum).
    """
    if not resume_text or not resume_text.strip():
        return 0
    return max(4, min(23, score))

# ------------ Public API ------------

@dataclass
class ATSResumeScore:
    total: int
    subscores: Dict[str, int]
    details: Dict[str, Any]  # parsed artifacts and heuristics for transparency

def score_resume_ats(job_description: str, resume_text: str, use_gemini: Optional[bool] = None) -> ATSResumeScore:
    """
    Returns ATSResumeScore with:
      - total (0–23, band-guarded)
      - subscores: keyword, impact, ats, clarity, role
      - details: parsed artifacts and signals
    """
    if use_gemini is None:
        use_gemini = USE_GEMINI

    if use_gemini:
        try:
            parsed = _gemini_extract(job_description, resume_text)
        except Exception:
            parsed = _fallback_extract(job_description, resume_text)
    else:
        parsed = _fallback_extract(job_description, resume_text)

    # Subscores
    s_keyword = _score_keyword_alignment(parsed["jd_skills"], parsed["resume_skills"])
    s_impact  = _score_quantified_impact(resume_text)
    s_ats     = _score_structure_ats(resume_text)
    s_clarity = _score_clarity_action(resume_text)
    s_role    = _score_role_relevance(parsed["jd_titles"], parsed["resume_titles"])

    raw_total = s_keyword + s_impact + s_ats + s_clarity + s_role
    total = _band_guard(raw_total, resume_text)

    details = {
        "parsed": parsed,
        "signals": {
            "percent_hits": len(PERC_RE.findall(resume_text)),
            "num_unit_hits": len(NUM_UNIT_RE.findall(resume_text)),
            "sections_ratio": _presence_of_sections(resume_text),
            "columns_signals": _extract_columns_signals(resume_text),
            "action_bullets": _count_action_verb_bullets(resume_text),
        },
        "raw_total_before_band_guard": raw_total,
        "weights": {
            "keyword": W_KEYWORD, "impact": W_IMPACT, "ats": W_ATS,
            "clarity": W_CLARITY, "role": W_ROLE
        }
    }

    subscores = {
        "keyword_alignment": s_keyword,
        "quantified_impact": s_impact,
        "structure_ats": s_ats,
        "clarity_action": s_clarity,
        "role_relevance": s_role
    }

    return ATSResumeScore(total=total, subscores=subscores, details=details)

# ------------ Example usage ------------
if __name__ == "__main__":
    JD = """We seek a Data Engineer with Python, SQL, Airflow, Spark, and AWS. Experience with dbt and Snowflake a plus."""
    RESUME = """
    SUMMARY: Data Engineer building ETL on AWS. 
    EXPERIENCE:
    - Optimized Spark ETL pipelines, reducing runtime by 45% processing 120M records on AWS EMR.
    - Built Airflow DAGs and dbt models; reduced data freshness lag from 24h to 2h (91% improvement).
    - Deployed Dockerized services; improved reliability (SLA 99.9%).
    PROJECTS:
    - Snowflake + dbt analytics stack with cost reduction of 35%.
    SKILLS: Python, SQL, Spark, Airflow, AWS, dbt, Snowflake, Docker
    EDUCATION: B.Tech
    """
    res = score_resume_ats(JD, RESUME, use_gemini=False)  # set True if GEMINI_API_KEY is configured
    print("TOTAL:", res.total)
    print("SUBSCORES:", res.subscores)
    print("DETAILS:", json.dumps(res.details, indent=2))
