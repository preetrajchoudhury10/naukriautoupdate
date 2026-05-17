import os
import time
import json
import logging
import sys
import ssl
import re
import threading
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import schedule
from flask import Flask, send_file, render_template_string
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PORT = int(os.getenv("PORT", 8080))

accounts = []
i = 1
while True:
    email = os.getenv(f"NAUKRI_EMAIL_{i}") or (os.getenv("NAUKRI_EMAIL") if i == 1 else None)
    password = os.getenv(f"NAUKRI_PASSWORD_{i}") or (os.getenv("NAUKRI_PASSWORD") if i == 1 else None)
    if not email or not password:
        if i == 1:
            log.error("No credentials found. Set NAUKRI_EMAIL_1/NAUKRI_PASSWORD_1 in .env")
            sys.exit(1)
        break
    accounts.append((email.strip(), password.strip()))
    log.info(f"Account {i}: {email[:3]}...{email.split('@')[0][-1]}@{email.split('@')[1]}")
    i += 1

if not accounts:
    sys.exit(1)

log.info(f"Total accounts loaded: {len(accounts)}")

BASE_DIR = Path(__file__).parent
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)
STATUS_FILE = BASE_DIR / "last_status.json"

BASE_URL = "https://www.naukri.com"
LOGIN_BTN_XPATH = "/html/body/div[1]/div[4]/div[2]/div/a[1]"
EMAIL_XPATH = "/html/body/div[1]/div[4]/div[2]/div/div/div[2]/div/form/div[2]/input"
PASSWORD_XPATH = "/html/body/div[1]/div[4]/div[2]/div/div/div[2]/div/form/div[3]/input"
PROFILE_URL = f"{BASE_URL}/mnjuser/profile"
EDIT_BTN_XPATH = "/html/body/div[1]/div[1]/div[4]/div/div/div/div[3]/div[2]/div[7]/div/div[1]/div/div/h1/span/img"
EDIT_TEXTAREA_XPATH = "/html/body/div[4]/div/div/div[2]/form/div[1]/div/div/textarea"
SAVE_BTN_XPATH = "/html/body/div[4]/div/div/div[2]/form/div[2]/button"

RETRIES = 3
last_status = {"success": False, "time": None, "error": None}
log_buffer = []


def save_status(s):
    global last_status
    last_status = s
    STATUS_FILE.write_text(json.dumps(s, indent=2))


def send_telegram(message, screenshot_path=None):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    for attempt in range(3):
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
            urllib.request.urlopen(req, timeout=30, context=ctx)
            return
        except Exception as e:
            if attempt < 2:
                time.sleep(3)
            log.warning(f"Telegram attempt {attempt+1} failed: {e}")


def init_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=options)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def login(driver, email, password):
    log.info("Navigating to naukri.com...")
    driver.get(BASE_URL)
    time.sleep(3)
    log.info("Clicking login button...")
    WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, LOGIN_BTN_XPATH))).click()
    time.sleep(2)
    log.info("Entering email...")
    el = WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, EMAIL_XPATH)))
    el.clear(); el.send_keys(email)
    log.info("Entering password...")
    pw = driver.find_element(By.XPATH, PASSWORD_XPATH)
    pw.clear(); pw.send_keys(password)
    driver.find_element(By.XPATH, "//button[@type='submit']").click()
    time.sleep(5)
    WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.XPATH, "//a[contains(@href, 'profile')]")))
    log.info("Login successful")


def update_profile(driver):
    log.info("Navigating to profile page...")
    driver.get(PROFILE_URL)
    time.sleep(5)
    log.info("Clicking edit button...")
    WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, EDIT_BTN_XPATH))).click()
    time.sleep(2)
    log.info("Toggling summary whitespace...")
    summary = WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.XPATH, EDIT_TEXTAREA_XPATH)))
    current = summary.get_attribute("value") or ""
    if current.endswith(" "):
        summary.clear(); summary.send_keys(current.rstrip())
    else:
        summary.clear(); summary.send_keys(current + " ")
    time.sleep(1)
    log.info("Saving...")
    driver.find_element(By.XPATH, SAVE_BTN_XPATH).click()
    time.sleep(4)


def run_account(email, password, acct_num, total):
    label = f"[{acct_num}/{total}] {email[:3]}...{email.split('@')[0][-1]}@{email.split('@')[1]}"
    log.info(f"{label} - Starting")
    start = time.time()
    ss_path = None

    for attempt in range(1, RETRIES + 1):
        driver = None
        try:
            driver = init_driver()
            login(driver, email, password)
            update_profile(driver)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            ss_path = str(SCREENSHOTS_DIR / f"acct{acct_num}_{ts}.png")
            driver.save_screenshot(ss_path)
            driver.quit()
            elapsed = time.time() - start
            msg = f"<b>Naukri Updated - Account {acct_num}</b>\nEmail: {email}\nTime: {elapsed:.0f}s"
            log.info(f"{label} - Success ({elapsed:.0f}s)")
            send_telegram(msg, ss_path)
            return True
        except Exception as e:
            log.error(f"{label} - Attempt {attempt} failed: {e}")
            if driver:
                try:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    driver.save_screenshot(str(SCREENSHOTS_DIR / f"debug_acct{acct_num}_{ts}.png"))
                except Exception:
                    pass
                try: driver.quit()
                except Exception: pass
            if attempt < RETRIES:
                time.sleep(attempt * 10)

    msg = f"<b>Naukri Failed - Account {acct_num}</b>\nEmail: {email}\nError: {last_error[:200]}"
    send_telegram(msg, ss_path if ss_path and Path(ss_path).exists() else None)
    return False


def run_update():
    log.info("=" * 50)
    log.info(f"Updating {len(accounts)} account(s)")
    overall_start = time.time()
    results = []

    for idx, (email, password) in enumerate(accounts, 1):
        log.info("-" * 40)
        ok = run_account(email, password, idx, len(accounts))
        results.append({"email": email, "success": ok})
        if idx < len(accounts):
            time.sleep(30)

    overall = time.time() - overall_start
    success_count = sum(1 for r in results if r["success"])
    log.info(f"Done: {success_count}/{len(accounts)} ({overall:.0f}s total)")

    summary = f"<b>Naukri Summary</b>\n{success_count}/{len(accounts)} successful"
    for r in results:
        summary += f"\n{'OK' if r['success'] else 'FAIL'} {r['email']}"
    send_telegram(summary)

    s = {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "total": len(accounts),
         "successful": success_count, "results": results}
    save_status(s)
    log.info("=" * 50)


def telegram_bot_loop():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    log.info("Telegram bot listening for commands...")
    offset = 0
    api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    while True:
        try:
            params = urllib.parse.urlencode({"offset": offset, "timeout": 30})
            req = urllib.request.Request(f"{api}/getUpdates?{params}")
            with urllib.request.urlopen(req, timeout=35, context=ctx) as resp:
                data = json.loads(resp.read())

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = (msg.get("text", "") or "").strip().lower()

                if chat_id != str(TELEGRAM_CHAT_ID):
                    continue

                if text == "/manualrun":
                    log.info("Manual run via Telegram")
                    send_telegram("Manual run started...")
                    threading.Thread(target=run_update, daemon=True).start()

                elif text == "/status":
                    s = last_status
                    lines = [f"Last run: {s.get('time', 'Never')}"]
                    if s.get("error"):
                        lines.append(f"Error: {s['error'][:200]}")
                    if s.get("results"):
                        for r in s["results"]:
                            lines.append(f"{'OK' if r['success'] else 'FAIL'} {r['email']}")
                    send_telegram("\n".join(lines))

                elif text in ("/start", "/help"):
                    send_telegram(
                        "Naukri Auto Updater\n"
                        "/manualrun - run update now\n"
                        "/status - last run result"
                    )

        except Exception as e:
            if "timed out" not in str(e).lower():
                log.warning(f"Bot error: {e}")
        time.sleep(3)


LAST_HTML = """<!DOCTYPE html>
<html><head><title>Naukri Auto Update</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font-family:Arial;max-width:800px;margin:40px auto;padding:0 20px;background:#f5f5f5}
.card{background:#fff;border-radius:8px;padding:20px;margin:20px 0;box-shadow:0 2px 4px rgba(0,0,0,0.1)}
.ok{color:#28a745;font-weight:bold;font-size:18px}
.fail{color:#dc3545;font-weight:bold;font-size:18px}
pre{background:#1e1e1e;color:#d4d4d4;padding:15px;border-radius:4px;overflow-x:auto;font-size:13px}
.error{color:#dc3545}
a{color:#007bff}
</style></head><body>
<h1>Naukri Auto Update</h1>
<div class="card">
  <p class="{{'ok' if s.get('successful',0)>0 else 'fail'}}">
    {{s.get('successful',0)}}/{{s.get('total',0)}} OK
  </p>
  <p><strong>Last run:</strong> {{s.get('time','Never')}}</p>
  {% if s.get('results') %}
  <ul>{% for r in s['results'] %}
    <li class="{{'ok' if r.success else 'fail'}}">{{'OK' if r.success else 'FAIL'}} {{r.email}}</li>
  {% endfor %}</ul>
  {% endif %}
</div>
<div class="card">
  <a href="/start">Run Update Now</a>
</div></body></html>"""

app = Flask(__name__)


@app.route("/")
def index():
    s = last_status
    return render_template_string(LAST_HTML, s=s)


@app.route("/laststatus")
def laststatus():
    return json.dumps(last_status, indent=2), 200, {"Content-Type": "application/json"}


@app.route("/start")
def start_now():
    threading.Thread(target=run_update, daemon=True).start()
    return "Update started", 202


if __name__ == "__main__":
    log.info("Starting Naukri updater service...")
    log.info(f"Accounts: {len(accounts)}")
    log.info(f"Flask UI: http://127.0.0.1:{PORT}")
    log.info("Telegram: /manualrun, /status, /help")

    threading.Thread(target=run_update, daemon=True).start()

    def scheduler_loop():
        schedule.every().day.at("08:00").do(lambda: threading.Thread(target=run_update, daemon=True).start())
        schedule.every().day.at("17:00").do(lambda: threading.Thread(target=run_update, daemon=True).start())
        while True:
            schedule.run_pending()
            time.sleep(60)
    threading.Thread(target=scheduler_loop, daemon=True).start()

    threading.Thread(target=telegram_bot_loop, daemon=True).start()

    def flask_runner():
        for port in [PORT, 8081, 8082, 8083]:
            try:
                app.run(host="127.0.0.1", port=port, debug=False)
                break
            except OSError:
                continue
    threading.Thread(target=flask_runner, daemon=True).start()

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log.info("Shutting down...")
