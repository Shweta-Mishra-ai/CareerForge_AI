/* Popup logic. Success is only reported after the text was really read AND really copied. */
const $ = (id) => document.getElementById(id);

function show(kind, message) {
  const el = $("status");
  el.className = kind;
  el.textContent = message;
  el.hidden = false;
}

$("extractBtn").addEventListener("click", async () => {
  $("manual").hidden = true;
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !globalThis.CareerForge.isLinkedInProfileUrl(tab.url || "")) {
      show("error", "Open your own LinkedIn profile (linkedin.com/in/your-name) in this tab first.");
      return;
    }
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["lib.js"] });
    const [injected] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => globalThis.CareerForge.extractProfileText(document),
    });
    const result = injected && injected.result;
    if (!result || !result.text || result.text.length < 80) {
      show("error", "Nothing could be read from this page. Scroll the profile fully, then try again.");
      return;
    }
    try {
      await navigator.clipboard.writeText(result.text);
    } catch (copyError) {
      // Clipboard blocked: never claim success. Offer the text for manual copy instead.
      $("manual").value = result.text;
      $("manual").hidden = false;
      $("manual").select();
      show("warn", "Could not copy automatically. Select the text below and copy it (Ctrl/Cmd+C).");
      return;
    }
    const n = result.text.length.toLocaleString();
    show(result.complete ? "ok" : "warn",
      result.complete
        ? `Copied ${n} characters. Paste them into CareerForge AI.`
        : `Copied ${n} characters, but could not find: ${result.missing.join(", ")}. Check the text before using it.`);
  } catch (e) {
    show("error", "The page could not be read. Reload the profile tab and try again.");
  }
});
