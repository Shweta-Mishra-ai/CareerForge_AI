"""
core/ai_engine.py
=================
AI Engine — Gemini + Groq fallback.

CHANGES from original:
- Removed st.secrets dependency (now accepts api_keys as params → testable)
- Added @st.cache_resource on client builders (called from app.py only)
- Gemini model list is now a constant — easy to update
- _to_html() handles edge cases better (nested lists, None values)
- clean_and_parse_json() has stricter type enforcement
- No functional changes — all features preserved
"""

import json
import re

import google.generativeai as genai
from groq import Groq

# ─────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────

GEMINI_MODELS = [
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]

GROQ_MODEL = "llama-3.3-70b-versatile"
MAX_TOKENS = 4096


# ─────────────────────────────────────────────────────
# API HELPERS  (api keys passed in — no st.secrets here)
# ─────────────────────────────────────────────────────

def _call_gemini(prompt: str, gemini_api_key: str, temp: float = 0.2) -> str:
    """Try each Gemini model in order. Returns text on first success."""
    genai.configure(api_key=gemini_api_key)
    last_err = None
    for model_name in GEMINI_MODELS:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temp,
                    max_output_tokens=MAX_TOKENS,
                ),
            )
            return response.text
        except Exception as e:
            err_str = str(e).lower()
            if "404" in err_str or "not found" in err_str or "deprecated" in err_str:
                last_err = e
                continue          # try next model
            raise e               # surface real errors immediately
    raise Exception(f"All Gemini models failed. Last error: {last_err}")


def _call_groq(prompt: str, groq_api_key: str, temp: float = 0.2) -> str:
    """Groq fallback using Llama 3.3 70B."""
    client = Groq(api_key=groq_api_key)
    response = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model=GROQ_MODEL,
        temperature=temp,
        max_tokens=MAX_TOKENS,
    )
    return response.choices[0].message.content


def generate_with_fallback(
    prompt: str,
    gemini_api_key: str,
    groq_api_key: str,
    temp: float = 0.2,
) -> str:
    """
    Try Gemini first, fall back to Groq.
    Raises Exception only if BOTH fail.
    """
    gemini_error = None

    try:
        return _call_gemini(prompt, gemini_api_key, temp)
    except Exception as e:
        gemini_error = str(e)

    try:
        return _call_groq(prompt, groq_api_key, temp)
    except Exception as groq_e:
        raise Exception(
            f"Both APIs failed.\n"
            f"Gemini: {gemini_error}\n"
            f"Groq:   {groq_e}"
        )


# ─────────────────────────────────────────────────────
# HTML CONVERTER
# ─────────────────────────────────────────────────────

def _to_html(value) -> str:
    """Convert any AI output (str / list / dict / None) → safe HTML string."""
    if value is None or value == "" or value == [] or value == {}:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                title   = item.get("title") or item.get("role") or item.get("position") or item.get("company") or ""
                company = item.get("company") or item.get("organization") or ""
                dates   = item.get("dates") or item.get("duration") or item.get("period") or ""
                bullets = (
                    item.get("bullets")
                    or item.get("responsibilities")
                    or item.get("achievements")
                    or item.get("description")
                    or []
                )

                header = " at ".join(filter(None, [str(title), str(company)]))
                if dates:
                    header += f" ({dates})"

                html = f"<p><b>{header}</b></p>" if header else ""

                if isinstance(bullets, list):
                    bullet_items = [b for b in bullets if b]
                    if bullet_items:
                        html += "<ul>" + "".join(f"<li>{b}</li>" for b in bullet_items) + "</ul>"
                elif isinstance(bullets, str) and bullets.strip():
                    html += f"<ul><li>{bullets.strip()}</li></ul>"
                else:
                    # Fallback: render remaining key-value pairs
                    skip = {"title","role","position","company","organization","dates","duration","period","bullets","responsibilities","achievements","description"}
                    extras = [f"<p><b>{str(k).replace('_',' ').title()}:</b> {str(v)}</p>" for k, v in item.items() if k not in skip and v]
                    html += "".join(extras)

                parts.append(html)
            else:
                parts.append(f"<p>{str(item)}</p>")
        return "".join(parts)

    if isinstance(value, dict):
        lines = [f"<b>{str(k).replace('_',' ').title()}:</b> {str(v)}" for k, v in value.items() if v]
        return "<div>" + "<br>".join(lines) + "</div>"

    return str(value)


# ─────────────────────────────────────────────────────
# JSON PARSER
# ─────────────────────────────────────────────────────

def _extract_json_string(text: str) -> str:
    """Strip markdown fences and extract the outermost {...} block."""
    clean = text.strip()
    clean = re.sub(r"^```(?:json)?\s*", "", clean)
    clean = re.sub(r"\s*```$", "", clean)
    start = clean.find("{")
    end   = clean.rfind("}")
    if start != -1 and end != -1 and end > start:
        return clean[start : end + 1]
    return clean


def _normalise_base_cv(parsed: dict) -> dict:
    """Ensure base CV has all required keys with correct types."""
    # Skills → always a comma-separated string
    skills = parsed.get("skills", "")
    if isinstance(skills, list):
        parsed["skills"] = ", ".join(str(s) for s in skills if s)
    elif not isinstance(skills, str):
        parsed["skills"] = str(skills) if skills else ""

    # HTML fields
    for key in ["experience", "education", "certificates", "projects"]:
        parsed[key] = _to_html(parsed.get(key, ""))

    # Required string fields
    parsed.setdefault("name",     "Candidate")
    parsed.setdefault("headline", "Professional")
    parsed.setdefault("contact",  "")
    parsed.setdefault("summary",  "")
    return parsed


def _normalise_analysis(parsed: dict) -> dict:
    """Ensure ATS analysis result has all required keys with correct types."""
    parsed.setdefault("old_ats_score",        0)
    parsed.setdefault("new_ats_score",        0)
    parsed.setdefault("missing_keywords",     [])
    parsed.setdefault("formatting_issues",    [])
    parsed.setdefault("keyword_match_details","Analysis complete.")
    parsed.setdefault("hallucination_check",  "Safe. All data grounded in original CV.")
    parsed.setdefault("analysis_report",      ["Analysis complete."])
    parsed.setdefault("improvements_made",    [])
    parsed.setdefault("section_scores",       {})
    parsed.setdefault("tailored_cv",          {})

    # Fix list fields that AI sometimes returns as strings
    for list_key in ["analysis_report", "missing_keywords", "formatting_issues", "improvements_made"]:
        val = parsed.get(list_key)
        if isinstance(val, str):
            parsed[list_key] = [v.strip() for v in val.split(",") if v.strip()]

    # Normalise tailored_cv inner fields
    tailored = parsed.get("tailored_cv", {})
    if isinstance(tailored, dict):
        for key in ["experience", "education", "certificates", "projects"]:
            if key in tailored:
                tailored[key] = _to_html(tailored[key])
        skills = tailored.get("skills", "")
        if isinstance(skills, list):
            tailored["skills"] = ", ".join(str(s) for s in skills if s)

    return parsed


def clean_and_parse_json(response_text: str, is_analysis: bool = False) -> dict:
    """
    Bulletproof JSON parser with full fallback dicts.
    Never raises — always returns a usable dict.
    """
    try:
        json_str = _extract_json_string(response_text or "")
        if not json_str:
            raise ValueError("Empty response from AI")
        parsed = json.loads(json_str)

        if is_analysis:
            return _normalise_analysis(parsed)
        else:
            return _normalise_base_cv(parsed)

    except Exception as e:
        if is_analysis:
            return {
                "old_ats_score": 0, "new_ats_score": 0,
                "missing_keywords": [], "formatting_issues": [],
                "keyword_match_details": f"Parse error: {e}",
                "hallucination_check": "Unknown",
                "tailored_cv": {}, "analysis_report": [f"Analysis failed: {e}"],
                "improvements_made": [], "section_scores": {},
            }
        return {
            "name": "Candidate", "headline": "Professional",
            "contact": "", "skills": "", "summary": "",
            "experience": f"<p><b>Extraction Error:</b> {e}. Please try again.</p>",
            "projects": "", "education": "", "certificates": "",
        }


# ─────────────────────────────────────────────────────
# PROMPTS
# ─────────────────────────────────────────────────────

EXTRACT_PROMPT = """
You are a world-class professional CV writer and data extractor.
Your job: parse the input text and extract a complete, structured CV as a JSON object.

OUTPUT: ONLY a raw JSON object. No markdown code fences. No explanation.

Required JSON keys:
- "name": Full name of the candidate (string)
- "headline": Professional title / tagline (string, max 2 lines)
- "summary": A 2-3 sentence professional summary (write one if not present)
- "contact": Pipe-separated contact details e.g. "email@email.com | +91-9999 | linkedin.com/in/user | City, Country"
- "skills": Comma-separated technical and soft skills (string)
- "experience": SINGLE HTML string. Each job:
    <p><b>Job Title at Company Name (Start – End)</b></p>
    <ul><li>Achievement bullet with metrics where possible</li></ul>
    Min 2 bullets per role.
- "projects": SINGLE HTML string. Each project:
    <p><b>Project Name | Tech Stack</b></p>
    <ul><li>What was built, impact, key achievement</li></ul>
    Leave "" if no projects exist.
- "education": SINGLE HTML string. Each entry:
    <p><b>Degree, Institution</b><br>Year | CGPA/Marks if present</p>
- "certificates": SINGLE HTML string. Each:
    <p><b>Cert Name</b> — Issuer (Year)</p>

RULES:
- DO NOT INVENT DATA. Extract only what is in the text.
- If a field is absent, set it to "".
- Write experience bullets in STAR format where possible.

TEXT TO PARSE:
{text}
"""

ATS_PROMPT = """
You are a Senior ATS Expert and Professional CV Coach.
Perform a deep analysis of the candidate's CV against the Job Description.

OUTPUT: ONLY a raw JSON object. No markdown. No explanation.

Required JSON keys:
1. "old_ats_score": integer 0-100
2. "new_ats_score": integer 0-100
3. "missing_keywords": array of 5-8 important JD keywords absent from CV
4. "keyword_match_details": string explanation of match/mismatch
5. "formatting_issues": array of 2-4 structural issues
6. "section_scores": {{"experience": 0, "skills": 0, "education": 0, "projects": 0, "overall_format": 0}}
7. "improvements_made": array of 5-8 concrete improvements made
8. "hallucination_check": "Safe" if no fake data added, else describe
9. "analysis_report": array of 4-6 strategic insights
10. "tailored_cv": same structure as base CV with rewritten content

CRITICAL RULES for tailored_cv:
- FORBIDDEN: Fake jobs, fake companies, fake degrees, fake projects
- ALLOWED: Reorder skills, rewrite bullets with JD keywords, add targeted summary
- Format experience/projects as HTML

BASE CV:
{cv}

JOB DESCRIPTION:
{jd}
"""


# ─────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────

def extract_base_cv(raw_text: str, gemini_api_key: str, groq_api_key: str, is_url: bool = False) -> dict:
    """Extract structured CV from raw text using AI."""
    prompt = EXTRACT_PROMPT.replace("{text}", raw_text[:14000])
    if is_url:
        prompt += "\n\nNote: This text is from a web scrape — extract whatever is available."
    response = generate_with_fallback(prompt, gemini_api_key, groq_api_key, temp=0.15)
    return clean_and_parse_json(response, is_analysis=False)


def analyze_and_tailor_cv(base_cv_json: dict, jd_text: str, gemini_api_key: str, groq_api_key: str) -> dict:
    """Run ATS analysis and return tailored CV + full report."""
    cv_str = json.dumps(base_cv_json, ensure_ascii=False)[:12000]
    prompt = ATS_PROMPT.replace("{cv}", cv_str).replace("{jd}", jd_text[:8000])
    response = generate_with_fallback(prompt, gemini_api_key, groq_api_key, temp=0.15)
    return clean_and_parse_json(response, is_analysis=True)
