import os
import time
import logging
import sys
import urllib.request
import urllib.parse
from pathlib import Path
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
if not EMAIL or not PASSWORD:
    log.error("NAUKRI_EMAIL and NAUKRI_PASSWORD must be set as environment variables")
    sys.exit(1)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://www.naukri.com"


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


def main():
    log.info("Starting Naukri profile updater...")
    start = time.time()
    driver = init_driver()
    try:
        login(driver)
        update_profile(driver)
        elapsed = time.time() - start
        msg = f"Naukri profile updated successfully ({elapsed:.0f}s)"
        log.info(msg)
        send_telegram(msg)
    except Exception as e:
        elapsed = time.time() - start
        msg = f"Naukri update failed after {elapsed:.0f}s: {e}"
        log.error(msg)
        send_telegram(msg)
        sys.exit(1)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
