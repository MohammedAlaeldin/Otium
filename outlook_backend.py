import asyncio
import os
import requests
from playwright.async_api import async_playwright

SESSION_FILE = "session.json"


class SimpleOutlookBackend:
    def __init__(self):
        self.token = None

    async def _get_token_silently(self):
        """Intercepts the Bearer token in the background."""
        if not os.path.exists(SESSION_FILE):
            raise FileNotFoundError("session.json missing! Please log in first.")

        token_future = asyncio.Future()
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(storage_state=SESSION_FILE)
            page = await context.new_page()

            async def intercept_headers(request):
                auth = request.headers.get("authorization", "")
                if auth.startswith("Bearer ey") and not token_future.done():
                    if "graph.microsoft.com" in request.url or "outlook.office.com" in request.url:
                        token_future.set_result(auth)

            page.on("request", intercept_headers)
            await page.goto("https://outlook.office.com/mail/", wait_until="domcontentloaded", timeout=25000)

            try:
                self.token = await asyncio.wait_for(token_future, timeout=12.0)
            except asyncio.TimeoutError:
                raise Exception("Token capture timed out.")
            finally:
                await browser.close()
        return self.token

    def fetch_recent_emails(self, limit=10):
        """Fetches emails from Microsoft Graph API using the token."""
        # Grab token if we don't have it yet
        if not self.token:
            asyncio.run(self._get_token_silently())

        endpoint = f"https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages?$top={limit}&$select=subject,sender,receivedDateTime,bodyPreview"
        headers = {"Authorization": self.token, "Accept": "application/json"}

        # Try Graph API
        res = requests.get(endpoint, headers=headers, timeout=10)

        # Fallback to REST v2.0 if Graph fails
        if res.status_code != 200:
            endpoint = f"https://outlook.office.com/api/v2.0/me/mailFolders/inbox/messages?$top={limit}&$select=Subject,Sender,ReceivedDateTime,BodyPreview"
            res = requests.get(endpoint, headers=headers, timeout=10)

        if res.status_code == 200:
            return res.json().get("value", [])
        else:
            raise Exception(f"API Error {res.status_code}: {res.text}")
