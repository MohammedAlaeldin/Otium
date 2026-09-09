import json
import re
import os
from playwright.sync_api import sync_playwright
import storage

def test_outlook_calendar_fetch() -> dict:
    if not os.path.exists(storage.SESSION_FILE):
        print("❌ No session file found. Please log in through Otium first.")
        return {"calendar": [], "meetings": []}

    extracted_calendar = []
    extracted_meetings = []

    def parse_outlook_payload(obj):
        if isinstance(obj, dict):
            value_list = obj.get("value")
            if isinstance(value_list, list):
                for item in value_list:
                    parse_outlook_payload(item)
                return

            subject = obj.get("Subject") or obj.get("subject")
            start_info = obj.get("Start") or obj.get("start")
            
            if subject and start_info and isinstance(start_info, dict) and "DateTime" in start_info:
                start_time = start_info.get("DateTime")
                end_info = obj.get("End") or obj.get("end") or {}
                end_time = end_info.get("DateTime")
                
                join_url = obj.get("OnlineMeetingUrl") or obj.get("onlineMeetingUrl") or obj.get("JoinUrl")
                if not join_url and isinstance(obj.get("OnlineMeeting"), dict):
                    join_url = obj["OnlineMeeting"].get("JoinUrl")

                if not join_url:
                    body = str(obj.get("Body", {})) + str(obj.get("body", {}))
                    matches = re.findall(r'https://teams\.microsoft\.com/l/meetup-join/[a-zA-Z0-9_\-\.%/=\+]+', body)
                    if matches:
                        join_url = matches[0]

                is_online = bool(join_url and "meetup-join" in join_url)
                
                extracted_calendar.append({
                    "subject": subject,
                    "start_time": start_time,
                    "end_time": end_time,
                    "organizer": obj.get("Organizer", {}).get("EmailAddress", {}).get("Name", ""),
                    "is_online": is_online
                })

                if is_online:
                    extracted_meetings.append({
                        "title": subject,
                        "join_url": join_url,
                        "start_time": start_time
                    })

            for val in obj.values():
                if isinstance(val, (dict, list)):
                    parse_outlook_payload(val)
                    
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, (dict, list)):
                    parse_outlook_payload(item)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=storage.SESSION_FILE, user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36")
        page = context.new_page()

        def handle_response(response):
            try:
                if response.status == 200 and "application/json" in response.headers.get("content-type", ""):
                    url = response.url.lower()
                    if "outlook.office.com" in url or "graph.microsoft.com" in url or "substrate" in url:
                        try:
                            parse_outlook_payload(response.json())
                        except:
                            pass
            except Exception:
                pass

        page.on("response", handle_response)
        
        print("🌐 Navigating to Outlook Calendar (Week View)...")
        page.goto("https://outlook.office.com/calendar/view/week", wait_until="domcontentloaded")
        page.wait_for_timeout(8000) 
        
        try:
            # Multi-layered fallback locator to guarantee a click
            next_arrow = (
                page.locator('button[aria-label*="next" i]').first
                .or_(page.locator('button[title*="next" i]').first)
                .or_(page.locator('button[title*="forward" i]').first)
                .or_(page.locator('button:has(i.fui-Icon-font:has-text("E"))').last) # Targets the exact Microsoft Font 'E' character you inspected
            )
            
            if next_arrow.is_visible():
                print("👉 Clicking the 'Next' arrow (Week 1)...")
                next_arrow.click()
                page.wait_for_timeout(6000) 
                
                print("👉 Clicking the 'Next' arrow (Week 2)...")
                next_arrow.click()
                page.wait_for_timeout(6000)
            else:
                # Absolute Fallback: Press the keyboard shortcut for 'Next' in Outlook
                print("⚠️ Arrow not visible via DOM. Falling back to keyboard shortcuts...")
                page.keyboard.press("Alt+Right")
                page.wait_for_timeout(6000)
                page.keyboard.press("Alt+Right")
                page.wait_for_timeout(6000)
                
        except Exception as e:
            print(f"⚠️ Arrow click failed: {e}")

        browser.close()

    unique_cal = list({c["subject"] + str(c["start_time"]): c for c in extracted_calendar}.values())
    unique_meetings = list({m["join_url"]: m for m in extracted_meetings}.values())

    return {
        "calendar": unique_cal,
        "meetings": unique_meetings
    }

if __name__ == "__main__":
    print("🚀 Starting Outlook API Fetch...")
    data = test_outlook_calendar_fetch()
    
    print(f"\n--- 📅 CALENDAR EVENTS FOUND ({len(data['calendar'])}) ---")
    for cal in data["calendar"]:
        print(f" - {cal['subject']} | Start: {cal['start_time']}")
        
    print(f"\n--- 💻 EVENTS ROUTED TO MEETINGS WITH JOIN BUTTON ({len(data['meetings'])}) ---")
    for meet in data["meetings"]:
        print(f" - {meet['title']} | Link: {meet['join_url'][:40]}...")