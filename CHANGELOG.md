# Changelog

## 0.2.0 (unreleased): the merge

CareerForge AI (CV builder) and CareerBoost AI (ATS, portfolio, jobs) were audited and merged into this single app.
The audit findings and how each was resolved are in [docs/MERGE_PLAN.md](docs/MERGE_PLAN.md).

### Portfolio and interface (latest)
* **CV and Portfolio are separate pages.** The portfolio is a builder of its own: look (layout, page colours, accent),
  content (which sections, in which order, what to show) and publishing (address, domain, search engines), a full-width
  live preview, then download and free-hosting links.
* **Portfolio design v3**: inline icons, a soft two-colour glow behind the introduction, a generated cover picture for
  every project (the same project always gets the same picture; it follows the page colours), company badges on the
  experience timeline, a contact panel with labelled link tiles, lift-on-hover for visitors who allow motion, and a
  profile card that only sticks when the window is tall enough. Still one file, no scripts, no external requests.
* **Eight named accent colours** that work on every theme, including the automatic one (a light and a dark shade each,
  all contrast-checked). Your own colour is still available, but is now also checked against the glow and refused on the
  automatic theme, where no single colour can be readable on both pages.
* **Section order** for the portfolio (`PortfolioOptions.order`).
* **App look**: a fixed stylesheet (no user data in it), logo, a "Next" box in the sidebar that says what to do now, and
  a three-step strip on the Start page.

### New
* Typed `Profile` as the single source of truth, with provenance and a submission-readiness gate on every export.
* Reading: PDF (column-aware), DOCX, TXT, pasted text, LinkedIn *Save to PDF* and data export, GitHub, saved profile.
  A rule-based reader for the no-AI case; AI extraction with a grounding check for messy documents.
* ATS v2: published weights, evidence-aware keyword scoring, PDF parse check, ATS-only mode, multi-posting comparison.
* Tailoring that rejects invented numbers, employers and skills; verified cover letters and interview prep.
* CV templates (3 ATS-safe, 1 designed) exported to PDF/DOCX/TXT/HTML; portfolio generator with 3 themes and a deploy guide.
* LinkedIn profile text from your CV ("reverse mode"), AI-free so nothing is invented.
* Job search with ATS-style ranking, application tracker with follow-ups, outreach drafts, roadmap, analytics.
* Streamlit multipage UI; mobile layout; keyboard and screen-reader support; no third-party requests.
* Model discovery for the free Gemini and Groq tiers, with a `doctor` command.

### Industry-standard upgrade: letter, outreach, job search, portfolio
Written conventions, not guarantees: see [docs/STANDARDS.md](docs/STANDARDS.md) for each rule, its source and how
sure we are. No tool can promise that a recruiter, hiring manager or ATS accepts a document.
* **Cover letter**: a real one-page business letter (sender block, date in your country's style, recipient, `Re:` subject
  with reference number, salutation, closing, enclosure) laid out by code. The body is written by AI or, with no AI,
  built from your own bullets matched to the posting's requirements. A lint report (length, paragraphs, company and role
  named, tailoring, a number, filler phrases, variety, next step, tone) and a real PDF page count. PDF, Word and text.
* **HR outreach**: replies for the other moments of a search (referral request, recruiter reply, interview confirmation,
  offer acknowledgement, withdrawing, reply to a rejection, message after a LinkedIn accept); an e-mail lint; the
  `First_Last_CV.pdf` attachment name; a LinkedIn Boolean people-search string. Notes now stay under 200 characters.
* **Job search**: company boards from a pasted Greenhouse or Lever careers-page link; The Muse (the free source the old CareerBoost app had), RemoteOK and Arbeitnow feeds;
  remote / seniority / employment normalised; filters; a multi-part score with a visible breakdown (skills 50%, role 20%,
  seniority 10%, freshness 10%, location 10%); warnings for common job-scam patterns; saved searches and "new since
  last search"; source, contact and next action on tracked applications.
* **Portfolio**: automatic light/dark theme (both palettes contrast-checked), featured case-study cards and live-demo
  links, an optional CV download button (PDF added to the zip), `robots.txt`, `sitemap.xml`, `404.html`, `CNAME`,
  a no-index option, an inline icon, richer `schema.org` data. Lighthouse (local): Performance, Accessibility and Best
  Practices 100; SEO 92, which is 100 once the page's own security policy is lifted for the audit (see STANDARDS.md).

### Portfolio redesign
* Three layouts to choose from: **Profile** (a profile card stays beside your work), **Hero** (landing-page style) and
  **Editorial** (serif, labels in the margin), each in light, dark, automatic and minimal colours. Initials avatar,
  skill chips, a dated timeline, case-study cards, short sections paired in rows, a Download CV / Email button.
  Your city is shown only if you tick a box. Same content in every layout (tested), axe clean in light and dark,
  Lighthouse Performance/Accessibility/Best Practices 100 for all three.
* The portfolio tab links to free hosts (Netlify Drop, GitHub Pages, Cloudflare Pages). Nothing is hosted for you:
  you download the zip, or send the single `index.html`.

### Audit pass (silent failures, dead code, bugs)
* **Silent failure fixed:** a secrets file that is not valid TOML, or keys pasted under a `[section]` header, were
  ignored without a word and the app ran with no AI. Settings now says what is wrong (never echoing a value).
  `GOOGLE_API_KEY` is accepted as the Gemini key.
* **Bug fixed:** a LinkedIn export with a very long description without spaces (a long URL, or text in a script that
  does not use spaces) broke the import at the 600-character limit.
* "Clear everything" now asks first; a save file too large to load back is flagged; the tracker shows a count per
  stage; the GitHub import shows its repo/star/follower summary and the LinkedIn import lists the files it read.
* Dead code removed: unused settings and parameters, a leftover `retryable` flag, invisible bidirectional characters
  in two source files (now guarded by a test), leftover empty `core/` and `templates/` folders.

### Real-browser review, load test and parity with the old app
* Boxes that looked blank (job posting after a file/link load, saved-search load) and a stray `None` on the Jobs page:
  fixed with real-browser tests. Measurements and what they do not prove: [docs/PERFORMANCE.md](docs/PERFORMANCE.md).
* CV header contact is two deliberate lines (no dangling separator when it wraps).
* From the old CareerBoost app: a job posting can be uploaded as PDF, Word or text; the learning roadmap downloads as
  Markdown.
* AI: models that do not exist or are out of quota are skipped for a while instead of being retried on every request;
  up to 5 candidates per provider; Settings has "Check every model now" showing which model names answer for your keys.

### Found while building it
* Letter recipient names were validated with a pattern that rejected 60-character names its own length cap allowed.
* The ATS matcher counts a project's tech list as "listed", not "applied", so projects without the skill in a bullet
  were invisible to the cover-letter evidence step; evidence now also looks at a project's tech list.
* Numbers typed into the letter form (a start date, a hook) were flagged as invented by the claims check.
* No custom accent colour can be readable on both the light and the dark page, so the automatic theme refuses one.
* The jobs page crashed the session if a provider returned an unsafe link; unsafe links are now skipped.

### Fixed (selected)
* XSS in generated CV HTML (all user and model text is now escaped; previews carry a CSP).
* The PDF reader merged columns; right-aligned dates and links no longer detach from their entries.
* The ATS table check counted heading rules as tables; fresher CVs were penalised for having no Experience heading.
* Silent fallbacks to fake data after AI failures; hard-coded `hr@company.com` guesses; empty-credential job API calls.
* API keys can no longer appear in error messages.
* Streamlit page icon was fetched from a Google CDN (a third-party request).

### Reader robustness (found by testing with documents from other software)
* Word/LibreOffice-made PDFs: tab-aligned dates, two-column table layouts with the name after the sidebar, company-first
  entries, numeric dates, wrapped date ranges, degrees such as B.Des/PGDM, LinkedIn-style company/title/dates blocks.

### Hardening
* Hostile or huge input cannot hang a session: the rule reader bounds line length, line count and document size
  (a 60,000-character line used to take over a minute); skill detection is linear (a 1 MB upload used to take minutes).
* The PDF engine is optional at runtime: if Pango is missing, Word/text/HTML export keep working and the PDF button
  explains why it is absent.

### Removed
* `google-generativeai` (end of life), the old `core/` and `templates/` modules and their tests.
