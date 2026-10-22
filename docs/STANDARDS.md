# Industry standards this app follows, and how sure we are

"Real industry standard" is a promise nobody can fully keep. ATS products are secret and differ from each other, and
no senior HR person's taste can be tested by software. What this app does is encode **documented conventions**, check
your documents against them with plain code, and **say where each rule comes from and how much weight it deserves**.

**What this document cannot tell you:**

* Whether a particular employer's ATS parses your file. The app checks the PDF with its own text extractor and says so.
* Whether a particular recruiter or hiring manager likes your letter, e-mail or site.
* That a rule below improves your chances. They are conventions repeated by career-advice sources, **not** results of
  controlled studies. We found no published study that fixes any of these numbers, and we do not quote survey
  percentages, because the ones in circulation could not be traced to a primary source.

Confidence tags used below:

| Tag | Meaning |
|---|---|
| **Standard** | A published specification or a hard limit of the service (the check is exact). |
| **Consensus** | The same rule appears across several career-advice sources checked while building this (The Muse, Rezi and Coursera guides were the ones read for the cover letter). They agree with each other; none is a study. Pages change; check them again if it matters. |
| **Convention** | Long-standing business-writing practice. Widely taught; regional variants exist. |
| **Design choice** | Our own number, chosen to be reasonable and shown to you. Not fitted to any outcome data. |
| **Unverified** | Built from documentation or memory and not tested against the live service. |

## Cover letter

| Rule the app applies | Basis | Tag |
|---|---|---|
| One page (measured on the real PDF, not estimated) | Every guide read agrees; the check is exact | Consensus; check is **Standard** |
| About 250-400 words in 3-5 short paragraphs | The range common to the guides; below 150 or above 450 words is flagged as a "fix" rather than a "suggestion" | Consensus |
| Business-letter layout: sender block, date, recipient block, subject line, salutation, body, closing, name, "Enclosure" | Standard block business-letter format | Convention |
| "Dear Ms. Rao," when you give a name; "Dear Hiring Manager," when you do not. A name is never guessed | Addressing a named person is the usual advice; guessing a name is worse than a generic greeting | Convention |
| Closing: "Sincerely," (US); "Yours sincerely," with a named person and "Yours faithfully," without one (UK); "Kind regards," (warm tone) | UK/US letter-closing conventions | Convention |
| Date written the way the reader's country writes it (US `October 10, 2026`, UK `10 October 2026`, or ISO) | Regional convention; ISO is unambiguous everywhere | Convention |
| Subject line `Re: Application for <role> (Ref: <number>)` | Common in business letters and email applications; the reference number is repeated because many employers file by it | Convention |
| Names the company and the role | Every guide | Consensus |
| Answers what the posting asks, each with one real example from your CV, ideally with a number | Every guide; the app pairs requirements with your own bullets (nothing is generated for this part) | Consensus |
| Avoids filler ("team player", "hard-working", "passionate about"...) and does not start most sentences with "I" | Every guide; the "I" threshold (at most half the sentences) is ours | Consensus; threshold **Design choice** |
| Ends with a clear next step | Every guide | Consensus |
| At most one exclamation mark, no emoji, no shouting | Professional-tone advice | Convention |
| PDF unless the employer asks otherwise | Common advice; a PDF keeps the layout | Consensus |
| The body cannot contain a number, employer, skill or name that is not in your CV, the posting, or what you typed in the form | The app's own honesty rule (checked by code after the AI writes) | Design choice |

The checks are **suggestions you can ignore**. A letter that fails one is not "wrong"; a letter that passes all of them
is not "accepted".

## HR outreach (e-mail and LinkedIn)

| Rule | Basis | Tag |
|---|---|---|
| Subject 60 characters or fewer | Rule of thumb that mobile inboxes cut long subjects. The cut-off differs by client | Unverified rule of thumb |
| Body 150 words or fewer (follow-ups shorter: 100 and 80) | Rule of thumb for cold outreach | Unverified rule of thumb |
| One request per message | Rule of thumb; the check counts request-like phrases and is a heuristic | Design choice |
| Signed with an e-mail or phone number | Basic courtesy | Convention |
| Attach the CV as `First_Last_CV.pdf` | Recruiters see the file name; widely repeated | Consensus |
| E-mail addresses are never guessed | Guessed addresses are mostly wrong and unsolicited mail to strangers is poor practice | Design choice |
| LinkedIn note kept under 200 characters | We could not verify today's limit: the figure has changed over time and may differ by account type, so the drafts stay under the lower one | **Unverified** |
| Boolean people search: quotes, upper-case `AND`/`OR`, brackets | LinkedIn documents Boolean search; this app has not run the string against the live site | Unverified |

Drafts for other moments (referral request, replying to a recruiter, confirming an interview, acknowledging an offer,
withdrawing, replying to a rejection) use only your CV and what you type. Anything left blank is left out.

## Job search

| Rule | Basis | Tag |
|---|---|---|
| Sources: Remotive, Jobicy, The Muse, RemoteOK, Arbeitnow (public feeds), Adzuna (needs your free keys), and any company's own Greenhouse or Lever board from its careers-page link | Each service's public documentation | **Unverified**: the build environment could not reach these services, so every parser is tested only against hand-written look-alike responses. Failures are reported per source, never hidden |
| The Muse has no keyword search, so the newest 3 pages (about 60 postings) are read and filtered here; a niche query can find few postings. Its page numbering and level names (used for seniority) come from the old CareerBoost code and memory | **Unverified** |
| Credit the source and link back (Remotive, RemoteOK) | Their terms ask for it; every card shows its source and the original link | Standard (their terms) |
| Career-page links are accepted only for the two services' real hosts | Prevents a pasted link from making the app contact an arbitrary server | Design choice |
| Score = skills 50%, role 20%, seniority 10%, freshness 10%, location 10%; parts that cannot be measured are dropped and the rest re-weighted | Shown on every card ("How this score was calculated"). Skills and role use the same engine as the ATS check | **Design choice**. The weights are not fitted to hiring outcomes |
| Seniority is read from the job title only (intern, junior, mid, senior, lead) and compared with the years in your CV's dates | Titles are the only reliable signal in the feeds; companies use titles differently | Design choice |
| Warnings on postings that ask for fees, gift cards, cheques, chat-app interviews, bank or ID details early, or promise high pay for no experience | Patterns listed in consumer-protection advice about job scams (for example from the US FTC; recalled, not re-checked while building) | Consensus; **a clean posting is not proof that it is genuine** |
| New postings are marked using links you have already seen, kept in your profile file | Convenience | n/a |

## Portfolio website

| Rule | Basis | Tag |
|---|---|---|
| Three layouts (Profile, Hero, Editorial) x four colour themes, all showing exactly the same content | Design choices: the look is ours, not a recognised standard; what is tested is that every layout shows every fact, has one `h1`, a banner, `main` and a page footer, a skip link, no horizontal scroll at 320 px, and no axe WCAG A/AA violation in light and dark | Design choice (tested) |
| Eight named accent colours, each with a light-page and a dark-page shade; every one is checked against every text colour and tint in every theme (also both pages of the automatic one) | WCAG 2.1 1.4.3, computed | **Standard**, exact |
| Project cover pictures and company badges are decorative: generated from the project or company name, hidden from screen readers, carry no text and no colour of their own | Design choice (tested) | Design choice |
| Text on the faint accent wash used for hero bands and chips meets AA in every palette | WCAG 2.1 1.4.3, computed from the exact blended colour | **Standard**, exact |
| One static HTML file, no JavaScript, no external requests, strict Content Security Policy | Security by construction | Design choice (tested) |
| WCAG 2.1 AA contrast for every text colour in every theme, in both palettes of the automatic theme | WCAG 2.1 success criterion 1.4.3 | **Standard**, exact |
| No single custom accent colour is readable on both the light and dark page, so the automatic theme refuses custom accents | Computed: none of 4,096 sample colours passed | Measured |
| `prefers-color-scheme` follows the visitor's device | CSS Media Queries Level 5 | **Standard** |
| `robots.txt`, `sitemap.xml` (when you give an address), `404.html`, `CNAME` (when you give a domain), inline icon | robotstxt.org and sitemaps.org protocols; GitHub Pages conventions | **Standard** / Convention |
| `schema.org` Person data: name, job title, links, skills (`knowsAbout`), current employer (`worksFor`, only for a role you marked current), schools (`alumniOf`) | schema.org vocabulary. Search engines may or may not use it | Standard format; effect **unverified** |
| No social preview image | We do not ship or fetch images; links shared on social media show text only | Limitation |

### Measured quality (Lighthouse 12.8.2, headless Chromium, local server, 2026-10-10)

Performance 100, Accessibility 100, Best Practices 100, SEO 92 for all four themes. The only SEO item that did not pass
was Lighthouse's *"robots.txt is valid"* audit. The cause is **not** a faulty `robots.txt`: Lighthouse fetches that
file from inside the page, and the page's strict Content Security Policy (`default-src 'none'`) forbids that request.
With the policy removed for the audit only (checked on the automatic theme), the same files scored **SEO 100** and
*"robots.txt is valid"*. We keep the
strict policy, because it is what stops a page from ever running code or loading anything from elsewhere.

Automated tools find only part of the accessibility problems that exist (the axe-core audit in our test suite and
Lighthouse both say so). Neither replaces testing with a screen reader.

## Still not verified

* Live job-board APIs and a real LinkedIn data export (see `docs/MERGE_PLAN.md`).
* Today's LinkedIn character limits and Boolean search behaviour.
* That any specific ATS parses the PDF or Word file the app produces. The app's PDF check is its own extractor.
* That any specific hiring manager prefers this letter or e-mail style.

If you know one of these is wrong, tell the repository owner; each rule above is one small, tested function that is easy
to change.
