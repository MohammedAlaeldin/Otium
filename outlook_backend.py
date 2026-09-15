import asyncio
import os
import time
import requests
import base64
import tempfile
import json
import re
from html import unescape
from playwright.async_api import async_playwright

from storage import SESSION_FILE


class OutlookBackend:
    """
    Robust Outlook Web API integration using native OWA REST v2 endpoints
    with automatic HTML-to-text cleaning for readable email bodies.
    """

    def __init__(self):
        self.token = None
        self.headers = None
        self.cache_file = os.path.join(tempfile.gettempdir(), "otium_outlook_cache.json")

    def _clean_html_to_text(self, html_content):
        """Strips HTML tags and converts entities into clean, readable plain text."""
        if not html_content:
            return ""
        # Unescape HTML entities (like &nbsp;, &amp;, etc.)
        text = unescape(html_content)
        # Remove script and style blocks
        text = re.sub(r'(?is)<(script|style)[^>]*>.*?</(script|style)>', '', text)
        # Convert breaks and paragraph ends to clean newlines
        text = re.sub(r'(?i)<br\s*/?>', '\n', text)
        text = re.sub(r'(?i)</p>', '\n\n', text)
        text = re.sub(r'(?i)</div>', '\n', text)
        # Strip all remaining HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        # Normalize whitespace and blank lines
        lines = [line.strip() for line in text.splitlines()]
        return '\n'.join(line for line in lines if line)

    def _load_cached_token(self):
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r") as f:
                    data = json.load(f)
                    if data.get("expires_at", 0) > time.time() + 300:
                        self.token = data.get("token")
                        self.headers = {
                            "Authorization": self.token,
                            "Accept": "application/json",
                            "Content-Type": "application/json",
                            "Prefer": 'outlook.body-content-type="text"'
                        }
                        return True
        except Exception:
            pass
        return False

    def _save_cached_token(self, token):
        try:
            with open(self.cache_file, "w") as f:
                json.dump({
                    "token": token,
                    "expires_at": time.time() + 3600
                }, f)
        except Exception:
            pass

    async def _get_token_silently(self):
        if not os.path.exists(SESSION_FILE):
            raise FileNotFoundError(f"Session missing at {SESSION_FILE}! Please log in first.")

        token_future = asyncio.Future()

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
            )
            context = await browser.new_context(
                storage_state=SESSION_FILE,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            async def intercept_headers(request):
                try:
                    auth = request.headers.get("authorization", "")
                    if auth.startswith("Bearer ey") and not token_future.done():
                        if "outlook.office.com" in request.url or "outlook.office365.com" in request.url:
                            token_future.set_result(auth)
                except Exception:
                    pass

            page.on("request", intercept_headers)

            try:
                await page.goto("https://outlook.office.com/mail/", wait_until="domcontentloaded", timeout=30000)
                self.token = await asyncio.wait_for(token_future, timeout=25.0)

                self.headers = {
                    "Authorization": self.token,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Prefer": 'outlook.body-content-type="text"'
                }
                self._save_cached_token(self.token)
            except asyncio.TimeoutError:
                raise Exception("Token capture timed out. The Microsoft server took too long to authenticate.")
            except Exception as e:
                raise Exception(f"Failed to capture token: {str(e)}")
            finally:
                await browser.close()

        return self.token

    def _ensure_auth(self):
        if not self.token:
            if not self._load_cached_token():
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop and loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(self._get_token_silently(), loop)
                    future.result()
                else:
                    asyncio.run(self._get_token_silently())

    def fetch_mail_folders(self):
        self._ensure_auth()
        url = "https://outlook.office.com/api/v2.0/me/mailfolders?$top=50"
        res = requests.get(url, headers=self.headers, timeout=15)

        if res.status_code == 401:
            if os.path.exists(self.cache_file):
                os.remove(self.cache_file)
            self.token = None
            raise Exception("Session expired (401). Cache cleared, please click Refresh again.")

        if res.status_code == 200:
            raw_folders = res.json().get("value", [])
            return {
                f.get("DisplayName", "Unknown"): {
                    "id": f.get("Id"),
                    "unread": f.get("UnreadItemCount", 0),
                    "total": f.get("TotalItemCount", 0)
                } for f in raw_folders
            }
        raise Exception(f"Failed to fetch folders. Status: {res.status_code}")

    def fetch_messages_in_folder(self, folder_id="inbox", limit=20, skip=0):
        self._ensure_auth()

        if not folder_id or folder_id.lower() == "inbox":
            url = f"https://outlook.office.com/api/v2.0/me/mailfolders/inbox/messages?$top={limit}&$skip={skip}"
        else:
            url = f"https://outlook.office.com/api/v2.0/me/messages?$filter=ParentFolderId eq '{folder_id}'&$top={limit}&$skip={skip}"

        res = requests.get(url, headers=self.headers, timeout=15)

        if res.status_code == 200:
            raw_msgs = res.json().get("value", [])
            parsed_msgs = []
            for msg in raw_msgs:
                sender_info = msg.get("Sender", {}).get("EmailAddress", {})
                raw_body = msg.get("Body", {}).get("Content", "")

                parsed_msgs.append({
                    "id": msg.get("Id"),
                    "subject": msg.get("Subject", "(No Subject)"),
                    "sender_name": sender_info.get("Name", "Unknown Sender"),
                    "sender_email": sender_info.get("Address", "Unknown Email"),
                    "time": msg.get("DateTimeReceived", "")[:16].replace("T", " "),
                    "preview": self._clean_html_to_text(msg.get("BodyPreview", ""))[:60],
                    "body": self._clean_html_to_text(raw_body),
                    "is_read": msg.get("IsRead", True),
                    "has_attachments": msg.get("HasAttachments", False)
                })
            return parsed_msgs

        raise Exception(f"Failed to fetch emails. Status: {res.status_code} - {res.text}")

    def search_emails(self, query):
        self._ensure_auth()
        url = f"https://outlook.office.com/api/v2.0/me/messages?$search=\"{query}\"&$top=25"
        res = requests.get(url, headers=self.headers, timeout=15)

        if res.status_code == 200:
            raw_msgs = res.json().get("value", [])
            return [{
                "id": m.get("Id"),
                "subject": m.get("Subject", "(No Subject)"),
                "sender_name": m.get("Sender", {}).get("EmailAddress", {}).get("Name", "Unknown"),
                "sender_email": m.get("Sender", {}).get("EmailAddress", {}).get("Address", "Unknown"),
                "time": m.get("DateTimeReceived", "")[:16].replace("T", " "),
                "preview": self._clean_html_to_text(m.get("BodyPreview", ""))[:60],
                "body": self._clean_html_to_text(m.get("Body", {}).get("Content", "")),
                "is_read": m.get("IsRead", True),
                "has_attachments": m.get("HasAttachments", False)
            } for m in raw_msgs]
        raise Exception(f"Search failed: {res.text}")

    def mark_as_read(self, msg_id, is_read=True):
        self._ensure_auth()
        url = f"https://outlook.office.com/api/v2.0/me/messages/{msg_id}"
        res = requests.patch(url, headers=self.headers, json={"IsRead": is_read}, timeout=10)
        return res.status_code == 200

    def delete_email(self, msg_id):
        self._ensure_auth()
        url = f"https://outlook.office.com/api/v2.0/me/messages/{msg_id}"
        res = requests.delete(url, headers=self.headers, timeout=10)
        return res.status_code in [200, 204]

    def download_attachments(self, msg_id, save_dir):
        self._ensure_auth()
        url = f"https://outlook.office.com/api/v2.0/me/messages/{msg_id}/attachments"
        res = requests.get(url, headers=self.headers, timeout=20)

        if res.status_code != 200:
            raise Exception("Failed to fetch attachments.")

        saved_files = []
        for att in res.json().get("value", []):
            if "ContentBytes" in att:
                safe_name = "".join(c for c in att["Name"] if c.isalnum() or c in (' ', '.', '_', '-')).strip()
                file_path = os.path.join(save_dir, safe_name)
                with open(file_path, "wb") as f:
                    f.write(base64.b64decode(att["ContentBytes"]))
                saved_files.append(file_path)

        return saved_files

    def send_email(self, to_email, subject, body, attachment_paths=None):
        self._ensure_auth()
        msg = {
            "Message": {
                "Subject": subject,
                "Body": {"ContentType": "Text", "Content": body},
                "ToRecipients": [{"EmailAddress": {"Address": to_email.strip()}}]
            }
        }

        if attachment_paths:
            attachments = []
            for path in attachment_paths:
                if os.path.exists(path):
                    with open(path, "rb") as f:
                        b64_content = base64.b64encode(f.read()).decode('utf-8')
                    attachments.append({
                        "@odata.type": "#Microsoft.OutlookServices.FileAttachment",
                        "Name": os.path.basename(path),
                        "ContentBytes": b64_content
                    })
            msg["Message"]["Attachments"] = attachments

        res = requests.post("https://outlook.office.com/api/v2.0/me/sendmail", headers=self.headers, json=msg,
                            timeout=20)
        if res.status_code not in [200, 202]:
            raise Exception(f"Failed to send email. Status: {res.status_code} - {res.text}")
        return True