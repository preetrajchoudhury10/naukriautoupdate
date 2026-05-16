import os
import time
import logging
import sys
import io
import threading
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import schedule
from flask import Flask, send_file, render_template_string

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

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
last_status = {"success": False, "time": None, "screenshot": None}


def init_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=options)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


LOGIN_BTN_XPATH = "/html/body/div[1]/div[4]/div[2]/div/a[1]"
EMAIL_XPATH = "/html/body/div[1]/div[4]/div[2]/div/div/div[2]/div/form/div[2]/input"
PASSWORD_XPATH = "/html/body/div[1]/div[4]/div[2]/div/div/div[2]/div/form/div[3]/input"


def login(driver):
    log.info("Navigating to naukri.com...")
    driver.get(BASE_URL)
    time.sleep(3)

    log.info("Clicking login button...")
    login_btn = WebDriverWait(driver, 15).until(
        EC.element_to_be_clickable((By.XPATH, LOGIN_BTN_XPATH))
    )
    login_btn.click()
    time.sleep(2)

    log.info("Entering email...")
    email_input = WebDriverWait(driver, 15).until(
        EC.element_to_be_clickable((By.XPATH, EMAIL_XPATH))
    )
    email_input.clear()
    email_input.send_keys(EMAIL)

    log.info("Entering password...")
    password_input = driver.find_element(By.XPATH, PASSWORD_XPATH)
    password_input.clear()
    password_input.send_keys(PASSWORD)

    login_btn = driver.find_element(By.XPATH, "//button[@type='submit']")
    login_btn.click()
    log.info("Login button clicked")

    time.sleep(5)
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.XPATH, "//a[contains(@href, 'profile')]"))
    )
    log.info("Login successful")
    return True


PROFILE_URL = f"{BASE_URL}/mnjuser/profile"
EDIT_BTN_XPATH = "/html/body/div[1]/div[1]/div[4]/div/div/div/div[3]/div[2]/div[7]/div/div[1]/div/div/h1/span/img"
EDIT_TEXTAREA_XPATH = "/html/body/div[4]/div/div/div[2]/form/div[1]/div/div/textarea"
SAVE_BTN_XPATH = "/html/body/div[4]/div/div/div[2]/form/div[2]/button"


def update_profile(driver):
    log.info("Navigating to profile page...")
    driver.get(PROFILE_URL)
    time.sleep(5)

    log.info("Clicking edit button...")
    edit_btn = WebDriverWait(driver, 15).until(
        EC.element_to_be_clickable((By.XPATH, EDIT_BTN_XPATH))
    )
    edit_btn.click()
    time.sleep(2)

    log.info("Waiting for edit modal textarea...")
    summary = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.XPATH, EDIT_TEXTAREA_XPATH))
    )

    current_text = summary.get_attribute("value") or ""
    if current_text.endswith(" "):
        summary.clear()
        summary.send_keys(current_text.rstrip())
        log.info("Removed trailing space from summary")
    else:
        summary.clear()
        summary.send_keys(current_text + " ")
        log.info("Added trailing space to summary")

    time.sleep(1)

    log.info("Clicking save button...")
    save_btn = driver.find_element(By.XPATH, SAVE_BTN_XPATH)
    save_btn.click()

    time.sleep(4)
    log.info("Profile update completed successfully")
    return True


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        data = urllib.parse.urlencode({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
        }).encode()
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        urllib.request.urlopen(url, data=data, timeout=10)
    except Exception as e:
        log.warning(f"Telegram send failed: {e}")


def run_update():
    global last_screenshot, last_status
    log.info("=" * 50)
    log.info("Starting scheduled Naukri profile update...")
    start = time.time()
    driver = init_driver()
    try:
        login(driver)
        update_profile(driver)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ss_path = SCREENSHOTS_DIR / f"profile_{timestamp}.png"
        driver.save_screenshot(str(ss_path))
        last_screenshot = ss_path
        last_status = {
            "success": True,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "screenshot": ss_path.name,
        }
        elapsed = time.time() - start
        msg = f"Naukri profile updated successfully ({elapsed:.0f}s)"
        log.info(msg)
        send_telegram(msg)
    except Exception as e:
        elapsed = time.time() - start
        msg = f"Naukri update failed after {elapsed:.0f}s: {e}"
        log.error(msg)
        send_telegram(msg)
    finally:
        driver.quit()
        log.info("=" * 50)


LAST_HTML = """<!DOCTYPE html>
<html>
<head><title>Naukri Auto Update Status</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family: Arial; max-width: 800px; margin: 40px auto; padding: 0 20px; background: #f5f5f5; }
.card { background: #fff; border-radius: 8px; padding: 20px; margin: 20px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
.status { font-size: 18px; font-weight: bold; }
.success { color: #28a745; }
.fail { color: #dc3545; }
img { max-width: 100%; border: 1px solid #ddd; border-radius: 4px; }
a { color: #007bff; }
</style></head>
<body>
<h1>Naukri Auto Update</h1>
<div class="card">
  <p class="status {{'success' if last_status.success else 'fail'}}">
    {{'SUCCESS' if last_status.success else 'NO UPDATE YET'}}
  </p>
  <p><strong>Last run:</strong> {{last_status.time or 'Never'}}</p>
</div>
{% if last_status.screenshot %}
<div class="card">
  <h3>Last Screenshot</h3>
  <p><em>{{last_status.time}}</em></p>
  <img src="/screenshot/{{last_status.screenshot}}" alt="Last profile screenshot">
</div>
{% endif %}
<div class="card">
  <a href="/start">Run Update Now</a> &nbsp;|&nbsp; <a href="/log">View Full Log</a>
</div>
</body></html>"""

app = Flask(__name__)

@app.route("/")
def index():
    return render_template_string(LAST_HTML, last_status=last_status)

@app.route("/laststatus")
def laststatus():
    return render_template_string(LAST_HTML, last_status=last_status)

@app.route("/log")
def get_log():
    log_content = log_buffer.getvalue()
    return f"<pre style='font-size:13px;'>{log_content}</pre>", 200, {"Content-Type": "text/html; charset=utf-8"}

@app.route("/start")
def start_now():
    t = threading.Thread(target=run_update, daemon=True)
    t.start()
    return "<p>Update started. Check <a href='/log'>/log</a> for progress.</p>"

@app.route("/screenshot/<name>")
def screenshot(name):
    path = SCREENSHOTS_DIR / name
    if path.exists():
        return send_file(str(path), mimetype="image/png")
    return "Not found", 404


def start_scheduler():
    schedule.every().day.at("08:00").do(run_update)
    schedule.every().day.at("17:00").do(run_update)
    log.info("Scheduler set: 08:00 and 17:00 daily")
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    log.info("Starting Naukri updater web service...")
    run_update()
    t = threading.Thread(target=start_scheduler, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=PORT)
