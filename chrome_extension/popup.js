document.getElementById('extractBtn').addEventListener('click', async () => {
  let [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

  if (tab.url.includes("linkedin.com/in/")) {
    chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ['content.js']
    }, () => {
      // Show success message briefly
      const statusElement = document.getElementById('status');
      statusElement.style.display = 'block';
      setTimeout(() => {
        statusElement.style.display = 'none';
      }, 3000);
    });
  } else {
    alert("Please navigate to a LinkedIn Profile page (linkedin.com/in/...) first.");
  }
});
