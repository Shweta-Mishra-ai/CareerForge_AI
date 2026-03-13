import google.generativeai as genai
from groq import Groq
import json
import streamlit as st

def call_groq(prompt, temp=0.2):
    client = Groq(api_key=st.secrets["GROQ_API_KEY"])
    response = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="llama-3.3-70b-versatile",
        temperature=temp,
    )
    return response.choices[0].message.content

def generate_with_fallback(prompt, temp=0.2):
    gemini_error = None
    groq_error = None

    # Try multiple Gemini model names for compatibility
    gemini_models = ["gemini-2.0-flash-lite", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-pro", "gemini-1.0-pro"]
    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        for model_name in gemini_models:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(temperature=temp)
                )
                return response.text
            except Exception as model_err:
                if "404" in str(model_err) or "not found" in str(model_err).lower():
                    continue  # Try next model
                raise model_err  # Re-raise non-404 errors
        gemini_error = "No supported Gemini model found for this API key"
    except Exception as e:
        gemini_error = str(e)

    try:
        return call_groq(prompt, temp)
    except Exception as groq_e:
        groq_error = str(groq_e)

    raise Exception(f"API Error: Gemini failed [{gemini_error}], Groq failed [{groq_error}]")

def _convert_to_html(value):
    """Converts any value type into a safe HTML string for rendering."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                # AI returned a list of dicts for experience - convert to HTML blocks
                lines = []
                for k, v in item.items():
                    lines.append(f"<b>{str(k).replace('_', ' ').title()}:</b> {str(v)}")
                parts.append("<div style='margin-bottom:15px;'>" + "<br>".join(lines) + "</div>")
            else:
                parts.append(f"<p>{str(item)}</p>")
        return "".join(parts)
    if isinstance(value, dict):
        # AI returned a single dict instead of a string
        lines = []
        for k, v in value.items():
            lines.append(f"<b>{str(k).replace('_', ' ').title()}:</b> {str(v)}")
        return "<div>" + "<br>".join(lines) + "</div>"
    return str(value)

def clean_and_parse_json(response_text, is_analysis=False):
    """Bulletproof JSON parser."""
    try:
        # Strip markdown code blocks if present
        clean = response_text.strip()
        if clean.startswith("```"):
            clean = clean[clean.find("{"):]  # strip ```json header
        if clean.endswith("```"):
            clean = clean[:clean.rfind("}") + 1]  # strip ``` footer

        start_idx = clean.find('{')
        end_idx = clean.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            parsed_data = json.loads(clean[start_idx:end_idx+1])
        else:
            parsed_data = json.loads(clean)

        if is_analysis:
            report = parsed_data.get("analysis_report", ["Analysis complete."])
            if isinstance(report, str):
                parsed_data["analysis_report"] = [report]
            elif not isinstance(report, list):
                parsed_data["analysis_report"] = ["Analysis generated."]
            
            # Ensure new keys exist
            if "formatting_issues" not in parsed_data:
                parsed_data["formatting_issues"] = ["None detected."]
            if "hallucination_check" not in parsed_data:
                parsed_data["hallucination_check"] = "Safe. All data grounded in original CV."
            if "keyword_match_details" not in parsed_data:
                parsed_data["keyword_match_details"] = "Keywords analyzed."
                
            # Also normalize tailored_cv if present
            tailored = parsed_data.get("tailored_cv", {})
            if isinstance(tailored, dict):
                for key in ["experience", "education", "certificates"]:
                    if key in tailored:
                        tailored[key] = _convert_to_html(tailored.get(key, ""))
                if isinstance(tailored.get("skills"), list):
                    tailored["skills"] = ", ".join(str(x) for x in tailored["skills"])
            return parsed_data
        else:
            # Normalize skills to comma-separated string
            if isinstance(parsed_data.get("skills"), list):
                parsed_data["skills"] = ", ".join(str(x) for x in parsed_data["skills"])
            elif not parsed_data.get("skills"):
                parsed_data["skills"] = ""

            # Normalize experience/education/certificates to HTML strings
            for key in ["experience", "education", "certificates"]:
                parsed_data[key] = _convert_to_html(parsed_data.get(key, ""))

            return parsed_data

    except Exception as e:
        if is_analysis:
            return {
                "old_ats_score": 0, 
                "missing_keywords": [], 
                "formatting_issues": [],
                "keyword_match_details": "Failed",
                "hallucination_check": "Failed",
                "tailored_cv": {}, 
                "new_ats_score": 0, 
                "analysis_report": [f"Analysis failed: {str(e)}"]
            }
        return {"name": "Candidate", "headline": "Professional", "contact": "", "skills": "", "experience": f"<p>Data extraction error: {str(e)}</p>", "education": "", "certificates": ""}

def extract_base_cv(raw_text, is_url=False):
    if is_url:
        # For URLs: LinkedIn blocks most data, so we use AI to generate professional content
        prompt = f"""
You are an Expert Resume Architect. Output ONLY a raw JSON object. No markdown, no explanation.
Required keys: "name", "headline", "contact", "skills", "experience", "education", "certificates"

The text is a limited scrape from a LinkedIn URL or Portfolio.
Your job: BUILD a complete professional CV based heavily on whatever is in the text.

INSTRUCTIONS:
1. Extract the name and headline.
2. "skills": Generate relevant skills as a comma-separated string based on the text.
3. "experience": Generate detailed, realistic job experiences as a SINGLE HTML string using <ul><li> tags. DO NOT invent false past companies if they are not listed. Keep it general if needed.
4. "education": Generate education as a SINGLE HTML string.
5. "certificates": Generate certificates as a SINGLE HTML string.
6. "contact": Format as "<p>Contact details extracted or placeholders</p>".

Text: {raw_text[:4000]}
"""
    else:
        # For PDFs & Paste: extract all the real data closely
        prompt = f"""
You are an expert resume parser. Output ONLY a raw JSON object. No markdown, no explanation.
Required keys: "name", "headline", "contact", "skills", "experience", "education", "certificates"

INSTRUCTIONS:
1. Extract all available data from the text. 
2. STRICT RULE: DO NOT INVENT ANYTHING. If a section genuinely does not exist in the text, set it to "".
3. "skills": Extract all skills as a comma-separated string.
4. "experience": Format ALL work experience as a SINGLE HTML string using <p><b>Title at Company (Dates)</b></p><ul><li>Achievement</li></ul> structure.
5. "education": Format ALL education as a SINGLE HTML string using <p> tags.
6. "certificates": Format ALL certifications as a SINGLE HTML string using <p> tags.
7. "contact": Extract email, LinkedIn, phone, location as a single string.

Text: {raw_text[:4000]}
"""
    response_text = generate_with_fallback(prompt, temp=0.1)
    return clean_and_parse_json(response_text, is_analysis=False)

def analyze_and_tailor_cv(base_cv_json, jd_text):
    # Trim the CV JSON to avoid token limits on free API tiers
    trimmed_cv = json.dumps(base_cv_json)[:4000]
    prompt = f"""
Act as an Expert ATS System. Output ONLY a raw JSON object. No markdown, no explanation.
Required output keys: "old_ats_score", "new_ats_score", "missing_keywords", "formatting_issues", "keyword_match_details", "hallucination_check", "tailored_cv", "analysis_report"

1. "old_ats_score": integer 0-100, how well the base CV matches the JD.
2. "new_ats_score": integer 0-100, improved score after NLP tailoring.
3. "missing_keywords": JSON array of 3-5 key terms from JD completely missing in CV.
4. "formatting_issues": JSON array of 1-3 issues identified in base CV structure (e.g., "Missing explicit Skills section", "Dates format unreadable").
5. "keyword_match_details": A short string explaining exactly why the score is what it is based on JD keywords.
6. "hallucination_check": A string declaring "Safe" if you successfully avoided adding fake experience/tenure, or explaining compromises made.
7. "tailored_cv": JSON object with keys: name, headline, contact, skills, experience, education, certificates.
   - STRICT RULE (ANTI-HALLUCINATION): You are FORBIDDEN from adding fake years of experience, fake job titles, or fake degrees.
   - You may ONLY rewrite existing bullet points in the "experience" section to better highlight JD keywords that the user demonstrably has.
   - Format experience as a single HTML string with <p><b>Title</b></p><ul><li> tags.
8. "analysis_report": JSON array of 3-5 strings explaining the strategic changes made to the CV targeting the JD.

BASE CV: {trimmed_cv}
JD: {jd_text[:3000]}
"""
    response_text = generate_with_fallback(prompt, temp=0.1)
    return clean_and_parse_json(response_text, is_analysis=True)
