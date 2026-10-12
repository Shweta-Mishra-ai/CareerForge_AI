"""Load and latency test: N simultaneous real browser sessions against a real Streamlit server.

    python tools/load_test.py USERS ROUNDS [pdf]

Each user opens the app, reads the sample CV and visits every page ROUNDS times in random order (with the word "pdf"
as the third argument, each user builds the CV files and the portfolio once instead). Reports per-page latency, any
page whose content stays blank, browser console errors, server-side tracebacks and the server's memory. Needs the dev
requirements and Chromium (playwright install chromium). The browsers run on the same machine as the server, so the
numbers are pessimistic.
"""
# ruff: noqa: E402, E741, B007, F841

import asyncio
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "tests"), str(ROOT)]
from e2e_fixtures import CV, JD
from e2e_support import AppServer, chromium_path
from playwright.async_api import async_playwright

N = int(sys.argv[1])
ROUNDS = int(sys.argv[2])
PAGES = [
    "Review & edit",
    "ATS check",
    "Tailor to a job",
    "Insights",
    "CV & portfolio",
    "LinkedIn profile",
    "Letters & interviews",
    "Jobs & tracker",
    "Settings",
    "How it works",
]
lat = {}
blanks = []
errors = []


async def title_visible(page, title, timeout=30000):
    t = time.time()
    await page.get_by_role("heading", name=title, exact=True).first.wait_for(state="visible", timeout=timeout)
    return time.time() - t


async def user(i, browser, url):
    ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
    page = await ctx.new_page()
    page.on("pageerror", lambda e: errors.append(f"u{i} pageerror {e}"))
    page.on(
        "console",
        lambda m: (
            errors.append(f"u{i} console {m.text[:120]}")
            if m.type == "error" and "favicon" not in m.text and "40" not in m.text[:60]
            else None
        ),
    )
    page.on(
        "response", lambda r: errors.append(f"404 {r.url.split('127.0.0.1')[-1][:90]}") if r.status == 404 else None
    )
    try:
        t = time.time()
        await page.goto(url)
        await title_visible(page, "Start")
        lat.setdefault("open_app", []).append(time.time() - t)
        if await page.get_by_text("Basic (no AI").count():
            await page.get_by_text("Basic (no AI, nothing leaves this app)", exact=True).first.click()
        await page.set_input_files("input[type=file]", str(CV))
        t = time.time()
        await page.get_by_role("button", name="Read this file").first.click()
        await title_visible(page, "Review & edit")
        lat.setdefault("read_cv", []).append(time.time() - t)
        if len(sys.argv) > 3 and sys.argv[3] == "pdf":
            await page.get_by_role("link", name="CV & portfolio").first.click()
            await title_visible(page, "CV & portfolio")
            t = time.time()
            await page.get_by_role("button", name="Build my files").first.click()
            await page.get_by_text("A simple ATS text extractor reads this PDF cleanly").first.wait_for(timeout=120000)
            lat.setdefault("build_pdf_docx_txt_html", []).append(time.time() - t)
            t = time.time()
            await page.get_by_text("Portfolio website", exact=True).first.click()
            await page.get_by_role("button", name="Download site (.zip with deploy guide)").wait_for(timeout=120000)
            lat.setdefault("portfolio_build", []).append(time.time() - t)
        for r in range(0 if (len(sys.argv) > 3 and sys.argv[3] == "pdf") else ROUNDS):
            order = PAGES[:]
            random.shuffle(order)
            for title in order:
                t = time.time()
                try:
                    await page.get_by_role("link", name=title).first.click()
                    await title_visible(page, title)
                    if title in ("ATS check", "Tailor to a job", "Letters & interviews", "Jobs & tracker"):
                        box = page.get_by_role("textbox", name="Job posting (paste the full text)")
                        if await box.count():
                            await box.fill(JD)
                            await box.blur()
                    tb = time.time()
                    n = 0
                    while time.time() - tb < 8:
                        n = await page.evaluate(
                            "document.querySelector('[data-testid=stMain]').innerText.trim().length"
                        )
                        if n >= 60:
                            break
                        await asyncio.sleep(0.1)
                    lat.setdefault("content_after_title", []).append(time.time() - tb)
                    if n < 60:
                        blanks.append((i, title, n))
                    lat.setdefault(title, []).append(time.time() - t)
                except Exception as e:
                    blanks.append((i, title, "TIMEOUT/ERR " + str(e)[:80]))
    except Exception as e:
        blanks.append((i, "setup", str(e)[:150]))
    await ctx.close()


def rss(pid):
    for l in open(f"/proc/{pid}/status"):
        if l.startswith("VmRSS"):
            return int(l.split()[1]) // 1024


async def sampler(pid, out, stop):
    while not stop.is_set():
        out.append(rss(pid))
        await asyncio.sleep(2)


async def main():
    tmp = Path(tempfile.mkdtemp())
    server = AppServer(tmp)
    try:
        async with async_playwright() as p:
            path = chromium_path()
            b = await (p.chromium.launch(executable_path=path) if path else p.chromium.launch())
            t0 = time.time()
            mem = [rss(server.proc.pid)]
            stop = asyncio.Event()
            smp = asyncio.create_task(sampler(server.proc.pid, mem, stop))
            await asyncio.gather(*[user(i, b, server.url) for i in range(N)])
            stop.set()
            await smp
            await asyncio.sleep(40)
            after = rss(server.proc.pid)
            wall = time.time() - t0
            await b.close()
        log = server.log_text()
    finally:
        server.stop()

    def q(v, p):
        v = sorted(v)
        return round(v[min(len(v) - 1, int(len(v) * p))], 2)

    print(f"server RSS MB: start={mem[0]} peak={max(mem)} 40s-after-all-closed={after}")
    print(f"users={N} rounds={ROUNDS} wall={wall:.0f}s")
    for k, v in lat.items():
        print(f"{k:24s} n={len(v):3d} median={statistics.median(v):5.2f} p95={q(v, 0.95):5.2f} max={max(v):5.2f}")
    print("BLANK/ERR:", blanks[:10], len(blanks))
    print("BROWSER ERRORS:", sorted(set(errors))[:10], len(errors))
    bad = [l for l in log.splitlines() if any(w in l for w in ("Traceback", "Error", "Exception"))]
    print("SERVER LOG problems:", len(bad))
    print("\n".join(bad[:8]))


asyncio.run(main())
