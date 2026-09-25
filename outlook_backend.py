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
    def __init__(self):
        self.token = None
        self.headers = None
        self.cache_file = os.path.join(tempfile.gettempdir(), "otium_outlook_cache.json")

    def _generate_preview(self, html_content):
        """Used ONLY for the small preview text on the left sidebar."""
        if not html_content:
            return ""
        text = unescape(html_content)
        text = re.sub(r'(?is)<(script|style)[^>]*>.*?</(script|style)>', '', text)
        text = re.sub(r'<[^>]+>', ' ', text)
        lines = [line.strip() for line in text.splitlines()]
        return ' '.join(line for line in lines if line)

    def _strip_mobile_signatures(self, html_content):
        """Removes annoying Outlook mobile signatures."""
        if not html_content:
            return ""
        # Strip HTML div wrappers containing the signature
        html = re.sub(r'(?is)<div[^>]*>\s*Get Outlook for (iOS|Android).*?</div>', '', html_content)
        html = re.sub(r'(?is)<div[^>]*>\s*Sent from Outlook for (iOS|Android).*?</div>', '', html)
        # Strip plaintext equivalents just in case
        html = re.sub(r'(?i)Get Outlook for (iOS|Android)', '', html)
        html = re.sub(r'(?i)Sent from Outlook for (iOS|Android)', '', html)
        return html

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
                            "Prefer": 'outlook.body-content-type="html"'  # Changed to HTML for rich text formatting
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
                    "Prefer": 'outlook.body-content-type="html"' # Enforce HTML response
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
                clean_html_body = self._strip_mobile_signatures(raw_body)

                parsed_msgs.append({
                    "id": msg.get("Id"),
                    "subject": msg.get("Subject", "(No Subject)"),
                    "sender_name": sender_info.get("Name", "Unknown Sender"),
                    "sender_email": sender_info.get("Address", "Unknown Email"),
                    "to_recipients": [r.get("EmailAddress", {}).get("Name", r.get("EmailAddress", {}).get("Address", "")) for r in msg.get("ToRecipients", [])],
                    "cc_recipients": [r.get("EmailAddress", {}).get("Name", r.get("EmailAddress", {}).get("Address", "")) for r in msg.get("CcRecipients", [])],
                    "time": msg.get("DateTimeReceived", "")[:16].replace("T", " "),
                    "preview": self._generate_preview(msg.get("BodyPreview", ""))[:60],
                    "body": clean_html_body,
                    "is_read": msg.get("IsRead", True),
                    "has_attachments": msg.get("HasAttachments", False)
                })
            return parsed_msgs
        raise Exception(f"Failed to fetch emails. Status: {res.status_code} - {res.text}")

    def search_emails(self, query):
        self._ensure_auth()
        url = f"https://outlook.office.com/api/v2.0/me/messages?$search={query}&$top=25"
        res = requests.get(url, headers=self.headers, timeout=15)

        if res.status_code == 200:
            raw_msgs = res.json().get("value", [])
            return [{
                "id": m.get("Id"),
                "subject": m.get("Subject", "(No Subject)"),
                "sender_name": m.get("Sender", {}).get("EmailAddress", {}).get("Name", "Unknown"),
                "sender_email": m.get("Sender", {}).get("EmailAddress", {}).get("Address", "Unknown"),
                "to_recipients": [r.get("EmailAddress", {}).get("Name", r.get("EmailAddress", {}).get("Address", "")) for r in m.get("ToRecipients", [])],
                "cc_recipients": [r.get("EmailAddress", {}).get("Name", r.get("EmailAddress", {}).get("Address", "")) for r in m.get("CcRecipients", [])],
                "time": m.get("DateTimeReceived", "")[:16].replace("T", " "),
                "preview": self._generate_preview(m.get("BodyPreview", ""))[:60],
                "body": self._strip_mobile_signatures(m.get("Body", {}).get("Content", "")),
                "is_read": m.get("IsRead", True),
                "has_attachments": m.get("HasAttachments", False)
            } for m in raw_msgs]
        raise Exception(f"Search failed: {res.text}")

    def mark_as_read(self, msg_id, is_read=True):
        self._ensure_auth()
        url = f"https://outlook.office.com/api/v2.0/me/messages/{msg_id}"
        res = requests.patch(url, headers=self.headers, json={"IsRead": is_read}, timeout=10)
        return res.status_code == 200

    def fetch_attachments_metadata(self, msg_id):
        self._ensure_auth()
        url = f"https://outlook.office.com/api/v2.0/me/messages/{msg_id}/attachments?$select=Id,Name,Size,ContentType"
        res = requests.get(url, headers=self.headers, timeout=15)
        if res.status_code == 200:
            return res.json().get("value", [])
        return []

    def download_single_attachment(self, msg_id, attachment_id, save_dir):
        self._ensure_auth()
        url = f"https://outlook.office.com/api/v2.0/me/messages/{msg_id}/attachments/{attachment_id}"
        res = requests.get(url, headers=self.headers, timeout=20)
        if res.status_code == 200:
            att = res.json()
            if "ContentBytes" in att:
                safe_name = "".join(c for c in att["Name"] if c.isalnum() or c in (' ', '.', '_', '-')).strip()
                if not safe_name: safe_name = f"attachment_{attachment_id}.bin"
                file_path = os.path.join(save_dir, safe_name)
                with open(file_path, "wb") as f:
                    f.write(base64.b64decode(att["ContentBytes"]))
                return file_path
        raise Exception(f"Failed to download attachment. HTTP {res.status_code}")

    def send_email(self, to_email, subject, body, attachment_paths=None):
        self._ensure_auth()
        msg = {
            "Message": {
                "Subject": subject,
                "Body": {"ContentType": "HTML", "Content": body},
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

        res = requests.post("https://outlook.office.com/api/v2.0/me/sendmail", headers=self.headers, json=msg, timeout=20)
        if res.status_code not in [200, 202]:
            raise Exception(f"Failed to send email. Status: {res.status_code} - {res.text}")
        return True

    def get_homepage_data():
        # Return your list of emails here
        return []
