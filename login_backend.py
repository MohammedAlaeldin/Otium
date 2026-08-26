import base64
import time
import pyotp
from playwright.sync_api import sync_playwright


#secret key check
def is_valid_base32(key: str) -> bool:
    clean_key = key.replace(" ", "").strip()
    # Allow standard 16 or 32 character secrets
    if len(clean_key) not in (16, 32):
        return False
    try:
        # Add padding for python base64 decoder
        padded_key = clean_key + "=" * (-len(clean_key) % 8)
        base64.b32decode(padded_key, casefold=True)
        return True
    except Exception:
        return False

def validate_credentials_format(email: str, password: str, secret_key: str):
    """Validates user input before launching Playwright."""
    clean_secret = secret_key.replace(" ", "").strip()

    if not email.endswith(".mmu.edu.my"):
        return False, "Email must end with '.mmu.edu.my'"
    if not is_valid_base32(clean_secret):
        return False, "Secret key must be 16 characters (Base32: A-Z, 2-7)"
    if not password:
        return False, "Password cannot be empty"

    return True, "Format valid"


def attempt_full_ebwise_login(user_email: str, user_password: str, totp_secret: str):
    """
    Launche playwright to perform authentication. Identifies the specific point of
    failure and handles 2FA prompt layouts.
    """
    clean_secret = totp_secret.replace(" ", "").strip()
    totp = pyotp.TOTP(clean_secret)

    print("🚀 Launching Playwright to test full login sequence...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=500)
        context = browser.new_context()
        page = context.new_page()

        try:
            #1)NAVIGATION & EMAIL
            page.goto("https://ebwise.mmu.edu.my/login/index.php", timeout=30000)

            try:
                page.click('text="Microsoft 365"', timeout=4000)
            except Exception:
                try:
                    page.click('text="OpenID Connect"', timeout=4000)
                except Exception:
                    page.click('a:has-text("Log in")', timeout=5000)

            page.wait_for_selector('input[type="email"]', timeout=10000)
            page.fill('input[type="email"]', user_email)
            page.click('input[type="submit"]')

            time.sleep(2)
            # Check for invalid email
            if page.is_visible("#usernameError") or page.is_visible('text="Enter a valid email address"') or page.is_visible('text="That Microsoft account doesn\'t exist"'):
                browser.close()
                return False, "EMAIL_ERROR: Microsoft rejected this email address."

            #2)Password
            try:
                page.wait_for_selector('input[type="password"]', timeout=10000)
            except Exception:
                # If password field didn't show up, email was likely invalid
                browser.close()
                return False, "EMAIL_ERROR: Account not found or email step failed."

            page.fill('input[type="password"]', user_password)
            page.click('input[type="submit"]')

            time.sleep(2.5)
            # Check for incorrect password
            if page.is_visible("#passwordError") or page.is_visible('text="Your account or password is incorrect"'):
                browser.close()
                return False, "PASSWORD_ERROR: Incorrect password."

            #3) 2FA SCREEN HANDLING
            print("⏳ Navigating 2FA screen...")
            time.sleep(2)

            # 1: Click "I can't use my Microsoft Authenticator app right now"
            try:
                page.click('text="I can\'t use my Microsoft Authenticator app right now"', timeout=3000)
                time.sleep(1)
            except Exception:
                pass

            # 2: Click "Use a verification code"
            try:
                page.click('text="Use a verification code"', timeout=3000)
                time.sleep(1)
            except Exception:
                pass

            # 3: Check if input field is ready, or try clicking option list item
            try:
                if not page.is_visible('input[name="otc"]'):
                    # Try clicking option list element containing 'verification code' text
                    page.click('text=/verification code/i', timeout=3000)
            except Exception:
                pass

            # Check if 2FA input field exists
            try:
                page.wait_for_selector('input[name="otc"]', timeout=8000)
            except Exception:
                browser.close()
                return False, "TOTP_ERROR: Unable to reach 2FA code entry field. Key may not be activated."

            #4) SUBMIT TOTP CODE
            time_left = 30 - (int(time.time()) % 30)
            if time_left < 3:
                time.sleep(time_left + 0.5)

            current_code = totp.now()
            print(f"🔢 Submitting TOTP Code: {current_code}")

            page.fill('input[name="otc"]', current_code)
            page.click('input[type="submit"]')

            time.sleep(3)

                # Check if Microsoft explicitly flagged an invalid TOTP code
            if (
                    page.is_visible('text="Enter the 6-digit code"')
                    or page.is_visible('text="That code didn\'t work"')
                    or page.is_visible('text="More information required"')
                    or page.is_visible('#otcError')
            ):
                browser.close()
                return False, "TOTP_ERROR: Microsoft rejected the code. Key may not be activated."

                # Handle "Stay signed in?" prompt
            try:
                if page.is_visible('input[id="idSIButton9"]'):
                    page.click('input[id="idSIButton9"]')
            except Exception:
                pass

                #5) STRICT VERDICT CHECK
            print("⏳ Waiting for redirection back to eBwise...")
            try:
                    # Wait for Playwright to redirect back to MMU eBwise domain
                page.wait_for_url(lambda url: "ebwise.mmu.edu.my" in url and "login" not in url, timeout=12000)
            except Exception:
                    # If we are still stuck on Microsoft's domain, the 2FA failed
                browser.close()
                return False, "TOTP_ERROR: Key activation failed or Microsoft rejected authentication."

                # Save valid session
            context.storage_state(path="ebwise_session.json")
            browser.close()
            return True, "Login Successful! Key verified."
        except Exception as e:
            browser.close()
            return False, f"LOGIN_FAILED: {str(e)}"
def generate_current_totp(secret_key: str):
    """Generates the active 6-digit TOTP code and seconds remaining in current interval."""
    try:
        clean_secret = secret_key.replace(" ", "").strip()
        totp = pyotp.TOTP(clean_secret)
        code = totp.now()
        time_left = 30 - (int(time.time()) % 30)
        return code, time_left
    except Exception:
        return "------", 0