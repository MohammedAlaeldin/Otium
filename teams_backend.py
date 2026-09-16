import json
import re
import os
from urllib.parse import unquote
from datetime import datetime
from playwright.sync_api import sync_playwright
import storage


def _is_garbage(text) -> bool:
    """Reject MRI IDs (8:orgid:...), JSON blobs, and concatenated metadata strings."""
    if not text:
        return True
    s = str(text).strip()
    if len(s) < 2:
        return True
    # Teams MRI IDs: 8:orgid:... / 8:unq:... / 8:aad:...
    if re.search(r'\b\d+:[a-zA-Z]+:', s):
        return True
    # Raw JSON
    if s.startswith('{') or s.startswith('['):
        return True
    # Long string with almost no spaces => concatenated metadata
    if len(s) > 60 and s.count(' ') < 2:
        return True
    return False


def fetch_teams_data_clean() -> dict:
    try:
        if not os.path.exists(storage.SESSION_FILE):
            return {"announcements": [], "chats": [], "meetings": [], "assignments": [], "calendar": []}

        extracted_meetings = []
        extracted_announcements = []
        conversations = {}
        extracted_calendar = []

        # --- NEW: ID-keyed chat data (for real message history) ---
        conv_meta = {}      # {conv_id: {"name": str, "preview_sender": str, "preview_body": str, "preview_ts": str}}
        conv_history = {}   # {conv_id: [ {sender, message, timestamp}, ... ]}

        # ==================================================================
        # YOUR ORIGINAL parse_payload — unchanged except the ONE garbage check
        # ==================================================================
        def parse_payload(obj, parent_ts=None, parent_title=None, parent_type="Unknown"):
            if isinstance(obj, dict):
                # 1. TIMESTAMPS & CONTEXT
                meeting_start_ts = None
                if isinstance(obj.get("start"), dict):
                    meeting_start_ts = obj.get("start", {}).get("dateTime")
                elif obj.get("startTime"):
                    meeting_start_ts = obj.get("startTime")
                elif isinstance(obj.get("eventDetail"), dict):
                    meeting_start_ts = obj["eventDetail"].get("startTime") or obj["eventDetail"].get("createdTime")

                current_ts = meeting_start_ts or obj.get("originalArrivalTime") or obj.get("composeTime") or obj.get("createdDateTime") or obj.get("lastModifiedDateTime") or parent_ts

                current_title = obj.get("subject") or obj.get("topic") or obj.get("displayName") or obj.get("threadProperties", {}).get("topic") or parent_title

                # 2. IDENTIFY DATA TYPE (Channel vs DM)
                current_type = parent_type
                thread_id = str(obj.get("threadId", "")) + str(obj.get("conversationId", "")) + str(obj.get("id", ""))

                if "teamId" in obj or "channelIdentity" in obj or "@thread.tacv2" in thread_id:
                    current_type = "Channel"
                elif "@thread.v2" in thread_id or "chatId" in obj:
                    current_type = "Chat"

                # 3. HUNT FOR MEETINGS
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
                        "title": str(current_title or "Scheduled Meeting")[:50],
                        "join_url": join_url,
                        "start_time": current_ts
                    })

                # 4. HUNT FOR ANNOUNCEMENTS & CHATS
                content = None
                sender = None

                if obj.get("content"):
                    content = obj.get("content")
                elif isinstance(obj.get("body"), dict) and obj["body"].get("content"):
                    content = obj["body"]["content"]
                elif isinstance(obj.get("lastMessagePreview"), dict):
                    preview = obj["lastMessagePreview"]
                    content = preview.get("content") or (preview.get("body", {}).get("content") if isinstance(preview.get("body"), dict) else None)
                    sender = preview.get("imDisplayName") or preview.get("sender")

                if not sender:
                    sender = obj.get("imDisplayName") or (obj.get("from", {}).get("user", {}).get("displayName") if isinstance(obj.get("from"), dict) else None)

                if content and isinstance(content, str) and sender and sender != "System":
                    clean_text = re.sub(r'<[^<]+?>', '', content).strip()
                    # >>> ONE LINE CHANGED: replaced `not clean_text.startswith("{")`
                    # with the proper _is_garbage() filter which also kills MRI IDs.
                    if len(clean_text) > 2 and not _is_garbage(clean_text) and "systemEventMessage" not in str(obj):

                        msg_data = {
                            "sender": str(sender),
                            "message": clean_text[:300],
                            "timestamp": str(current_ts)
                        }

                        if current_type == "Channel":
                            msg_data["channel_name"] = str(current_title or "General")
                            if msg_data not in extracted_announcements:
                                extracted_announcements.append(msg_data)
                        elif current_type == "Chat":
                            conv_name = str(current_title or sender)
                            if conv_name not in conversations:
                                conversations[conv_name] = []
                            if msg_data not in conversations[conv_name]:
                                conversations[conv_name].append(msg_data)

                # 5. HUNT FOR CALENDAR
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
        # NEW: activity feed walker (announcements)
        # ==================================================================
        def parse_activity_feed(obj):
            if isinstance(obj, dict):
                if "activityType" in obj and any(
                    k in obj for k in ("timestamp", "activityTimestamp", "originalArrivalTime")
                ):
                    try:
                        actor = obj.get("actor") or {}
                        sender = actor.get("displayName") or actor.get("name") or "Unknown"

                        preview = (obj.get("previewText") or obj.get("content")
                                   or obj.get("message") or obj.get("title") or "")
                        clean = re.sub(r'<[^<]+?>', '', str(preview)).strip()

                        target = obj.get("target") or {}
                        chan = (target.get("displayName") or target.get("channelName")
                                or (obj.get("context") or {}).get("channelName")
                                or obj.get("activityType") or "Activity")

                        ts = (obj.get("timestamp") or obj.get("activityTimestamp")
                              or obj.get("originalArrivalTime") or "")

                        if clean and not _is_garbage(clean):
                            extracted_announcements.append({
                                "sender": str(sender),
                                "channel_name": str(chan),
                                "message": clean[:300],
                                "timestamp": str(ts),
                            })
                    except Exception:
                        pass
                for v in obj.values():
                    if isinstance(v, (dict, list)):
                        parse_activity_feed(v)
            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, (dict, list)):
                        parse_activity_feed(item)

        # ==================================================================
        # NEW: /conversations list -> id->name / preview map
        # ==================================================================
        def parse_conversations_list(data):
            if not isinstance(data, dict):
                return
            items = data.get("conversations")
            if not isinstance(items, list):
                return
            for c in items:
                if not isinstance(c, dict):
                    continue
                cid = c.get("id")
                if not cid:
                    continue
                meta = conv_meta.setdefault(cid, {
                    "name": "", "preview_sender": "", "preview_body": "", "preview_ts": ""
                })
                props = c.get("threadProperties") or {}
                preview = c.get("lastMessagePreview") or {}

                # ---- Name resolution ----
                if not meta["name"]:
                    topic = props.get("topic") or props.get("subject")
                    if topic and str(topic).strip().lower() not in ("", "chat"):
                        meta["name"] = str(topic).strip()
                    else:
                        members = props.get("members") or c.get("members") or []
                        names = []
                        for m in members:
                            if isinstance(m, dict):
                                n = (m.get("friendlyName") or m.get("displayName")
                                     or m.get("name") or (m.get("user") or {}).get("displayName"))
                                if n and n not in names and not _is_garbage(str(n)):
                                    names.append(str(n))
                        if names:
                            meta["name"] = ", ".join(names[:3])

                # ---- Preview ----
                body = preview.get("content") or ""
                if not body and isinstance(preview.get("body"), dict):
                    body = preview["body"].get("content", "")
                body_clean = re.sub(r'<[^<]+?>', '', str(body)).strip() if body else ""
                if body_clean and not _is_garbage(body_clean) and not meta["preview_body"]:
                    meta["preview_body"] = body_clean

                if not meta["preview_sender"]:
                    s = preview.get("imDisplayName") or preview.get("sender")
                    if s and not _is_garbage(str(s)):
                        meta["preview_sender"] = str(s)

                ts = preview.get("composeTime") or preview.get("originalArrivalTime")
                if ts and not meta["preview_ts"]:
                    meta["preview_ts"] = str(ts)

        # ==================================================================
        # NEW: /conversations/{id}/messages -> history
        # ==================================================================
        def parse_messages_endpoint(url, data):
            m = re.search(r'/conversations/([^/]+)/messages', url)
            if not m or not isinstance(data, dict):
                return
            cid = unquote(m.group(1))
            msgs = data.get("messages")
            if not isinstance(msgs, list):
                return

            bucket = conv_history.setdefault(cid, [])
            seen = {x.get("timestamp") for x in bucket}

            for msg in msgs:
                if not isinstance(msg, dict):
                    continue
                if "ThreadActivity" in (msg.get("messageType") or ""):
                    continue

                content = msg.get("content") or ""
                if not content and isinstance(msg.get("body"), dict):
                    content = msg["body"].get("content", "")
                clean = re.sub(r'<[^<]+?>', '', str(content)).strip() if content else ""
                if not clean or _is_garbage(clean):
                    continue

                sender = msg.get("imDisplayName")
                if not sender and isinstance(msg.get("from"), dict):
                    sender = (msg["from"].get("user") or {}).get("displayName")
                sender = sender or "Unknown"

                ts = msg.get("composeTime") or msg.get("originalArrivalTime") or ""
                if ts in seen:
                    continue

                bucket.append({
                    "sender": str(sender),
                    "message": clean[:500],
                    "timestamp": str(ts),
                })
                seen.add(ts)

            bucket.sort(key=lambda x: str(x.get("timestamp") or ""))

            # If the /conversations list didn't give us a name, derive one
            meta = conv_meta.setdefault(cid, {
                "name": "", "preview_sender": "", "preview_body": "", "preview_ts": ""
            })
            if not meta["name"] and bucket:
                senders = []
                for m2 in bucket:
                    s = m2.get("sender")
                    if s and s != "Unknown" and s not in senders:
                        senders.append(s)
                if senders:
                    meta["name"] = ", ".join(senders[:3])

        # ==================================================================
        # PLAYWRIGHT
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
                        # ORIGINAL walker (meetings + calendar + chat previews)
                        parse_payload(data)
                        # NEW handlers (additive — don't touch the original)
                        parse_activity_feed(data)
                        parse_conversations_list(data)
                        parse_messages_endpoint(url, data)
                except Exception:
                    pass

            page.on("response", handle_response)

            print("🌐 Ghost User loading Teams...")
            page.goto("https://teams.microsoft.com/v2/", wait_until="domcontentloaded")
            page.wait_for_timeout(4500)

            # --- Chat tab: force DMs and click each chat to trigger /messages ---
            try:
                print("💬 Opening Chat tab...")
                page.locator('button[data-tid="app-bar-chat"], button[aria-label*="Chat"]').first.click(timeout=3000)
                page.wait_for_timeout(3500)
            except Exception as e:
                print(f"  chat tab: {e}")

            try:
                selectors = [
                    '[data-tid="chat-list-item"]',
                    '[data-tid="chat-list-item-container"]',
                    '[data-tid="chatListItem"]',
                    'div[role="treeitem"]',
                    'li[role="listitem"]',
                ]
                chosen = None
                for sel in selectors:
                    try:
                        n = page.locator(sel).count()
                    except Exception:
                        n = 0
                    if n >= 1:
                        chosen = sel
                        print(f"  found {n} chat items via {sel}")
                        break

                if chosen:
                    n = min(page.locator(chosen).count(), 12)
                    print(f"  clicking {n} chats to load history...")
                    for i in range(n):
                        try:
                            page.locator(chosen).nth(i).click(timeout=1500, force=True)
                            page.wait_for_timeout(1100)
                        except Exception:
                            continue
            except Exception as e:
                print(f"  chat clicks: {e}")

            # --- Activity tab: feed announcements ---
            try:
                print("📢 Opening Activity tab...")
                page.locator('button[data-tid="app-bar-activity"], button[aria-label*="Activity"]').first.click(timeout=3000)
                page.wait_for_timeout(4000)
            except Exception as e:
                print(f"  activity tab: {e}")

            # --- Calendar tab: meetings ---
            try:
                print("📅 Opening Calendar tab...")
                page.locator('button[data-tid="app-bar-calendar"], button[aria-label*="Calendar"]').first.click(timeout=3000)
                page.wait_for_timeout(3000)
            except Exception as e:
                print(f"  calendar tab: {e}")

            browser.close()

        # ==================================================================
        # POST-PROCESSING
        # ==================================================================

        # ---- MEETINGS (exact original post-processing) ----
        unique_meetings_dict = {}
        for m in extracted_meetings:
            url = m["join_url"]
            if url not in unique_meetings_dict or m["start_time"] is not None:
                unique_meetings_dict[url] = m

        # ---- CALENDAR (exact original post-processing) ----
        unique_cal = list({c["subject"]: c for c in extracted_calendar}.values())

        # ---- ANNOUNCEMENTS: dedupe + sort ----
        seen_a, deduped_a = set(), []
        for a in extracted_announcements:
            k = (a["sender"], a["message"][:80], a["timestamp"])
            if k in seen_a:
                continue
            seen_a.add(k)
            deduped_a.append(a)
        deduped_a.sort(key=lambda x: str(x.get("timestamp") or ""), reverse=True)

        # ---- CHATS: prefer ID-keyed (has real history), fall back to walker ----
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
            if not name:
                name = "Chat"

            last_body = meta.get("preview_body") or ""
            last_sender = meta.get("preview_sender") or ""
            last_time = meta.get("preview_ts") or ""

            if history:
                last = history[-1]
                if not last_body or _is_garbage(last_body):
                    last_body = last["message"]
                if not last_sender:
                    last_sender = last["sender"]
                if not last_time:
                    last_time = last["timestamp"]

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

        # Fallback: use walker's name-keyed conversations if ID-keyed came up empty
        if not formatted_chats and conversations:
            for name, msgs in conversations.items():
                sorted_msgs = sorted(msgs, key=lambda x: str(x.get("timestamp") or ""))
                formatted_chats.append({
                    "id": "",
                    "name": name,
                    "last_sender": sorted_msgs[-1].get("sender") if sorted_msgs else "",
                    "last_message": sorted_msgs[-1].get("message") if sorted_msgs else "",
                    "latest_time": sorted_msgs[-1].get("timestamp") if sorted_msgs else "",
                    "messages": sorted_msgs,
                    "teams_url": "",
                })
            formatted_chats.sort(key=lambda x: str(x.get("latest_time") or ""), reverse=True)

        print(f"[Teams] meetings={len(unique_meetings_dict)}  "
              f"calendar={len(unique_cal)}  "
              f"announcements={len(deduped_a)}  "
              f"chats={len(formatted_chats)}  "
              f"(conv_meta={len(conv_meta)}, conv_hist={len(conv_history)})")

        return {
            "announcements": deduped_a[:15],
            "chats": formatted_chats[:15],
            "meetings": list(unique_meetings_dict.values())[:15],
            "assignments": [],
            "calendar": unique_cal[:10],
        }

    except Exception as e:
        print(f"CRITICAL BACKEND ERROR: {e}")
        import traceback
        traceback.print_exc()
        return {"announcements": [], "chats": [], "meetings": [], "assignments": [], "calendar": []}