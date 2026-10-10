/* CareerForge AI extension - pure helpers (no clipboard, no chrome.* APIs) so they can be unit-tested in a browser.
 *
 * Reads only what the signed-in user can already see on THEIR OWN open LinkedIn profile tab, on demand, after they
 * click the extension. LinkedIn's page structure changes often: when a section cannot be found we fall back to the
 * main text of the page, and the extension says so instead of pretending the extract is complete.
 */
(function (root) {
  "use strict";

  /** True only for https://[www.]linkedin.com/in/<handle>... - parsed, not substring-matched. */
  function isLinkedInProfileUrl(raw) {
    let u;
    try { u = new URL(raw); } catch (e) { return false; }
    if (u.protocol !== "https:") return false;
    const host = u.hostname.toLowerCase();
    if (host !== "linkedin.com" && !host.endsWith(".linkedin.com")) return false;
    return /^\/in\/[^/]+/.test(u.pathname);
  }

  const NOISE = /^(show all \d+.*|…?\s*see more|see less|show more|show less|endorse|endorsed by.*|show credential|follow|connect|message|more|\d+ endorsements?|\d+ mutual connections?)$/i;

  function dedupeDoubled(line) {
    const m = line.match(/^(.{3,}?)\s*\1$/);
    return m ? m[1] : line;
  }

  /** LinkedIn renders each text twice (visible + screen-reader copy), and adds UI chrome. Clean both. */
  function cleanLines(text) {
    const out = [];
    for (const raw of String(text || "").split("\n")) {
      const line = raw.replace(/\s+/g, " ").trim();
      if (!line) continue;
      // adjacent inline spans (visible + screen-reader copy) concatenate into "TextText" on one line
      const clean = dedupeDoubled(line.replace(/\s*…?\s*see (?:more|less)\s*$/i, ""));
      if (NOISE.test(clean)) continue;
      if (out.length && out[out.length - 1] === clean) continue;
      out.push(clean);
    }
    return out.join("\n");
  }

  function textOf(el) { return el ? (el.innerText || el.textContent || "").trim() : ""; }

  function sectionTitle(section) {
    // Priority order matters: a comma-separated selector would return the <h2> itself (document order),
    // whose text contains BOTH the visible and the screen-reader copy.
    const selectors = ['h2.pvs-header__title span[aria-hidden="true"]', 'h2 span[aria-hidden="true"]', "h2"];
    for (const sel of selectors) {
      const el = section.querySelector(sel);
      if (el) return dedupeDoubled(textOf(el).replace(/\s+/g, " ")).toLowerCase();
    }
    return "";
  }

  /** Returns { text, complete, missing[] } for the page in `doc`. */
  function extractProfileText(doc) {
    const name = textOf(doc.querySelector("h1"));
    const headline = textOf(doc.querySelector("div.text-body-medium.break-words"));
    const location = textOf(doc.querySelector("span.text-body-small.inline.t-black--light.break-words"));
    const wanted = { about: "ABOUT", experience: "EXPERIENCE", education: "EDUCATION", skills: "SKILLS",
                     licenses: "CERTIFICATIONS", certifications: "CERTIFICATIONS" };
    const found = {};
    doc.querySelectorAll("section").forEach(function (section) {
      const title = sectionTitle(section);
      for (const key of Object.keys(wanted)) {
        if (title.indexOf(key) !== -1 && !found[wanted[key]]) {
          const lines = cleanLines(textOf(section)).split("\n");
          if (lines.length && lines[0].toLowerCase() === title) lines.shift(); // the heading repeats the label
          found[wanted[key]] = lines.join("\n");
        }
      }
    });

    const missing = ["EXPERIENCE", "EDUCATION", "SKILLS"].filter(function (k) { return !found[k]; });
    const parts = ["[LinkedIn profile text copied from the page by the CareerForge AI extension]"];
    if (name) parts.push("Name: " + name);
    if (headline) parts.push("Headline: " + headline);
    if (location) parts.push("Location: " + location);
    for (const label of ["ABOUT", "EXPERIENCE", "EDUCATION", "SKILLS", "CERTIFICATIONS"]) {
      if (found[label]) parts.push("\n" + label + ":\n" + found[label]);
    }
    if (missing.length === 3) {
      // No recognisable sections: LinkedIn changed its markup. Give the page's main text, clearly labelled.
      const main = doc.querySelector("main") || doc.body;
      const fallback = cleanLines(textOf(main)).slice(0, 12000);
      if (fallback) parts.push("\nPAGE TEXT (sections could not be identified):\n" + fallback);
    }
    return { text: parts.join("\n"), complete: missing.length === 0, missing: missing };
  }

  const api = { isLinkedInProfileUrl: isLinkedInProfileUrl, extractProfileText: extractProfileText, cleanLines: cleanLines };
  root.CareerForge = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
