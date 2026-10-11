# Changelog

## 0.2.0 (unreleased): the merge

CareerForge AI (CV builder) and CareerBoost AI (ATS, portfolio, jobs) were audited and merged into this single app.
The audit findings and how each was resolved are in [docs/MERGE_PLAN.md](docs/MERGE_PLAN.md).

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
