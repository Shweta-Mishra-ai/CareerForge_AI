<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:0f0c29,50:302b63,100:24243e&height=200&section=header&text=CareerForge%20AI&fontSize=60&fontColor=ffffff&fontAlignY=38&desc=LinkedIn%20Profile%20→%20Professional%20CV%20in%20Seconds&descAlignY=60&descSize=18&animation=fadeIn" width="100%"/>

<br/>

[![Live Demo](https://img.shields.io/badge/🌐_Live_Demo-Streamlit_Cloud-FF4B4B?style=for-the-badge&logoColor=white)](https://linkedin-cv-generator-d4v5vnoshm4rzvnchamfqj.streamlit.app/)
[![Demo Video](https://img.shields.io/badge/📺_Demo_Video-Loom-625DF5?style=for-the-badge&logoColor=white)](https://www.loom.com/share/e5b1c8ffb00b447c90a910b9b27efe70)
[![GitHub Stars](https://img.shields.io/github/stars/Shweta-Mishra-ai/CareerForge_AI?style=for-the-badge&logo=github&color=f0c040&labelColor=1a1a2e)](https://github.com/Shweta-Mishra-ai/CareerForge_AI/stargazers)
[![Forks](https://img.shields.io/github/forks/Shweta-Mishra-ai/CareerForge_AI?style=for-the-badge&logo=github&color=4fc3f7&labelColor=1a1a2e)](https://github.com/Shweta-Mishra-ai/CareerForge_AI/network/members)
[![License: MIT](https://img.shields.io/badge/License-MIT-00e676?style=for-the-badge&labelColor=1a1a2e)](https://github.com/Shweta-Mishra-ai/CareerForge_AI/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white&labelColor=1a1a2e)](https://www.python.org/)

<br/>

> **Transform your raw LinkedIn profile into a polished, ATS-ready CV — powered by Google Gemini AI, with bulletproof anti-bot resilience.**

</div>

---

## 📌 Table of Contents

- [Why CareerForge AI?](#-why-careerforge-ai)
- [Live Demo](#-live-demo)
- [Architecture](#-system-architecture)
- [Key Features](#-key-features)
- [Tech Stack](#-tech-stack)
- [Quick Start](#-quick-start)
- [How It Works](#-how-it-works)
- [Project Structure](#-project-structure)
- [V2 Roadmap](#-v2-roadmap)
- [Contributing](#-contributing)
- [Support the Project](#-support-the-project)

---

## 💡 Why CareerForge AI?

LinkedIn's anti-bot defenses (`HTTP 999`, `403 Forbidden`) are some of the most aggressive on the web. Cloud-hosted scrapers get IP-banned within seconds. Most CV generators either break silently or crash entirely.

**CareerForge AI solves this with a two-layer resilience strategy:**

| Layer | Method | Reliability |
|---|---|---|
| 🥇 **Primary** | Native LinkedIn PDF Upload | ✅ 100% — No network, no ban |
| 🥈 **Fallback** | Randomised UA scraper + slug parsing | ⚡ Best-effort, graceful degradation |

Once data is extracted — messy or clean — **Google Gemini 2.0 Flash** restructures it into a perfect JSON schema. The result is a **print-ready, Canva-quality HTML CV** you can save as a PDF instantly.

---

## 🌐 Live Demo

> 🔗 **[Try it live → linkedin-cv-generator.streamlit.app](https://linkedin-cv-generator-d4v5vnoshm4rzvnchamfqj.streamlit.app/)**

> 📺 **[Watch the walkthrough on Loom](https://www.loom.com/share/e5b1c8ffb00b447c90a910b9b27efe70)**

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER INPUT LAYER                         │
│                                                                 │
│    ┌──────────────────────┐    ┌──────────────────────────┐    │
│    │  📄 LinkedIn PDF     │    │  🔗 LinkedIn Profile URL │    │
│    │  (Primary — 100%)    │    │  (Fallback — Best Effort)│    │
│    └──────────┬───────────┘    └─────────────┬────────────┘    │
└───────────────┼─────────────────────────────┼─────────────────┘
                │                             │
                ▼                             ▼
┌──────────────────────────────────────────────────────────────┐
│                     EXTRACTION LAYER                         │
│   ┌────────────────┐          ┌──────────────────────────┐  │
│   │  pdfplumber    │          │  Requests + BeautifulSoup│  │
│   │  (layout-aware)│          │  (Randomised UA Headers) │  │
│   └───────┬────────┘          └────────────┬─────────────┘  │
│           └────────────┬───────────────────┘                │
└────────────────────────┼───────────────────────────────────┘
                         │  Raw Unstructured Text
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                      AI ENGINE LAYER                         │
│   ┌──────────────────────────────────────────────────────┐  │
│   │  Gemini 2.0 Flash → 1.5 Flash → 1.5 Pro (cascade)   │  │
│   │  Fallback: Groq Llama 3.3 70B                        │  │
│   │  Output: { name, headline, skills[], experience[] }  │  │
│   └────────────────────────┬─────────────────────────────┘  │
└────────────────────────────┼────────────────────────────────┘
                             │  Clean JSON Schema
                             ▼
┌──────────────────────────────────────────────────────────────┐
│                    CV GENERATION LAYER                       │
│   ┌──────────────────────────────────────────────────────┐  │
│   │  7 Premium HTML/CSS Templates                        │  │
│   │  Two-Column · Executive · Creative · Minimalist      │  │
│   │  Teal Accent · Academic · Dark Premium               │  │
│   └────────────────────────┬─────────────────────────────┘  │
└────────────────────────────┼────────────────────────────────┘
                             ▼
                    📥 Download CV  (HTML → PDF via Ctrl+P)
```

---

## ✨ Key Features

### 🛡️ Anti-Bot Resilience
LinkedIn's `HTTP 999` and `403` errors handled proactively. The app **never crashes** — degrades gracefully from URL scraping to PDF upload with clear user guidance.

### 🧠 Dual-LLM Cascade (4-layer fallback)
**Gemini 2.0 Flash-Lite → 2.0 Flash → 1.5 Flash → Groq Llama 3.3 70B** — four layers ensure 99.9% uptime regardless of API rate limits or model deprecations.

### 🎨 7 Premium CV Templates
Each template is hand-crafted with production-grade HTML/CSS — Two-Column Navy, Executive Corporate, Creative Ribbons, Minimalist Clean, Teal Accent, Academic Structured, Dark Premium Gold.

### 🎯 Deep ATS Analysis Engine
Section-by-section scoring, missing keyword detection, formatting audit, hallucination integrity check, and a fully tailored CV — all in one click.

### 📊 Career Tools Suite
Auto-generated **Cover Letter** and **Interview Prep Questions** grounded in your actual CV and the target JD. No generic output.

### 📎 Chrome Extension (MV3)
Capture your LinkedIn profile directly from the browser — no manual PDF export needed.

---

## 🛠️ Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Frontend / Hosting** | Streamlit | UI & Cloud Deployment |
| **PDF Parsing** | pdfplumber | Layout-aware text extraction |
| **Web Scraping** | BeautifulSoup4, Requests | URL fallback extraction |
| **Primary AI** | Google Gemini 2.0/1.5 | JSON structuring from raw text |
| **Fallback LLM** | Groq (Llama 3.3 70B) | Rate-limit & deprecation resilience |
| **CV Rendering** | HTML5 / CSS3 | Print-ready output |
| **Distribution** | Base64 Encoding | In-browser file download |
| **Browser Tool** | Chrome Extension MV3 | Direct LinkedIn capture |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.9+
- Google Gemini API Key → [Get free key](https://makersuite.google.com/app/apikey)
- Groq API Key → [Get free key](https://console.groq.com)

### 1. Clone & Install

```bash
git clone https://github.com/Shweta-Mishra-ai/CareerForge_AI.git
cd CareerForge_AI
pip install -r requirements.txt
```

### 2. Configure API Keys

Create `.streamlit/secrets.toml`:

```toml
GEMINI_API_KEY = "your_gemini_api_key_here"
GROQ_API_KEY   = "your_groq_api_key_here"
```

### 3. Run

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501)

---

## 🎯 How It Works

```
Step 1 → Upload LinkedIn PDF   (LinkedIn → Me → Save to PDF)
           OR paste LinkedIn URL
           OR paste text / use Chrome Extension

Step 2 → (Optional) Paste Job Description for ATS targeting

Step 3 → Click "Analyze & Generate"
           AI extracts → structures → templates your profile

Step 4 → Download as HTML → Save as PDF via Ctrl+P
```

---

## 📁 Project Structure

```
CareerForge_AI/
│
├── .streamlit/
│   └── secrets.toml          # API keys (gitignored — never committed)
│
├── chrome_extension/         # MV3 Chrome Extension
│   ├── manifest.json
│   ├── content.js
│   ├── popup.html
│   └── popup.js
│
├── core/                     # Business logic (zero Streamlit imports)
│   ├── ai_engine.py          # LLM cascade + JSON parsing + prompts
│   └── scraper.py            # PDF extraction + URL scraping
│
├── templates/
│   └── cv_styles.py          # 7 premium HTML/CSS CV templates
│
├── app.py                    # Streamlit entry point
├── requirements.txt
├── .gitignore
├── LICENSE
└── README.md
```

---

## 🗺️ V2 Roadmap

> V1 is stable and live. These are confirmed V2 features.

| Status | Feature | Description |
|---|---|---|
| ✅ **V1 Done** | PDF + URL + Paste input | Bulletproof dual-layer extraction |
| ✅ **V1 Done** | 7 premium CV templates | Hand-crafted HTML/CSS designs |
| ✅ **V1 Done** | ATS scoring + CV tailoring | Full gap analysis + rewritten CV |
| ✅ **V1 Done** | Cover letter generator | JD-grounded, no filler templates |
| ✅ **V1 Done** | Interview prep questions | Gap-focused, role-specific |
| ✅ **V1 Done** | Chrome Extension (MV3) | Direct LinkedIn browser capture |
| 🔄 **V2 Planned** | **ATS-Only Mode** | Score your existing CV without regenerating it — keep original format, get only keyword fix suggestions |
| 🔄 **V2 Planned** | **CV Analytics Dashboard** | HR-style visual report — skill gap radar, experience timeline, keyword density heatmap, career progression score |
| 🔄 **V2 Planned** | **Section-Level Tips Engine** | Personalised, line-by-line improvement tips per CV section — *"Add metrics to bullet 2"*, *"Missing cloud keywords in Skills"* |
| 🔄 **V2 Planned** | **DOCX Export** | Download CV as editable Word document |
| 🔄 **V2 Planned** | **Multi-JD Comparison** | Match your CV against 3 JDs simultaneously, ranked by fit |
| 📋 **V3 Future** | LinkedIn OAuth | Official API — no scraping needed |
| 📋 **V3 Future** | Reverse Mode | CV → LinkedIn profile sections generator |

---

## 🤝 Contributing

Contributions are welcome!

```bash
# Fork the repo, then:
git clone https://github.com/YOUR_USERNAME/CareerForge_AI.git
git checkout -b feature/your-feature-name

# Make your changes, then:
git commit -m "feat: describe your change"
git push origin feature/your-feature-name
# Open a Pull Request
```

Please follow [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`

For major changes, open an Issue first to discuss scope.

---

## 📄 License

MIT License — free for personal, commercial, and portfolio use.
See [`LICENSE`](https://github.com/Shweta-Mishra-ai/CareerForge_AI/blob/main/LICENSE) for full terms.

---

## ⭐ Support the Project

If CareerForge AI helped your job search:

```
⭐ Star this repo    — helps other job seekers find this tool
🍴 Fork it          — build on it, make it yours
🐛 Open an Issue    — your bug report makes it better for everyone
📢 Share it         — LinkedIn, Twitter, wherever developers gather
```

---

<div align="center">

**Built for job seekers, by a job seeker.**

*Open source. Free forever.*

[![Star History Chart](https://api.star-history.com/svg?repos=Shweta-Mishra-ai/CareerForge_AI&type=Date)](https://star-history.com/#Shweta-Mishra-ai/CareerForge_AI)

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:24243e,50:302b63,100:0f0c29&height=120&section=footer" width="100%"/>

</div>
