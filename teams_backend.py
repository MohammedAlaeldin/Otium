import json
import re
import os
from urllib.parse import unquote
from datetime import datetime
from playwright.sync_api import sync_playwright
import storage

def clean_html(html_str) -> str:
    if not html_str: return ""
    s = str(html_str)
    s = re.sub(r'(?i)<br\s*/?>', ' ', s)
    s = re.sub(r'(?i)</p>', ' ', s)
    s = re.sub(r'(?i)</div>', ' ', s)
    s = re.sub(r'<[^<]+?>', '', s)
    return re.sub(r'\s+', ' ', s).strip()

def _is_garbage(text) -> bool:
    if not text: return True
    s = str(text).strip()
    if len(s) < 2: return True
    if re.search(r'\b\d+:[a-zA-Z]+:', s): return True
    if s.startswith('{') or s.startswith('['): return True
    if len(s) > 60 and s.count(' ') < 2: return True
    return False

def _is_human_message(msg_dict: dict) -> bool:
    """Strictly blocks Teams system events, call logs, and recording notifications."""
    msg_type = msg_dict.get("messageType", "") or msg_dict.get("type", "")
    
    # 1. Reject explicit non-message types (Events, ThreadActivities, etc.)
    if msg_type and msg_type not in ["Message", "Text", "RichText/Html"]:
        return False
        
    # 2. Reject known system text patterns (like the ones in your screenshot)
    content = str(msg_dict.get("content", ""))
    if not content and isinstance(msg_dict.get("body"), dict):
        content = str(msg_dict.get("body", {}).get("content", ""))
        
    system_phrases = [
        "Recording stopped",
        "Recording has been saved",
        "Meeting ended",
        "false false callStarted",
        "systemEventMessage"
    ]
    
    for phrase in system_phrases:
        if phrase in content:
            return False
            
    return True

def fetch_teams_data_clean() -> dict:
    try:
        if not os.path.exists(storage.SESSION_FILE):
            return {"announcements": [], "chats": [], "meetings": [], "assignments": [], "calendar": []}

        extracted_meetings = []
        extracted_announcements = []
        conversations = {}
        extracted_calendar = []

        conv_meta = {}
        conv_history = {}

        # ==================================================================
        # 1. ORIGINAL PARSE PAYLOAD (Meetings Restored)
        # ==================================================================
        # RESTORED: parent_title="Live Class/Call" exactly as you originally had it
        def parse_payload(obj, parent_ts=None, parent_title="Live Class/Call", parent_type="Unknown"):
            if isinstance(obj, dict):
                
                meeting_start_ts = None
                if isinstance(obj.get("start"), dict):
                    meeting_start_ts = obj.get("start", {}).get("dateTime")
                elif obj.get("startTime"):
                    meeting_start_ts = obj.get("startTime")
                elif isinstance(obj.get("eventDetail"), dict):
                    meeting_start_ts = obj["eventDetail"].get("startTime") or obj["eventDetail"].get("createdTime")

                current_ts = meeting_start_ts or obj.get("originalArrivalTime") or obj.get("composeTime") or obj.get("createdDateTime") or obj.get("lastModifiedDateTime") or parent_ts
                current_title = obj.get("subject") or obj.get("topic") or obj.get("threadProperties", {}).get("topic") or parent_title

                current_type = parent_type
                thread_id = str(obj.get("threadId", "")) + str(obj.get("conversationId", "")) + str(obj.get("id", ""))
                if "teamId" in obj or "channelIdentity" in obj or "@thread.tacv2" in thread_id:
                    current_type = "Channel"
                elif "@thread.v2" in thread_id or "chatId" in obj:
                    current_type = "Chat"

                # RESTORED: Your exact original meeting hunting logic
                join_url = None
                if isinstance(obj.get("onlineMeeting"), dict):
                    join_url = obj["onlineMeeting"].get("joinUrl")
                if not join_url:
                    join_url = obj.get("onlineMeetingUrl") or obj.get("joinUrl")
                    
                if not join_url:
                    for key, val in obj.items():
                        if isinstance(val, str) and "meetup-join" in val:
                            matches = re.findall(r'https://teams\.microsoft\.com/l/meetup-join/[^\s"\'>]+', val)
                            if matches:
                                join_url = matches[0]
                                break
                                
                if join_url and "meetup-join" in join_url:
                    extracted_meetings.append({
                        "title": current_title[:50] if current_title else "Live Class/Call",
                        "join_url": join_url,
                        "start_time": current_ts
                    })

                # Announcements / Chats (Fallback)
                if _is_human_message(obj):
                    content = obj.get("content") or (obj.get("body", {}).get("content") if isinstance(obj.get("body"), dict) else None)
                    if not content and isinstance(obj.get("lastMessagePreview"), dict):
                        preview = obj["lastMessagePreview"]
                        content = preview.get("content") or (preview.get("body", {}).get("content") if isinstance(preview.get("body"), dict) else None)
                    
                    sender = obj.get("imDisplayName") or (obj.get("from", {}).get("user", {}).get("displayName") if isinstance(obj.get("from"), dict) else None)
                    if not sender and isinstance(obj.get("lastMessagePreview"), dict):
                        sender = obj["lastMessagePreview"].get("imDisplayName") or obj["lastMessagePreview"].get("sender")

                    if content and isinstance(content, str) and sender and sender != "System":
                        clean_text = clean_html(content)
                        if len(clean_text) > 2 and not _is_garbage(clean_text):
                            msg_data = {
                                "sender": str(sender),
                                "message": clean_text[:300],
                                "timestamp": str(current_ts)
                            }
                            if current_type == "Channel":
                                msg_data["channel_name"] = str(current_title) if current_title != "Live Class/Call" else "Activity Feed"
                                if msg_data not in extracted_announcements:
                                    extracted_announcements.append(msg_data)
                            elif current_type == "Chat":
                                conv_name = str(current_title) if current_title != "Live Class/Call" else str(sender)
                                if conv_name not in conversations: conversations[conv_name] = []
                                if msg_data not in conversations[conv_name]: conversations[conv_name].append(msg_data)

                if "start" in obj and isinstance(obj.get("start"), dict) and "dateTime" in obj["start"]:
                    end_time = obj.get("end", {}).get("dateTime") if isinstance(obj.get("end"), dict) else None
                    organizer = obj.get("organizer", {}).get("emailAddress", {}).get("name") if isinstance(obj.get("organizer"), dict) else ""
                    extracted_calendar.append({
                        "subject": obj.get("subject") or "Scheduled Event",
                        "start_time": obj["start"]["dateTime"],
                        "end_time": end_time,
                        "organizer": organizer,
                        "is_online": True if join_url else False
                    })

                for val in obj.values():
                    if isinstance(val, (dict, list)):
                        parse_payload(val, current_ts, current_title, current_type)

            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, (dict, list)):
                        parse_payload(item, parent_ts, parent_title, parent_type)

        # ==================================================================
        # 2. CHAT CONVERSATIONS WALKER
        # ==================================================================
        def parse_conversations_list(data):
            if not isinstance(data, dict): return
            items = data.get("conversations")
            if not isinstance(items, list): return
            
            for c in items:
                if not isinstance(c, dict): continue
                cid = c.get("id")
                if not cid: continue
                
                meta = conv_meta.setdefault(cid, {"name": "", "preview_sender": "", "preview_body": "", "preview_ts": ""})
                props = c.get("threadProperties") or {}
                
                # Name Resolution
                if not meta["name"]:
                    topic = props.get("topic") or props.get("subject")
                    if topic and str(topic).strip().lower() not in ("", "chat", "live class/call"):
                        meta["name"] = str(topic).strip()
                    else:
                        members = props.get("members") or c.get("members") or []
                        names = []
                        for m in members:
                            if isinstance(m, dict):
                                n = m.get("friendlyName") or m.get("displayName") or m.get("name") or (m.get("user") or {}).get("displayName")
                                if n and n not in names and not _is_garbage(str(n)):
                                    names.append(str(n))
                        if names:
                            meta["name"] = ", ".join(names[:3])

                # Safe Preview Resolution
                preview = c.get("lastMessagePreview") or {}
                if _is_human_message(preview):
                    body = preview.get("content") or ""
                    if not body and isinstance(preview.get("body"), dict):
                        body = preview["body"].get("content", "")
                    
                    body_clean = clean_html(body)
                    if body_clean and not _is_garbage(body_clean) and not meta["preview_body"]:
                        meta["preview_body"] = body_clean

                    if not meta["preview_sender"]:
                        s = preview.get("imDisplayName") or preview.get("sender")
                        if s and not _is_garbage(str(s)): meta["preview_sender"] = str(s)

                    ts = preview.get("composeTime") or preview.get("originalArrivalTime")
                    if ts and not meta["preview_ts"]: meta["preview_ts"] = str(ts)

        # ==================================================================
        # 3. CHAT HISTORY (MESSAGES) WALKER
        # ==================================================================
        def parse_messages_endpoint(url, data):
            m = re.search(r'/conversations/([^/]+)/messages', url)
            if not m or not isinstance(data, dict): return
            cid = unquote(m.group(1))
            msgs = data.get("messages")
            if not isinstance(msgs, list): return

            bucket = conv_history.setdefault(cid, [])
            seen = {x.get("timestamp") for x in bucket}

            for msg in msgs:
                if not isinstance(msg, dict): continue
                
                # Applying the strict filter to kill system spam
                if not _is_human_message(msg):
                    continue

                content = msg.get("content") or ""
                if not content and isinstance(msg.get("body"), dict):
                    content = msg["body"].get("content", "")
                
                clean = clean_html(content)
                if not clean or _is_garbage(clean): continue

                sender = msg.get("imDisplayName")
                if not sender and isinstance(msg.get("from"), dict):
                    sender = (msg["from"].get("user") or {}).get("displayName")
                sender = sender or "Unknown"

                ts = msg.get("composeTime") or msg.get("originalArrivalTime") or ""
                if ts in seen: continue

                bucket.append({
                    "sender": str(sender),
                    "message": clean[:500],
                    "timestamp": str(ts),
                })
                seen.add(ts)

            bucket.sort(key=lambda x: str(x.get("timestamp") or ""))

        # ==================================================================
        # PLAYWRIGHT EXECUTION
        # ==================================================================
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                storage_state=storage.SESSION_FILE,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
            )
            page = context.new_page()

            def handle_response(response):
                try:
                    if response.status == 200 and "application/json" in response.headers.get("content-type", ""):
                        data = response.json()
                        url = response.url or ""
                        parse_payload(data)
                        parse_conversations_list(data)
                        parse_messages_endpoint(url, data)
                except Exception:
                    pass

            page.on("response", handle_response)

            print("🌐 Ghost User loading Teams...")
            page.goto("https://teams.microsoft.com/v2/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(4000)

            # --- Explicit UI Clicks before Hash Fallbacks to force Activity ---
            try:
                print("📢 Clicking Activity Tab...")
                page.locator('button[data-tid="app-bar-activity"]').first.click(timeout=3000)
                page.wait_for_timeout(3000)
            except Exception:
                print("📢 Fallback to Activity Hash Route...")
                page.goto("https://teams.microsoft.com/v2/#/activity", wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)

            try:
                print("💬 Clicking Chats Tab...")
                page.locator('button[data-tid="app-bar-chat"]').first.click(timeout=3000)
                page.wait_for_timeout(3000)
            except Exception:
                page.goto("https://teams.microsoft.com/v2/#/chats", wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)

            try:
                print("📅 Clicking Calendar Tab...")
                page.locator('button[data-tid="app-bar-calendar"]').first.click(timeout=3000)
                page.wait_for_timeout(3000)
            except Exception:
                page.goto("https://teams.microsoft.com/v2/#/calendar", wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)

            browser.close()

        # ==================================================================
        # POST-PROCESSING
        # ==================================================================
        unique_meetings_dict = {}
        for m in extracted_meetings:
            url = m["join_url"]
            if url not in unique_meetings_dict or m["start_time"] is not None:
                unique_meetings_dict[url] = m

        unique_cal = list({c["subject"]: c for c in extracted_calendar}.values())

        seen_a, deduped_a = set(), []
        for a in extracted_announcements:
            k = (a["sender"], a["message"][:80], a["timestamp"])
            if k in seen_a: continue
            seen_a.add(k)
            deduped_a.append(a)
        deduped_a.sort(key=lambda x: str(x.get("timestamp") or ""), reverse=True)

        formatted_chats = []
        all_ids = set(conv_meta.keys()) | set(conv_history.keys())
        for cid in all_ids:
            meta = conv_meta.get(cid, {})
            history = conv_history.get(cid, [])

            name = meta.get("name") or ""
            if not name and history:
                senders = []
                for m in history:
                    s = m.get("sender")
                    if s and s != "Unknown" and s not in senders:
                        senders.append(s)
                name = ", ".join(senders[:3])
            if not name: name = "Chat"

            last_body = meta.get("preview_body") or ""
            last_sender = meta.get("preview_sender") or ""
            last_time = meta.get("preview_ts") or ""

            if history:
                last = history[-1]
                if not last_body or _is_garbage(last_body): last_body = last["message"]
                if not last_sender: last_sender = last["sender"]
                if not last_time: last_time = last["timestamp"]

            # Double check our system filter against the preview
            if "Recording stopped" in last_body or "false false callStarted" in last_body:
                last_body = "Message history available."

            formatted_chats.append({
                "id": cid,
                "name": name,
                "last_sender": last_sender,
                "last_message": last_body,
                "latest_time": last_time,
                "messages": history,
                "teams_url": f"https://teams.microsoft.com/l/chat/{cid}/conversations",
            })
        
        formatted_chats.sort(key=lambda x: str(x.get("latest_time") or ""), reverse=True)

        return {
            "announcements": deduped_a[:15],
            "chats": formatted_chats[:15],
            "meetings": list(unique_meetings_dict.values())[:15],
            "assignments": [],
            "calendar": unique_cal[:10],
        }

    except Exception as e:
        print(f"CRITICAL BACKEND ERROR: {e}")
        return {"announcements": [], "chats": [], "meetings": [], "assignments": [], "calendar": []}