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
        if not raw_text: return ""
        # 1. Immediately drop system events
        if "systemEventMessage" in raw_text or "ThreadActivity" in raw_text: return ""
        
        # 2. Format HTML
        clean = re.sub(r'(?i)<br\s*/?>', ' ', raw_text)
        clean = re.sub(r'(?i)</p>', ' ', clean)
        clean = re.sub(r'(?i)</div>', ' ', clean)
        clean = re.sub(r'<[^<]+?>', '', clean)
        clean = html.unescape(clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        
        # 3. Drop dict-mashed gibberish
        if len(clean) > 60 and clean.count(' ') < 2: return ""
        if "flightproxy.teams" in clean: return ""
        if "callStarted" in clean or "falsefalse" in clean: return ""
        
        return clean

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
            try: os.remove(self.cache_file)
            except Exception: pass

    async def _get_tokens_silently(self):
        if not os.path.exists(SESSION_FILE):
            raise FileNotFoundError(f"Session missing at {SESSION_FILE}! Please log in first.")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--disable-blink-features=AutomationControlled"]
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
                        if not token.startswith("Bearer"): token = f"Bearer {token}"

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
                    pass

                self._save_cached_tokens()
            finally:
                await browser.close()

    def _ensure_auth(self, force_refresh=False):
        if force_refresh:
            self._clear_cache()
        if not self.skype_token or not self.graph_token:
            if not force_refresh and self._load_cached_tokens(): return
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._get_tokens_silently())
                loop.close()
            except Exception as e:
                self.last_errors.append(f"Auth Capture Error: {str(e)}")

    def fetch_dashboard_data(self, is_retry=False) -> dict:
        self.last_errors = []
        self._ensure_auth(force_refresh=is_retry)

        teams_data = []
        chats = []
        calls = []
        needs_retry = False

        # 1. Fetch Teams
        if self.graph_token:
            headers = {"Authorization": self.graph_token, "Accept": "application/json"}
            try:
                res = requests.get("https://graph.microsoft.com/v1.0/me/joinedTeams", headers=headers, timeout=30)
                if res.status_code == 401: needs_retry = True
                elif res.status_code == 200:
                    for team in res.json().get("value", []):
                        chan_res = requests.get(f"https://graph.microsoft.com/v1.0/teams/{team['id']}/channels", headers=headers, timeout=20)
                        chans = chan_res.json().get("value", []) if chan_res.status_code == 200 else []
                        teams_data.append({"id": team["id"], "displayName": team["displayName"], "channels": chans})
            except Exception as e:
                self.last_errors.append(f"Teams Exception: {str(e)}")

        # 2. Fetch Chats (Graph with strictly authorized Skype Fallback)
        if self.graph_token:
            headers = {"Authorization": self.graph_token, "Accept": "application/json"}
            chat_url = "https://graph.microsoft.com/beta/me/chats?$expand=lastMessagePreview&$top=20"
            try:
                res = requests.get(chat_url, headers=headers, timeout=15)
                if res.status_code == 401: needs_retry = True
                elif res.status_code == 200:
                    for chat in res.json().get("value", []):
                        topic = chat.get("topic")
                        chat_type = chat.get("chatType", "")
                        title = topic if topic else ("1-on-1 Chat" if chat_type == "oneOnOne" else "Group Chat")
                        preview = chat.get("lastMessagePreview", {})
                        content = preview.get("body", {}).get("content", "")
                        clean_text = self._clean_text(content)
                        if not clean_text: continue
                        
                        sender = preview.get("from", {}).get("user", {}).get("displayName", "Unknown") if preview.get("from") else "Unknown"
                        chats.append({"id": chat.get("id"), "title": title, "sender": sender, "last_message": clean_text[:120]})
                
                # THE FALLBACK: Uses strict x-skypetoken headers
                elif res.status_code in [403, 401] and self.skype_token:
                    raw_skype = self.skype_token.replace("Bearer ", "").strip()
                    csa_headers = {
                        "Authentication": f"skypetoken={raw_skype}",
                        "x-skypetoken": raw_skype,
                        "Accept": "application/json"
                    }
                    csa_url = "https://teams.microsoft.com/api/chatsvcagg/v1/users/ME/conversations?$top=20"
                    csa_res = requests.get(csa_url, headers=csa_headers, timeout=15)
                    
                    if csa_res.status_code == 200:
                        for conv in csa_res.json().get("conversations", []):
                            cid = conv.get("id")
                            props = conv.get("threadProperties", {})
                            topic = props.get("topic")
                            
                            title = topic if topic else "Chat"
                            if not topic:
                                members = conv.get("members", [])
                                names = [m.get("displayName") for m in members if m.get("displayName")]
                                if names: title = ", ".join(names[:2])

                            preview = conv.get("lastMessagePreview", {})
                            content = preview.get("content", "")
                            
                            clean_text = self._clean_text(content)
                            if not clean_text: continue 
                            
                            sender = preview.get("imDisplayName") or "Unknown"

                            chats.append({
                                "id": cid, 
                                "title": title, 
                                "sender": sender, 
                                "last_message": clean_text[:120]
                            })
                    else:
                        self.last_errors.append(f"Skype CSA Fallback Error: {csa_res.status_code}")
            except Exception as e:
                self.last_errors.append(f"Chat Exception: {str(e)}")

        # 3. Fetch Calls 
        if self.graph_token:
            headers = {"Authorization": self.graph_token, "Accept": "application/json"}
            call_url = "https://graph.microsoft.com/v1.0/me/events?$select=subject,start,end,isOnlineMeeting,onlineMeeting,onlineMeetingUrl&$top=25"
            try:
                res = requests.get(call_url, headers=headers, timeout=15)
                if res.status_code == 401: needs_retry = True
                elif res.status_code == 200:
                    for ev in res.json().get("value", []):
                        if ev.get("isOnlineMeeting"):
                            join_url = ev.get("onlineMeetingUrl", "")
                            if not join_url and isinstance(ev.get("onlineMeeting"), dict):
                                join_url = ev["onlineMeeting"].get("joinUrl", "")
                            
                            calls.append({
                                "subject": ev.get("subject", "Call / Online Meeting"),
                                "start_time": ev.get("start", {}).get("dateTime", ""),
                                "join_url": join_url
                            })
            except Exception:
                pass

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
                    if not clean_text: continue
                    sender = msg.get("from", {}).get("user", {}).get("displayName", "Unknown") if msg.get("from") else "Unknown"
                    msgs.append({"sender": sender, "content": clean_text})
                return msgs
                
            elif res.status_code in [403, 401] and self.skype_token:
                raw_skype = self.skype_token.replace("Bearer ", "").strip()
                csa_headers = {"Authentication": f"skypetoken={raw_skype}", "x-skypetoken": raw_skype, "Accept": "application/json"}
                csa_url = f"https://teams.microsoft.com/api/chatsvcagg/v1/users/ME/conversations/{chat_id}/messages?$top=20"
                csa_res = requests.get(csa_url, headers=csa_headers, timeout=15)
                
                if csa_res.status_code == 200:
                    msgs = []
                    for msg in csa_res.json().get("messages", []):
                        content = msg.get("content", "")
                        clean = self._clean_text(content)
                        if not clean or msg.get("messageType") != "Message": continue
                        sender = msg.get("imDisplayName") or "Unknown"
                        msgs.append({"sender": sender, "content": clean})
                    return msgs
        except Exception:
            pass
        return []

    def fetch_channel_messages(self, team_id: str, channel_id: str) -> list:
        if not self.graph_token: return []
        headers = {"Authorization": self.graph_token, "Accept": "application/json"}
        try:
            res = requests.get(f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels/{channel_id}/messages?$top=20", headers=headers, timeout=30)
            if res.status_code == 200:
                msgs = []
                for msg in res.json().get("value", []):
                    content = msg.get("body", {}).get("content", "")
                    clean_text = self._clean_text(content)
                    if not clean_text: continue
                    sender = msg.get("from", {}).get("user", {}).get("displayName", "Unknown") if msg.get("from") else "Unknown"
                    msgs.append({"sender": sender, "content": clean_text})
                return msgs
        except Exception:
            pass
        return []

_teams_backend_instance = TeamsBackend()
def fetch_dashboard_data() -> dict: return _teams_backend_instance.fetch_dashboard_data()
def fetch_chat_history(chat_id: str) -> list: return _teams_backend_instance.fetch_chat_history(chat_id)
def fetch_channel_messages(team_id: str, channel_id: str) -> list: return _teams_backend_instance.fetch_channel_messages(team_id, channel_id)