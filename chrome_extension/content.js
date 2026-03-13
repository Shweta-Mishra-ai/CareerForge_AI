// This script runs in the context of the LinkedIn page
function extractLinkedInData() {
  // Helper to safely get text content
  const getText = (selector) => {
    const el = document.querySelector(selector);
    return el ? el.innerText.trim() : "";
  };

  // Helper to get array of text from multiple elements
  const getTextArray = (selector) => {
    const els = document.querySelectorAll(selector);
    return Array.from(els).map(el => el.innerText.trim()).filter(text => text.length > 0);
  };

  const profileData = {
    source: "CareerForge AI LinkedIn Extractor",
    timestamp: new Date().toISOString(),
    extractedData: {
      name: getText('h1.text-heading-xlarge'),
      headline: getText('div.text-body-medium.break-words'),
      location: getText('span.text-body-small.inline.t-black--light.break-words'),
      about: getText('div[id="about"] ~ div.display-flex .visually-hidden') || getText('div#about ~ div .pv-shared-text-with-see-more'),
    }
  };

  // 1. Try to grab the Experience section text block entirely
  // LinkedIn DOM changes frequently, so grabbing the full text block under standard headers is safer than querying nested elements
  
  const sections = document.querySelectorAll('section');
  
  sections.forEach(section => {
    const sectionTitle = section.querySelector('h2.pvs-header__title span[aria-hidden="true"]');
    if (!sectionTitle) return;
    
    const titleText = sectionTitle.innerText.trim().toLowerCase();
    
    if (titleText.includes("experience")) {
      profileData.extractedData.experience_raw = section.innerText;
    } else if (titleText.includes("education")) {
      profileData.extractedData.education_raw = section.innerText;
    } else if (titleText.includes("skills")) {
      profileData.extractedData.skills_raw = section.innerText;
    } else if (titleText.includes("licenses") || titleText.includes("certifications")) {
      profileData.extractedData.certificates_raw = section.innerText;
    }
  });

  // Fallback: If the structured section finder fails, just grab the main container text
  if (!profileData.extractedData.experience_raw) {
    const mainNode = document.querySelector('main.scaffold-layout__main');
    if (mainNode) {
      profileData.extractedData.full_page_fallback = mainNode.innerText;
    }
  }

  // Format as a clear string for the AI parser
  const finalString = `
[LINKEDIN PROFILE VERIFIED EXTRACT]
Name: ${profileData.extractedData.name}
Headline: ${profileData.extractedData.headline}
Location: ${profileData.extractedData.location}

ABOUT:
${profileData.extractedData.about}

EXPERIENCE:
${profileData.extractedData.experience_raw || 'Not found'}

EDUCATION:
${profileData.extractedData.education_raw || 'Not found'}

SKILLS:
${profileData.extractedData.skills_raw || 'Not found'}

CERTIFICATES:
${profileData.extractedData.certificates_raw || 'Not found'}

(Fallback Text if sections missing):
${profileData.extractedData.full_page_fallback ? profileData.extractedData.full_page_fallback.substring(0, 3000) : 'None'}
`;

  // Copy to clipboard
  const copyToClipboard = async (text) => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        // Legacy fallback
        const textArea = document.createElement("textarea");
        textArea.value = text;
        textArea.style.position = "fixed";
        textArea.style.left = "-999999px";
        textArea.style.top = "-999999px";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        try {
          document.execCommand('copy');
        } catch (err) {
          console.error('Fallback copy failed', err);
        }
        textArea.remove();
      }
    } catch (err) {
      console.error('Failed to copy!', err);
    }
  };

  copyToClipboard(finalString);
  console.log("CareerForge AI: LinkedIn Data Extracted and Copied to Clipboard!");
}

extractLinkedInData();
