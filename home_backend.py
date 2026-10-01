import os
import concurrent.futures
from datetime import datetime, timedelta, timezone
import requests

from storage import SESSION_FILE, load_preferences, save_preferences
from ebwise_backend import _load_cookies_into_session, _get_official_app_token, _ws_call
from outlook_backend import OutlookBackend
from teams_backend import fetch_dashboard_data, fetch_channel_messages


def _parse_flexible_datetime(dt_input):
    if not dt_input: return None
    if isinstance(dt_input, datetime):
        return dt_input.astimezone().replace(tzinfo=None)

    dt_str = str(dt_input).strip()
    is_utc = dt_str.endswith("Z") or "+00:00" in dt_str
    clean_str = dt_str.split(".")[0].replace("Z", "").replace("+00:00", "")

    parsed_dt = None
    formats = ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y-%m-%d %I:%M %p",
               "%Y-%m-%d %I:%M:%S %p"]
    for fmt in formats:
        try:
            parsed_dt = datetime.strptime(clean_str, fmt)
            break
        except ValueError:
            pass

    if parsed_dt:
        if is_utc: parsed_dt = parsed_dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        return parsed_dt
    return None


def save_cached_home_data(data):
    prefs = load_preferences()
    safe_data = {"live_meeting": data.get("live_meeting")}

    safe_data["feed"] = [{k: v.isoformat() if isinstance(v, datetime) else v for k, v in item.items()} for item in
                         data.get("feed", [])]
    safe_data["assignments"] = [{k: v.isoformat() if isinstance(v, datetime) else v for k, v in item.items()} for item
                                in data.get("assignments", [])]

    prefs["cached_home_data"] = safe_data
    save_preferences(prefs)


def get_cached_home_data() -> dict:
    prefs = load_preferences()
    safe_data = prefs.get("cached_home_data", {"feed": [], "assignments": [], "live_meeting": None})

    for item in safe_data.get("feed", []) + safe_data.get("assignments", []):
        if "time" in item and isinstance(item["time"], str):
            item["time"] = _parse_flexible_datetime(item["time"])
        if "due_date" in item and isinstance(item["due_date"], str):
            item["due_date"] = _parse_flexible_datetime(item["due_date"])

    return safe_data


def get_dismissed_notifications() -> list:
    prefs = load_preferences()
    return prefs.get("dismissed_notifications", [])


def dismiss_notification(notif_id: str):
    prefs = load_preferences()
    dismissed = prefs.get("dismissed_notifications", [])
    if notif_id not in dismissed:
        dismissed.append(notif_id)
        prefs["dismissed_notifications"] = dismissed

        # Instantly purge from cache to prevent ghost notifications on next launch
        cache = prefs.get("cached_home_data", {})
        if "feed" in cache:
            cache["feed"] = [item for item in cache.get("feed", []) if item.get("id") != notif_id]
            prefs["cached_home_data"] = cache

        save_preferences(prefs)


def get_custom_tasks() -> list:
    prefs = load_preferences()
    return prefs.get("custom_tasks", [])


def add_custom_task(title: str, course: str, due_date_str: str) -> bool:
    try:
        due_dt = _parse_flexible_datetime(due_date_str)
        if not due_dt: return False
        prefs = load_preferences()
        tasks = prefs.get("custom_tasks", [])
        tasks.append({
            "id": f"custom_{int(datetime.now().timestamp())}",
            "title": title,
            "course": course if course else "Personal Task",
            "due_date": due_dt.strftime("%Y-%m-%d %H:%M"),
            "source": "Custom"
        })
        prefs["custom_tasks"] = tasks
        save_preferences(prefs)
        return True
    except Exception as e:
        print(f"HomeBackend - Error adding task: {e}")
        return False


def delete_custom_task(task_id: str):
    prefs = load_preferences()
    tasks = prefs.get("custom_tasks", [])
    tasks = [t for t in tasks if t.get("id") != task_id]
    prefs["custom_tasks"] = tasks

    # Instantly purge from cache to prevent ghost tasks on next launch
    cache = prefs.get("cached_home_data", {})
    if "assignments" in cache:
        cache["assignments"] = [item for item in cache.get("assignments", []) if item.get("id") != task_id]
        prefs["cached_home_data"] = cache

    save_preferences(prefs)


def get_home_data() -> dict:
    results = {
        "live_meeting": None,
        "feed": [],
        "assignments": []
    }

    now = datetime.now()
    forty_eight_hours_ago = now - timedelta(hours=48)
    dismissed = set(get_dismissed_notifications())

    def fetch_outlook():
        try:
            ob = OutlookBackend()
            if not ob._load_cached_token() and not ob.token:
                try:
                    ob._ensure_auth()
                except Exception:
                    pass

            if ob.token or ob.headers:
                msgs = ob.fetch_messages_in_folder("inbox", limit=30)
                for msg in msgs:
                    msg_id = msg.get("id", "")
                    notif_key = f"outlook_{msg_id}"
                    if notif_key in dismissed: continue

                    time_raw = msg.get("time")
                    msg_time = _parse_flexible_datetime(time_raw)
                    if not msg_time: msg_time = now

                    if msg_time >= forty_eight_hours_ago:
                        sender_name = msg.get("sender_name")
                        if not sender_name:
                            sender_obj = msg.get("sender") or msg.get("from")
                            if isinstance(sender_obj, dict):
                                email_addr = sender_obj.get("emailAddress", {})
                                sender_name = email_addr.get("name") or email_addr.get("address") or "Unknown"
                            elif isinstance(sender_obj, str):
                                sender_name = sender_obj
                            else:
                                sender_name = "Unknown"

                        results["feed"].append({
                            "id": notif_key, "source": "Outlook", "title": msg.get("subject") or "(No Subject)",
                            "subtitle": f"From: {sender_name}", "time": msg_time,
                            "url": f"https://outlook.office.com/mail/inbox/id/{msg_id}",
                            "type": "email", "msg_id": msg_id,
                            "preview": msg.get("preview") or msg.get("bodyPreview") or ""
                        })
        except Exception as e:
            print(f"HomeBackend - Outlook fetch skipped: {e}")

    def fetch_teams():
        try:
            td = fetch_dashboard_data()

            for call in td.get("calls", []):
                st_str = call.get("start_time", "")
                st_local = _parse_flexible_datetime(st_str)
                if not st_local: continue

                if st_local - timedelta(minutes=15) <= now <= st_local + timedelta(hours=2):
                    results["live_meeting"] = {
                        "subject": call.get("subject", "Teams Meeting"),
                        "url": call.get("join_url", ""),
                        "time": st_local.strftime("%I:%M %p")
                    }
                elif forty_eight_hours_ago <= st_local <= now:
                    notif_key = f"teams_call_{call.get('subject')}_{st_local.timestamp()}"
                    if notif_key not in dismissed:
                        results["feed"].append({
                            "id": notif_key, "source": "Teams", "title": call.get("subject", "Teams Call"),
                            "subtitle": "Scheduled Call / Online Meeting", "time": st_local,
                            "url": call.get("join_url", ""), "type": "meeting"
                        })

            for chat in td.get("chats", []):
                chat_id = chat.get("id", "")
                chat_title = chat.get("title", "Teams Chat")
                sender = chat.get("sender", "User")
                last_msg = chat.get("last_message", "")

                notif_key = f"teams_chat_{chat_id}"
                raw_time = chat.get("time")
                chat_time = _parse_flexible_datetime(raw_time) if raw_time else (now - timedelta(minutes=15))

                if notif_key not in dismissed and last_msg and last_msg != "No recent messages...":
                    results["feed"].append({
                        "id": notif_key, "source": "Teams", "title": f"Chat: {chat_title}",
                        "subtitle": f"{sender}: {last_msg}", "time": chat_time, "url": "",
                        "type": "chat", "chat_id": chat_id, "chat_title": chat_title
                    })

            for team in td.get("teams", []):
                team_id = team.get("id")
                team_name = team.get("displayName", "Team")
                for chan in team.get("channels", []):
                    chan_id = chan.get("id")
                    chan_name = chan.get("displayName", "General")
                    try:
                        chan_msgs = fetch_channel_messages(team_id, chan_id)
                        for cmsg in chan_msgs:
                            c_time = _parse_flexible_datetime(cmsg.get("created_at"))
                            if c_time and c_time >= forty_eight_hours_ago:
                                notif_key = f"teams_chan_{team_id}_{chan_id}_{c_time.timestamp()}"
                                if notif_key not in dismissed:
                                    results["feed"].append({
                                        "id": notif_key, "source": "Teams",
                                        "title": f"[{team_name} > {chan_name}] {cmsg.get('sender')}",
                                        "subtitle": cmsg.get("content", "")[:120], "time": c_time, "url": "",
                                        "type": "channel_post", "team_id": team_id, "channel_id": chan_id
                                    })
                    except Exception:
                        pass
        except Exception as e:
            print(f"HomeBackend - Teams fetch skipped: {e}")

    def fetch_ebwise():
        if not os.path.exists(SESSION_FILE): return
        try:
            s = requests.Session()
            state = _load_cookies_into_session(s)
            token = _get_official_app_token(s, state)
            if not token: return

            thirty_days_ago = now - timedelta(days=30)
            ts_from = int(thirty_days_ago.timestamp())

            events_res = _ws_call(s, token, "core_calendar_get_action_events_by_timesort", timesortfrom=ts_from,
                                  limitnum=30)

            for ev in events_res.get("events", []):
                ts = ev.get("timesort")
                ev_time = datetime.fromtimestamp(ts)

                time_modified_ts = ev.get("timemodified", ts)
                time_modified = datetime.fromtimestamp(time_modified_ts)

                url = ev.get("url", "")
                course_name = ev.get("course", {}).get("fullname", "eBwise Course")
                name = ev.get("name", "Assignment")

                notif_key = f"ebwise_event_{ev.get('id', ts)}"
                assign_id = f"ebwise_assign_{ev.get('id', ts)}"

                if ev_time >= now:
                    # Unconditional render for upcoming non-dismissed tasks
                    results["assignments"].append({
                        "id": assign_id,
                        "title": name,
                        "course": course_name,
                        "due_date": ev_time,
                        "url": url,
                        "source": "eBwise",
                        "is_custom": False
                    })

                    if time_modified >= forty_eight_hours_ago:
                        new_notif_key = f"{notif_key}_newly_posted"
                        if new_notif_key not in dismissed:
                            results["feed"].append({
                                "id": new_notif_key, "source": "eBwise", "title": f"New Assignment Posted: {name}",
                                "subtitle": course_name, "time": time_modified, "url": url, "type": "assignment"
                            })

                    if ev_time <= now + timedelta(days=7) and notif_key not in dismissed:
                        results["feed"].append({
                            "id": notif_key, "source": "eBwise", "title": f"Upcoming Deadline: {name}",
                            "subtitle": course_name, "time": now, "url": url, "type": "assignment"
                        })
                elif ev_time >= thirty_days_ago:
                    # Conditionally add MISSED tasks so they appear greyed out and can be dismissed
                    if assign_id not in dismissed:
                        results["assignments"].append({
                            "id": assign_id,
                            "title": name,
                            "course": course_name,
                            "due_date": ev_time,
                            "url": url,
                            "source": "eBwise",
                            "is_custom": False
                        })

                    if notif_key not in dismissed:
                        results["feed"].append({
                            "id": notif_key, "source": "eBwise", "title": f"Deadline Passed: {name}",
                            "subtitle": course_name, "time": ev_time, "url": url, "type": "assignment"
                        })

            try:
                site_info = _ws_call(s, token, "core_webservice_get_site_info")
                user_id = site_info.get("userid")

                if user_id:
                    notif_res = _ws_call(s, token, "message_popup_get_popup_notifications", useridto=user_id, limit=20)
                    for n in notif_res.get("notifications", []):
                        n_id = n.get("id")
                        notif_key = f"ebwise_notif_{n_id}"
                        if notif_key in dismissed: continue

                        timecreated = n.get("timecreated", 0)
                        n_time = datetime.fromtimestamp(timecreated)

                        if n_time >= thirty_days_ago:
                            raw_subject = n.get("subject", "Notification")
                            c_tag = raw_subject.split(" ")[0] if " - " in raw_subject else ""
                            results["feed"].append({
                                "id": notif_key, "source": "eBwise", "course_tag": c_tag,
                                "title": n.get("subject", "Notification"), "subtitle": n.get("shortenedsubject", ""),
                                "time": n_time, "url": n.get("contexturl", ""), "type": "notification"
                            })
            except Exception as e:
                print(f"HomeBackend - Notification fetch failed: {e}")
        except Exception as e:
            print(f"HomeBackend - eBwise fetch skipped: {e}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        executor.submit(fetch_outlook)
        executor.submit(fetch_teams)
        executor.submit(fetch_ebwise)

    # Process all custom tasks
    for task in get_custom_tasks():
        due_dt = _parse_flexible_datetime(task.get("due_date"))
        if due_dt:
            results["assignments"].append({
                "id": task.get("id"),
                "title": task.get("title"),
                "course": task.get("course", "Personal"),
                "due_date": due_dt,
                "url": "",
                "source": "Custom",
                "is_custom": True
            })

    results["feed"].sort(key=lambda x: x["time"], reverse=True)
    results["assignments"].sort(key=lambda x: x["due_date"])

    return results