import asyncio
import os
import time
import requests
import json
import re
import html
from playwright.async_api import async_playwright
from cryptography.fernet import Fernet

from storage import SESSION_FILE, get_app_dir, _get_or_create_master_key


class TeamsBackend:
    def __init__(self):
        self.skype_auth = None
        self.graph_token = None
        self.chat_svc_url = None
        self.cache_file = os.path.join(get_app_dir(), "teams_token_cache.bin")
        self.last_errors = []

    def _clean_text(self, raw_text: str) -> str:
        if not raw_text:
            return ""
        clean = re.sub(r'<[^>]+?>', '', raw_text)
        clean = html.unescape(clean)
        clean = clean.replace('\xa0', ' ').strip()
        
        if clean.startswith("8:orgid:") or clean.startswith("8:0:"):
            return ""
        return clean

    def _load_cached_tokens(self):
        try:
            if os.path.exists(self.cache_file):
                fernet = Fernet(_get_or_create_master_key())
                with open(self.cache_file, "rb") as f:
                    data = json.loads(fernet.decrypt(f.read()).decode("utf-8"))
                if data.get("expires_at", 0) > time.time() + 300:
                    self.skype_auth = data.get("skype_auth")
                    self.graph_token = data.get("graph_token")
                    self.chat_svc_url = data.get("chat_svc_url")
                    return bool(self.skype_auth and self.chat_svc_url and self.graph_token)
        except Exception:
            pass
        return False

    def _save_cached_tokens(self):
        try:
            fernet = Fernet(_get_or_create_master_key())
            payload = json.dumps({
                "skype_auth": self.skype_auth,
                "graph_token": self.graph_token,
                "chat_svc_url": self.chat_svc_url,
                "expires_at": time.time() + 3600
            }).encode("utf-8")
            with open(self.cache_file, "wb") as f:
                f.write(fernet.encrypt(payload))
        except Exception:
            pass

    def _clear_cache(self):
        self.skype_auth = None
        self.graph_token = None
        self.chat_svc_url = None
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

            try:
                await page.goto("https://teams.microsoft.com/v2/", wait_until="domcontentloaded", timeout=60000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                await page.wait_for_timeout(2000)

                tokens_js = """
                () => {
                    function decode(raw) {
                        try {
                            let secret = raw;
                            if (typeof raw === 'string' && raw.startsWith('{')) {
                                const parsed = JSON.parse(raw);
                                secret = parsed.secret || parsed.accessToken || raw;
                            }
                            if (typeof secret !== 'string' || !secret.startsWith('eyJ')) return null;
                            const parts = secret.split('.');
                            if (parts.length !== 3) return null;
                            let b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
                            const pad = b64.length % 4;
                            if (pad) b64 += '='.repeat(4 - pad);
                            const payload = JSON.parse(atob(b64));
                            return { secret, aud: payload.aud || '' };
                        } catch (e) { return null; }
                    }

                    let graphToken = null;
                    let spacesToken = null;
                    for (const store of [localStorage, sessionStorage]) {
                        for (let i = 0; i < store.length; i++) {
                            const decoded = decode(store.getItem(store.key(i)));
                            if (!decoded) continue;
                            if (!graphToken && decoded.aud.includes('graph.microsoft.com')) {
                                graphToken = decoded.secret;
                            }
                            if (!spacesToken && decoded.aud.includes('api.spaces.skype.com')) {
                                spacesToken = decoded.secret;
                            }
                        }
                    }
                    return { graphToken, spacesToken };
                }
                """
                found = await page.evaluate(tokens_js)
                graph_token_raw = found.get("graphToken")
                spaces_token_raw = found.get("spacesToken")

                if graph_token_raw:
                    self.graph_token = f"Bearer {graph_token_raw}"
                else:
                    self.last_errors.append("Failed to extract Graph token.")

                if spaces_token_raw:
                    authz_js = """
                    async (bearer) => {
                        try {
                            const res = await fetch('https://teams.microsoft.com/api/authsvc/v1.0/authz', {
                                method: 'POST',
                                headers: { 'Authorization': 'Bearer ' + bearer },
                            });
                            if (!res.ok) return { error: 'HTTP ' + res.status };
                            return await res.json();
                        } catch (e) {
                            return { error: String(e) };
                        }
                    }
                    """
                    authz_result = await page.evaluate(authz_js, spaces_token_raw)

                    if authz_result and not authz_result.get("error"):
                        skype_token = (authz_result.get("tokens") or {}).get("skypeToken")
                        chat_service_base = (authz_result.get("regionGtms") or {}).get("chatService")
                        if skype_token:
                            self.skype_auth = skype_token
                        if chat_service_base:
                            self.chat_svc_url = chat_service_base.rstrip("/") + "/v1/users/ME/conversations"
                        if not (skype_token and chat_service_base):
                            self.last_errors.append("authsvc/authz response missing tokens/chatService.")
                    else:
                        err = authz_result.get("error") if authz_result else "no response"
                        self.last_errors.append(f"authsvc/authz call failed: {err}")
                else:
                    self.last_errors.append("No Spaces/Skype-resource AAD token found in Teams' token cache.")

                self._save_cached_tokens()
            finally:
                await browser.close()

    def _ensure_auth(self, force_refresh=False):
        if force_refresh:
            self._clear_cache()

        if not self.skype_auth or not self.graph_token or not self.chat_svc_url:
            if not force_refresh and self._load_cached_tokens():
                return
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._get_tokens_silently())
            except Exception as e:
                self.last_errors.append(f"Auth Capture Error: {str(e)}")
            finally:
                loop.close()

    def _get_skype_headers(self):
        if not self.skype_auth: return {}
        auth_val = self.skype_auth.replace("Bearer ", "").replace("skypetoken=", "")
        return {
            "Authentication": f"skypetoken={auth_val}",
            "x-skypetoken": auth_val,
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        }

    def fetch_dashboard_data(self, is_retry=False) -> dict:
        self.last_errors = []
        self._ensure_auth(force_refresh=is_retry)

        teams_data = []
        chats = []
        calls = []
        needs_retry = False

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
                    self.last_errors.append(f"Teams API Error {res.status_code}")
            except Exception as e:
                self.last_errors.append(f"Teams Exception: {str(e)}")

        if self.chat_svc_url and self.skype_auth:
            try:
                res = requests.get(self.chat_svc_url, headers=self._get_skype_headers(), timeout=15)
                if res.status_code in [401, 403]:
                    needs_retry = True
                elif res.status_code == 200:
                    data = res.json()
                    for conv in data.get("conversations", [])[:20]:
                        thread_id = conv.get("id", "")

                        title = conv.get("properties", {}).get("topic", "")
                        if not title:
                            title = conv.get("threadProperties", {}).get("topic", "")
                        
                        last_msg = conv.get("lastMessage", {})
                        
                        if not title:
                            title = last_msg.get("imdisplayname", "")
                            if not title:
                                title = "Group Chat" if "19:" in thread_id else "1-on-1 Chat"

                        content = last_msg.get("content", "")
                        
                        if content.strip().startswith("{") and ('"eventtime"' in content or '"initiator"' in content):
                            content = "System event or call log..."

                        clean_text = self._clean_text(content) if content else "No recent messages..."
                        sender = last_msg.get("imdisplayname", "Unknown")

                        chats.append({
                            "id": thread_id,
                            "title": title,
                            "sender": sender,
                            "last_message": clean_text[:120] if clean_text else "No recent messages..."
                        })
                else:
                    self.last_errors.append(f"Internal Chat Error {res.status_code}")
            except Exception as e:
                self.last_errors.append(f"Chat Exception: {str(e)}")
        else:
            self.last_errors.append("Missing Internal Chat URL/Token for Chats.")

        if self.graph_token:
            headers = {"Authorization": self.graph_token, "Accept": "application/json"}
            call_url = "https://graph.microsoft.com/v1.0/me/events?$select=subject,start,end,isOnlineMeeting,onlineMeeting,onlineMeetingUrl&$top=25"
            try:
                res = requests.get(call_url, headers=headers, timeout=15)
                if res.status_code == 401:
                    needs_retry = True
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
            except Exception as e:
                self.last_errors.append(f"Calls Exception: {str(e)}")

        if needs_retry and not is_retry:
            print("⚠️ Token Expired (401/403). Retrying once...")
            return self.fetch_dashboard_data(is_retry=True)

        return {
            "teams": teams_data,
            "chats": chats,
            "calls": calls,
            "errors": self.last_errors,
            "debug": {"has_graph": bool(self.graph_token), "has_skype": bool(self.skype_auth)}
        }

    def fetch_chat_history(self, chat_id: str) -> list:
        if not self.chat_svc_url or not self.skype_auth: return []

        url = f"{self.chat_svc_url}/{chat_id}/messages?pageSize=30"
        try:
            res = requests.get(url, headers=self._get_skype_headers(), timeout=15)
            if res.status_code == 200:
                msgs = []
                for msg in res.json().get("messages", []):
                    msg_type = msg.get("messagetype", "")
                    
                    if msg_type.startswith("Event/") or msg_type.startswith("ThreadActivity/") or msg_type.startswith("Control/"):
                        continue

                    content = msg.get("content", "")
                    
                    if content.strip().startswith("{") and ('"eventtime"' in content or '"initiator"' in content or '"members"' in content):
                        continue

                    clean_text = self._clean_text(content)
                    sender = msg.get("imdisplayname") or "User"

                    if clean_text:
                        msgs.append({"sender": sender, "content": clean_text})
                return msgs
            else:
                print(f"❌ [CONSOLE ERROR] Fetch Chat History Failed ({res.status_code}): {res.text}")
        except Exception as e:
            print(f"❌ [CONSOLE EXCEPTION] Fetch Chat History Exception: {e}")
        return []

    def fetch_channel_messages(self, team_id: str, channel_id: str) -> list:
        """Fetches channel posts, extracting creation timestamps and aggressively parsing attachments."""
        self._ensure_auth()
        if not self.graph_token: return []
        
        headers = {"Authorization": self.graph_token, "Accept": "application/json"}
        try:
            # Increased $top from 20 to 40 to ensure older announcements with files aren't missed
            res = requests.get(
                f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels/{channel_id}/messages?$top=40",
                headers=headers, timeout=30)
            
            if res.status_code == 200:
                msgs = []
                for msg in res.json().get("value", []):
                    raw_content = msg.get("body", {}).get("content", "")
                    clean_text = self._clean_text(raw_content)
                    
                    if not clean_text:
                        clean_text = msg.get("summary", "")
                    if not clean_text:
                        clean_text = msg.get("subject", "")

                    # Broadened attachment extraction logic
                    attachments = []
                    for att in (msg.get("attachments") or []):
                        name = att.get("name")
                        # Some Graph API attachments use webUrl instead of contentUrl
                        url = att.get("contentUrl") or att.get("webUrl")
                        
                        # Ignore inline base64 images, but keep valid links even if the name is blank
                        if url and not url.startswith("data:"):
                            attachments.append({
                                "name": name if name else "Attached File", 
                                "url": url
                            })

                    # Ignore ghost messages that have neither text nor valid files
                    if not clean_text and not attachments:
                        continue

                    sender = "Unknown"
                    from_obj = msg.get("from", {})
                    if isinstance(from_obj, dict):
                        user_data = from_obj.get("user") or from_obj.get("application") or from_obj.get("device") or {}
                        if isinstance(user_data, dict):
                            sender = user_data.get("displayName", "Unknown")

                    created_at = msg.get("createdDateTime", "")

                    msgs.append({
                        "sender": sender,
                        "content": clean_text,
                        "attachments": attachments,
                        "created_at": created_at
                    })
                return msgs
            else:
                print(f"Channel Msg Fetch Error: HTTP {res.status_code}")
        except Exception as e:
            print(f"Channel Msg Fetch Exception: {e}")
        return []


# --- Global Instance & Top-Level Exports ---
_teams_backend_instance = TeamsBackend()

def fetch_dashboard_data() -> dict: return _teams_backend_instance.fetch_dashboard_data()

def fetch_chat_history(chat_id: str) -> list: return _teams_backend_instance.fetch_chat_history(chat_id)

def fetch_channel_messages(team_id: str, channel_id: str) -> list: 
    return _teams_backend_instance.fetch_channel_messages(team_id, channel_id)