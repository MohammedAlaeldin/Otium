import base64
import os
import time
import pyotp
import asyncio
from playwright.sync_api import sync_playwright

from storage import SESSION_FILE
import auto_login


def is_valid_base32(key: str) -> bool:
    clean_key = key.replace(" ", "").strip()
    if len(clean_key) not in (16, 32):
        return False
    try:
        padded_key = clean_key + "=" * (-len(clean_key) % 8)
        base64.b32decode(padded_key, casefold=True)
        return True
    except Exception:
        return False


def validate_credentials_format(email: str, password: str, secret_key: str):
    clean_secret = secret_key.replace(" ", "").strip()
    if not email.lower().endswith(".mmu.edu.my"):
        return False, "Email must end with '.mmu.edu.my'"
    if not is_valid_base32(clean_secret):
        return False, "Secret key must be 16 characters (Base32: A-Z, 2-7)"
    if not password:
        return False, "Password cannot be empty"
    return True, "Format valid"


def attempt_full_ebwise_login(user_email: str, user_password: str, totp_secret: str):
    """
    Routes manual/GUI login attempts through the unified async pipeline.
    Shows the browser (headless=False) and forces a fresh session check.
    """
    creds = {
        "email": user_email,
        "password": user_password,
        "totp_secret": totp_secret
    }

    # Run the robust async login flow synchronously for the GUI
    success, message = asyncio.run(
        auto_login.run_daily_login_async(creds, headless=False, force_fresh=True)
    )

    return success, message


def generate_current_totp(secret_key: str):
    try:
        clean_secret = secret_key.replace(" ", "").strip()
        totp = pyotp.TOTP(clean_secret)
        code = totp.now()
        time_left = 30 - (int(time.time()) % 30)
        return code, time_left
    except Exception:
        return "------", 0


def open_authenticated_service(target_url: str):
    """
    Spawns a visible browser pre-loaded with the user's saved session cookies
    and holds it open for manual interaction.
    """
    if not os.path.exists(SESSION_FILE):
        print(f"⚠️ No session file found at {SESSION_FILE}. Run full login first.")
        return False

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=200,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(storage_state=SESSION_FILE)
        page = context.new_page()

        page.goto(target_url)
        # Keep the browser open for the user until they manually close it
        page.wait_for_timeout(9999999)

    return True