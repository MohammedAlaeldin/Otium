import asyncio
import os
import re
from datetime import datetime
from playwright.async_api import async_playwright
from storage import SESSION_FILE

LOGIN_URL = "https://clic.mmu.edu.my/psp/csprd/?cmd=login"


NO_DATA_PATTERNS = [
    r"no matching values were found",
    r"you do not have any scheduled classes",
    r"no classes (were )?found",
    r"no classes (are )?scheduled",
    r"no rows returned",
]


async def _read_from_to_dates(frame):
    """Reads the two date text boxes (From, To — left to right as shown on the page)
    and returns their raw text values, or (None, None) if they can't be found."""
    try:
        values = await frame.evaluate("""
            () => {
                const inputs = Array.from(document.querySelectorAll('input[type="text"]'))
                    .filter(el => /^\\d{2}\\/\\d{2}\\/\\d{4}$/.test(el.value.trim()));
                return inputs.slice(0, 2).map(el => el.value.trim());
            }
        """)
        if len(values) == 2:
            return values[0], values[1]
    except Exception:
        pass
    return None, None


async def fetch_raw_schedule():
    if not os.path.exists(SESSION_FILE):
        return {"error": "auth"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-gpu"])
        context = await browser.new_context(
            storage_state=SESSION_FILE,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            # 1. Login & Authentication
            await page.goto(LOGIN_URL, wait_until="networkidle", timeout=25000)

            sso_button = page.locator("button[title='Sign in with Microsoft']").or_(
                page.locator("button[onclick*='oauth_signin']")
            ).first
            if await sso_button.is_visible(timeout=5000):
                await sso_button.click()
            else:
                await page.evaluate(
                    "() => { if (typeof oauth_signin === 'function') oauth_signin(document.forms[0]); }")

            account_tile = page.locator("div[role='button'], div.table-row, div.tile-container, div.tile").filter(
                has_text=re.compile(r"student\.mmu\.edu\.my|Signed in", re.IGNORECASE)
            ).first
            try:
                await account_tile.wait_for(state="visible", timeout=10000)
                await account_tile.click()
            except Exception:
                pass

            try:
                stay_btn = page.locator("input[value='Yes'], input[value='No'], #idSIButton9").first
                if await stay_btn.is_visible(timeout=4000):
                    await stay_btn.click()
            except Exception:
                pass

            # 2. Navigate to Clic Dashboard -> Class Schedule
            await page.wait_for_url("**/c/NUI_FRAMEWORK.PT_LANDINGPAGE.**", timeout=25000)
            await page.wait_for_load_state("networkidle", timeout=15000)
            await asyncio.sleep(2)

            class_sched_tile = page.get_by_text("Class Schedule", exact=True).last
            await class_sched_tile.wait_for(state="visible", timeout=10000)
            await class_sched_tile.click()

            await page.wait_for_load_state("networkidle", timeout=15000)
            await asyncio.sleep(2)

            frame = page.frame(name="TargetContent") or page.frame(name="ptifrmtgtframe") or page.main_frame

            menu_item = frame.locator("text=/View My Classes/i").first
            await menu_item.wait_for(state="visible", timeout=15000)
            await menu_item.click()

            await page.wait_for_load_state("networkidle", timeout=15000)


            by_date_btn = frame.locator("text=/By Date|List View/i").first
            await by_date_btn.wait_for(state="visible", timeout=10000)
            await by_date_btn.click()
            await page.wait_for_load_state("networkidle", timeout=8000)
            await asyncio.sleep(2)


            needs_extension = True
            from_str, to_str = await _read_from_to_dates(frame)
            if from_str and to_str:
                for fmt in ("%d/%m/%Y", "%m/%d/%Y"):
                    try:
                        from_dt = datetime.strptime(from_str, fmt)
                        to_dt = datetime.strptime(to_str, fmt)
                        needs_extension = (to_dt - from_dt).days != 7
                        break
                    except ValueError:
                        continue

            if needs_extension:
                try:
                    # Find all calendar icons; the 'To' date is typically the second one
                    cal_btns = frame.locator(
                        "img[src*='PT_CALENDAR'], a[id*='prompt'], img[alt*='Calendar'], img[alt*='Choose a date']")
                    if await cal_btns.count() >= 2:
                        await cal_btns.nth(1).click()
                    elif await cal_btns.count() == 1:
                        await cal_btns.first.click()

                    await page.wait_for_timeout(1500)  # Wait for the popup widget to render

                    # Simulate pressing the Right Arrow 7 times
                    for _ in range(7):
                        await page.keyboard.press("ArrowRight")
                        await asyncio.sleep(0.1)

                    # Hit Enter to lock in the date
                    await page.keyboard.press("Enter")

                    # Allow the grid to refresh with the newly requested week of data
                    await page.wait_for_timeout(4000)
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass  # If it fails, we fall back to extracting whatever is already visible

            # 5. Extract all readable text from the frames
            raw_text = await page.evaluate("document.body.innerText")
            for f in page.frames:
                try:
                    raw_text += "\n" + await f.evaluate("document.body.innerText")
                except Exception:
                    pass

            lower_text = raw_text.lower()
            for pattern in NO_DATA_PATTERNS:
                if re.search(pattern, lower_text):
                    # Surface CLIC's own wording where we can find the exact line,
                    # rather than a guessed generic message.
                    for line in raw_text.splitlines():
                        if re.search(pattern, line.lower()):
                            return {"status": "empty", "message": line.strip()}
                    return {"status": "empty", "message": "No classes were found for this period."}

            return {"status": "success", "data": raw_text}

        except Exception:
            return {"error": "network"}
        finally:
            await browser.close()