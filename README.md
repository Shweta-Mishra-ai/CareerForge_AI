---
title: CareerForge
emoji: 🚀
colorFrom: blue
colorTo: sky
sdk: streamlit
sdk_version: 1.31.0
app_file: streamlit_app.py
pinned: true
license: mit
---

<div align="center">
  <h1>🚀 AI-Powered LinkedIn to CV Generator</h1>
  <p><strong>A smart, resilient, and beautifully designed web application built with Streamlit and Google's Gemini AI.</strong></p>

  <p>
    <a href="https://github.com/Shweta-Mishra-ai/careerforge/stargazers">
      <img src="https://img.shields.io/github/stars/Shweta-Mishra-ai/careerforge?style=for-the-badge&logo=github&color=gold" alt="GitHub stars">
    </a>
    <a href="https://github.com/Shweta-Mishra-ai/careerforge/network/members">
      <img src="https://img.shields.io/github/forks/Shweta-Mishra-ai/careerforge?style=for-the-badge&logo=github&color=blue" alt="GitHub forks">
    </a>
    <a href="https://github.com/Shweta-Mishra-ai/careerforge/blob/main/LICENSE">
      <img src="https://img.shields.io/github/license/Shweta-Mishra-ai/careerforge?style=for-the-badge&logo=github&color=green" alt="License">
    </a>
  </p>

  <h3><a href="https://www.loom.com/share/e5b1c8ffb00b447c90a910b9b27efe70">📺 Watch the Demo Video</a></h3>
</div>

---

## 🌟 Overview

**CareerForge** extracts unstructured data from LinkedIn profiles and converts it into a professional, print-ready HTML CV. It is designed to be resilient, bypass anti-bot mechanisms, and leverage Google's Gemini AI for perfect data structuring.

## ✨ Key Features

- 📄 **Bulletproof PDF Parsing** — Bypass LinkedIn's strict anti-bot mechanisms entirely by uploading a native LinkedIn Profile PDF export. **100% reliable.**
- 🔗 **Smart URL Scraping** — Features an intelligent URL scraper that uses Googlebot header spoofing and URL slug parsing as a fallback if LinkedIn blocks the request.
- 🧠 **AI-Driven Extraction** — Powered by **Google's Gemini API** (`gemini-pro` / `gemini-1.5-flash`) to intelligently read raw, messy text and structure it into perfect JSON (Name, Headline, Skills, Experience).
- 🎨 **Pro-Level Design Template** — It doesn't just dump plain text. It generates a beautifully formatted, **Canva-style HTML resume** that is instantly ready to be saved as a PDF (Ctrl+P).

## 🛠️ Tech Stack & Architecture

- **Frontend & Hosting:** [Streamlit](https://streamlit.io/) (Python)
- **Data Extraction:** BeautifulSoup4, Requests
- **PDF Processing:** PyPDF2
- **AI Engine:** Google Generative AI (Gemini API)
- **Document Generation:** HTML/CSS with Base64 encoding for direct downloads

## 🚀 How to Run Locally

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Shweta-Mishra-ai/careerforge.git
   cd careerforge
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up your API Key:**
   Create a `.streamlit/secrets.toml` file in the root directory and add your Google Gemini API key:
   ```toml
   GEMINI_API_KEY = "your_api_key_here"
   ```

4. **Run the application:**
   ```bash
   streamlit run streamlit_app.py
   ```

## 🧠 Why This Approach?

Directly scraping LinkedIn URLs from a cloud server often results in immediate IP bans (HTTP 999/403 errors). To solve this real-world engineering problem, this application prioritizes the **PDF Upload method** for guaranteed **100% uptime**, while maintaining a smart **URL Parsing fallback** to fulfill basic scraping requirements without crashing the app.

---

## 🎯 How to Use

1. **Upload your LinkedIn PDF** in the sidebar (get this from LinkedIn → More → Save to PDF).
2. (Optional) **Paste a job description** or URL for targeted ATS analysis.
3. Click **🚀 Analyze & Generate**.
4. **Download your CV** as a beautiful HTML file or save it directly as a PDF (Ctrl+P).

## 💎 Why CareerForge?

- **Anti-Ban Resilience:** Designed to handle LinkedIn's 403 and 999 errors proactively.
- **Premium Aesthetics:** Dark-mode Streamlit UI paired with high-end, clean CV templates.
- **AI-Powered Precision:** Uses the latest Gemini 1.5 models for human-like data extraction.

---

## 💖 Support the Developer

If you find this tool helpful, please consider supporting its development:

- ⭐ **Star this repository on [GitHub](https://github.com/Shweta-Mishra-ai/careerforge)** to show your support!
- 🎁 **Gift/Sponsor:** If you'd like to support my work further, feel free to reach out or contribute!
- 📣 **Share:** Tell your friends and colleagues about CareerForge.

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.

---

<div align="center">
  <p>Built with ❤️ by Developers for Job Seekers</p>
</div>
