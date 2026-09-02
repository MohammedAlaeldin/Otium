import json
import re
import os
from datetime import datetime
from playwright.sync_api import sync_playwright
import storage

def fetch_teams_data_clean() -> dict:
    # Check if the global session file from login exists
    if not os.path.exists(storage.SESSION_FILE):
        return {"activity": [], "meetings": [], "assignments": [], "calendar": []}

    extracted_meetings = []
    extracted_chats = []
    extracted_calendar = []

    def parse_payload(obj, parent_ts=None, parent_title="Live Class/Call"):
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

            # 1.FOR MEETINGS
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
                    "title": current_title[:50],
                    "join_url": join_url,
                    "start_time": current_ts
                })

            # 2.FOR ACTIVITY
            content = obj.get("content") or (obj.get("body", {}).get("content") if isinstance(obj.get("body"), dict) else None)
            sender = obj.get("imDisplayName") or (obj.get("from", {}).get("user", {}).get("displayName") if isinstance(obj.get("from"), dict) else None)

            if content and isinstance(content, str) and sender and sender != "System":
                clean_text = re.sub(r'<[^<]+?>', '', content).strip()
                if len(clean_text) > 2 and not clean_text.startswith("{"):
                    extracted_chats.append({
                        "sender": sender,
                        "message": clean_text[:150],
                        "timestamp": current_ts
                    })

            # 3.FOR CALENDAR 
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
                    parse_payload(val, current_ts, current_title)
                    
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, (dict, list)):
                    parse_payload(item, parent_ts, parent_title)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Use Otium's centralized session file
        context = browser.new_context(storage_state=storage.SESSION_FILE, user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36")
        page = context.new_page()

        def handle_response(response):
            try:
                if response.status == 200 and "application/json" in response.headers.get("content-type", ""):
                    url = response.url.lower()
                    if any(domain in url for domain in ["teams.microsoft.com", "substrate"]):
                        parse_payload(response.json())
            except Exception:
                pass

        page.on("response", handle_response)
        print("🌐 Intercepting raw Teams data feeds...")
        page.goto("https://teams.microsoft.com/v2/", wait_until="domcontentloaded")
        page.wait_for_timeout(15000)
        browser.close()

    unique_meetings_dict = {}
    for m in extracted_meetings:
        url = m["join_url"]
        if url not in unique_meetings_dict or m["start_time"] is not None:
            unique_meetings_dict[url] = m

    unique_chats = list({c["message"]: c for c in extracted_chats}.values())
    unique_cal = list({c["subject"]: c for c in extracted_calendar}.values())

    return {
        "activity": unique_chats[:15],
        "meetings": list(unique_meetings_dict.values())[:15],
        "assignments": [], 
        "calendar": unique_cal[:10]
    }