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
    clean_secret = secret_key.replace(" ", "").strip()
    if not email.lower().endswith(".mmu.edu.my"):
        return False, "Email must end with '.mmu.edu.my'"
    if not is_valid_base32(clean_secret):
        return False, "Secret key must be 16 characters (Base32: A-Z, 2-7)"
    if not password:
        return False, "Password cannot be empty"
    return True, "Format valid"


def handle_security_interrupts(page):
    """Bypasses Microsoft passkey prompts or 'Skip for now' screens."""
    interrupt_selectors = [
        'text=/skip for now/i',
        'text=/ask later/i',
        'text=/no thanks/i',
        '#iCancel',
        'input[value="Skip for now"]'
    ]
    for sel in interrupt_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1000):
                print(f"🛡️ Skipping security interrupt: {sel}")
                btn.click()
                time.sleep(1)
        except Exception:
            pass


def _try_check_persist_checkbox(page):
    """Targets the 'Don't ask again for 1 day' / persistence checkbox safely."""
    known_selectors = [
        '#idChkBx_SAOTCC_TD',  # Standard 2FA "Don't ask again for 1 day" checkbox
        '#KmsiCheckboxField',  # "Stay signed in?" checkbox
    ]

    for sel in known_selectors:
        try:
            checkbox = page.locator(sel)
            if checkbox.is_visible(timeout=1000):
                if not checkbox.is_checked():
                    checkbox.check(force=True)
                    print(f"☑️ Checked persistence checkbox: {sel}")
                    time.sleep(0.5)
                return True
        except Exception:
            continue

    try:
        label = page.locator("text=/don't ask again|1 day|don't show this again/i").first
        if label.is_visible(timeout=1000):
            label.click(force=True)
            print("☑️ Checked persistence checkbox via '1 day' label click")
            time.sleep(0.5)
            return True
    except Exception:
        pass

    return False


def sync_additional_services(context):
    print("🌐 Synchronizing auth state for Teams and Outlook...")

    try:
        teams_page = context.new_page()
        teams_page.goto("https://teams.microsoft.com", wait_until="domcontentloaded", timeout=20000)
        time.sleep(2)
        teams_page.close()
        print("✅ Teams session primed.")
    except Exception as e:
        print(f"⚠️ Teams sync skipped/timed out: {e}")

    try:
        outlook_page = context.new_page()
        outlook_page.goto("https://outlook.office.com/mail/", wait_until="domcontentloaded", timeout=20000)
        time.sleep(2)
        outlook_page.close()
        print("✅ Outlook session primed.")
    except Exception as e:
        print(f"⚠️ Outlook sync skipped/timed out: {e}")


def attempt_full_ebwise_login(user_email: str, user_password: str, totp_secret: str):
    clean_secret = totp_secret.replace(" ", "").strip()
    totp = pyotp.TOTP(clean_secret)

    print("🚀 Launching Playwright authentication pipeline...")

    # Nuke the old session file to guarantee a fresh login flow
    if os.path.exists(SESSION_FILE):
        print("🗑️ Deleting old session file to force a pristine login environment...")
        os.remove(SESSION_FILE)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=200,
            args=["--disable-blink-features=AutomationControlled"]
        )

        # Fresh context with NO storage_state
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # ... (rest of the login logic remains exactly the same as previously provided) ...

        try:
            # 1. NAVIGATION
            page.goto("https://ebwise.mmu.edu.my/login/index.php", wait_until="networkidle")

            login_btn = (
                page.locator('text="Microsoft 365"')
                .or_(page.locator('text="OpenID Connect"'))
                .or_(page.locator('a:has-text("Log in")'))
            )
            login_btn.first.click(timeout=8000)
            time.sleep(1.5)

            # Check for remembered account tile
            try:
                account_tile = page.locator(f'div[data-test-id="{user_email}"], text="{user_email}"').first
                if account_tile.is_visible(timeout=2000):
                    account_tile.click()
                    time.sleep(1.5)
            except Exception:
                pass

            # State check: Is email input visible and NOT password input?
            email_input = page.locator('input[type="email"]:visible, input[name="loginfmt"]:visible').first
            password_input = page.locator('input[type="password"]:visible, input[name="passwd"]:visible').first

            if email_input.is_visible(timeout=2000) and not password_input.is_visible(timeout=500):
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

            handle_security_interrupts(page)

            # 2. PASSWORD
            password_input = page.locator('input[type="password"]:visible, input[name="passwd"]:visible').first
            try:
                password_input.wait_for(state="visible", timeout=10000)
            except Exception:
                browser.close()
                return False, "EMAIL_ERROR: Password field not visible."

            password_input.fill(user_password)
            page.locator('input[type="submit"]').click()
            time.sleep(2)

            pwd_error = page.locator("#passwordError").or_(page.locator("text='Your account or password is incorrect'"))
            if pwd_error.is_visible():
                browser.close()
                return False, "PASSWORD_ERROR: Incorrect password."

            handle_security_interrupts(page)

            # 3. 2FA HANDSHAKE
            time.sleep(1)
            for selector in [
                'text="I can\'t use my Microsoft Authenticator app right now"',
                'text="Use a verification code"',
                'text=/verification code/i'
            ]:
                loc = page.locator(selector).first
                if loc.is_visible():
                    loc.click()
                    time.sleep(1)

            otc_input = page.locator('input[name="otc"]:visible').first
            try:
                otc_input.wait_for(state="visible", timeout=10000)
            except Exception:
                browser.close()
                return False, "TOTP_ERROR: Unable to reach 2FA code entry field."

            # 4. SUBMIT TOTP & CHECK 1-DAY PERSISTENCE
            time_left = 30 - (int(time.time()) % 30)
            if time_left < 3:
                time.sleep(time_left + 0.5)

            current_code = totp.now()
            print(f"🔢 Submitting TOTP Code: {current_code}")

            otc_input.fill(current_code)
            _try_check_persist_checkbox(page)

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

            handle_security_interrupts(page)

            # 5. "STAY SIGNED IN?"
            stay_signed_in_btn = page.locator('input[id="idSIButton9"]').or_(page.locator('input[value="Yes"]')).first
            try:
                if stay_signed_in_btn.is_visible(timeout=4000):
                    _try_check_persist_checkbox(page)
                    stay_signed_in_btn.click()
            except Exception:
                pass

            # 6. VERIFY REDIRECT & EXPORT STORAGE STATE
            print("⏳ Waiting for eBwise home dashboard...")
            page.wait_for_url(lambda url: "ebwise.mmu.edu.my" in url and "login" not in url, timeout=15000)

            sync_additional_services(context)
            context.storage_state(path=SESSION_FILE)
            print(f"✅ Unified Microsoft SSO session state stored to {SESSION_FILE}")

            browser.close()
            return True, "Login Successful! Session saved."

        except Exception as e:
            browser.close()
            return False, f"LOGIN_FAILED: {str(e)}"


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
        page.wait_for_timeout(300000)
    return True
#try 2