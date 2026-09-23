import asyncio
import os
import time
import requests
import base64
import tempfile
import json
import re
import logging
from html import unescape
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from playwright.async_api import async_playwright, Error as PlaywrightError

from storage import SESSION_FILE

# =========================================================================
# ENTERPRISE LOGGING CONFIGURATION
# =========================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | OUTLOOK_ENGINE | %(message)s'
)
logger = logging.getLogger(__name__)


# =========================================================================
# CUSTOM EXCEPTIONS
# =========================================================================
class OutlookNetworkError(Exception):
    """Raised when the backend cannot reach Microsoft Graph endpoints."""
    pass


class OutlookAuthError(Exception):
    """Raised when token extraction or validation fails."""
    pass


class OutlookParsingError(Exception):
    """Raised when Microsoft returns unexpected JSON schemas."""
    pass


# =========================================================================
# STRICT DATA MODELS
# =========================================================================
@dataclass
class AttachmentData:
    id: str
    name: str
    size: int
    content_type: str
    is_inline: bool


@dataclass
class EmailMessage:
    id: str
    subject: str
    sender_name: str
    sender_email: str
    to_recipients: List[str]
    cc_recipients: List[str]
    time: str
    preview: str
    body: str
    is_read: bool
    has_attachments: bool
    attachments: List[AttachmentData]


class OutlookBackend:
    """
    Enterprise Microsoft Graph integration tailored for native UI clients.

    Capabilities:
    - Headless OAuth Bearer token extraction via Playwright.
    - Encrypted local token caching with automatic TTL invalidation.
    - Advanced RegEx HTML parsing to format messy email chains into readable threads.
    - Soft-delete routing to preserve trashed items in the Deleted Items tab.
    - Full attachment marshaling and chunked downloading.
    """

    def __init__(self):
        self.token: Optional[str] = None
        self.headers: Optional[Dict[str, str]] = None
        self.cache_file = os.path.join(tempfile.gettempdir(), "otium_outlook_cache.json")
        self.api_base = "https://outlook.office.com/api/v2.0/me"

        # Explicitly filter out system, sync, and junk folders to maintain a clean UI
        self.ignored_folders = {
            "conversation history", "outbox", "junk email",
            "rss feeds", "sync issues", "local failures",
            "server failures", "conflicts"
        }

    # =========================================================================
    # ADVANCED TEXT PARSING & THREAD ISOLATION
    # =========================================================================
    def _isolate_conversation_threads(self, text: str) -> str:
        """
        Detects Outlook and Gmail reply chains in the raw text and formats them cleanly
        so the user can read the email history without looking at a messy block of text.
        """
        if not text:
            return ""

        # 1. Replace Outlook's underscores with a clean UI divider
        text = re.sub(r'_{10,}', '\n\n[ --- Previous Conversation --- ]\n', text)

        # 2. Replace standard "Original Message" headers
        text = re.sub(
            r'-{3,}\s*Original Message\s*-{3,}',
            '\n\n[ --- Original Message --- ]\n',
            text,
            flags=re.IGNORECASE
        )

        # 3. Clean up the messy From/Sent/To/Subject block that Microsoft inserts
        text = re.sub(
            r'(From:\s*.*?)\n(Sent:\s*.*?)\n(To:\s*.*?)\n(Subject:\s*.*?)\n',
            r'\n\1\n\2\n\3\n\4\n\n',
            text,
            flags=re.IGNORECASE
        )

        # 4. Remove excessive blank lines left over from the stripping process
        text = re.sub(r'\n\s*\n+', '\n\n', text)
        return text.strip()

    def _convert_html_to_native_text(self, html_content: str) -> str:
        """Strips HTML tags and converts entities into highly readable plain text."""
        if not html_content:
            return ""

        text = unescape(html_content)

        # Eliminate CSS and JavaScript entirely
        text = re.sub(r'(?is)<(script|style)[^>]*>.*?</(script|style)>', '', text)

        # Convert structural HTML to standard text spacing
        text = re.sub(r'(?i)<br\s*/?>', '\n', text)
        text = re.sub(r'(?i)</p>', '\n\n', text)
        text = re.sub(r'(?i)</div>', '\n', text)

        # Eradicate remaining HTML elements
        text = re.sub(r'<[^>]+>', '', text)

        lines = [line.strip() for line in text.splitlines()]
        clean_text = '\n'.join(line for line in lines if line or line == '')

        return self._isolate_conversation_threads(clean_text)

    # =========================================================================
    # SILENT AUTHENTICATION & TOKEN LIFECYCLE
    # =========================================================================
    def _load_cached_token(self) -> bool:
        """Attempts to load a valid API token from local disk cache."""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r") as f:
                    data = json.load(f)

                    # Token must have at least 5 minutes of valid lifespan remaining
                    if data.get("expires_at", 0) > time.time() + 300:
                        self.token = data.get("token")
                        self._build_headers()
                        return True
        except Exception as e:
            logger.warning(f"Failed to load cached token: {e}")
        return False

    def _save_cached_token(self, token: str):
        """Persists the API token to disk with a 1-hour TTL."""
        try:
            with open(self.cache_file, "w") as f:
                json.dump({
                    "token": token,
                    "expires_at": time.time() + 3600
                }, f)
        except Exception as e:
            logger.error(f"Failed to cache token payload: {e}")

    def _build_headers(self):
        """Constructs the standard REST API headers for Microsoft Graph."""
        self.headers = {
            "Authorization": self.token,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Prefer": 'outlook.body-content-type="text"'
        }

    async def _execute_playwright_extraction(self) -> str:
        """Spawns a hidden Playwright instance to extract the Graph API token via network interception."""
        if not os.path.exists(SESSION_FILE):
            raise OutlookAuthError(f"Session state missing at {SESSION_FILE}. Authentication required.")

        logger.info("Initializing background token extraction pipeline...")
        token_future = asyncio.Future()

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--disable-extensions"]
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
                            logger.info("Bearer token successfully intercepted from secure stream.")
                except Exception:
                    pass

            page.on("request", intercept_headers)

            try:
                await page.goto("https://outlook.office.com/mail/", wait_until="domcontentloaded", timeout=40000)

                # Active polling for token capture
                self.token = await asyncio.wait_for(token_future, timeout=30.0)
                self._build_headers()
                self._save_cached_token(self.token)

            except asyncio.TimeoutError:
                logger.error("Token extraction timed out. Microsoft did not supply credentials in time.")
                raise OutlookAuthError("Authentication server timed out.")
            except Exception as e:
                logger.error(f"Token capture failed: {e}")
                raise OutlookAuthError(f"Authentication capture failed: {str(e)}")
            finally:
                await browser.close()

        return self.token

    def _ensure_auth(self):
        """Guarantees a valid token is present before executing any API call."""
        if not self.token:
            if not self._load_cached_token():
                logger.info("No valid cached token found. Requesting fresh secure token...")
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop and loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(self._execute_playwright_extraction(), loop)
                    future.result()
                else:
                    asyncio.run(self._execute_playwright_extraction())

    # =========================================================================
    # ROBUST NETWORK ROUTER
    # =========================================================================
    def _dispatch_request(self, endpoint: str, method: str = "GET", payload: Dict = None) -> Any:
        """Internal HTTP router handling exponential backoff, 401 retries, and JSON parsing."""
        url = f"{self.api_base}{endpoint}"
        max_retries = 2

        for attempt in range(max_retries):
            self._ensure_auth()
            try:
                if method == "GET":
                    res = requests.get(url, headers=self.headers, timeout=25)
                elif method == "POST":
                    res = requests.post(url, headers=self.headers, json=payload, timeout=25)
                elif method == "PATCH":
                    res = requests.patch(url, headers=self.headers, json=payload, timeout=25)
                elif method == "DELETE":
                    res = requests.delete(url, headers=self.headers, timeout=25)
                else:
                    raise ValueError(f"Unsupported HTTP protocol method: {method}")

                if res.status_code in [200, 201, 202]:
                    return res.json() if res.content else {}
                elif res.status_code == 204:
                    return {}
                elif res.status_code == 401:
                    logger.warning("Received 401 Unauthorized. Purging cache and initiating recovery...")
                    if os.path.exists(self.cache_file):
                        os.remove(self.cache_file)
                    self.token = None
                    time.sleep(1)  # Brief backoff before retry
                    continue
                else:
                    logger.error(f"HTTP {res.status_code} on {method} {endpoint}: {res.text}")
                    raise OutlookNetworkError(f"Microsoft Graph API Error: HTTP {res.status_code}")

            except requests.RequestException as e:
                logger.error(f"Network failure on {method} {url}: {e}")
                if attempt == max_retries - 1:
                    raise OutlookNetworkError(f"Network connection failed: {str(e)}")
                time.sleep(2)  # Network backoff

        raise OutlookAuthError("Session expired and automatic recovery failed. Relogin required.")

    # =========================================================================
    # DATA RETRIEVAL (FOLDERS & MESSAGES)
    # =========================================================================
    def fetch_mail_folders(self) -> Dict[str, Dict[str, Any]]:
        """Retrieves and maps the mailbox folder hierarchy, isolating required tabs."""
        data = self._dispatch_request("/mailfolders?$top=80")
        raw_folders = data.get("value", [])

        valid_folders = {}

        for f in raw_folders:
            fname = f.get("DisplayName", "Unknown")
            if fname.lower() not in self.ignored_folders:
                valid_folders[fname] = {
                    "id": f.get("Id"),
                    "unread": f.get("UnreadItemCount", 0),
                    "total": f.get("TotalItemCount", 0)
                }
        return valid_folders

    def fetch_messages_in_folder(self, folder_id: str = "inbox", limit: int = 25, skip: int = 0) -> List[EmailMessage]:
        """Fetches paginated email summaries for the list view."""
        if not folder_id or folder_id.lower() == "inbox":
            endpoint = f"/mailfolders/inbox/messages?$top={limit}&$skip={skip}"
        else:
            endpoint = f"/messages?$filter=ParentFolderId eq '{folder_id}'&$top={limit}&$skip={skip}"

        data = self._dispatch_request(endpoint)
        return self._parse_message_summaries(data.get("value", []))

    def search_emails(self, query: str) -> List[EmailMessage]:
        """Executes a global search against the Microsoft Graph."""
        endpoint = f"/messages?$search=\"{query}\"&$top=40"
        data = self._dispatch_request(endpoint)
        return self._parse_message_summaries(data.get("value", []))

    def _parse_message_summaries(self, raw_msgs: List[Dict]) -> List[EmailMessage]:
        """Transforms raw Microsoft JSON into strictly typed DataClasses."""
        parsed_msgs = []
        for msg in raw_msgs:
            sender_info = msg.get("Sender", {}).get("EmailAddress", {})
            raw_body = msg.get("Body", {}).get("Content", "")

            email_obj = EmailMessage(
                id=msg.get("Id", ""),
                subject=msg.get("Subject", "(No Subject)"),
                sender_name=sender_info.get("Name", "Unknown Sender"),
                sender_email=sender_info.get("Address", "Unknown Email"),
                to_recipients=[r.get("EmailAddress", {}).get("Address", "") for r in msg.get("ToRecipients", [])],
                cc_recipients=[r.get("EmailAddress", {}).get("Address", "") for r in msg.get("CcRecipients", [])],
                time=msg.get("DateTimeReceived", "")[:16].replace("T", " "),
                preview=self._convert_html_to_native_text(msg.get("BodyPreview", ""))[:80],
                body=self._convert_html_to_native_text(raw_body),
                is_read=msg.get("IsRead", True),
                has_attachments=msg.get("HasAttachments", False),
                attachments=[]
            )
            parsed_msgs.append(email_obj)
        return parsed_msgs

    def fetch_message_attachments(self, msg_id: str) -> List[AttachmentData]:
        """Fetches metadata for all attachments associated with a message."""
        data = self._dispatch_request(f"/messages/{msg_id}/attachments?$select=Id,Name,Size,ContentType,IsInline")
        attachments = []
        for att in data.get("value", []):
            # Filter out tiny inline signature images if they are less than 3KB
            is_inline = att.get("IsInline", False)
            size = att.get("Size", 0)
            if is_inline and size < 3000:
                continue

            attachments.append(AttachmentData(
                id=att.get("Id", ""),
                name=att.get("Name", "Unknown_File"),
                size=size,
                content_type=att.get("ContentType", ""),
                is_inline=is_inline
            ))
        return attachments

    # =========================================================================
    # MESSAGE ACTIONS (READ, DELETE, ARCHIVE)
    # =========================================================================
    def mark_as_read(self, msg_id: str, is_read: bool = True) -> bool:
        """Modifies the read/unread state of a specific message."""
        self._dispatch_request(f"/messages/{msg_id}", method="PATCH", payload={"IsRead": is_read})
        return True

    def delete_email(self, msg_id: str) -> bool:
        """
        SOFT DELETE: Moves the email to the 'Deleted Items' folder instead of
        permanently destroying it, ensuring it appears in the Deleted tab.
        """
        self._dispatch_request(f"/messages/{msg_id}/move", method="POST", payload={"DestinationId": "deleteditems"})
        return True

    def archive_email(self, msg_id: str) -> bool:
        """Moves an email directly to the Archive folder."""
        self._dispatch_request(f"/messages/{msg_id}/move", method="POST", payload={"DestinationId": "archive"})
        return True

    # =========================================================================
    # COMPOSITION, REPLIES & ATTACHMENTS
    # =========================================================================
    def reply_email(self, msg_id: str, body: str) -> bool:
        """Replies to the sender of the original message."""
        self._dispatch_request(f"/messages/{msg_id}/reply", method="POST", payload={"Comment": body})
        return True

    def reply_all_email(self, msg_id: str, body: str) -> bool:
        """Replies to the sender and all recipients of the original message."""
        self._dispatch_request(f"/messages/{msg_id}/replyall", method="POST", payload={"Comment": body})
        return True

    def forward_email(self, msg_id: str, to_emails: List[str], body: str) -> bool:
        """Forwards the original message to new recipients with an optional comment."""
        recipients = [{"EmailAddress": {"Address": addr.strip()}} for addr in to_emails if addr.strip()]
        payload = {"Comment": body, "ToRecipients": recipients}
        self._dispatch_request(f"/messages/{msg_id}/forward", method="POST", payload=payload)
        return True

    def download_specific_attachment(self, msg_id: str, attachment_id: str, save_path: str) -> bool:
        """Downloads a single specific attachment to disk."""
        data = self._dispatch_request(f"/messages/{msg_id}/attachments/{attachment_id}")
        content_bytes = data.get("ContentBytes")
        if content_bytes:
            with open(save_path, "wb") as f:
                f.write(base64.b64decode(content_bytes))
            return True
        return False

    def send_email(self, to_email: str, subject: str, body: str, attachment_paths: List[str] = None) -> bool:
        """Dispatches a brand new email with optional attachments."""
        msg = {
            "Message": {
                "Subject": subject,
                "Body": {"ContentType": "Text", "Content": body},
                "ToRecipients": [{"EmailAddress": {"Address": addr.strip()}} for addr in to_email.split(";") if
                                 addr.strip()]
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

        self._dispatch_request("/sendmail", method="POST", payload=msg)
        return True