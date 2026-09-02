import base64
import os
import time
import pyotp
from playwright.sync_api import sync_playwright

from storage import SESSION_FILE

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
    """Validates user input before launching Playwright."""
    clean_secret = secret_key.replace(" ", "").strip()

    if not email.endswith(".mmu.edu.my") or email.endswith(".MMU.EDU.MY"):
        return False, "Email must end with '.mmu.edu.my'"
    if not is_valid_base32(clean_secret):
        return False, "Secret key must be 16 characters (Base32: A-Z, 2-7)"
    if not password:
        return False, "Password cannot be empty"

    return True, "Format valid"


def sync_additional_services(context):
    """Primes Teams and Outlook sessions using the active SSO context."""
    print("🌐 Synchronizing auth state for Teams and Outlook...")

    # 1. Sync Teams Session
    try:
        teams_page = context.new_page()
        teams_page.goto("https://teams.microsoft.com", wait_until="domcontentloaded", timeout=20000)
        time.sleep(2)
        teams_page.close()
        print("✅ Teams session primed.")
    except Exception as e:
        print(f"⚠️ Teams sync skipped/timed out: {e}")

    # 2. Sync Outlook Session
    try:
        outlook_page = context.new_page()
        outlook_page.goto("https://outlook.office.com/mail/", wait_until="domcontentloaded", timeout=20000)
        time.sleep(2)
        outlook_page.close()
        print("✅ Outlook session primed.")
    except Exception as e:
        print(f"⚠️ Outlook sync skipped/timed out: {e}")


def attempt_full_ebwise_login(user_email: str, user_password: str, totp_secret: str):
    """
    Executes authentication flow at a stable speed and exports
    Microsoft SSO session state for eBwise, Teams, and Outlook to session.json.
    """
    clean_secret = totp_secret.replace(" ", "").strip()
    totp = pyotp.TOTP(clean_secret)

    print("🚀 Launching Playwright authentication pipeline...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=300)
        context = browser.new_context()
        page = context.new_page()

        def handle_response(response):
            if "service.php" in response.url and response.status == 200:
                try:
                    data = response.json()
                    print("Intercepted Login Response JSON:", data)
                except Exception:
                    pass

        try:
            # 1. NAVIGATION & EMAIL
            page.goto("https://ebwise.mmu.edu.my/login/index.php", wait_until="networkidle")

            login_btn = (
                page.locator('text="Microsoft 365"')
                .or_(page.locator('text="OpenID Connect"'))
                .or_(page.locator('a:has-text("Log in")'))
            )
            login_btn.first.click(timeout=8000)

            email_input = page.locator('input[type="email"]')
            email_input.wait_for(state="visible", timeout=12000)
            email_input.fill(user_email)
            page.locator('input[type="submit"]').click()

            time.sleep(2)
            email_error = (
                page.locator("#usernameError")
                .or_(page.locator("text='Enter a valid email address'"))
                .or_(page.locator("text=\"That Microsoft account doesn't exist\""))
            )
            if email_error.is_visible():
                browser.close()
                return False, "EMAIL_ERROR: Microsoft rejected this email address."

            # 2. PASSWORD
            password_input = page.locator('input[type="password"]')
            try:
                password_input.wait_for(state="visible", timeout=10000)
            except Exception:
                browser.close()
                return False, "EMAIL_ERROR: Account not found or email step failed."

            password_input.fill(user_password)
            page.locator('input[type="submit"]').click()

            time.sleep(2)
            pwd_error = page.locator("#passwordError").or_(page.locator("text='Your account or password is incorrect'"))
            if pwd_error.is_visible():
                browser.close()
                return False, "PASSWORD_ERROR: Incorrect password."

            # 3. 2FA HANDSHAKE
            print("⏳ Handling 2FA verification options...")
            time.sleep(1.5)

            for selector in [
                'text="I can\'t use my Microsoft Authenticator app right now"',
                'text="Use a verification code"',
                'text=/verification code/i'
            ]:
                loc = page.locator(selector)
                if loc.is_visible():
                    loc.click()
                    time.sleep(1)

            otc_input = page.locator('input[name="otc"]')
            try:
                otc_input.wait_for(state="visible", timeout=10000)
            except Exception:
                browser.close()
                return False, "TOTP_ERROR: Unable to reach 2FA code entry field. Key may not be activated."

            # 4. GENERATE & SUBMIT TOTP
            time_left = 30 - (int(time.time()) % 30)
            if time_left < 3:
                time.sleep(time_left + 0.5)

            current_code = totp.now()
            print(f"🔢 Submitting TOTP Code: {current_code}")

            otc_input.fill(current_code)
            page.locator('input[type="submit"]').click()

            time.sleep(2)
            totp_error = (
                page.locator('text="That code didn\'t work"')
                .or_(page.locator('text="More information required"'))
                .or_(page.locator('#otcError'))
            )
            if totp_error.is_visible():
                browser.close()
                return False, "TOTP_ERROR: Microsoft rejected the code."

            # 5. SAVE SSO SESSION ("Stay signed in?")
            stay_signed_in_btn = page.locator('input[id="idSIButton9"]').or_(page.locator('input[value="Yes"]'))
            try:
                stay_signed_in_btn.wait_for(state="visible", timeout=5000)
                stay_signed_in_btn.click()
            except Exception:
                pass

            # 6. VERIFY REDIRECT & EXPORT STORAGE STATE
            print("⏳ Waiting for eBwise home dashboard...")
            page.wait_for_url(lambda url: "ebwise.mmu.edu.my" in url and "login" not in url, timeout=15000)

            # 7. ADDED STEP: PRIME TEAMS AND OUTLOOK (Only reached if credentials pass)
            sync_additional_services(context)

            # Export unified session cookies to disk
            context.storage_state(path=SESSION_FILE)
            print(f"✅ Unified Microsoft SSO session state stored to {SESSION_FILE}")

            browser.close()
            return True, "Login Successful! Session saved."

        except Exception as e:
            browser.close()
            return False, f"LOGIN_FAILED: {str(e)}"


def generate_current_totp(secret_key: str):
    """Generates active 6-digit TOTP code and seconds remaining."""
    try:
        clean_secret = secret_key.replace(" ", "").strip()
        totp = pyotp.TOTP(clean_secret)
        code = totp.now()
        time_left = 30 - (int(time.time()) % 30)
        return code, time_left
    except Exception:
        return "------", 0


def open_authenticated_service(target_url: str):
    """Launches browser pre-authenticated with saved session state."""
    if not os.path.exists(SESSION_FILE):
        print(f"⚠️ No session file found at {SESSION_FILE}. Run full login first.")
        return False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=200)
        context = browser.new_context(storage_state=SESSION_FILE)
        page = context.new_page()

        page.goto(target_url)
        page.wait_for_timeout(300000)
    return True