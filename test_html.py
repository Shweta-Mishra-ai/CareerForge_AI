import requests

url = "https://www.linkedin.com/in/shweta-mishra-ai/" # User's actual URL from github
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": "\"Not_A Brand\";v=\"8\", \"Chromium\";v=\"120\", \"Google Chrome\";v=\"120\"",
}
try:
    response = requests.get(url, headers=headers, timeout=10)
    html_str = response.text
    
    with open("test.html", "w", encoding="utf-8") as f:
        f.write(html_str)
        
    print("Saved HTML size:", len(html_str))
    
    # Check if the page is an authwall or a real profile
    if "authwall" in response.url:
        print("Redirected to Authwall:", response.url)
    elif "experience" in html_str.lower() or "education" in html_str.lower():
        print("Found keywords 'experience' or 'education' in the raw HTML!")
    else:
        print("Did not find experience/education keywords...")
        
except Exception as e:
    print("Error:", e)
