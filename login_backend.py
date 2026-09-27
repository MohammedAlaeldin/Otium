import asyncio
import base64
import os
import time
import pyotp
from playwright.async_api import async_playwright

import storage
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


async def handle_security_interrupts(page):
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
            if await btn.is_visible(timeout=1500):
                print(f"🛡️ Skipping security interrupt: {sel}")
                await btn.click(timeout=10000)
                await asyncio.sleep(1.5)
        except Exception:
            pass


async def _try_check_persist_checkbox(page):
    """Targets the 'Don't ask again for 1 day' / persistence checkbox safely."""
    known_selectors = [
        '#idChkBx_SAOTCC_TD',  # Standard 2FA "Don't ask again for 1 day" checkbox
        '#KmsiCheckboxField',  # "Stay signed in?" checkbox
    ]

    for sel in known_selectors:
        try:
            checkbox = page.locator(sel)
            if await checkbox.is_visible(timeout=2000):
                if not await checkbox.is_checked():
                    await checkbox.check(force=True, timeout=5000)
                    print(f"☑️ Checked persistence checkbox: {sel}")
                    await asyncio.sleep(0.5)
                return True
        except Exception:
            continue

    try:
        label = page.locator("text=/don't ask again|1 day|don't show this again/i").first
        if await label.is_visible(timeout=2000):
            await label.click(force=True, timeout=5000)
            print("☑️ Checked persistence checkbox via '1 day' label click")
            await asyncio.sleep(0.5)
            return True
    except Exception:
        pass

    return False


async def sync_teams(context):
    print("⏳ Priming Teams session...")
    try:
        page = await context.new_page()
        await page.goto("https://teams.microsoft.com", timeout=60000, wait_until="domcontentloaded")
        try:
            await page.wait_for_url(lambda url: "teams.microsoft.com" in url or "teams.live.com" in url, timeout=20000)
        except Exception:
            pass
        await asyncio.sleep(3)
        print("✅ Teams session primed.")
        await page.close()
    except Exception as e:
        print(f"⚠️ Teams sync warning: {e}")


async def sync_outlook(context):
    print("⏳ Priming Outlook session...")
    try:
        page = await context.new_page()
        await page.goto("https://outlook.office.com/mail/", timeout=45000, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        print("✅ Outlook session primed.")
        await page.close()
    except Exception as e:
        print(f"⚠️ Outlook sync warning: {e}")


async def attempt_full_ebwise_login_async(user_email: str, user_password: str, totp_secret: str) -> tuple[bool, str]:
    clean_secret = totp_secret.replace(" ", "").strip()
    totp = pyotp.TOTP(clean_secret)

    print("🚀 Launching headless Playwright authentication pipeline...")

    # Nuke the old session file to guarantee a fresh login environment
    if os.path.exists(SESSION_FILE):
        print("🗑️ Deleting old session file to force a pristine login environment...")
        try:
            os.remove(SESSION_FILE)
        except Exception as e:
            print(f"⚠️ Could not remove old session file: {e}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--disable-gpu"]
        )

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            # 1. NAVIGATION & SSO TRIGGER
            print("🌐 Navigating to eBwise login page...")
            await page.goto("https://ebwise.mmu.edu.my/login/index.php", timeout=45000)

            if "microsoftonline.com" not in page.url:
                print("🔄 Clicking Microsoft 365 SSO button...")
                try:
                    sso_btn = page.get_by_role("link", name="Microsoft 365").or_(
                        page.get_by_role("button", name="OpenID Connect")
                    )
                    await sso_btn.first.click(timeout=15000)
                    await page.wait_for_url(lambda url: "microsoftonline.com" in url, timeout=30000)
                except Exception as e:
                    print(f"⚠️ SSO redirect notice: {e}")

            if "microsoftonline.com" not in page.url:
                if not ("ebwise.mmu.edu.my" in page.url and "login" not in page.url):
                    await browser.close()
                    return False, "Failed to reach Microsoft login page. Please check your network connection."

            await asyncio.sleep(1)

            # Check for remembered account tile
            try:
                account_tile = page.get_by_text(user_email).first
                if await account_tile.is_visible(timeout=3000):
                    print("👤 Clicking remembered account tile...")
                    await account_tile.click(timeout=10000)
                    await asyncio.sleep(2)
            except Exception:
                pass

            # 2. EMAIL STEP & CHECK
            email_field = page.get_by_placeholder("Email, phone, or Skype").or_(
                page.locator('input[type="email"]')).first
            password_field = page.get_by_placeholder("Password").or_(page.locator('input[type="password"]')).first

            email_entered = False
            for _ in range(15):  # Poll for up to 30 seconds on slow networks
                if await email_field.is_visible():
                    print("📧 Filling email field...")
                    # Wait explicitly for it to be fully interactable
                    await email_field.wait_for(state="visible", timeout=15000)
                    await email_field.fill(user_email)
                    await page.get_by_role("button", name="Next").click(timeout=15000)
                    await asyncio.sleep(2.5)
                    email_entered = True
                    break
                elif await password_field.is_visible():
                    print("⏩ Email step skipped (Password field already visible).")
                    break
                await asyncio.sleep(2)

            if email_entered:
                email_error = page.locator("#usernameError").or_(
                    page.get_by_text("Enter a valid email address")
                ).or_(
                    page.get_by_text("That Microsoft account doesn't exist")
                ).or_(
                    page.get_by_text("We couldn't find an account with that username")
                ).or_(
                    page.get_by_text("This username may be incorrect")
                )
                try:
                    if await email_error.is_visible(timeout=3000):
                        await browser.close()
                        return False, "Email does not exist. Please check your email address."
                except Exception:
                    pass

            await handle_security_interrupts(page)

            # 3. PASSWORD STEP & CHECK
            try:
                print("⏳ Waiting for password field...")
                await password_field.wait_for(state="visible", timeout=30000)
            except Exception:
                await browser.close()
                return False, "Email does not exist or password field failed to load."

            print("🔑 Filling password field...")
            await password_field.fill(user_password)
            await page.get_by_role("button", name="Sign in").click(timeout=15000)
            await asyncio.sleep(3)

            pwd_error = page.locator("#passwordError").or_(
                page.get_by_text("Your account or password is incorrect")
            ).or_(
                page.get_by_text("Password is incorrect")
            ).or_(
                page.get_by_text("Enter the password for")
            )
            try:
                if await pwd_error.is_visible(timeout=3000):
                    await browser.close()
                    return False, "Incorrect password. Please check your password and try again."
            except Exception:
                pass

            await handle_security_interrupts(page)

            # 4. 2FA HANDSHAKE & OTP CHECK
            print("🛡️ Processing 2FA...")
            for text_sel in [
                "I can't use my Microsoft Authenticator app right now",
                "Use a verification code",
                "verification code"
            ]:
                try:
                    opt = page.get_by_role("button", name=text_sel).or_(page.get_by_text(text_sel)).first
                    if await opt.is_visible(timeout=2000):
                        print(f"🖱️ Clicking 2FA alternative: {text_sel}")
                        await opt.click(timeout=15000)
                        await asyncio.sleep(1.5)
                except Exception:
                    pass

            otc_input = page.get_by_placeholder("Code").or_(page.locator('input[name="otc"]')).first
            try:
                print("⏳ Waiting for 2FA code input field...")
                await otc_input.wait_for(state="visible", timeout=30000)
            except Exception:
                await browser.close()
                return False, "Unable to reach 2FA code entry field."

            time_left = 30 - (int(time.time()) % 30)
            if time_left < 3:
                print("⏳ TOTP code near expiration, waiting for next 30s cycle...")
                await asyncio.sleep(time_left + 1.0)

            current_code = totp.now()
            print(f"🔢 Submitting TOTP Code: {current_code}")
            await otc_input.fill(current_code)

            await _try_check_persist_checkbox(page)

            await page.get_by_role("button", name="Verify").click(timeout=15000)
            await asyncio.sleep(3)

            # Extended error checks mapping to the specific 2FA failure string
            totp_error = page.locator('#otcError').or_(
                page.get_by_text("That code didn't work")
            ).or_(
                page.get_by_text("More information required")
            ).or_(
                page.get_by_text("Enter the code correctly")
            ).or_(
                page.locator("text=/didn't enter the expected verification code/i")
            ).or_(
                page.get_by_text("didn't enter the expected verification code", exact=False)
            )

            try:
                # 4-second timeout allows slow networks time to render the red verification warning
                if await totp_error.is_visible(timeout=4000):
                    await browser.close()
                    return False, "OTP rejected. Please check if your secret_key is correct or activated."
            except Exception:
                pass

            await handle_security_interrupts(page)

            # 5. "STAY SIGNED IN?" PROMPT
            stay_signed_in_btn = page.get_by_role("button", name="Yes").or_(
                page.locator('input[id="idSIButton9"]')).first
            try:
                if await stay_signed_in_btn.is_visible(timeout=5000):
                    print("✅ Handling 'Stay signed in?' prompt...")
                    await _try_check_persist_checkbox(page)
                    await stay_signed_in_btn.click(timeout=15000)
            except Exception:
                pass

            # 6. VERIFY REDIRECT, SYNC SERVICES & SAVE DATA
            print("⏳ Waiting for eBwise home dashboard redirect...")
            await page.wait_for_url(lambda url: "ebwise.mmu.edu.my" in url and "login" not in url, timeout=45000)

            print("🌐 Synchronizing auth state with Microsoft Teams and Outlook concurrently...")
            await asyncio.gather(
                sync_teams(context),
                sync_outlook(context)
            )

            await context.storage_state(path=SESSION_FILE)
            print(f"✅ Session state saved to {SESSION_FILE}")

            # Save credentials so logout can clear them later
            if hasattr(storage, "save_credentials"):
                try:
                    storage.save_credentials(user_email, user_password, clean_secret)
                    print("💾 Credentials saved to local storage.")
                except Exception as e:
                    print(f"⚠️ Save credentials notice: {e}")

            await browser.close()
            return True, "Login Successful! Session and credentials saved."

        except Exception as e:
            await browser.close()
            err_str = str(e)
            if "Timeout" in err_str or "wait_for_url" in err_str:
                return False, "Login timed out. Please check your internet connection or credentials."
            return False, f"Login failed: {err_str}"


def attempt_full_ebwise_login(user_email: str, user_password: str, totp_secret: str) -> tuple[bool, str]:
    """Synchronous entry point that runs the headless login pipeline with error feedback."""
    valid, msg = validate_credentials_format(user_email, user_password, totp_secret)
    if not valid:
        return False, msg

    try:
        return asyncio.run(attempt_full_ebwise_login_async(user_email, user_password, totp_secret))
    except Exception as e:
        return False, f"Authentication pipeline error: {str(e)}"


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

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            slow_mo=200,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(storage_state=SESSION_FILE)
        page = context.new_page()

        page.goto(target_url)
        page.wait_for_timeout(300000)
    return True