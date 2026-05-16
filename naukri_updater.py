import os
import time
import json
import logging
import sys
import urllib.request
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
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

EMAIL = os.getenv("NAUKRI_EMAIL")
PASSWORD = os.getenv("NAUKRI_PASSWORD")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not EMAIL or not PASSWORD:
    log.error("NAUKRI_EMAIL and NAUKRI_PASSWORD must be set in .env file")
    sys.exit(1)

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


def init_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--window-position=-32000,-32000")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=options)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


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


def run():
    log.info("=" * 50)
    log.info("Starting Naukri profile update...")
    start = time.time()
    ss_path = None
    last_error = None

    for attempt in range(1, RETRIES + 1):
        log.info(f"Attempt {attempt}/{RETRIES}")
        driver = None
        try:
            driver = init_driver()
            login(driver)
            update_profile(driver)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            ss_path = str(SCREENSHOTS_DIR / f"profile_{ts}.png")
            driver.save_screenshot(ss_path)
            driver.quit()
            driver = None
            status = {"success": True, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                      "screenshot": Path(ss_path).name, "error": None}
            elapsed = time.time() - start
            msg = f"<b>Naukri Profile Updated</b>\nTime: {elapsed:.0f}s\nDate: {status['time']}"
            log.info(f"Naukri profile updated successfully ({elapsed:.0f}s)")
            send_telegram(msg, ss_path)
            STATUS_FILE.write_text(json.dumps(status, indent=2))
            log.info("=" * 50)
            return
        except Exception as e:
            last_error = str(e)
            log.error(f"Attempt {attempt} failed: {e}")
            if driver:
                try:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    ss_path = str(SCREENSHOTS_DIR / f"debug_{ts}.png")
                    driver.save_screenshot(ss_path)
                except Exception:
                    pass
                try:
                    driver.quit()
                except Exception:
                    pass
            if attempt < RETRIES:
                wait = attempt * 10
                log.info(f"Retrying in {wait}s...")
                time.sleep(wait)

    elapsed = time.time() - start
    status = {"success": False, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "screenshot": Path(ss_path).name if ss_path and Path(ss_path).exists() else None,
              "error": last_error}
    msg = f"<b>Naukri Update Failed</b>\nError: {last_error[:300]}\nTime: {elapsed:.0f}s"
    log.error(msg.replace("<b>", "").replace("</b>", ""))
    send_telegram(msg, ss_path if ss_path and Path(ss_path).exists() else None)
    STATUS_FILE.write_text(json.dumps(status, indent=2))
    log.info("=" * 50)


if __name__ == "__main__":
    run()
