import streamlit as st
import streamlit.components.v1 as components
import base64
import json
from core.scraper import extract_pdf_text, scrape_url_text
from core.ai_engine import extract_base_cv, analyze_and_tailor_cv
from templates.cv_styles import render_cv

st.set_page_config(page_title="CareerForge AI - Pro ATS CV", page_icon="🎯", layout="wide")

st.title("🎯 CareerForge AI")
st.markdown("Transform any profile or CV into an ATS-optimized professional resume. No hallucinations, 100% verified data.")

# --- SIDEBAR ---
st.sidebar.title("🎨 Formatting Options")
template_options = [
    "Executive Blue (Premium)", 
    "Modern Accent (Clean)", 
    "Classic Corporate",
    "Modern Sidebar (Original)",
    "Minimalist Tech (Original)"
]
selected_template = st.sidebar.selectbox("Choose CV Template:", template_options)

# --- TABS ---
tab1, tab2, tab3 = st.tabs(["📄 Step 1: Profile Parsing", "🎯 Step 2: ATS Tailoring", "🚀 Step 3: Career Tools"])

if "base_cv_data" not in st.session_state:
    st.session_state.base_cv_data = None
if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = None

# ==========================================
# TAB 1: DATA FETCH & BASE PREVIEW
# ==========================================
with tab1:
    st.subheader("Extract Your Professional Data")
    input_method = st.radio("Select Input Method:", (
        "📄 Upload Any CV (PDF)", 
        "🔗 Enter Profile/CV URL",
        "📝 Paste Profile Text / Extension Data"
    ))
    
    if input_method == "📄 Upload Any CV (PDF)":
        uploaded_file = st.file_uploader("Upload Profile PDF", type=['pdf'])
        if st.button("Extract Data", type="primary") and uploaded_file:
            with st.spinner("Extracting real data from PDF..."):
                try:
                    raw_text = extract_pdf_text(uploaded_file)
                    st.session_state.base_cv_data = extract_base_cv(raw_text)
                    st.session_state.analysis_result = None
                    st.success("✅ Profile Data Extracted Successfully!")
                except Exception as e:
                    st.error(f"❌ Extraction failed: {str(e)}")
                    
    elif input_method == "🔗 Enter Profile/CV URL":
        linkedin_url = st.text_input("Enter URL (LinkedIn, Portfolio, or Online CV):")
        if st.button("Extract Data", type="primary") and linkedin_url:
            with st.spinner("Fetching and analyzing data..."):
                try:
                    raw_text = scrape_url_text(linkedin_url)
                    st.session_state.base_cv_data = extract_base_cv(raw_text, is_url=True)
                    st.session_state.analysis_result = None
                    st.success("✅ Profile Data Extracted Successfully!")
                except Exception as e:
                    st.error(f"❌ Extraction failed: {str(e)}")
                    
    elif input_method == "📝 Paste Profile Text / Extension Data":
        pasted_text = st.text_area("Paste text content or the JSON copied from our Chrome Extension:", height=200)
        if st.button("Extract Data", type="primary") and pasted_text:
            with st.spinner("Processing raw text..."):
                try:
                    st.session_state.base_cv_data = extract_base_cv(pasted_text)
                    st.session_state.analysis_result = None
                    st.success("✅ Profile Data Extracted Successfully!")
                except Exception as e:
                    st.error(f"❌ Extraction failed: {str(e)}")

    # BASE PREVIEW & DOWNLOAD
    if st.session_state.base_cv_data:
        st.markdown("---")
        st.markdown("### 👀 Base CV Preview (Real Data)")
        base_html = render_cv(selected_template, st.session_state.base_cv_data)
        components.html(base_html, height=600, scrolling=True)
        
        b64_base = base64.b64encode(base_html.encode()).decode()
        href_base = f'<a href="data:text/html;base64,{b64_base}" download="Base_Real_CV.html" style="display:inline-block; padding:12px 24px; background-color:#1e3a8a; color:white; text-decoration:none; border-radius:5px; font-weight:bold; text-align:center; width:100%;">📥 Download Base CV</a>'
        st.markdown(href_base, unsafe_allow_html=True)

# ==========================================
# TAB 2: ATS ANALYSIS & OPTIMIZED PREVIEW
# ==========================================
with tab2:
    st.subheader("ATS Analysis & Tailoring")
    if not st.session_state.base_cv_data:
        st.warning("⚠️ Please extract your professional data in Step 1 first.")
    else:
        jd_input = st.text_area("Paste the Target Job Description here:", height=150)
        
        if st.button("Run Strict ATS Analysis", type="primary") and jd_input:
            with st.spinner("AI is analyzing and tailoring your CV (Anti-Hallucination active)..."):
                try:
                    st.session_state.analysis_result = analyze_and_tailor_cv(st.session_state.base_cv_data, jd_input)
                except Exception as e:
                    st.error(f"❌ ATS Analysis failed: {str(e)}")

        if st.session_state.analysis_result:
            analysis = st.session_state.analysis_result
            
            # SCORE METRICS
            st.markdown("### 📈 ATS Score Optimization")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Original Score", f"{analysis.get('old_ats_score', 0)}%")
            with col2:
                delta = analysis.get('new_ats_score', 0) - analysis.get('old_ats_score', 0)
                st.metric("Tailored Score", f"{analysis.get('new_ats_score', 0)}%", f"+{delta}%")
            with col3:
                st.write("**🚨 Missing Keywords (JD vs Base CV):**")
                st.write(", ".join(analysis.get('missing_keywords', [])))
            
            # DETAILED REPORT (NEW ANTI-HALLUCINATION FEATURES)
            st.markdown("### 🛡️ Quality & Integrity Report")
            
            st.info(f"**Keyword Match Details:** {analysis.get('keyword_match_details', 'N/A')}")
            
            hallucination_msg = analysis.get('hallucination_check', 'Status unknown.')
            if "Safe" in hallucination_msg:
                st.success(f"**Hallucination Check:** {hallucination_msg}")
            else:
                st.warning(f"**Hallucination Check:** {hallucination_msg}")
                
            with st.expander("Show Formatting Issues"):
                for issue in analysis.get('formatting_issues', []):
                    st.write(f"- {issue}")

            with st.expander("Show Tailoring Report"):
                for pt in analysis.get('analysis_report', []):
                    st.write(f"- {pt}")
            
            st.markdown("---")
            
            # OPTIMIZED PREVIEW & DOWNLOAD
            st.markdown("### 👀 Tailored CV Preview")
            tailored_html = render_cv(selected_template, analysis.get('tailored_cv', {}))
            components.html(tailored_html, height=600, scrolling=True)
            
            b64_tailored = base64.b64encode(tailored_html.encode()).decode()
            href_tailored = f'<a href="data:text/html;base64,{b64_tailored}" download="Tailored_ATS_CV.html" style="display:inline-block; padding:12px 24px; background-color:#14b8a6; color:white; text-decoration:none; border-radius:5px; font-weight:bold; text-align:center; width:100%;">📥 Download Tailored CV</a>'
            st.markdown(href_tailored, unsafe_allow_html=True)


# ==========================================
# TAB 3: CAREER TOOLS (COVER LETTER & PREP)
# ==========================================
from core.ai_engine import generate_with_fallback # type: ignore

with tab3:
    st.subheader("🚀 Advanced Career Tools")
    if not st.session_state.analysis_result:
        st.warning("⚠️ Please complete the ATS Tailoring in Step 2 to unlock Career Tools.")
    else:
        st.markdown("We use your tailored CV and the Job Description to generate highly specific resources.")
        
        col_cl, col_prep = st.columns(2)
        
        with col_cl:
            st.markdown("### ✉️ Cover Letter Generator")
            if st.button("Generate Cover Letter", use_container_width=True):
                with st.spinner("Writing highly personalized cover letter..."):
                    try:
                        tailored_data = json.dumps(st.session_state.analysis_result.get('tailored_cv', {}))
                        jd_data = jd_input # from Tab 2
                        
                        cl_prompt = f"""
                        You are an expert career coach. Write a compelling, highly personalized cover letter.
                        Base it ONLY on the candidate's Tailored CV and the target Job Description.
                        Do not hallucinate facts. Make it confident but professional. 
                        Output ONLY the text of the cover letter, ready to copy-paste.
                        
                        CV: {tailored_data[:3000]}
                        JD: {jd_data[:3000]}
                        """
                        cl_text = generate_with_fallback(cl_prompt, temp=0.4)
                        st.session_state.cover_letter = cl_text
                    except Exception as e:
                        st.error(f"Failed to generate: {str(e)}")
            
            if "cover_letter" in st.session_state:
                st.text_area("Your Cover Letter:", st.session_state.cover_letter, height=400)
                
        with col_prep:
            st.markdown("### 🎤 Interview Prep Guide")
            if st.button("Generate Interview Prep", use_container_width=True):
                with st.spinner("Analyzing gaps for interview questions..."):
                    try:
                        tailored_data = json.dumps(st.session_state.analysis_result.get('tailored_cv', {}))
                        missing_skills = ", ".join(st.session_state.analysis_result.get('missing_keywords', []))
                        
                        ip_prompt = f"""
                        You are an expert technical interviewer. Based on the candidate's CV and the Job Description, 
                        generate 5 specific interview questions they are likely to be asked.
                        
                        Pay special attention to these missing skills which the candidate lacked: {missing_skills}.
                        The recruiter will likely grill them on these gaps.
                        
                        Format as Markdown:
                        **Q1:** [Question]
                        *Hint/Strategy:* [How the candidate should answer based on their CV]
                        
                        CV: {tailored_data[:2000]}
                        JD: {jd_data[:2000]}
                        """
                        ip_text = generate_with_fallback(ip_prompt, temp=0.4)
                        st.session_state.interview_prep = ip_text
                    except Exception as e:
                        st.error(f"Failed to generate: {str(e)}")
                        
            if "interview_prep" in st.session_state:
                st.markdown(st.session_state.interview_prep)
