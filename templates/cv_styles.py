def render_cv(template_name, data):
    name = str(data.get("name", "Name Not Found"))
    headline = str(data.get("headline", ""))
    contact = str(data.get("contact", ""))
    
    # Defensive type conversions: AI sometimes returns lists instead of strings
    skills_raw = data.get("skills", "")
    skills = [s.strip() for s in skills_raw.split(',')] if isinstance(skills_raw, str) else [str(s).strip() for s in skills_raw]
    
    exp_raw = data.get("experience", "<p>No experience data found.</p>")
    experience = "".join([f"<p>{str(e)}</p>" for e in exp_raw]) if isinstance(exp_raw, list) else str(exp_raw)
    
    # Clean up AI experience tags to match our structured CSS
    experience = experience.replace("<p><b>", "<div class='job-title'>").replace("</b></p>", "</div>")
    
    edu_raw = data.get("education", "")
    education = "".join([f"<p>{str(e)}</p>" for e in edu_raw]) if isinstance(edu_raw, list) else str(edu_raw)
    
    cert_raw = data.get("certificates", "")
    certificates = "".join([f"<p>{str(e)}</p>" for e in cert_raw]) if isinstance(cert_raw, list) else str(cert_raw)

    has_edu = len(education) > 5 and "hidden" not in education.lower()
    has_cert = len(certificates) > 5 and "hidden" not in certificates.lower()

    # ==========================================
    # 1. Premium Two-Column (Mariana Anderson Ref)
    # ==========================================
    if template_name == "Premium Two-Column (Navy & White)":
        skills_html = "".join([f'<li class="skill-item">{s}</li>' for s in skills if s])
        
        return f"""
        <html>
        <head>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
            body {{ font-family: 'Inter', sans-serif; margin: 0; padding: 0; background: #e5e7eb; color: #333; }}
            .cv-container {{ max-width: 900px; margin: 20px auto; background: white; display: flex; box-shadow: 0 10px 30px rgba(0,0,0,0.1); min-height: 1100px; }}
            .left-col {{ width: 33%; background: #2f3640; color: white; padding: 40px 30px; box-sizing: border-box; }}
            .right-col {{ width: 67%; padding: 40px 45px; box-sizing: border-box; }}
            
            /* Left Sidebar */
            .profile-img {{ width: 150px; height: 150px; background: #e0e0e0; border-radius: 50%; margin: 0 auto 30px auto; border: 4px solid #4a5463; }}
            .sidebar-header {{ font-size: 16px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; margin-top: 40px; margin-bottom: 15px; border-bottom: 1px solid #4a5463; padding-bottom: 5px; }}
            .sidebar-text {{ font-size: 13px; color: #cbd5e1; line-height: 1.6; margin-bottom: 15px; }}
            .skill-list {{ list-style-type: none; padding: 0; margin: 0; }}
            .skill-item {{ font-size: 13px; color: #cbd5e1; margin-bottom: 8px; position: relative; padding-left: 15px; }}
            .skill-item::before {{ content: '•'; position: absolute; left: 0; color: #cbd5e1; }}
            
            /* Right Main Content */
            .name {{ font-size: 38px; font-weight: 700; color: #1e293b; letter-spacing: 1px; margin: 0 0 5px 0; }}
            .headline {{ font-size: 18px; font-weight: 500; color: #64748b; text-transform: uppercase; letter-spacing: 2px; margin: 0 0 30px 0; }}
            
            .section-header {{ font-size: 20px; font-weight: 700; color: #1e293b; margin-top: 35px; margin-bottom: 20px; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; }}
            
            /* Experience Timeline styling */
            .experience-wrapper {{ border-left: 2px solid #cbd5e1; padding-left: 20px; margin-left: 8px; }}
            .job-title {{ font-size: 16px; font-weight: 700; color: #0f172a; position: relative; margin-top: 25px; margin-bottom: 10px; }}
            .job-title::before {{ content: ''; position: absolute; left: -27px; top: 4px; width: 10px; height: 10px; background: white; border: 2px solid #64748b; border-radius: 50%; }}
            .exp-text ul {{ padding-left: 20px; margin-top: 5px; }}
            .exp-text li {{ font-size: 13px; color: #475569; line-height: 1.6; margin-bottom: 6px; }}
            
            .standard-text {{ font-size: 13px; color: #475569; line-height: 1.6; }}
        </style>
        </head>
        <body>
            <div class="cv-container">
                <div class="left-col">
                    <div class="sidebar-header">Contact</div>
                    <div class="sidebar-text">{contact.replace(' | ', '<br>')}</div>
                    
                    <div class="sidebar-header">Expertise</div>
                    <ul class="skill-list">{skills_html}</ul>
                    
                    {f'<div class="sidebar-header">Education</div><div class="sidebar-text">{education}</div>' if has_edu else ''}
                    {f'<div class="sidebar-header">Certifications</div><div class="sidebar-text">{certificates}</div>' if has_cert else ''}
                </div>
                
                <div class="right-col">
                    <h1 class="name">{name}</h1>
                    <h2 class="headline">{headline}</h2>
                    
                    <div class="section-header">Experience</div>
                    <div class="experience-wrapper exp-text">
                        {experience}
                    </div>
                </div>
            </div>
        </body>
        </html>
        """

    # ==========================================
    # 2. Executive Corporate (Ethan Smith Ref)
    # ==========================================
    elif template_name == "Executive Corporate (Clean & Bold)":
        skills_html = ", ".join(skills)
        
        return f"""
        <html>
        <head>
        <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700&display=swap" rel="stylesheet">
        <style>
            body {{ font-family: 'Montserrat', sans-serif; margin: 0; padding: 0; background: #f4f4f5; }}
            .cv {{ max-width: 900px; margin: 30px auto; background: white; padding: 50px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }}
            
            /* Header */
            .header {{ border-bottom: 2px solid #111; padding-bottom: 20px; margin-bottom: 30px; }}
            .name {{ font-size: 40px; font-weight: 700; text-transform: uppercase; letter-spacing: 2px; margin: 0; color: #111; }}
            .headline {{ font-size: 16px; font-weight: 600; color: #3b82f6; margin: 5px 0 15px 0; }}
            .contact {{ font-size: 12px; color: #555; display: flex; gap: 15px; flex-wrap: wrap; }}
            
            /* Grid Layout */
            .grid {{ display: grid; grid-template-columns: 2fr 1fr; gap: 40px; }}
            
            /* Sections */
            .section-title {{ font-size: 14px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: #111; border-bottom: 2px solid #111; padding-bottom: 5px; margin-bottom: 15px; margin-top: 0; }}
            
            /* Main Content (Experience) */
            .job-title {{ font-size: 15px; font-weight: 700; color: #111; margin-top: 25px; margin-bottom: 5px; }}
            .exp-text ul {{ padding-left: 20px; margin-top: 5px; }}
            .exp-text li {{ font-size: 13px; color: #444; line-height: 1.6; margin-bottom: 5px; }}
            
            /* Right Column Sidebar */
            .side-block {{ margin-bottom: 35px; }}
            .side-text {{ font-size: 13px; color: #444; line-height: 1.6; }}
        </style>
        </head>
        <body>
            <div class="cv">
                <div class="header">
                    <h1 class="name">{name}</h1>
                    <div class="headline">{headline}</div>
                    <div class="contact">{contact.replace(' | ', ' &bull; ')}</div>
                </div>
                
                <div class="grid">
                    <div class="main-column">
                        <h2 class="section-title">Professional Experience</h2>
                        <div class="exp-text">
                            {experience}
                        </div>
                    </div>
                    
                    <div class="side-column">
                        <div class="side-block">
                            <h2 class="section-title">Core Competencies</h2>
                            <div class="side-text">{skills_html}</div>
                        </div>
                        
                        {f'<div class="side-block"><h2 class="section-title">Education</h2><div class="side-text">{education}</div></div>' if has_edu else ''}
                        
                        {f'<div class="side-block"><h2 class="section-title">Certifications</h2><div class="side-text">{certificates}</div></div>' if has_cert else ''}
                    </div>
                </div>
            </div>
        </body>
        </html>
        """

    # ==========================================
    # 3. Creative Professional (Steven Terry Ref)
    # ==========================================
    elif template_name == "Creative Professional (Ribbons & Colors)":
        skills_html = "".join([f'<span class="skill-pill">{s}</span>' for s in skills if s])
        
        return f"""
        <html>
        <head>
        <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700;900&display=swap" rel="stylesheet">
        <style>
            body {{ font-family: 'Roboto', sans-serif; margin: 0; padding: 0; background: #e0e7ff; color: #333; }}
            .cv {{ max-width: 850px; margin: 30px auto; background: white; display: grid; grid-template-columns: 2fr 3fr; min-height: 1050px; box-shadow: 0 10px 25px rgba(0,0,0,0.15); }}
            
            /* Left Column */
            .left-col {{ border-right: 1px solid #e5e7eb; padding: 40px 0; display: flex; flex-direction: column; align-items: center; text-align: center; }}
            .name {{ font-size: 28px; font-weight: 900; letter-spacing: 2px; text-transform: uppercase; color: #111; margin: 0; padding: 0 20px; }}
            .headline {{ font-size: 15px; color: #ef4444; font-weight: 500; font-style: italic; margin-top: 5px; margin-bottom: 30px; }}
            
            /* Ribbon Sections */
            .ribbon {{ background: #fca5a5; color: white; text-transform: uppercase; font-weight: 700; font-size: 14px; letter-spacing: 1px; padding: 8px 15px; width: 100%; box-sizing: border-box; text-align: left; position: relative; margin-top: 30px; margin-bottom: 15px; display:flex; align-items: center; gap: 10px; }}
            .ribbon::after {{ content: ''; position: absolute; right: -15px; top: 0; width: 0; height: 0; border-top: 17px solid transparent; border-bottom: 17px solid transparent; border-left: 15px solid #fca5a5; }}
            
            .left-text {{ font-size: 13px; color: #4b5563; line-height: 1.6; padding: 0 20px; text-align: left; width: 100%; box-sizing: border-box; }}
            .skill-wrapper {{ display: flex; flex-wrap: wrap; gap: 8px; padding: 0 20px; width: 100%; box-sizing: border-box; justify-content: flex-start; }}
            .skill-pill {{ font-size: 11px; background: #e5e7eb; padding: 4px 10px; border-radius: 20px; color: #374151; font-weight: 500; }}
            
            /* Right Column (Offset Ribbons) */
            .right-col {{ padding: 40px 0; }}
            .ribbon-right {{ background: #fca5a5; color: white; text-transform: uppercase; font-weight: 700; font-size: 14px; letter-spacing: 1px; padding: 8px 15px; width: 93%; box-sizing: border-box; text-align: left; margin-bottom: 20px; clip-path: polygon(0 0, 100% 0, 95% 50%, 100% 100%, 0 100%); margin-left: 15px; }}
            
            .right-content {{ padding: 0 30px 30px 30px; }}
            .job-title {{ font-size: 15px; font-weight: 700; color: #111; margin-top: 0; margin-bottom: 10px; }}
            .exp-wrapper ul {{ padding-left: 15px; margin-top: 5px; }}
            .exp-wrapper li {{ font-size: 13px; color: #4b5563; line-height: 1.6; margin-bottom: 8px; }}
            
        </style>
        </head>
        <body>
            <div class="cv">
                <div class="left-col">
                    <h1 class="name">{name}</h1>
                    <div class="headline">{headline}</div>
                    
                    <div class="ribbon">✒️ CONTACTS</div>
                    <div class="left-text">{contact.replace(' | ', '<br><br>')}</div>
                    
                    <div class="ribbon">🛠️ SKILLS</div>
                    <div class="skill-wrapper">{skills_html}</div>
                </div>
                
                <div class="right-col">
                    <div class="ribbon-right">💼 WORK EXPERIENCE</div>
                    <div class="right-content exp-wrapper">
                        {experience}
                    </div>
                    
                    {f'<div class="ribbon-right">🎓 EDUCATION</div><div class="right-content left-text">{education}</div>' if has_edu else ''}
                    {f'<div class="ribbon-right">📜 CERTIFICATES</div><div class="right-content left-text">{certificates}</div>' if has_cert else ''}
                </div>
            </div>
        </body>
        </html>
        """

    # ==========================================
    # 4. Minimalist Tech (James Christopher Ref)
    # ==========================================
    else: 
        skills_html = "".join([f'<span style="display:inline-block; border: 1px solid #d1d5db; color: #374151; padding: 4px 12px; margin: 4px; border-radius: 4px; font-size: 12px;">{s}</span>' for s in skills if s])
        
        return f"""
        <html>
        <head>
        <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap" rel="stylesheet">
        <style>
            body {{ font-family: 'Roboto', sans-serif; margin: 0; padding: 0; background: #e5e7eb; }}
            .cv {{ max-width: 900px; margin: 30px auto; background: white; padding: 50px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); min-height: 1050px; }}
            
            /* Header */
            .name {{ font-size: 44px; font-weight: 400; color: #111; margin: 0 0 5px 0; letter-spacing: 1px; }}
            .headline {{ font-size: 18px; color: #4b5563; margin-bottom: 20px; }}
            .contact {{ font-size: 12px; color: #6b7280; border-top: 1px solid #e5e7eb; border-bottom: 1px solid #e5e7eb; padding: 10px 0; margin-bottom: 35px; display: flex; gap: 20px; }}
            
            /* Grid */
            .grid {{ display: grid; grid-template-columns: 3fr 2fr; gap: 50px; }}
            
            /* Sections */
            .section-title {{ font-size: 15px; font-weight: 700; color: #111; text-transform: uppercase; letter-spacing: 1px; border-bottom: 2px solid #111; padding-bottom: 5px; margin-bottom: 20px; margin-top: 0; }}
            
            /* Job styling */
            .job-title {{ font-size: 14px; font-weight: 700; color: #111; margin-top: 25px; margin-bottom: 5px; }}
            .exp-text ul {{ padding-left: 20px; margin-top: 5px; }}
            .exp-text li {{ font-size: 13px; color: #4b5563; line-height: 1.6; margin-bottom: 8px; }}
            
            /* Sidebar Text */
            .side-block {{ margin-bottom: 40px; }}
            .side-text {{ font-size: 13px; color: #4b5563; line-height: 1.6; }}
            .skills-wrap {{ display: flex; flex-wrap: wrap; margin-left: -4px; }}
        </style>
        </head>
        <body>
            <div class="cv">
                <h1 class="name">{name}</h1>
                <div class="headline">{headline}</div>
                <div class="contact">{contact.replace(' | ', '&nbsp;&nbsp;&bull;&nbsp;&nbsp;')}</div>
                
                <div class="grid">
                    <div class="main-column">
                        <h2 class="section-title">Work Experience</h2>
                        <div class="exp-text">
                            {experience}
                        </div>
                    </div>
                    
                    <div class="side-column">
                        <div class="side-block">
                            <h2 class="section-title">Skills</h2>
                            <div class="skills-wrap">{skills_html}</div>
                        </div>
                        
                        {f'<div class="side-block"><h2 class="section-title">Education</h2><div class="side-text">{education}</div></div>' if has_edu else ''}
                        {f'<div class="side-block"><h2 class="section-title">Certifications</h2><div class="side-text">{certificates}</div></div>' if has_cert else ''}
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
