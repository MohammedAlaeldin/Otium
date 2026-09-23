import json
import os
import re
import base64
import requests
import webbrowser
import threading
import concurrent.futures

from storage import SESSION_FILE

EBWISE_BASE_URL = "https://ebwise.mmu.edu.my"
REST_ENDPOINT = f"{EBWISE_BASE_URL}/webservice/rest/server.php"


def _load_cookies_into_session(session: requests.Session) -> dict:
    """Loads Playwright session cookies into a requests.Session instance."""
    with open(SESSION_FILE, "r") as f:
        state = json.load(f)

    for cookie in state.get("cookies", []):
        session.cookies.set(
            name=cookie["name"],
            value=cookie["value"],
            domain=cookie["domain"].lstrip("."),
            path=cookie.get("path", "/"),
        )
    return state


def _get_official_app_token(session: requests.Session, state: dict) -> str | None:
    cached = state.get("wstoken")
    if cached:
        return cached

    launch_url = f"{EBWISE_BASE_URL}/admin/tool/mobile/launch.php"
    params = {"service": "moodle_mobile_app", "passport": "otium_auth", "urlscheme": "moodlemobile"}

    try:
        res = session.get(launch_url, params=params, allow_redirects=False, timeout=10)
        location = res.headers.get("Location", "")

        if "login" in res.url or "microsoftonline.com" in res.url or not location:
            return None

        candidate_tokens = []
        token_param_match = re.search(r"token=([^&]+)", location)
        if token_param_match:
            raw_val = token_param_match.group(1)
            if re.match(r"^[a-f0-9]{32}$", raw_val):
                candidate_tokens.append(raw_val)
            else:
                try:
                    padded_val = raw_val + "=" * ((4 - len(raw_val) % 4) % 4)
                    decoded = base64.b64decode(padded_val).decode("utf-8")
                    hex_matches = re.findall(r"[a-f0-9]{32}", decoded)
                    candidate_tokens.extend(hex_matches)
                except Exception:
                    pass

        if not candidate_tokens:
            hex_matches = re.findall(r"[a-f0-9]{32}", location)
            candidate_tokens.extend(hex_matches)

        valid_wstoken = None
        for candidate in candidate_tokens:
            try:
                test_payload = {"wstoken": candidate, "wsfunction": "core_webservice_get_site_info", "moodlewsrestformat": "json"}
                test_res = session.post(REST_ENDPOINT, data=test_payload, timeout=10).json()
                if isinstance(test_res, dict) and test_res.get("exception"):
                    continue
                valid_wstoken = candidate
                break
            except Exception:
                continue

        if valid_wstoken:
            state["wstoken"] = valid_wstoken
            with open(SESSION_FILE, "w") as f:
                json.dump(state, f, indent=2)
            return valid_wstoken
        return None
    except Exception:
        return None


def _ws_call(session: requests.Session, wstoken: str, wsfunction: str, **params):
    payload = {"wstoken": wstoken, "wsfunction": wsfunction, "moodlewsrestformat": "json"}
    payload.update(params)
    res = session.post(REST_ENDPOINT, data=payload, timeout=20)
    data = res.json()
    if isinstance(data, dict) and data.get("exception"):
        raise RuntimeError(f"{wsfunction} failed: {data.get('errorcode')} - {data.get('message')}")
    return data


def _attach_token(fileurl: str, wstoken: str) -> str:
    sep = "&" if "?" in fileurl else "?"
    return f"{fileurl}{sep}token={wstoken}"


def fetch_ebwise_data(classification: str = "inprogress", progress_callback=None, cancel_event: threading.Event = None) -> dict:
    if not os.path.exists(SESSION_FILE):
        return {"status": "EXPIRED"}

    master_session = requests.Session()
    master_session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"})

    try:
        state = _load_cookies_into_session(master_session)
        wstoken = _get_official_app_token(master_session, state)
        if not wstoken or (cancel_event and cancel_event.is_set()):
            return {"status": "CANCELLED" if cancel_event and cancel_event.is_set() else "NO_TOKEN"}

        try:
            site_info = _ws_call(master_session, wstoken, "core_webservice_get_site_info")
        except RuntimeError as e:
            if "invalidtoken" in str(e).lower():
                state.pop("wstoken", None)
                with open(SESSION_FILE, "w") as f: json.dump(state, f, indent=2)
                wstoken = _get_official_app_token(master_session, state)
                if not wstoken or (cancel_event and cancel_event.is_set()): return {"status": "CANCELLED" if cancel_event and cancel_event.is_set() else "NO_TOKEN"}
                site_info = _ws_call(master_session, wstoken, "core_webservice_get_site_info")
            else:
                raise e

        if cancel_event and cancel_event.is_set():
            return {"status": "CANCELLED"}

        courses_res = _ws_call(master_session, wstoken, "core_course_get_enrolled_courses_by_timeline_classification", classification=classification, limit=0, offset=0)
        course_list = courses_res.get("courses", [])

        formatted_courses = []

        def process_course(course):
            if cancel_event and cancel_event.is_set():
                return None

            cid = course.get("id")
            fullname = course.get("fullname", f"Course {cid}")
            if not cid: return None

            thread_session = requests.Session()
            thread_session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            _load_cookies_into_session(thread_session)

            files = []
            try:
                sections = _ws_call(thread_session, wstoken, "core_course_get_contents", courseid=cid)
                for section in sections:
                    if cancel_event and cancel_event.is_set(): break
                    section_name = section.get("name") or "General"
                    for module in section.get("modules", []):
                        mod_title = module.get("name")
                        module_contents = module.get("contents") or []
                        if module_contents:
                            for c in module_contents:
                                fileurl = c.get("fileurl")
                                if fileurl: fileurl = _attach_token(fileurl, wstoken)
                                files.append({"title": c.get("filename") or mod_title, "fileurl": fileurl, "section": section_name, "type": module.get("modname")})
                        else:
                            mod_url = module.get("url")
                            if mod_url: files.append({"title": mod_title, "fileurl": mod_url, "section": section_name, "type": module.get("modname")})
            except Exception as e:
                print(f"⚠️ Could not fetch contents for '{fullname}': {e}")

            instructors = []
            if not (cancel_event and cancel_event.is_set()):
                try:
                    users_res = _ws_call(thread_session, wstoken, "core_enrol_get_enrolled_users", courseid=cid)
                    for user in users_res:
                        roles = user.get("roles", [])
                        if any(r.get("shortname") in ["lecturer", "editingteacher"] for r in roles):
                            instructors.append({
                                "fullname": user.get("fullname", "Unknown"),
                                "email": user.get("email", "No email provided")
                            })
                except Exception as e:
                    print(f"⚠️ Could not fetch lecturers for '{fullname}': {e}")

            if not instructors:
                instructors = [{"fullname": "No lecturers found", "email": "No email provided"}]

            return {
                "id": cid,
                "fullname": fullname,
                "files": files,
                "instructors": instructors
            }

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_course = {executor.submit(process_course, c): c for c in course_list}
            for future in concurrent.futures.as_completed(future_to_course):
                if cancel_event and cancel_event.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                    return {"status": "CANCELLED", "courses": []}
                try:
                    course_dict = future.result()
                    if course_dict and not (cancel_event and cancel_event.is_set()):
                        formatted_courses.append(course_dict)
                        if progress_callback:
                            progress_callback(course_dict)
                except Exception as e:
                    print(f"⚠️ Async processing error: {e}")

        original_order = {c.get("id"): idx for idx, c in enumerate(course_list)}
        formatted_courses.sort(key=lambda x: original_order.get(x["id"], 999))

        return {"status": "SUCCESS", "courses": formatted_courses, "upcoming": []}

    except Exception as e:
        print(f"⚠️ Web service API error: {e}")
        return {"status": "FAILED", "error": str(e)}


def _launch_playwright_browser(url: str):
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, args=["--start-maximized"])
            context = browser.new_context(storage_state=SESSION_FILE, no_viewport=True)
            page = context.new_page()
            page.goto(url)
            page.wait_for_event("close", timeout=0)
    except Exception:
        webbrowser.open(url)


def open_ebwise_url_authenticated(url: str) -> bool:
    if not url: return False
    if "pluginfile.php" in url:
        webbrowser.open(url)
        return True
    if os.path.exists(SESSION_FILE):
        threading.Thread(target=_launch_playwright_browser, args=(url,), daemon=True).start()
        return True
    webbrowser.open(url)
    return False