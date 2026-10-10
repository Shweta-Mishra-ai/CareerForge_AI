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
