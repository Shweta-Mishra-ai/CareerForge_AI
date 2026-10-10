# CareerForge AI v2: merge plan (CareerBoost AI → CareerForge AI)

Status key: ✅ done · 🔄 in progress · ⬜ not started

## Decisions (confirmed)
| Topic | Decision |
|---|---|
| Deployment | Streamlit Community Cloud. PDF engine = WeasyPrint (needs `packages.txt`); no server-side Chromium |
| UI stack | Stay on Streamlit; multipage via `st.navigation`, one design system |
| Missing experience | **Never invent.** GitHub-only mode yields projects and skills; experience is user-entered in a review form. AI-written text is marked "suggested" until confirmed |
| Workflow | Phase by phase; review after each phase group |

## Core principle
One typed `Profile` model (Pydantic) is the single source of truth. All text is escaped at render time (Jinja2 autoescape; XML-escape for any PDF/DOCX text API). Every AI output is schema-validated and grounding-checked against the source text. Failures are loud, never a success banner.

## Goal pipeline: old CV or LinkedIn profile → ready-to-submit CV + portfolio
```
 old CV (PDF/DOCX/TXT) ─┐
 LinkedIn "Save to PDF" ─┤→ ingest → Profile draft → REVIEW/EDIT → improve (grounded, suggestions) →
 LinkedIn data export ───┤                                          readiness gate → export CV + portfolio
 GitHub / paste / ext. ──┘
```
* **Review/edit is mandatory** before any export: extraction is never trusted blindly (Phase 3 UI).
* **Improve** = rewrite weak bullets, add missing keywords the candidate really has, tailor to a JD. Every change is
  shown as a diff; text not traceable to the source is flagged `suggested` and excluded until confirmed (Phase 2/4).
* **Readiness gate** (`careerforge/readiness.py`, done): blockers (name, email, placeholders, nothing to show), warnings
  (no dates, first person, gaps), tips (quantify). Exporters must call `require_ready()` (Phase 5).
* LinkedIn: official sources only. Phase 3 supports the profile "Save to PDF" and the LinkedIn *data export* archive
  (CSV files) and the Chrome-extension paste. A LinkedIn URL alone cannot be read; the app says so honestly.
  The data-export CSV layout must be verified against a real export before relying on it.

## ATS v2 (Phase 4): a transparent, mostly deterministic score
The old ATS score was a number an LLM made up. v2 is built from components you can see and verify:
1. **Keyword coverage** - required vs preferred terms extracted from the JD, matched with word boundaries, aliases and
   the skills taxonomy (so `k8s` = Kubernetes), weighted by where they appear (skills, recent role, bullets).
2. **Section & structure** - standard headings present, reverse-chronological, dates parseable, contact in the body.
3. **Parseability of the *actual exported PDF*** - extract its text and check order, single column, no tables/images
   carrying content, fonts embedded. This is tested on the real artifact, not guessed.
4. **Content quality** - quantified bullets, action verbs, length, no first person (shares rules with readiness).
5. **LLM only for explanation and semantic gaps** (never for the number), with evidence quotes from the CV and JD.
Output: component scores, the exact missing keywords, and line-level fixes. Limits we will state in the UI: no
tool can reproduce a specific vendor's ATS (Workday, Greenhouse, Lever...); the score is a well-grounded proxy.

## Phases
| # | Phase | Status |
|---|---|---|
| 0 | Foundation: hygiene, pinned deps, ruff, pytest, CI, fixtures, characterisation tests | ✅ |
| 1 | `Profile` model, JSON import/export, legacy adapter, skills taxonomy, **submission-readiness gate** | ✅ |
| 2 | AI layer: `google-genai` + Groq cascade, retry/backoff, validated output, grounding checker, injection-safe extraction | ✅ (rewrite/tailor prompts + rewrite-mode grounding land with their features in Phase 4) |
| 3 | Ingestion: PDF/DOCX/TXT/paste/LinkedIn (PDF + data export)/GitHub; SSRF-safe URL fetch; extension fixes; review logic | ✅ (the Streamlit review-and-edit *form* is built with the UI in Phase 6; its logic, `careerforge/review.py`, is done) |
| 4 | Feature port (matrix below) | ⬜ |
| 5 | CV + portfolio upgrade: Jinja2 templates, PDF/DOCX/HTML export, ATS-safe variants, 3 portfolio themes | ⬜ |
| 6 | UI/UX: multipage, wizard, lazy tabs, mobile, a11y | ⬜ |
| 7 | Test hardening: Playwright e2e, visual regression, axe, security matrix, coverage gate | ⬜ |
| 8 | Docs/release; archive `careerboost-ai` with a pointer README | ⬜ |

## Feature matrix
| Feature | From | Phase |
|---|---|---|
| PDF/URL/paste input, 7 templates, ATS + tailored CV, cover letter, interview prep, Chrome extension | CareerForge | kept/rebuilt 3–5 |
| GitHub import, job search, HR finder + emails, skills roadmap, portfolio, Harvard/Modern PDF | CareerBoost | 4–5 |
| ATS-only mode, multi-JD comparison | CF V2 | 4 |
| Analytics dashboard (skill-gap radar, timeline, keyword heatmap) | CF V2 | 4 |
| Section-level tips engine | CF V2 | 4 |
| DOCX export | CF V2 | 5 |
| Application tracker (kanban), scoring history (via profile file) | CB roadmap | 4 |
| Multiple portfolio themes | CB roadmap | 5 |
| Reverse mode (CV → LinkedIn sections) | CF V3 | 4 if time |
| **Deferred:** LinkedIn OAuth (believed to need partner approval), Naukri (no known public API; scraping ToS risk), extension one-click ATS, "Caria" SaaS rewrite | both | not planned |

## Audit backlog → where each is fixed (and which test flips)
Tests marked `xfail(strict=True)` in `tests/` flip to passing when fixed. Remove the marker then.

| Audit item | Fixed in | Regression test |
|---|---|---|
| Fabricated experience (`enrich_from_github_llm`), invented metrics in cover letter/interview prompts | 2, 4 | grounding tests (new) |
| "Hallucination check" is LLM self-attestation | 2 | grounding tests (new) |
| Parse failure shown as success; fixed 4096 token cap truncates ATS output | 2 | `test_garbage_response_raises` |
| Substring skill matching (`R`, `go`, `ios`, `rag`, `java` in `javascript`) | 3 | skill-matching tests (new) |
| No HTML escaping in templates/portfolio (XSS) | 5 | `test_name_and_skills_are_html_escaped[*]` |
| `skills=None` crash; score `"85%"` crash; missing tailored_cv defaults | 1–2 | `test_none_skills_does_not_crash`, `test_analysis_scores_are_coerced_to_int`, `test_tailored_cv_gets_required_keys` |
| Contact icon matches substring `up` | 5 | `test_contact_icon_not_fooled_by_substring_up` |
| Unknown template silently falls back | 5 | `test_unknown_template_name_is_rejected` |
| Slug-only LinkedIn stub passes the 50-char gate | 3 | `test_slug_only_result_is_too_thin_to_generate_from` |
| SSRF in URL fetchers; no size/status checks | 3 | SSRF tests (new) |
| reportlab crash on `<b>` / `a<b` text; hyphen-splitting destroys bullets (CareerBoost code) | 5 (re-tested on ported code) | PDF text tests (new) |
| Eager LLM calls on every rerun (≈5 per Generate); no retry/backoff | 2, 6 | AppTest call-count test (new) |
| Cached failures (`[Failed…]` letter, unretryable interview prep) | 6 | AppTest (new) |
| Stale cache keys (filename-only; email/phone edits ignored) | 1, 6 | AppTest (new) |
| Dead Adzuna/Muse fallbacks, swallowed errors in job search | 4 | provider tests with recorded responses |
| Extension: loose URL check, over-broad permission, false success message | 3 | extension unit tests |
| `google-generativeai` package is end-of-life (confirmed by its own warning) | 2 | import test |
| Unused deps (`httpx`, `lxml`), phantom docstring claims, README claims we can't back | 0 (CareerBoost side), 8 | n/a |

## Phase 2 notes
* `careerforge/ai/`: `providers` (Gemini, Groq; no hidden SDK retries - verified), `client` (cascade, backoff, deadline,
  repair-retry, token-budget growth on truncation), `grounding` (deterministic), `safety` (sanitise + fence),
  `extract` (document text -> grounded Profile), `settings` (keys/models from secrets/env).
* Offline tests run the **real SDKs** against a local fake server. They prove our request construction and error
  mapping, not that the live services match the fake. Run `pytest -m live -s tests/test_ai_live_smoke.py` with real keys
  to verify model names and wire formats (manual; excluded from CI).
* Legacy `core/ai_engine.py` still imports the end-of-life `google-generativeai`; it is removed with `app.py` in Phase 6.

## Phase 3 notes
* `careerforge/ingest/`: `pdf` (column-aware XY-cut reader on pdfplumber word positions; MIT-only deps), `docx_reader`,
  `files` (type sniffing, 10 MB cap, zip-bomb guard), `linkedin` (data-export CSVs, explicit file allow-list),
  `github` (projects only, nothing invented), `web` (SSRF-safe fetch with pinned connections), `pipeline` (one entry point).
* Measured, not assumed: `pdfplumber extract_text()` and `layout=True` BOTH interleave side-by-side columns line by
  line (the old README claim was wrong). PyMuPDF reads columns correctly but is AGPL, so it was not adopted.
* The PDF reader was tuned on generated layouts (sidebar left/right, header + columns, 3 columns, tables, dates
  columns) plus a property test (no word lost/duplicated). It has NOT been validated on a corpus of real-world CV
  PDFs (Word/Canva/LaTeX exports): collect a few and add them as fixtures.
* Extension: URL parsed (not substring-matched), no host permissions, success only after the copy resolved, honest
  labelling, tested in real Chromium. Selectors still depend on LinkedIn's markup.

## Model selection (changed after Phase 3)
* Model names are no longer hard-coded: `careerforge/ai/models.py` asks each provider which models the key can use,
  ranks them (stable flash > flash-lite > pro > aliases > previews; Groq by JSON-following families and context),
  keeps the top 3 per provider and caches for 1 h. `CAREERFORGE_*_MODELS` pins models and skips discovery. The old
  names survive only as an unverified last-resort fallback, and the app says so when it uses them.
* Neither provider's list API says which models are on the FREE plan. That is found empirically: a model with no free
  quota fails fast (`AIQuotaExhausted`) and the cascade moves on without retrying.
* Run `python -m careerforge.ai.doctor` with your keys: it prints what works for YOU right now and the settings to pin.
* The provider docs could not be fetched from the build sandbox, and third-party summaries disagreed, so no free-tier
  claim from them was relied on.

## Open unknowns (verify, do not assume)
- LinkedIn data-export CSV column names/format: implemented from memory without a real export (tolerant parser).
- Real-world PDF layouts beyond the generated ones (see Phase 3 notes).
- GitHub import cannot prove the account belongs to the user (needs OAuth); the UI must say "import your own account only".
- Which Gemini/Groq model IDs are currently served. Defaults in `careerforge/ai/settings.py` are best guesses; override with `CAREERFORGE_GEMINI_MODELS` / `CAREERFORGE_GROQ_MODELS`. Unserved models are skipped automatically; confirm with the live smoke test.
- Live job-API behaviour (Remotive, Jobicy): to be recorded once and replayed in tests.
- ~~`pdfplumber(layout=True)` column interleaving~~ - RESOLVED in Phase 3: confirmed broken, replaced (see notes above).
- Whether Streamlit Cloud sanitises `data:` download links: replaced by `st.download_button` regardless.
