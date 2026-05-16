import os
import time
import json
import logging
import sys
import ssl
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

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

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
PROFILES_DIR = BASE_DIR / "profiles"
PROFILES_DIR.mkdir(exist_ok=True)
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


def init_driver(profile_path=None):
    options = webdriver.ChromeOptions()
    options.add_argument("--window-position=-32000,-32000")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    if profile_path:
        profile_path = str(profile_path)
        options.add_argument(f"--user-data-dir={profile_path}")
        options.add_argument("--profile-directory=Default")
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
    email_input.send_keys(email)

    log.info("Entering password...")
    password_input = driver.find_element(By.XPATH, PASSWORD_XPATH)
    password_input.clear()
    password_input.send_keys(password)

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


def try_profile_login(driver):
    driver.get(PROFILE_URL)
    time.sleep(4)
    if "login" in driver.current_url.lower():
        return False
    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.XPATH, "//a[contains(@href, 'profile')]"))
        )
        return True
    except Exception:
        return False


def run_account(email, password, acct_num, total):
    label = f"[{acct_num}/{total}] {email[:3]}...{email.split('@')[0][-1]}@{email.split('@')[1]}"
    log.info(f"{label} - Starting")
    start = time.time()
    ss_path = None
    last_error = None
    profile_dir = PROFILES_DIR / f"account_{acct_num}"

    for attempt in range(1, RETRIES + 1):
        driver = None
        try:
            driver = init_driver(profile_dir)

            if try_profile_login(driver):
                log.info(f"{label} - Already logged in via saved profile")
            else:
                log.info(f"{label} - Profile expired or new, logging in...")
                if attempt > 1:
                    fresh_dir = PROFILES_DIR / f"account_{acct_num}_fresh"
                    driver.quit()
                    driver = init_driver(fresh_dir)
                    driver.get(BASE_URL)
                    time.sleep(3)
                login(driver, email, password)

            update_profile(driver)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            ss_path = str(SCREENSHOTS_DIR / f"acct{acct_num}_{ts}.png")
            driver.save_screenshot(ss_path)
            driver.quit()
            driver = None
            elapsed = time.time() - start
            msg = f"<b>Naukri Updated - Account {acct_num}</b>\nEmail: {email}\nTime: {elapsed:.0f}s"
            log.info(f"{label} - Success ({elapsed:.0f}s)")
            send_telegram(msg, ss_path)
            return True
        except Exception as e:
            last_error = str(e)
            log.error(f"{label} - Attempt {attempt} failed: {e}")
            if driver:
                try:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    driver.save_screenshot(str(SCREENSHOTS_DIR / f"debug_acct{acct_num}_{ts}.png"))
                except Exception:
                    pass
                try:
                    driver.quit()
                except Exception:
                    pass
            if attempt < RETRIES:
                time.sleep(attempt * 10)

    msg = f"<b>Naukri Failed - Account {acct_num}</b>\nEmail: {email}\nError: {last_error[:200]}"
    log.error(f"{label} - Failed: {last_error[:200]}")
    send_telegram(msg, ss_path if ss_path and Path(ss_path).exists() else None)
    return False


def run():
    log.info("=" * 50)
    log.info(f"Starting Naukri update for {len(accounts)} account(s)")
    overall_start = time.time()
    results = []

    for idx, (email, password) in enumerate(accounts, 1):
        log.info("-" * 40)
        ok = run_account(email, password, idx, len(accounts))
        results.append({"email": email, "success": ok})
        if idx < len(accounts):
            delay = 30
            log.info(f"Waiting {delay}s before next account...")
            time.sleep(delay)

    overall = time.time() - overall_start
    success_count = sum(1 for r in results if r["success"])
    log.info("=" * 50)
    log.info(f"Done: {success_count}/{len(accounts)} accounts updated ({overall:.0f}s total)")

    summary_lines = [f"<b>Naukri Summary</b>\n{success_count}/{len(accounts)} successful"]
    for r in results:
        icon = "OK" if r["success"] else "FAIL"
        summary_lines.append(f"{icon} {r['email']}")
    send_telegram("\n".join(summary_lines))

    status = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(accounts),
        "successful": success_count,
        "results": results,
    }
    STATUS_FILE.write_text(json.dumps(status, indent=2))
    log.info("=" * 50)


if __name__ == "__main__":
    run()
