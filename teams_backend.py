import asyncio
import os
import time
import requests
import tempfile
import json
import re
import html
from playwright.async_api import async_playwright

from storage import SESSION_FILE


class TeamsBackend:
    def __init__(self):
        self.skype_token = None
        self.graph_token = None
        self.cache_file = os.path.join(tempfile.gettempdir(), "otium_teams_cache.json")
        self.last_errors = []

    def _clean_text(self, raw_text: str) -> str:
        if not raw_text:
            return ""
        clean = re.sub(r'<[^<]+?>', '', raw_text)
        clean = html.unescape(clean)
        return clean.replace('\xa0', ' ').strip()

    def _load_cached_tokens(self):
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r") as f:
                    data = json.load(f)
                    if data.get("expires_at", 0) > time.time() + 300:
                        self.skype_token = data.get("skype_token")
                        self.graph_token = data.get("graph_token")
                        return bool(self.skype_token and self.graph_token)
        except Exception:
            pass
        return False

    def _save_cached_tokens(self):
        try:
            with open(self.cache_file, "w") as f:
                json.dump({
                    "skype_token": self.skype_token,
                    "graph_token": self.graph_token,
                    "expires_at": time.time() + 3600
                }, f)
        except Exception:
            pass

    def _clear_cache(self):
        self.skype_token = None
        self.graph_token = None
        if os.path.exists(self.cache_file):
            try:
                os.remove(self.cache_file)
            except Exception:
                pass

    async def _get_tokens_silently(self):
        if not os.path.exists(SESSION_FILE):
            raise FileNotFoundError(f"Session missing at {SESSION_FILE}! Please log in first.")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                      "--disable-blink-features=AutomationControlled"]
            )
            context = await browser.new_context(
                storage_state=SESSION_FILE,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            skype_future = asyncio.Future()
            graph_future = asyncio.Future()

            async def handle_request(request):
                try:
                    auth = request.headers.get("authorization", "") or request.headers.get("x-ms-skypetoken", "")
                    if auth:
                        token = auth.replace("skypetoken=", "")
                        if not token.startswith("Bearer"):
                            token = f"Bearer {token}"

                        if "api.spaces.skype.com" in request.url or "teams.microsoft.com/api" in request.url or "chatsvcagg" in request.url:
                            if not skype_future.done(): skype_future.set_result(token)
                        elif "graph.microsoft.com" in request.url or "outlook.office.com" in request.url:
                            if not graph_future.done(): graph_future.set_result(token)
                except Exception:
                    pass

            page.on("request", handle_request)

            try:
                await page.goto("https://teams.microsoft.com/v2/", wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(10000)

                js_script = """
                () => {
                    let tokens = { skype: null, graph: null };
                    function checkToken(val) {
                        try {
                            if (typeof val !== 'string') return;
                            let secret = val;
                            if (val.startsWith('{')) {
                                let parsed = JSON.parse(val);
                                secret = parsed.secret || parsed.accessToken || val;
                            }
                            if (typeof secret === 'string' && secret.startsWith('eyJ')) {
                                let parts = secret.split('.');
                                if (parts.length === 3) {
                                    let base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
                                    let pad = base64.length % 4;
                                    if (pad) { base64 += new Array(5 - pad).join('='); }
                                    let payload = JSON.parse(atob(base64));

                                    if (payload.aud) {
                                        if (payload.aud.includes("skype.com") || payload.aud.includes("teams.microsoft.com")) { tokens.skype = secret; }
                                        if (payload.aud.includes("graph.microsoft.com")) { tokens.graph = secret; }
                                    }
                                }
                            }
                        } catch(e) {}
                    }
                    for (let i = 0; i < localStorage.length; i++) { checkToken(localStorage.getItem(localStorage.key(i))); }
                    for (let i = 0; i < sessionStorage.length; i++) { checkToken(sessionStorage.getItem(sessionStorage.key(i))); }
                    return tokens;
                }
                """
                extracted = await page.evaluate(js_script)

                if extracted.get('skype'): self.skype_token = f"Bearer {extracted['skype']}"
                if extracted.get('graph'): self.graph_token = f"Bearer {extracted['graph']}"

                try:
                    if not self.skype_token: self.skype_token = await asyncio.wait_for(skype_future, timeout=20.0)
                    if not self.graph_token: self.graph_token = await asyncio.wait_for(graph_future, timeout=20.0)
                except asyncio.TimeoutError:
                    print("⚠️ [DEBUG] Network Interceptor Timeout for tokens.")

                if not self.skype_token and not self.graph_token:
                    raise Exception("Failed to capture any valid MSAL tokens from Teams session.")

                self._save_cached_tokens()
            finally:
                await browser.close()

    def _ensure_auth(self, force_refresh=False):
        if force_refresh:
            self._clear_cache()

        if not self.skype_token or not self.graph_token:
            if not force_refresh and self._load_cached_tokens():
                return
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._get_tokens_silently())
                loop.close()
            except Exception as e:
                print(f"❌ [DEBUG] Auth Capture Error: {e}")
                self.last_errors.append(f"Auth Capture Error: {str(e)}")

    def fetch_dashboard_data(self, is_retry=False) -> dict:
        self.last_errors = []
        self._ensure_auth(force_refresh=is_retry)

        teams_data = []
        chats = []
        calls = []
        needs_retry = False

        # 1. Fetch Teams (Graph API)
        if self.graph_token:
            headers = {"Authorization": self.graph_token, "Accept": "application/json"}
            try:
                res = requests.get("https://graph.microsoft.com/v1.0/me/joinedTeams", headers=headers, timeout=30)
                if res.status_code == 401:
                    needs_retry = True
                elif res.status_code == 200:
                    for team in res.json().get("value", []):
                        chan_res = requests.get(f"https://graph.microsoft.com/v1.0/teams/{team['id']}/channels",
                                                headers=headers, timeout=20)
                        chans = chan_res.json().get("value", []) if chan_res.status_code == 200 else []
                        teams_data.append({"id": team["id"], "displayName": team["displayName"], "channels": chans})
                else:
                    print(f"❌ [CONSOLE ERROR] Teams Graph API failed with status {res.status_code}: {res.text}")
                    self.last_errors.append(f"Teams API Error {res.status_code}")
            except Exception as e:
                print(f"❌ [CONSOLE EXCEPTION] Teams Request Exception: {e}")
                self.last_errors.append(f"Teams Exception: {str(e)}")

        # 2. Fetch Chats using Graph API (Beta endpoint handles chat list cleanly)
        if self.graph_token:
            headers = {"Authorization": self.graph_token, "Accept": "application/json"}
            chat_url = "https://graph.microsoft.com/beta/me/chats?$expand=lastMessagePreview&$top=20"
            try:
                res = requests.get(chat_url, headers=headers, timeout=15)
                print(f"🔍 [CONSOLE DEBUG] Graph Chat API Response Status: {res.status_code}")

                if res.status_code == 401:
                    needs_retry = True
                elif res.status_code == 200:
                    data = res.json()
                    for chat in data.get("value", []):
                        topic = chat.get("topic")
                        chat_type = chat.get("chatType", "")

                        title = topic if topic else ("1-on-1 Chat" if chat_type == "oneOnOne" else "Group Chat")

                        preview = chat.get("lastMessagePreview", {})
                        content = preview.get("body", {}).get("content", "")
                        clean_text = self._clean_text(content) if content else "No recent messages..."

                        sender = "Unknown"
                        if preview.get("from") and preview.get("from").get("user"):
                            sender = preview.get("from").get("user").get("displayName", "Unknown")

                        chats.append(
                            {"id": chat.get("id"), "title": title, "sender": sender, "last_message": clean_text[:120]})
                else:
                    # PRINT FULL ERROR TO CONSOLE SO YOU CAN READ IT CLEARLY
                    print(
                        f"❌ [CONSOLE ERROR] Graph Chat API Failed:\nURL: {chat_url}\nStatus: {res.status_code}\nResponse: {res.text}")
                    self.last_errors.append(f"Graph Chat Error {res.status_code} (Check Console)")
            except Exception as e:
                print(f"❌ [CONSOLE EXCEPTION] Graph Chat Request Exception: {e}")
                self.last_errors.append(f"Chat Exception: {str(e)}")
        else:
            self.last_errors.append("Missing Graph Token for Chats.")

        # 3. Fetch Calls (Graph API)
        if self.graph_token:
            headers = {"Authorization": self.graph_token, "Accept": "application/json"}
            call_url = "https://graph.microsoft.com/v1.0/me/events?$select=subject,start,end,isOnlineMeeting&$top=25"
            try:
                res = requests.get(call_url, headers=headers, timeout=15)
                if res.status_code == 401:
                    needs_retry = True
                elif res.status_code == 200:
                    for ev in res.json().get("value", []):
                        if ev.get("isOnlineMeeting"):
                            calls.append({"subject": ev.get("subject", "Call / Online Meeting"),
                                          "start_time": ev.get("start", {}).get("dateTime", "")})
            except Exception as e:
                print(f"❌ [CONSOLE EXCEPTION] Calls Exception: {e}")

        if needs_retry and not is_retry:
            print("⚠️ Token Expired (401). Retrying once...")
            return self.fetch_dashboard_data(is_retry=True)

        return {
            "teams": teams_data,
            "chats": chats,
            "calls": calls,
            "errors": self.last_errors,
            "debug": {"has_graph": bool(self.graph_token), "has_skype": bool(self.skype_token)}
        }

    def fetch_chat_history(self, chat_id: str) -> list:
        """Fetches messages inside a specific Chat using Graph API."""
        if not self.graph_token: return []
        headers = {"Authorization": self.graph_token, "Accept": "application/json"}

        url = f"https://graph.microsoft.com/v1.0/me/chats/{chat_id}/messages?$top=20"

        try:
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code == 200:
                msgs = []
                for msg in res.json().get("value", []):
                    content = msg.get("body", {}).get("content", "")
                    clean_text = self._clean_text(content)

                    sender = "Unknown"
                    if msg.get("from") and msg.get("from").get("user"):
                        sender = msg.get("from").get("user").get("displayName", "Unknown")

                    if clean_text: msgs.append({"sender": sender, "content": clean_text})
                return msgs
            else:
                print(f"❌ [CONSOLE ERROR] Fetch Chat History Failed ({res.status_code}): {res.text}")
        except Exception as e:
            print(f"❌ [CONSOLE EXCEPTION] Fetch Chat History Exception: {e}")
        return []

    def fetch_channel_messages(self, team_id: str, channel_id: str) -> list:
        if not self.graph_token: return []
        headers = {"Authorization": self.graph_token, "Accept": "application/json"}
        try:
            res = requests.get(
                f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels/{channel_id}/messages?$top=20",
                headers=headers, timeout=30)
            if res.status_code == 200:
                msgs = []
                for msg in res.json().get("value", []):
                    content = msg.get("body", {}).get("content", "")
                    clean_text = self._clean_text(content)

                    sender = "Unknown"
                    if msg.get("from") and msg.get("from").get("user"):
                        sender = msg.get("from").get("user").get("displayName", "Unknown")

                    if clean_text: msgs.append({"sender": sender, "content": clean_text})
                return msgs
        except Exception as e:
            print(f"Channel Msg Fetch Error: {e}")
        return []


# --- Global Instance & Top-Level Exports ---
_teams_backend_instance = TeamsBackend()


def fetch_dashboard_data() -> dict: return _teams_backend_instance.fetch_dashboard_data()


def fetch_chat_history(chat_id: str) -> list: return _teams_backend_instance.fetch_chat_history(chat_id)


def fetch_channel_messages(team_id: str,
                           channel_id: str) -> list: return _teams_backend_instance.fetch_channel_messages(team_id,
                                                                                                           channel_id)