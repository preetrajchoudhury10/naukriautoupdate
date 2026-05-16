import os
import time
import logging
import sys
import io
import json
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


LOGIN_BTN = "/html/body/div[1]/div[4]/div[2]/div/a[1]"
EMAIL_INPUT = "/html/body/div[1]/div[4]/div[2]/div/div/div[2]/div/form/div[2]/input"
PASSWORD_INPUT = "/html/body/div[1]/div[4]/div[2]/div/div/div[2]/div/form/div[3]/input"
EDIT_BTN = "/html/body/div[1]/div[1]/div[4]/div/div/div/div[3]/div[2]/div[7]/div/div[1]/div/div/h1/span/img"
EDIT_TEXTAREA = "/html/body/div[4]/div/div/div[2]/form/div[1]/div/div/textarea"
SAVE_BTN = "/html/body/div[4]/div/div/div[2]/form/div[2]/button"


def send_telegram(message, screenshot_path=None):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        if screenshot_path and os.path.exists(screenshot_path):
            import http.client
            import mimetypes
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


def playwright_update():
    global last_screenshot, last_status
    log.info("=" * 50)
    log.info("Starting Naukri profile update...")
    start = time.time()
    ss_path = None

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
            page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
            time.sleep(2)

            log.info("Clicking login button...")
            page.locator(f"xpath={LOGIN_BTN}").first.click(timeout=15000)
            time.sleep(2)

            log.info("Entering email...")
            page.locator(f"xpath={EMAIL_INPUT}").first.fill(EMAIL, timeout=15000)

            log.info("Entering password...")
            page.locator(f"xpath={PASSWORD_INPUT}").first.fill(PASSWORD, timeout=15000)

            log.info("Submitting login...")
            page.locator("button[type='submit']").first.click(timeout=15000)
            time.sleep(5)
            page.wait_for_load_state("networkidle", timeout=20000)
            log.info("Login successful")

            log.info("Navigating to profile page...")
            page.goto(f"{BASE_URL}/mnjuser/profile", wait_until="networkidle", timeout=30000)
            time.sleep(3)

            log.info("Clicking edit button...")
            page.locator(f"xpath={EDIT_BTN}").first.click(timeout=15000)
            time.sleep(2)

            log.info("Toggling summary whitespace...")
            summary = page.locator(f"xpath={EDIT_TEXTAREA}").first
            summary.wait_for(state="visible", timeout=15000)
            current = summary.input_value() or ""
            if current.endswith(" "):
                summary.fill(current.rstrip())
                log.info("Removed trailing space")
            else:
                summary.fill(current + " ")
                log.info("Added trailing space")
            time.sleep(1)

            log.info("Saving...")
            page.locator(f"xpath={SAVE_BTN}").first.click(timeout=15000)
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
        last_status = {
            "success": False,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "screenshot": None,
            "error": str(e),
        }
        msg = f"<b>Naukri Update Failed</b>\nError: {str(e)[:200]}\nTime: {elapsed:.0f}s"
        log.error(f"Naukri update failed after {elapsed:.0f}s: {e}")
        send_telegram(msg, ss_path if ss_path and os.path.exists(ss_path) else None)

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
