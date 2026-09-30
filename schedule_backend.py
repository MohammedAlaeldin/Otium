import asyncio
import os
from playwright.async_api import async_playwright
from storage import SESSION_FILE

LOGIN_URL = "https://clic.mmu.edu.my/psp/csprd/?cmd=login"

async def fetch_raw_schedule():
    if not os.path.exists(SESSION_FILE):
        return {"error": "No saved Microsoft session found. Please log in via the main app first."}

    async with async_playwright() as p:
        # Running headless so the user doesn't see the popup
        browser = await p.chromium.launch(headless=True, args=["--start-maximized", "--disable-gpu"])
        context = await browser.new_context(
            storage_state=SESSION_FILE,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            sso_button = page.locator("button[title='Sign in with Microsoft']").or_(
                page.locator("button[onclick*='oauth_signin']")
            ).first

            if await sso_button.is_visible(timeout=5000):
                await sso_button.click()
            else:
                await page.evaluate("() => { if (typeof oauth_signin === 'function') oauth_signin(document.forms[0]); }")

            await page.wait_for_timeout(2500)

            try:
                account_tile = (
                    page.locator("text='Signed in'")
                    .or_(page.locator("div[data-test-id='table-row']"))
                    .or_(page.locator(".tile-container"))
                ).first

                if await account_tile.is_visible(timeout=5000):
                    await account_tile.click()
            except Exception:
                pass

            await page.wait_for_url("**/c/NUI_FRAMEWORK.PT_LANDINGPAGE.**", timeout=30000)
            await page.wait_for_timeout(3000)

            await page.get_by_text("Class Schedule", exact=True).first.click()
            await page.wait_for_timeout(3000)

            await page.locator("text=/View My Classes/i").first.click()
            await page.wait_for_timeout(3000)

            await page.locator("text=/By Date/i").first.click()
            await page.wait_for_timeout(5000)

            raw_text = await page.evaluate("""() => {
                const container = document.querySelector('.ps_pagecontainer') || document.body;
                return container.innerText;
            }""")

            return {"status": "success", "data": raw_text}

        except Exception as e:
            return {"error": str(e)}
        finally:
            await browser.close()