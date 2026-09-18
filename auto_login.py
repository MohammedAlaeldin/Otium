import asyncio
import os
import time
import pyotp
from playwright.async_api import async_playwright

from storage import SESSION_FILE


async def is_session_valid(page) -> bool:
    """Navigates straight to eBwise (/my/). If valid, loads without login prompts."""
    try:
        print("🌐 Navigating straight to eBwise Dashboard (/my/)...")
        await page.goto("https://ebwise.mmu.edu.my/my/", timeout=20000)
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(1.5)

        current_url = page.url

        if any(keyword in current_url for keyword in ["login", "microsoftonline", "openid"]):
            print("🔑 Existing cookies expired or invalid. Full re-auth needed.")
            return False

        if "ebwise.mmu.edu.my" in current_url:
            print("🟢 Active session detected! Reusing existing cookies instantly.")
            return True

    except Exception as e:
        print(f"⚠️ Session check issue: {e}")
    return False


async def handle_security_interrupts(page):
    """Bypasses Microsoft passkey prompts, 'Make your account secure', or 'Skip for now' screens."""
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
            if await checkbox.is_visible(timeout=1000):
                if not await checkbox.is_checked():
                    await checkbox.check(force=True)
                    print(f"☑️ Checked persistence checkbox: {sel}")
                    await asyncio.sleep(0.5)  # Let JS register checked state
                return True
        except Exception:
            continue

    # Fallback targeting label text specifically containing '1 day' or 'don't ask'
    try:
        label = page.locator("text=/don't ask again|1 day|don't show this again/i").first
        if await label.is_visible(timeout=1000):
            await label.click(force=True)
            print("☑️ Checked persistence checkbox via '1 day' label click")
            await asyncio.sleep(0.5)
            return True
    except Exception:
        pass

    return False


async def authenticate_with_credentials(page, email: str, password: str, totp_secret: str) -> bool:
    """State-driven Microsoft 2FA login flow."""
    totp = pyotp.TOTP(totp_secret)

    await page.goto("https://ebwise.mmu.edu.my/login/index.php", timeout=30000)

    # Trigger Microsoft SSO if on local eBwise page
    if "microsoftonline.com" not in page.url:
        try:
            await page.click('text="Microsoft 365"', timeout=3000)
        except Exception:
            try:
                await page.click('text="OpenID Connect"', timeout=2000)
            except Exception:
                pass

    await asyncio.sleep(2)
    if "ebwise.mmu.edu.my" in page.url and "login" not in page.url:
        return True

    # Check for Account Picker Tile (e.g. remembered email)
    try:
        account_tile = page.locator(f'div[data-test-id="{email}"], text="{email}"').first
        if await account_tile.is_visible(timeout=2000):
            print("👤 Clicking remembered account tile...")
            await account_tile.click()
            await asyncio.sleep(1.5)
    except Exception:
        pass

    # State Check: Is Email Step actually visible?
    email_field = page.locator('input[type="email"]:visible, input[name="loginfmt"]:visible').first
    password_field = page.locator('input[type="password"]:visible, input[name="passwd"]:visible').first

    if await email_field.is_visible(timeout=2000) and not await password_field.is_visible(timeout=500):
        print("📧 Filling email field...")
        await email_field.fill(email)
        await page.click('input[type="submit"], input[id="idSIButton9"]')
        await asyncio.sleep(2)

    await handle_security_interrupts(page)

    # Password Step
    password_field = page.locator('input[type="password"]:visible, input[name="passwd"]:visible').first
    try:
        await password_field.wait_for(state="visible", timeout=8000)
        print("🔑 Filling password field...")
        await password_field.fill(password)
        await page.click('input[type="submit"], input[id="idSIButton9"]')
        await asyncio.sleep(2.5)
    except Exception:
        if "ebwise.mmu.edu.my" in page.url and "login" not in page.url:
            return True

    await handle_security_interrupts(page)

    # 2FA Option Selection
    for text_sel in [
        'text="I can\'t use my Microsoft Authenticator app right now"',
        'text="Use a verification code"',
        'text=/verification code/i'
    ]:
        try:
            opt = page.locator(text_sel).first
            if await opt.is_visible(timeout=2000):
                await opt.click()
                await asyncio.sleep(1)
        except Exception:
            pass

    otc_input = page.locator('input[name="otc"]:visible').first
    await otc_input.wait_for(state="visible", timeout=10000)

    # TOTP timing check
    time_left = 30 - (int(time.time()) % 30)
    if time_left < 3:
        await asyncio.sleep(time_left + 0.5)

    print(f"🔢 Submitting TOTP Code: {totp.now()}")
    await otc_input.fill(totp.now())

    # Check "Don't ask again for 1 day"
    await _try_check_persist_checkbox(page)

    await page.click('input[type="submit"], input[id="idSIButton9"]')
    await asyncio.sleep(3)

    await handle_security_interrupts(page)

    # "Stay signed in?" Prompt
    try:
        stay_btn = page.locator('input[id="idSIButton9"], input[value="Yes"]').first
        if await stay_btn.is_visible(timeout=3000):
            await _try_check_persist_checkbox(page)
            await stay_btn.click()
    except Exception:
        pass

    await page.wait_for_url(lambda url: "ebwise.mmu.edu.my" in url and "login" not in url, timeout=20000)
    return True


async def sync_teams(context):
    print("⏳ [Async] Priming Teams session...")
    try:
        page = await context.new_page()
        await page.goto("https://teams.microsoft.com", timeout=45000, wait_until="domcontentloaded")
        try:
            await page.wait_for_url(lambda url: "teams.microsoft.com" in url or "teams.live.com" in url, timeout=15000)
        except Exception:
            pass
        await asyncio.sleep(3)
        print("✅ Teams authentication state primed.")
        await page.close()
    except Exception as e:
        print(f"⚠️ Teams sync warning: {e}")


async def sync_outlook(context):
    print("⏳ [Async] Priming Outlook session...")
    try:
        page = await context.new_page()
        await page.goto("https://outlook.office.com/mail/", timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        print("✅ Outlook authentication state primed.")
        await page.close()
    except Exception as e:
        print(f"⚠️ Outlook sync warning: {e}")


async def run_daily_login_async(creds: dict) -> bool:
    email = creds.get("email")
    password = creds.get("password")
    totp_secret = creds.get("totp_secret", "").replace(" ", "").strip()

    if not email or not password or not totp_secret:
        return False

    print("🚀 Starting daily auto-login process (Parallel Sync)...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )

        base_context_kwargs = {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        # 1. Test Existing Session (If it exists)
        session_authenticated = False
        if os.path.exists(SESSION_FILE):
            print(f"📁 Found existing {SESSION_FILE}, testing session validity...")
            test_context = await browser.new_context(storage_state=SESSION_FILE, **base_context_kwargs)
            test_page = await test_context.new_page()

            session_authenticated = await is_session_valid(test_page)

            if session_authenticated:
                context = test_context # Keep using this context
            else:
                print("🗑️ Session expired. Nuking old session data to start completely fresh...")
                await test_context.close()
                os.remove(SESSION_FILE) # Delete the bad cookie file

        # 2. Perform Fresh Login if needed
        if not session_authenticated:
            print("✨ Spawning pristine browser context for a clean login...")
            # Notice we do NOT pass storage_state here, ensuring a 100% clean browser
            context = await browser.new_context(**base_context_kwargs)
            page = await context.new_page()

            try:
                session_authenticated = await authenticate_with_credentials(page, email, password, totp_secret)
            except Exception as e:
                print(f"❌ Login sequence failed: {e}")
                await browser.close()
                return False

        # 3. Sync and Save
        if session_authenticated:
            print("🌐 Synchronizing auth state with Microsoft Teams and Outlook concurrently...")
            await asyncio.gather(
                sync_teams(context),
                sync_outlook(context)
            )

            await context.storage_state(path=SESSION_FILE)
            await browser.close()
            print(f"💾 All sessions successfully updated and saved to {SESSION_FILE}!")
            return True

        await browser.close()
        return False
#try 2
def run_daily_login(creds: dict) -> bool:
    return asyncio.run(run_daily_login_async(creds))

