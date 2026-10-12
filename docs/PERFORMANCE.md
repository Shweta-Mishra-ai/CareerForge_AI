# Load and latency: what was measured, and what it does not prove

Measured with `python tools/load_test.py USERS ROUNDS [pdf]`: N real Chromium sessions against one real Streamlit
server, each reading the sample CV and visiting every page in random order. Date: 2026-10-12.

**Conditions (read these before quoting any number):** a 4-core sandbox with 16 GB, the browsers and the server on the
**same machine** (so the numbers are pessimistic for the server and say nothing about network distance), no AI calls
(AI latency is the provider's and was not measured), basic CV reader. This is **not** Streamlit Community Cloud, whose
free tier has less CPU and memory and sleeps idle apps; its cold start (the first visit after the app slept) is not
covered here.

| Simultaneous users | Page change, median | Page change, slowest | Build PDF+Word+text+HTML (median) | Portfolio build (median) | Blank pages | Console / server errors |
|---|---|---|---|---|---|---|
| 1 | 0.2-0.6 s | 1.0 s | 1.5 s | 0.3 s | 0 | 0 |
| 10 | ~1.1 s | 3.0 s | 5.7 s | 1.2 s | 0 | 0 |
| 20 | n/a | n/a | 9.2 s | 3.2 s | 0 | 0 |
| 30 | ~5 s | 8.6 s | n/a | n/a | 0 | 0 |

* "Blank" means: after a page's title appeared, the main area still held almost no text 8 seconds later.
* Server memory: about 60 MB when idle, about 200-250 MB with 20-30 sessions open (roughly 7 MB per session) and it did
  not fall back after the sessions closed within 40 seconds.
* Streamlit runs one Python process, so the work of many users shares one core: latency grows with the number of users
  doing something at the same moment, and PDF building (CPU-bound) grows fastest.

## Blank or stale boxes found and fixed while testing

These looked like "the UI went blank" because a box showed nothing while the app already held the value:

1. **Job-posting box stayed empty** after loading a posting from a file or a link (the app knew the text: the detected
   title appeared, the box did not). The value was cleared after the box had been drawn. Fixed by assigning it before
   the box is drawn in the next run.
2. **Loading a saved search left the old text in the boxes** for the same reason (fixed with a button callback).
3. **A saved search did not appear in the list** until the next click (fixed).
4. A stray `None` printed under the Jobs page (Streamlit prints a bare `a() if x else b()` statement). A test now scans
   every UI module for such statements.

Each has a real-browser test that fails without the fix.

## Not reproduced

* A sidebar that stays open and covers the page on a phone appeared in a desktop browser narrowed to 390 px, but not in
  mobile emulation (touch + phone user agent), where Streamlit closes it after navigation. Real phones were not tested.
* Occasional `404` console messages under 20 simultaneous PDF builds appeared once and did not repeat; the cause is
  unknown.

## Reproduce

    pip install -r requirements-dev.txt && playwright install chromium
    python tools/load_test.py 10 2        # 10 users, 2 rounds of every page
    python tools/load_test.py 10 1 pdf    # 10 users building the CV files and portfolio
