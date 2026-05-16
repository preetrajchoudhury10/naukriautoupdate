import os
import time
import logging
import sys
import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

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
    log.error("NAUKRI_EMAIL and NAUKRI_PASSWORD must be set in .env file")
    sys.exit(1)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_DIR = Path(__file__).parent
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

STATUS_FILE = BASE_DIR / "last_status.json"
LOG_FILE = BASE_DIR / "last_log.txt"


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


LOGIN_BTN = "/html/body/div[1]/div[4]/div[2]/div/a[1]"
EMAIL_XPATH = "/html/body/div[1]/div[4]/div[2]/div/div/div[2]/div/form/div[2]/input"
PASSWORD_XPATH = "/html/body/div[1]/div[4]/div[2]/div/div/div[2]/div/form/div[3]/input"
EDIT_BTN = "/html/body/div[1]/div[1]/div[4]/div/div/div/div[3]/div[2]/div[7]/div/div[1]/div/div/h1/span/img"
EDIT_TEXTAREA = "/html/body/div[4]/div/div/div[2]/form/div[1]/div/div/textarea"
SAVE_BTN = "/html/body/div[4]/div/div/div[2]/form/div[2]/button"


def try_click_login(page):
    strategies = [
        ("exact login btn", LOGIN_BTN),
        ("role link with Login", None),
    ]
    for name, xpath in strategies:
        try:
            if xpath:
                el = page.locator(f"xpath={xpath}").first
                el.wait_for(state="visible", timeout=5000)
                el.click()
                log.info(f"Found login via: {name}")
                return True
        except Exception:
            continue
    for fn_name, fn in [
        ("role link", lambda: page.get_by_role("link", name=re.compile("login", re.IGNORECASE)).first),
        ("role button", lambda: page.get_by_role("button", name=re.compile("login", re.IGNORECASE)).first),
        ("text", lambda: page.get_by_text(re.compile("login", re.IGNORECASE)).first),
        ("href", lambda: page.locator("a[href*='login' i], [href*='login' i]").first),
        ("class/id", lambda: page.locator("[class*='login' i], [id*='login' i]").first),
        ("sign in", lambda: page.get_by_text(re.compile("sign.in", re.IGNORECASE)).first),
        ("header link", lambda: page.locator("header a, nav a").first),
    ]:
        try:
            el = fn()
            if el.is_visible(timeout=3000):
                el.click()
                log.info(f"Found login via: {fn_name}")
                return True
        except Exception:
            continue
    return False


def try_fill_login(page):
    for name, xpath in [("exact email", EMAIL_XPATH), ("type email", "//input[@type='email']"), ("first text", "(//input[@type='text'])[1]")]:
        try:
            el = page.locator(f"xpath={xpath}").first
            el.wait_for(state="visible", timeout=3000)
            el.fill(EMAIL)
            log.info(f"Email via: {name}")
            break
        except Exception:
            continue
    else:
        return False

    for name, xpath in [("exact pw", PASSWORD_XPATH), ("type password", "//input[@type='password']")]:
        try:
            el = page.locator(f"xpath={xpath}").first
            el.fill(PASSWORD)
            log.info(f"Password via: {name}")
            break
        except Exception:
            continue

    try:
        page.locator("button[type='submit'], input[type='submit']").first.click(timeout=5000)
        return True
    except Exception:
        return False


def run_update():
    log.info("=" * 50)
    log.info("Starting Naukri profile update...")
    start = time.time()
    page = None
    ss_path = None

    try:
        with sync_playwright() as pw:
            proxy_url = os.getenv("PROXY_URL")
            launch_kwargs = {
                "headless": True,
                "args": [
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--single-process",
                    "--no-zygote",
                ],
            }
            if proxy_url:
                launch_kwargs["proxy"] = {"server": proxy_url}
            browser = pw.chromium.launch(**launch_kwargs)
            page = browser.new_page(viewport={"width": 1920, "height": 1080})

            log.info("Navigating to naukri.com...")
            page.goto("https://www.naukri.com", wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)

            logged_in = False
            for sel in ["a[href*='profile' i]", "[class*='userName' i]", "[class*='avatar' i]"]:
                try:
                    if page.locator(sel).first.is_visible(timeout=2000):
                        logged_in = True
                        log.info(f"Already logged in (found: {sel})")
                        break
                except Exception:
                    continue

            if not logged_in:
                clicked = try_click_login(page)
                if not clicked:
                    for url in [f"https://www.naukri.com/nlogin/login",
                                "https://login.naukri.com",
                                "https://www.naukri.com/login"]:
                        try:
                            page.goto(url, wait_until="domcontentloaded", timeout=15000)
                            time.sleep(3)
                            if try_fill_login(page):
                                clicked = True
                                break
                        except Exception:
                            continue
                if not clicked:
                    raise RuntimeError("Could not find login button or form")

                time.sleep(2)
                if not try_fill_login(page):
                    raise RuntimeError("Could not fill login form")

                time.sleep(5)
                log.info(f"Post-login URL: {page.url}")

            log.info("Navigating to profile page...")
            page.goto("https://www.naukri.com/mnjuser/profile", wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)

            for name, xpath in [("exact edit", EDIT_BTN), ("img edit", "//img[contains(@src, 'edit')]"),
                                ("span edit", "//span[contains(@class, 'edit')]"),
                                ("button edit", "//button[contains(text(), 'Edit')]")]:
                try:
                    el = page.locator(f"xpath={xpath}").first
                    el.wait_for(state="visible", timeout=3000)
                    el.click()
                    log.info(f"Clicked edit via: {name}")
                    break
                except Exception:
                    continue
            else:
                log.warning("Edit button not found, continuing anyway")
            time.sleep(2)

            textarea = None
            for name, xpath in [("exact textarea", EDIT_TEXTAREA), ("any textarea", "//textarea"),
                                ("contenteditable", "//div[@contenteditable='true']")]:
                try:
                    el = page.locator(f"xpath={xpath}").first
                    el.wait_for(state="visible", timeout=3000)
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

            for name, xpath in [("exact save", SAVE_BTN), ("button save", "//button[contains(text(), 'Save')]"),
                                ("submit", "//button[@type='submit']")]:
                try:
                    el = page.locator(f"xpath={xpath}").first
                    el.wait_for(state="visible", timeout=3000)
                    el.click()
                    log.info(f"Clicked save via: {name}")
                    break
                except Exception:
                    continue

            time.sleep(4)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            ss_path = str(SCREENSHOTS_DIR / f"profile_{ts}.png")
            page.screenshot(path=ss_path, full_page=True)
            browser.close()

        status = {
            "success": True,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "screenshot": Path(ss_path).name,
            "error": None,
        }
        elapsed = time.time() - start
        msg = f"<b>Naukri Profile Updated</b>\nTime: {elapsed:.0f}s\nDate: {status['time']}"
        log.info(msg.replace("<b>", "").replace("</b>", ""))
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
        status = {
            "success": False,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "screenshot": Path(debug_ss).name if debug_ss else None,
            "error": str(e),
        }
        msg = f"<b>Naukri Update Failed</b>\nError: {str(e)[:300]}\nTime: {elapsed:.0f}s"
        log.error(msg.replace("<b>", "").replace("</b>", ""))
        send_telegram(msg, debug_ss)

    STATUS_FILE.write_text(json.dumps(status, indent=2))
    log.info("=" * 50)


if __name__ == "__main__":
    run_update()
