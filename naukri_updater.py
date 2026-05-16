import os
import time
import logging
import sys
import io
import json
import re
import threading
import urllib.request
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import schedule
from flask import Flask, send_file, render_template_string
from playwright.sync_api import sync_playwright

load_dotenv()

log_buffer = io.StringIO()
handler = logging.StreamHandler(log_buffer)
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), handler],
)
log = logging.getLogger(__name__)

EMAIL = os.getenv("NAUKRI_EMAIL")
PASSWORD = os.getenv("NAUKRI_PASSWORD")
if not EMAIL or not PASSWORD:
    log.error("NAUKRI_EMAIL and NAUKRI_PASSWORD must be set as environment variables")
    sys.exit(1)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PORT = int(os.getenv("PORT", 8080))

BASE_URL = "https://www.naukri.com"
SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)
last_screenshot = None
last_status = {"success": False, "time": None, "screenshot": None, "error": None}


def send_telegram(message, screenshot_path=None):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        if screenshot_path and os.path.exists(screenshot_path):
            boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
            filename = os.path.basename(screenshot_path)
            with open(screenshot_path, "rb") as f:
                file_bytes = f.read()
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
                f"{TELEGRAM_CHAT_ID}\r\n"
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="caption"\r\n\r\n'
                f"{message}\r\n"
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="photo"; filename="{filename}"\r\n'
                f"Content-Type: image/png\r\n\r\n"
            ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
        else:
            data = json.dumps({
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
            }).encode()
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                data=data,
                headers={"Content-Type": "application/json"},
            )
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        log.warning(f"Telegram send failed: {e}")


def try_click_login(page):
    strategies = [
        ("role link with Login", lambda: page.get_by_role("link", name=re.compile("login", re.IGNORECASE)).first),
        ("role button with Login", lambda: page.get_by_role("button", name=re.compile("login", re.IGNORECASE)).first),
        ("text Login", lambda: page.get_by_text(re.compile("login", re.IGNORECASE)).first),
        ("any element with text Login", lambda: page.locator("//*[contains(translate(text(),'LOGIN','login'),'login')]").first),
        ("a with href login", lambda: page.locator("a[href*='login' i]").first),
        ("any with href login", lambda: page.locator("[href*='login' i]").first),
        ("class contains login", lambda: page.locator("[class*='login' i]").first),
        ("id contains login", lambda: page.locator("[id*='login' i]").first),
        ("data-* contains login", lambda: page.locator("[data-*='login' i]").first),
        ("Sign In text", lambda: page.get_by_text(re.compile("sign.in", re.IGNORECASE)).first),
        ("Log In text", lambda: page.get_by_text(re.compile("log.in", re.IGNORECASE)).first),
        ("header link 1", lambda: page.locator("header a").first),
        ("any a in top section", lambda: page.locator("div[class*='header'] a, nav a, div[class*='top'] a").first),
    ]
    for name, fn in strategies:
        try:
            el = fn()
            if el.is_visible(timeout=3000):
                log.info(f"Found login element via: {name}")
                el.click()
                return True
        except Exception:
            continue
    return False


def try_fill_login_form(page):
    strategies = [
        ("input type email", "//input[@type='email']"),
        ("input type text", "//input[@type='text']"),
        ("input placeholder email", "//input[contains(translate(@placeholder,'EMAIL','email'),'email')]"),
        ("input placeholder username", "//input[contains(translate(@placeholder,'USERNAME','username'),'username')]"),
        ("input name username", "//input[contains(@name, 'username')]"),
        ("input name email", "//input[contains(@name, 'email')]"),
        ("input id email", "//input[contains(@id, 'email')]"),
        ("first text input", "(//input[@type='text'])[1]"),
    ]
    email_el = None
    for name, xpath in strategies:
        try:
            el = page.locator(xpath).first
            if el.is_visible(timeout=2000):
                log.info(f"Found email field via: {name}")
                el.fill(EMAIL)
                email_el = el
                break
        except Exception:
            continue
    if not email_el:
        return False

    pw_strategies = [
        ("input type password", "//input[@type='password']"),
        ("input placeholder password", "//input[contains(translate(@placeholder,'PASSWORD','password'),'password')]"),
        ("input name password", "//input[contains(@name, 'password')]"),
        ("input id password", "//input[contains(@id, 'password')]"),
    ]
    for name, xpath in pw_strategies:
        try:
            el = page.locator(xpath).first
            if el.is_visible(timeout=2000):
                log.info(f"Found password field via: {name}")
                el.fill(PASSWORD)
                break
        except Exception:
            continue

    submit_strategies = [
        ("button type submit", "//button[@type='submit']"),
        ("submit button text", "//button[contains(translate(text(),'LOGIN','login'),'login')]"),
        ("submit input type", "//input[@type='submit']"),
        ("any submit", "//*[@type='submit']"),
    ]
    for name, xpath in submit_strategies:
        try:
            el = page.locator(xpath).first
            if el.is_visible(timeout=2000):
                log.info(f"Found submit via: {name}")
                el.click()
                return True
        except Exception:
            continue
    return False


def playwright_update():
    global last_screenshot, last_status
    log.info("=" * 50)
    log.info("Starting Naukri profile update...")
    start = time.time()
    ss_path = None
    page = None

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--single-process",
                    "--no-zygote",
                ],
            )
            page = browser.new_page(viewport={"width": 1920, "height": 1080})

            log.info("Navigating to naukri.com...")
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)

            diagnostic_ss = str(SCREENSHOTS_DIR / "diagnostic.png")
            page.screenshot(path=diagnostic_ss, full_page=False)
            title = page.title()
            log.info(f"Page title: {title}")
            send_telegram(f"Naukri page loaded\nTitle: {title}\nURL: {page.url}", diagnostic_ss)

            logged_in = False
            profile_indicators = [
                "a[href*='profile' i]",
                "a[href*='myaccount' i]",
                "[class*='userName' i]",
                "[class*='profile' i]",
                "[class*='avatar' i]",
                "img[alt*='profile' i]",
            ]
            for sel in profile_indicators:
                try:
                    if page.locator(sel).first.is_visible(timeout=2000):
                        logged_in = True
                        log.info(f"Already logged in (found: {sel})")
                        break
                except Exception:
                    continue

            if not logged_in:
                log.info("Clicking login button...")
                clicked = try_click_login(page)
                if not clicked:
                    log.warning("Login button not found on homepage, trying direct pages...")
                    login_urls = [
                        "https://www.naukri.com/nlogin/login",
                        "https://login.naukri.com",
                        "https://www.naukri.com/login",
                        "https://www.naukri.com/mnjuser/homepage",
                    ]
                    for url in login_urls:
                        try:
                            page.goto(url, wait_until="domcontentloaded", timeout=15000)
                            time.sleep(3)
                            if try_fill_login_form(page):
                                clicked = True
                                log.info(f"Login form found on: {url}")
                                break
                        except Exception:
                            continue

                if not clicked:
                    raise RuntimeError("Could not find login button or form")

                time.sleep(2)
                filled = try_fill_login_form(page)
                if not filled:
                    raise RuntimeError("Could not find email/password fields")

                log.info("Waiting for login to complete...")
                time.sleep(5)
                try:
                    page.wait_for_url(re.compile(r"(naukri\.com/?$|mnjuser|homepage)"), timeout=15000)
                except Exception:
                    pass
                log.info(f"Post-login URL: {page.url}")

            log.info("Navigating to profile page...")
            page.goto(f"{BASE_URL}/mnjuser/profile", wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)

            log.info("Looking for edit button...")
            edit_strategies = [
                ("img edit icon", "//img[contains(@src, 'edit') or contains(@class, 'edit')]"),
                ("span edit icon", "//span[contains(@class, 'edit')]"),
                ("i edit icon", "//i[contains(@class, 'edit')]"),
                ("button edit", "//button[contains(text(), 'Edit')]"),
                ("a edit", "//a[contains(text(), 'Edit')]"),
                ("first img in profile section", "(//div[contains(@class, 'profile') or contains(@class, 'section')]//img)[1]"),
            ]
            edit_found = False
            for name, xpath in edit_strategies:
                try:
                    el = page.locator(xpath).first
                    if el.is_visible(timeout=3000):
                        el.click()
                        log.info(f"Clicked edit via: {name}")
                        edit_found = True
                        break
                except Exception:
                    continue
            if not edit_found:
                log.warning("Edit button not found, trying to scroll to bottom of profile")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1)
            time.sleep(2)

            log.info("Looking for textarea...")
            ta_strategies = [
                ("textarea", "//textarea"),
                ("rich text editor", "//div[@contenteditable='true']"),
                ("profile summary field", "//*[contains(@id, 'summary') or contains(@class, 'summary') or contains(@name, 'summary')]"),
            ]
            textarea = None
            for name, xpath in ta_strategies:
                try:
                    el = page.locator(xpath).first
                    if el.is_visible(timeout=3000):
                        textarea = el
                        log.info(f"Found text field via: {name}")
                        break
                except Exception:
                    continue

            if textarea:
                current = textarea.input_value() or ""
                if current.endswith(" "):
                    textarea.fill(current.rstrip())
                    log.info("Removed trailing space")
                else:
                    textarea.fill(current + " ")
                    log.info("Added trailing space")
                time.sleep(1)

            log.info("Looking for save button...")
            save_strategies = [
                ("button Save text", "//button[contains(translate(text(),'SAVE','save'),'save')]"),
                ("button type submit", "//button[@type='submit']"),
                ("button save id", "//button[contains(@id, 'save')]"),
                ("any save", "//*[contains(@type, 'submit')]"),
            ]
            for name, xpath in save_strategies:
                try:
                    el = page.locator(xpath).first
                    if el.is_visible(timeout=3000):
                        el.click()
                        log.info(f"Clicked save via: {name}")
                        break
                except Exception:
                    continue

            time.sleep(4)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ss_path = str(SCREENSHOTS_DIR / f"profile_{timestamp}.png")
            page.screenshot(path=ss_path, full_page=True)
            browser.close()

        last_screenshot = ss_path
        last_status = {
            "success": True,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "screenshot": Path(ss_path).name,
            "error": None,
        }
        elapsed = time.time() - start
        msg = f"<b>Naukri Profile Updated</b>\nTime: {elapsed:.0f}s\nDate: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        log.info(f"Naukri profile updated successfully ({elapsed:.0f}s)")
        send_telegram(msg, ss_path)

    except Exception as e:
        elapsed = time.time() - start
        debug_ss = None
        if page:
            try:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                debug_ss = str(SCREENSHOTS_DIR / f"debug_{ts}.png")
                page.screenshot(path=debug_ss, full_page=True)
            except Exception:
                pass
        last_status = {
            "success": False,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "screenshot": Path(debug_ss).name if debug_ss else None,
            "error": str(e),
        }
        msg = f"<b>Naukri Update Failed</b>\nError: {str(e)[:300]}\nTime: {elapsed:.0f}s"
        log.error(f"Naukri update failed after {elapsed:.0f}s: {e}")
        send_telegram(msg, debug_ss)

    log.info("=" * 50)


LAST_HTML = """<!DOCTYPE html>
<html><head><title>Naukri Auto Update</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font-family:Arial;max-width:800px;margin:40px auto;padding:0 20px;background:#f5f5f5}
.card{background:#fff;border-radius:8px;padding:20px;margin:20px 0;box-shadow:0 2px 4px rgba(0,0,0,0.1)}
.success{color:#28a745;font-weight:bold;font-size:18px}
.fail{color:#dc3545;font-weight:bold;font-size:18px}
img{max-width:100%;border:1px solid #ddd;border-radius:4px}
pre{background:#1e1e1e;color:#d4d4d4;padding:15px;border-radius:4px;overflow-x:auto;font-size:13px}
.error{color:#dc3545}
a{color:#007bff}
</style></head><body>
<h1>Naukri Auto Update</h1>
<div class="card">
  <p class="{{'success' if last_status.success else 'fail'}}">
    {{'SUCCESS' if last_status.success else ('FAILED' if last_status.time else 'NO UPDATE YET')}}
  </p>
  <p><strong>Last run:</strong> {{last_status.time or 'Never'}}</p>
  {% if last_status.error %}<p class="error"><strong>Error:</strong> {{last_status.error}}</p>{% endif %}
</div>
{% if last_status.screenshot %}
<div class="card">
  <h3>Last Screenshot</h3>
  <p><em>{{last_status.time}}</em></p>
  <img src="/screenshot/{{last_status.screenshot}}" alt="Screenshot">
</div>
{% endif %}
<div class="card">
  <a href="/start">Run Update Now</a> &nbsp;|&nbsp; <a href="/log">View Full Log</a>
</div></body></html>"""

app = Flask(__name__)


@app.route("/")
def index():
    return render_template_string(LAST_HTML, last_status=last_status)


@app.route("/laststatus")
def laststatus():
    return render_template_string(LAST_HTML, last_status=last_status)


@app.route("/start")
def start_now():
    threading.Thread(target=playwright_update, daemon=True).start()
    return "<p>Update started. Check <a href='/log'>/log</a> for progress.</p>"


@app.route("/log")
def get_log():
    content = log_buffer.getvalue()
    return f"<pre>{content}</pre>", 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/screenshot/<name>")
def screenshot(name):
    path = SCREENSHOTS_DIR / name
    if path.exists():
        return send_file(str(path), mimetype="image/png")
    return "Not found", 404


def start_scheduler():
    schedule.every().day.at("08:00").do(playwright_update)
    schedule.every().day.at("17:00").do(playwright_update)
    log.info("Scheduler set: 08:00 and 17:00 daily")
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    log.info("Starting Naukri updater web service...")
    playwright_update()
    t = threading.Thread(target=start_scheduler, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=PORT)
