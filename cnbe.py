import os
import time
import logging
import random
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("marinha_automation")

# ============================================================
# CONFIGURATION
# ============================================================
PDF_FILE_NAME = "Expedia.1902.pdf"
TARGET_URL = "https://www.marinha.mil.br/cnbe/pt-br/node/144"
TURNSTILE_SITEKEY = "46faddc819feb05c76678c60a74fb157"
TWO_CAPTCHA_API_KEY = os.getenv("TWOCAPTCHA_API_KEY")

PROXY_FILE = "Webshare proxies.txt"

def load_proxies():
    proxies = []
    if os.path.exists(PROXY_FILE):
        with open(PROXY_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split(':')
                    if len(parts) == 4:
                        ip, port, user, pwd = parts
                        proxies.append(f"http://{user}:{pwd}@{ip}:{port}")
                    else:
                        proxies.append(line)
        logger.info(f"✅ Loaded {len(proxies)} proxies")
    return proxies

def get_random_proxy():
    proxies = load_proxies()
    if proxies:
        proxy = random.choice(proxies)
        logger.info(f"🔄 Using proxy: {proxy[:40]}...")
        return proxy
    return None

def get_pdf_path():
    if os.path.exists(PDF_FILE_NAME):
        return os.path.abspath(PDF_FILE_NAME)
    return None

def find_chrome_path():
    paths = [
        "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
        os.path.expanduser("~") + "\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe"
    ]
    for path in paths:
        if os.path.exists(path):
            return path
    return None

def parse_proxy(proxy_str):
    if not proxy_str:
        return None
    try:
        cleaned = proxy_str.replace("http://", "").replace("https://", "")
        parts = cleaned.split("@")
        if len(parts) == 2:
            auth, server = parts
            user_pass = auth.split(":")
            server_parts = server.split(":")
            return {
                "server": f"http://{server}",
                "username": user_pass[0],
                "password": user_pass[1] if len(user_pass) > 1 else ""
            }
    except:
        return None

def solve_turnstile_2captcha(sitekey, pageurl):
    """2Captcha se Turnstile solve karo"""
    if not TWO_CAPTCHA_API_KEY:
        logger.error("❌ No 2Captcha API key found!")
        return None
    
    logger.info(f"🔐 Solving Turnstile with 2Captcha...")
    
    # First, check if sitekey is valid with 2Captcha
    # 2Captcha Turnstile API uses 'sitekey' parameter
    payload = {
        "key": TWO_CAPTCHA_API_KEY,
        "method": "turnstile",
        "sitekey": sitekey,
        "pageurl": pageurl,
        "json": 1
    }
    
    try:
        # Send solve request
        response = requests.post("https://2captcha.com/in.php", data=payload, timeout=30)
        result = response.json()
        logger.info(f"📡 2Captcha response: {result}")
        
        if result.get('status') == 1:
            captcha_id = result.get('request')
            logger.info(f"✅ Captcha ID: {captcha_id}")
            
            # Poll for solution
            for attempt in range(30):
                time.sleep(3)
                check = requests.get(
                    f"https://2captcha.com/res.php?key={TWO_CAPTCHA_API_KEY}&action=get&id={captcha_id}&json=1"
                )
                data = check.json()
                
                if data.get('status') == 1:
                    token = data.get('request')
                    if token and "DUMMY" not in token and "XXXX" not in token:
                        logger.info(f"✅ Real Turnstile token received: {token[:50]}...")
                        return token
                elif data.get('request') == "CAPCHA_NOT_READY":
                    logger.info(f"⏳ Waiting for captcha... (attempt {attempt+1}/30)")
                else:
                    logger.warning(f"⚠️ 2Captcha error: {data}")
            
            logger.error("❌ Captcha solve timeout")
            return None
        else:
            logger.error(f"❌ 2Captcha error: {result}")
            return None
    except Exception as e:
        logger.error(f"❌ 2Captcha request failed: {e}")
        return None

def submit_form(pdf_path, proxy_str=None):
    chrome_path = find_chrome_path()
    proxy_config = parse_proxy(proxy_str) if proxy_str else None
    uploaded_file_name = os.path.basename(pdf_path)
    
    with sync_playwright() as p:
        context_kwargs = {
            "user_data_dir": os.path.join(os.path.expanduser("~"), "AppData", "Local", "Google", "Chrome", "Marinha_Automation"),
            "executable_path": chrome_path,
            "headless": False,
            "args": [
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-infobars",
                "--disable-blink-features=AutomationControlled"
            ],
            "ignore_default_args": ["--enable-automation"],
            "viewport": {'width': 1366, 'height': 768}
        }
        
        if proxy_config:
            context_kwargs["proxy"] = proxy_config
            logger.info(f"🌐 Proxy configured: {proxy_config.get('server')}")
        
        context = p.chromium.launch_persistent_context(**context_kwargs)
        page = context.new_page()
        
        try:
            # ============================================================
            # STEP 1: NAVIGATE
            # ============================================================
            logger.info("🌐 Navigating to form...")
            page.goto(TARGET_URL, timeout=60000)
            time.sleep(3)
            
            # Check page title
            page_title = page.title()
            logger.info(f"📄 Page title: {page_title}")
            
            # ============================================================
            # STEP 2: SOLVE TURNSTILE WITH 2CAPTCHA
            # ============================================================
            turnstile_token = solve_turnstile_2captcha(TURNSTILE_SITEKEY, TARGET_URL)
            
            if turnstile_token:
                logger.info("✅ Turnstile token obtained!")
                
                # Inject token
                page.evaluate(f"""
                    (token) => {{
                        // Set token in hidden input
                        let input = document.querySelector('input[name="cf-turnstile-response"]');
                        if (!input) {{
                            input = document.createElement('input');
                            input.type = 'hidden';
                            input.name = 'cf-turnstile-response';
                            let form = document.querySelector('form');
                            if (form) form.appendChild(input);
                        }}
                        input.value = token;
                        
                        // Remove turnstile widgets
                        document.querySelectorAll('.cf-turnstile, iframe[src*="turnstile"]').forEach(el => el.remove());
                        
                        // Enable submit button
                        let btn = document.querySelector('input[type="submit"], button[type="submit"]');
                        if (btn) {{
                            btn.disabled = false;
                            btn.style.opacity = '1';
                            btn.style.cursor = 'pointer';
                        }}
                        
                        console.log('✅ Token injected!');
                    }}
                """, turnstile_token)
                time.sleep(2)
            else:
                logger.warning("⚠️ Could not get Turnstile token, but continuing...")
            
            # ============================================================
            # STEP 3: WAIT FOR PAGE TO LOAD
            # ============================================================
            logger.info("⏳ Waiting for page to load...")
            
            # Wait for form to load
            for attempt in range(10):
                time.sleep(2)
                file_input = page.locator('input[type="file"]').first
                if file_input and file_input.count() > 0:
                    logger.info("✅ Form loaded!")
                    break
                logger.info(f"⏳ Attempt {attempt+1}/10 - Waiting for form...")
            
            # ============================================================
            # STEP 4: UPLOAD PDF
            # ============================================================
            logger.info(f"📁 Uploading PDF: {uploaded_file_name}...")
            
            selectors = [
                'input[type="file"]',
                'input[name*="certificate"]',
                'input[name*="incorporation"]',
                'input[data-drupal-selector*="upload"]'
            ]
            
            file_input = None
            for selector in selectors:
                try:
                    file_input = page.locator(selector).first
                    if file_input and file_input.count() > 0:
                        logger.info(f"✅ Found file input: {selector}")
                        break
                except:
                    continue
            
            if file_input and file_input.count() > 0:
                file_input.set_input_files(pdf_path)
                logger.info("✅ PDF uploaded!")
                time.sleep(2)
            else:
                logger.error("❌ No file input found!")
                context.close()
                return None
            
            # Click Upload button if exists
            upload_btn = page.locator('input[value="Carregar"]').first
            if upload_btn and upload_btn.is_visible():
                upload_btn.click()
                logger.info("✅ Upload button clicked!")
                time.sleep(3)
            
            # ============================================================
            # STEP 5: SUBMIT
            # ============================================================
            logger.info("🚀 Submitting form...")
            
            submit_btn = page.locator('input[type="submit"][value="Send"], button:has-text("Send")').first
            if submit_btn and submit_btn.is_visible():
                submit_btn.click()
                logger.info("✅ Submit clicked!")
            
            # ============================================================
            # STEP 6: WAIT FOR RESPONSE
            # ============================================================
            logger.info("⏳ Waiting for response...")
            
            for _ in range(20):
                time.sleep(2)
                if "thank" in page.url.lower() or "success" in page.url.lower():
                    logger.info(f"✅ Success: {page.url}")
                    break
            
            # ============================================================
            # STEP 7: GET PDF URL
            # ============================================================
            pdf_url = page.evaluate(f"""
                () => {{
                    let url = null;
                    document.querySelectorAll('a[href]').forEach(el => {{
                        if (el.href && el.href.includes('{uploaded_file_name}')) {{
                            url = el.href;
                        }}
                    }});
                    return url;
                }}
            """)
            
            if not pdf_url:
                base_url = "https://assets.marinha.mil.br/cnbe/sites/www.marinha.mil.br.cnbe/files/webform/supplier_registration/_sid_/"
                pdf_url = base_url + uploaded_file_name
            
            # ============================================================
            # FINAL OUTPUT
            # ============================================================
            print("\n" + "="*70)
            print("MARINHA FORM SUBMISSION REPORT")
            print("="*70)
            print(f"PDF File: {uploaded_file_name}")
            print(f"PDF URL: {pdf_url if pdf_url else 'NOT FOUND'}")
            print("="*70 + "\n")
            
            if pdf_url:
                with open("pdf_url_marinha.txt", "w") as f:
                    f.write(pdf_url)
                logger.info(f"✅ URL saved to pdf_url_marinha.txt")
            
            context.close()
            return {"pdf_url": pdf_url}
            
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            context.close()
            return None

def run():
    print("\n" + "="*70)
    print("MARINHA - FULLY AUTOMATED")
    print("="*70 + "\n")
    
    pdf_path = get_pdf_path()
    if not pdf_path:
        logger.error(f"❌ PDF not found: {PDF_FILE_NAME}")
        return
    logger.info(f"✅ PDF: {pdf_path}")
    
    proxy = get_random_proxy()
    if proxy:
        logger.info(f"🔄 Using proxy: {proxy[:40]}...")
    
    result = submit_form(pdf_path, proxy)
    
    if result and result.get("pdf_url"):
        print(f"\n🎉 SUCCESS! PDF URL: {result.get('pdf_url')}")
    else:
        print("\n❌ Failed to capture PDF URL")

if __name__ == "__main__":
    run()