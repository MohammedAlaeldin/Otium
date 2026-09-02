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
        response = await page.goto("https://ebwise.mmu.edu.my/my/", timeout=20000)
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(1.5)

        current_url = page.url

        # Check if URL redirected to login or Microsoft Auth
        if "login" in current_url or "microsoftonline" in current_url or "openid" in current_url:
            print("🔑 Existing cookies expired or invalid. Full re-auth needed.")
            return False

        if "ebwise.mmu.edu.my" in current_url:
            print("🟢 Active session detected! Reusing existing cookies instantly.")
            return True

    except Exception as e:
        print(f"⚠️ Session check issue: {e}")
    return False
async def sync_teams(context):
    """Fast-sync Teams auth: Waits for the final domain redirect without waiting for heavy UI rendering."""
    print("⏳ [Async] Priming Teams session...")
    try:
        page = await context.new_page()
        # Navigate to Teams
        await page.goto("https://teams.microsoft.com", timeout=45000, wait_until="domcontentloaded")

        # Smart Wait: Wait until URL leaves Microsoft Login and reaches Teams domain
        try:
            await page.wait_for_url(lambda url: "teams.microsoft.com" in url or "teams.live.com" in url, timeout=15000)
        except Exception:
            pass  # Fallback if already on URL

        # Short buffer to allow IndexedDB token writes
        await asyncio.sleep(3)
        print("✅ Teams authentication state primed.")
        await page.close()
    except Exception as e:
        print(f"⚠️ Teams sync warning: {e}")


async def sync_outlook(context):
    """Fast-sync Outlook Mail auth cookies."""
    print("⏳ [Async] Priming Outlook session...")
    try:
        page = await context.new_page()
        await page.goto("https://outlook.office.com/mail/", timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        print("✅ Outlook authentication state primed.")
        await page.close()
    except Exception as e:
        print(f"⚠️ Outlook sync warning: {e}")


async def authenticate_with_credentials(page, email: str, password: str, totp_secret: str) -> bool:
    """Full Microsoft 2FA login flow if session is expired or missing."""
    totp = pyotp.TOTP(totp_secret)

    await page.goto("https://ebwise.mmu.edu.my/login/index.php", timeout=30000)

    if "microsoftonline.com" not in page.url:
        try:
            await page.click('text="Microsoft 365"', timeout=4000)
        except Exception:
            try:
                await page.click('text="OpenID Connect"', timeout=3000)
            except Exception:
                pass

    await asyncio.sleep(2)
    if "ebwise.mmu.edu.my" in page.url and "login" not in page.url:
        print("⚡ SSO session automatically restored!")
        return True

    # Email Step
    try:
        await page.wait_for_selector('input[type="email"], input[name="loginfmt"]', timeout=8000)
        await page.fill('input[type="email"], input[name="loginfmt"]', email)
        await page.click('input[type="submit"], input[id="idSIButton9"]')
        await asyncio.sleep(2)
    except Exception:
        if "ebwise.mmu.edu.my" in page.url and "login" not in page.url:
            return True

    # Password Step
    try:
        await page.wait_for_selector('input[type="password"], input[name="passwd"]', timeout=8000)
        await page.fill('input[type="password"], input[name="passwd"]', password)
        await page.click('input[type="submit"], input[id="idSIButton9"]')
        await asyncio.sleep(2.5)
    except Exception:
        if "ebwise.mmu.edu.my" in page.url and "login" not in page.url:
            return True

    # 2FA Step
    try:
        await page.click('text="I can\'t use my Microsoft Authenticator app right now"', timeout=3000)
        await asyncio.sleep(1)
    except Exception:
        pass

    try:
        await page.click('text="Use a verification code"', timeout=3000)
        await asyncio.sleep(1)
    except Exception:
        pass

    try:
        if not await page.is_visible('input[name="otc"]'):
            await page.click('text=/verification code/i', timeout=3000)
    except Exception:
        pass

    await page.wait_for_selector('input[name="otc"]', timeout=10000)

    time_left = 30 - (int(time.time()) % 30)
    if time_left < 3:
        await asyncio.sleep(time_left + 0.5)

    await page.fill('input[name="otc"]', totp.now())
    await page.click('input[type="submit"], input[id="idSIButton9"]')
    await asyncio.sleep(3)

    try:
        if await page.is_visible('input[id="idSIButton9"]'):
            await page.click('input[id="idSIButton9"]')
    except Exception:
        pass

    await page.wait_for_url(lambda url: "ebwise.mmu.edu.my" in url and "login" not in url, timeout=20000)
    return True


async def run_daily_login_async(creds: dict) -> bool:
    email = creds.get("email")
    password = creds.get("password")
    totp_secret = creds.get("totp_secret", "").replace(" ", "").strip()

    if not email or not password or not totp_secret:
        return False

    print("🚀 Starting daily auto-login process (Parallel Sync)...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)

        context_kwargs = {}
        if os.path.exists(SESSION_FILE):
            print(f"📁 Found existing {SESSION_FILE}, testing session validity...")
            context_kwargs["storage_state"] = SESSION_FILE

        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        session_authenticated = False

        if "storage_state" in context_kwargs:
            session_authenticated = await is_session_valid(page)

        if not session_authenticated:
            print("🔑 Session expired or missing. Executing login sequence...")
            try:
                session_authenticated = await authenticate_with_credentials(page, email, password, totp_secret)
            except Exception as e:
                print(f"❌ Login sequence failed: {e}")
                await browser.close()
                return False

        if session_authenticated:
            print("🌐 Synchronizing auth state with Microsoft Teams and Outlook concurrently...")

            # RUN TEAMS AND OUTLOOK AT THE EXACT SAME TIME
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


# Synchronous wrapper for easy execution from main.py
def run_daily_login(creds: dict) -> bool:
    return asyncio.run(run_daily_login_async(creds))