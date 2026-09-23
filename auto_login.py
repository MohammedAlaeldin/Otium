import asyncio
import os
import time
import pyotp
from playwright.async_api import async_playwright

from storage import SESSION_FILE

# Global timeouts for deployment scaling
PAGE_TIMEOUT = 90000  # 90 seconds for heavy page loads
ELEM_TIMEOUT = 30000  # 30 seconds for specific UI element interactivity
FAST_TIMEOUT = 3000  # 3 seconds for optional popups (interrupts, persist checkboxes)


async def is_session_valid(page) -> bool:
    """Navigates directly to eBwise (/my/). If active cookies exist, bypasses authentication."""
    try:
        print("🌐 Navigating straight to eBwise Dashboard (/my/)...")
        await page.goto("https://ebwise.mmu.edu.my/my/", timeout=PAGE_TIMEOUT)
        await page.wait_for_load_state("domcontentloaded", timeout=ELEM_TIMEOUT)
        await asyncio.sleep(1.5)

        current_url = page.url
        if any(keyword in current_url for keyword in ["login", "microsoftonline", "openid"]):
            print("🔑 Existing cookies expired or invalid. Full re-auth needed.")
            return False

        if "ebwise.mmu.edu.my" in current_url:
            print("🟢 Active session detected! Reusing existing cookies instantly.")
            return True
    except Exception as e:
        print(f"⚠️ Session check issue (Network may be slow): {e}")
    return False


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
                await btn.click()
                await asyncio.sleep(1)
        except Exception:
            pass


async def _try_check_persist_checkbox(page):
    """Targets the 'Don't ask again for 1 day' / persistence checkbox without freezing."""
    known_selectors = [
        '#idChkBx_SAOTCC_TD',  # Standard 2FA "Don't ask again for 1 day" checkbox
        '#KmsiCheckboxField',  # "Stay signed in?" checkbox
    ]

    for sel in known_selectors:
        try:
            checkbox = page.locator(sel)
            if await checkbox.is_visible(timeout=FAST_TIMEOUT):
                if not await checkbox.is_checked():
                    await checkbox.check(force=True)
                    print(f"☑️ Checked persistence checkbox: {sel}")
                    await asyncio.sleep(0.5)
                return True
        except Exception:
            continue

    try:
        label = page.locator("text=/don't ask again|1 day|don't show this again/i").first
        if await label.is_visible(timeout=FAST_TIMEOUT):
            await label.click(force=True)
            print("☑️ Checked persistence checkbox via '1 day' label click")
            await asyncio.sleep(0.5)
            return True
    except Exception:
        pass

    return False


async def authenticate_with_credentials(page, email: str, password: str, totp_secret: str) -> tuple[bool, str]:
    """State-driven Microsoft 2FA login flow."""
    clean_secret = totp_secret.replace(" ", "").strip()
    totp = pyotp.TOTP(clean_secret)

    print("🌐 Navigating to eBwise login page...")
    await page.goto("https://ebwise.mmu.edu.my/login/index.php", wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)

    # 1. TRIGGER SSO REDIRECT
    if "microsoftonline.com" not in page.url:
        print("🔄 Clicking Microsoft 365 SSO button...")
        sso_btn = (
            page.locator('a[title="Microsoft 365"]')
            .or_(page.locator('text="Microsoft 365"'))
            .or_(page.locator('text="OpenID Connect"'))
        )
        try:
            await sso_btn.first.click(timeout=ELEM_TIMEOUT)
            print("⏳ Waiting for redirect to Microsoft Login...")
            await page.wait_for_url(lambda url: "microsoftonline.com" in url, timeout=PAGE_TIMEOUT)
        except Exception as e:
            print(f"⚠️ Warning during SSO redirect: {e}")

        if "microsoftonline.com" not in page.url:
            if "ebwise.mmu.edu.my" in page.url and "login" not in page.url:
                return True, "Login Successful! Session saved."
            return False, "TIMEOUT_ERROR: Failed to reach Microsoft login page."

    await asyncio.sleep(1)

    # 2. ACCOUNT PICKER TILE (If email was remembered)
    try:
        account_tile = page.locator(f'div[data-test-id="{email}"], text="{email}"').first
        if await account_tile.is_visible(timeout=FAST_TIMEOUT):
            print("👤 Clicking remembered account tile...")
            await account_tile.click()
            await asyncio.sleep(1.5)
    except Exception:
        pass

    # 3. DYNAMIC DOM SYNC (Email vs Password)
    email_input = page.locator('input[type="email"], input[name="loginfmt"]').first
    password_input = page.locator('input[type="password"], input[name="passwd"]').first

    try:
        # Waits exactly for whichever field appears first, eliminating arbitrary sleeps
        await email_input.or_(password_input).wait_for(state="visible", timeout=ELEM_TIMEOUT)

        if await email_input.is_visible():
            print("📧 Filling email field exactly as it rendered...")
            await email_input.fill(email)
            await page.locator('input[type="submit"], input[id="idSIButton9"]').first.click()
            await asyncio.sleep(1.5)
        else:
            print("⏩ Email step skipped (Password field already visible).")
    except Exception:
        return False, "TIMEOUT_ERROR: Login fields failed to load."

    email_error = (
        page.locator("#usernameError")
        .or_(page.locator("text='Enter a valid email address'"))
        .or_(page.locator("text=\"That Microsoft account doesn't exist\""))
    )
    if await email_error.is_visible():
        return False, "EMAIL_ERROR: Microsoft rejected this email address."

    await handle_security_interrupts(page)

    # 4. PASSWORD STEP
    try:
        await password_input.wait_for(state="visible", timeout=ELEM_TIMEOUT)
        print("🔑 Filling password field...")
        await password_input.fill(password)
        await page.locator('input[type="submit"], input[id="idSIButton9"]').first.click()
        await asyncio.sleep(2)
    except Exception:
        if "ebwise.mmu.edu.my" in page.url and "login" not in page.url:
            return True, "Login Successful! Session saved."
        return False, "TIMEOUT_ERROR: Password field not interactable."

    pwd_error = page.locator("#passwordError").or_(page.locator("text='Your account or password is incorrect'"))
    if await pwd_error.is_visible():
        return False, "PASSWORD_ERROR: Incorrect password."

    await handle_security_interrupts(page)

    # 5. 2FA HANDSHAKE & SUBMISSION
    await asyncio.sleep(1)
    for selector in [
        'a[id="idA_SASTP_SASS_OTC"]',
        'text="I can\'t use my Microsoft Authenticator app right now"',
        'text="Use a verification code"',
        'text=/verification code/i'
    ]:
        try:
            loc = page.locator(selector).first
            if await loc.is_visible(timeout=1500):
                print(f"🖱️ Clicking 2FA alternative: {selector}")
                await loc.click()
                await asyncio.sleep(1)
                break
        except Exception:
            pass

    otc_input = page.locator('input[name="otc"]:visible').first
    try:
        await otc_input.wait_for(state="visible", timeout=ELEM_TIMEOUT)
    except Exception:
        return False, "TIMEOUT_ERROR: Unable to reach 2FA code entry field."

    # TOTP Boundary safeguard
    time_left = 30 - (int(time.time()) % 30)
    if time_left < 3:
        await asyncio.sleep(time_left + 0.5)

    current_code = totp.now()
    print(f"🔢 Submitting TOTP Code: {current_code}")

    await otc_input.fill(current_code)
    await _try_check_persist_checkbox(page)

    await page.locator('input[type="submit"], input[id="idSIButton9"]').first.click()
    await asyncio.sleep(2.5)

    totp_error = (
        page.locator('text="That code didn\'t work"')
        .or_(page.locator('text="More information required"'))
        .or_(page.locator('#otcError'))
    )
    if await totp_error.is_visible():
        return False, "TOTP_ERROR: Microsoft rejected the code."

    await handle_security_interrupts(page)

    # 6. "STAY SIGNED IN?" PROMPT (Strictly non-blocking)
    try:
        stay_signed_in_btn = page.locator('input[id="idSIButton9"]').or_(page.locator('input[value="Yes"]')).first
        if await stay_signed_in_btn.is_visible(timeout=FAST_TIMEOUT):
            print("✅ Handling 'Stay signed in?' prompt...")
            await _try_check_persist_checkbox(page)
            await stay_signed_in_btn.click(force=True)
    except Exception as e:
        print(f"⏩ Skipped 'Stay Signed in' prompt safely: {e}")

    # 7. VERIFY DASHBOARD REDIRECT
    print("⏳ Waiting for eBwise home dashboard...")
    try:
        await page.wait_for_url(lambda url: "ebwise.mmu.edu.my" in url and "login" not in url, timeout=PAGE_TIMEOUT)
    except Exception:
        return False, "TIMEOUT_ERROR: eBwise dashboard failed to load."

    return True, "Login Successful! Session saved."


async def sync_teams(context):
    print("⏳ [Async] Priming Teams session...")
    try:
        page = await context.new_page()
        await page.goto("https://teams.microsoft.com", timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        print("✅ Teams session primed.")
        await page.close()
    except Exception as e:
        print(f"⚠️ Teams sync skipped/timed out: {e}")


async def sync_outlook(context):
    print("⏳ [Async] Priming Outlook session...")
    try:
        page = await context.new_page()
        await page.goto("https://outlook.office.com/mail/", timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        print("✅ Outlook session primed.")
        await page.close()
    except Exception as e:
        print(f"⚠️ Outlook sync skipped/timed out: {e}")


async def run_daily_login_async(creds: dict, headless: bool = True, force_fresh: bool = False) -> tuple[bool, str]:
    email = creds.get("email")
    password = creds.get("password")
    totp_secret = creds.get("totp_secret", "").replace(" ", "").strip()

    if not email or not password or not totp_secret:
        return False, "Missing credentials."

    max_retries = 3
    last_msg = "Unknown error"

    for attempt in range(1, max_retries + 1):
        print(f"🚀 Starting login pipeline (Attempt {attempt}/{max_retries})...")
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=headless,
                    args=["--disable-blink-features=AutomationControlled"]
                )

                context_kwargs = {
                    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }

                if force_fresh and os.path.exists(SESSION_FILE):
                    os.remove(SESSION_FILE)

                session_authenticated = False
                if not force_fresh and os.path.exists(SESSION_FILE):
                    test_context = await browser.new_context(storage_state=SESSION_FILE, **context_kwargs)
                    test_page = await test_context.new_page()
                    session_authenticated = await is_session_valid(test_page)

                    if session_authenticated:
                        context = test_context
                        last_msg = "Session valid."
                    else:
                        await test_context.close()
                        if os.path.exists(SESSION_FILE):
                            os.remove(SESSION_FILE)

                if not session_authenticated:
                    context = await browser.new_context(**context_kwargs)
                    page = await context.new_page()
                    success, last_msg = await authenticate_with_credentials(page, email, password, totp_secret)

                    if not success:
                        await browser.close()
                        # Short-circuit logic: immediately fail if credentials are wrong.
                        # Only retry if it was a connection/timeout error.
                        if any(err in last_msg for err in ["PASSWORD_ERROR", "EMAIL_ERROR", "TOTP_ERROR"]):
                            return False, last_msg

                        print(f"⚠️ Attempt {attempt} failed due to network/timeout: {last_msg}. Retrying...")
                        continue

                    session_authenticated = True

                if session_authenticated:
                    print("🌐 Synchronizing auth state for Teams and Outlook...")
                    await asyncio.gather(
                        sync_teams(context),
                        sync_outlook(context)
                    )
                    await context.storage_state(path=SESSION_FILE)
                    await browser.close()
                    print(f"💾 Session state saved to {SESSION_FILE}")
                    return True, "Login Successful! Session saved."

        except Exception as e:
            last_msg = f"Crash during attempt {attempt}: {e}"
            print(last_msg)
            await asyncio.sleep(2)

    return False, last_msg


def run_daily_login(creds: dict) -> bool:
    success, _ = asyncio.run(run_daily_login_async(creds, headless=False, force_fresh=False))
    return success