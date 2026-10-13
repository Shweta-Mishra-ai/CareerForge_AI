# Deploying CareerForge AI

The app is a plain Streamlit app. These steps are for **Streamlit Community Cloud** (free). I could not test a
deployment from the build environment, so treat the Cloud-specific details as what the documentation says, and tell
us if a step is out of date.

## 1. Prepare

1. Fork or push the repository to your GitHub account (public or private).
2. Make sure these files are at the repository root: `app.py`, `requirements.txt`, `packages.txt`, `.streamlit/config.toml`.
   - `packages.txt` lists the Debian packages Streamlit Cloud installs before starting: the Pango/HarfBuzz libraries
     that WeasyPrint (PDF export) needs and the Liberation and Carlito fonts that the CV templates use.
   - `requirements.txt` pins every Python dependency.

## 2. Create the app

1. Sign in at share.streamlit.io with GitHub and choose **Create app**.
2. Repository: yours. Branch: `main`. Main file path: `app.py`.
3. **Advanced settings → Python version:** pick 3.13 (the version the project is developed and tested on).
4. **Advanced settings → Secrets:** paste the lines you want from `.streamlit/secrets.toml.example`. Everything is
   optional; with no keys the app runs in basic mode.

## 3. Decide who pays for AI

* **Your key in Secrets:** every visitor can use AI, up to `CAREERFORGE_SESSION_AI_LIMIT` actions per session
  (default 30). Use a key with a low quota or spending limit: the per-session limit is a courtesy limit, not
  protection against someone who opens many sessions.
* **No key in Secrets:** visitors run in basic mode, or paste their own free key in **Settings**; it is kept for their
  session only.

## 4. Check it works

After the first build, open the app and run through this list (about five minutes):

1. **Start → Paste text** with a small CV → *Read this text* → Review page shows your details.
2. **CV & portfolio → Build my files** → download the PDF and open it. If the build fails with a message about
   `libpango` or fonts, `packages.txt` was not picked up: check it is at the repository root and reboot the app.
3. If the app says **AI: not set up** although you added keys, open **Settings**: it names the problem (secrets that
   are not valid TOML, or keys placed under a `[section]` header). Keys must be top-level lines like
   `GEMINI_API_KEY = "..."`, quotes included.
4. If you set a key: **Settings → Test the AI connection** shows the provider and model that answered.
5. Optional: run `python -m careerforge.ai.doctor` locally with your keys and put its suggested
   `CAREERFORGE_*_MODELS` into Secrets, so the app does not have to discover models on every start.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| PDF export fails, `cannot load library 'libpango...'` | `packages.txt` missing or not at the repository root |
| PDF looks different from the preview (fonts) | The listed fonts were not installed; check the build log for `fonts-liberation` |
| Chinese/Arabic/other non-Latin names show as boxes | Add a font package for that script to `packages.txt` (for example a Noto font) |
| "AI service could not be reached" | Provider outage or blocked egress; the basic reader still works |
| "out of quota or too busy" | Free-tier limits; wait, pin a different model, or add a second provider key |
| Job search shows an error for one board | That board's API changed or is down; the others still work |
