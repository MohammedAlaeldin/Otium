import json
import os
import re
import base64
import requests

from storage import SESSION_FILE

EBWISE_BASE_URL = "https://ebwise.mmu.edu.my"
REST_ENDPOINT = f"{EBWISE_BASE_URL}/webservice/rest/server.php"


def _load_cookies_into_session(session: requests.Session) -> dict:
    """Loads the Playwright-exported storage_state cookies into a plain requests.Session."""
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
    """Intercepts Moodle's SSO app-launch redirect and dynamically verifies the correct token."""
    cached = state.get("wstoken")
    if cached:
        return cached

    launch_url = f"{EBWISE_BASE_URL}/admin/tool/mobile/launch.php"
    params = {
        "service": "moodle_mobile_app",
        "passport": "otium_auth",
        "urlscheme": "moodlemobile"
    }

    try:
        res = session.get(launch_url, params=params, allow_redirects=False, timeout=10)
        location = res.headers.get("Location", "")

        if "login" in res.url or "microsoftonline.com" in res.url:
            print("🔎 Redirected to login -> cookies did not authenticate this request.")
            return None

        if not location:
            print("⚠️ Token redirect failed. MMU might have blocked the mobile launch endpoint.")
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
                except Exception as e:
                    print(f"⚠️ Base64 decode failed: {e}")

        if not candidate_tokens:
            hex_matches = re.findall(r"[a-f0-9]{32}", location)
            candidate_tokens.extend(hex_matches)

        valid_wstoken = None
        for candidate in candidate_tokens:
            try:
                test_payload = {
                    "wstoken": candidate,
                    "wsfunction": "core_webservice_get_site_info",
                    "moodlewsrestformat": "json"
                }
                test_res = session.post(REST_ENDPOINT, data=test_payload, timeout=10).json()

                if isinstance(test_res, dict) and test_res.get("exception"):
                    continue

                valid_wstoken = candidate
                break
            except Exception:
                continue

        if valid_wstoken:
            print(f"✅ Official Mobile App Token acquired and verified: {valid_wstoken[:6]}...")
            state["wstoken"] = valid_wstoken
            with open(SESSION_FILE, "w") as f:
                json.dump(state, f, indent=2)
            return valid_wstoken

        print(f"⚠️ None of the extracted tokens were valid. Extracted candidates: {candidate_tokens}")
        return None

    except Exception as e:
        print(f"⚠️ Token generation request failed: {e}")
        return None


def _ws_call(session: requests.Session, wstoken: str, wsfunction: str, **params):
    """Generic caller for Moodle's webservice/rest/server.php."""
    payload = {
        "wstoken": wstoken,
        "wsfunction": wsfunction,
        "moodlewsrestformat": "json",
    }
    payload.update(params)

    res = session.post(REST_ENDPOINT, data=payload, timeout=20)
    data = res.json()

    if isinstance(data, dict) and data.get("exception"):
        raise RuntimeError(f"{wsfunction} failed: {data.get('errorcode')} - {data.get('message')}")

    return data


def _attach_token(fileurl: str, wstoken: str) -> str:
    """pluginfile.php links require the token to be downloadable outside a browser session."""
    sep = "&" if "?" in fileurl else "?"
    return f"{fileurl}{sep}token={wstoken}"


def fetch_ebwise_data(classification: str = "inprogress") -> dict:
    """Fetches active, future, or past courses and their resources based on the chosen filter classification."""
    if not os.path.exists(SESSION_FILE):
        return {"status": "EXPIRED"}

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })

    try:
        state = _load_cookies_into_session(session)

        wstoken = _get_official_app_token(session, state)
        if not wstoken:
            return {"status": "NO_TOKEN"}

        try:
            site_info = _ws_call(session, wstoken, "core_webservice_get_site_info")
        except RuntimeError as e:
            if "invalidtoken" in str(e).lower():
                print("♻️ Cached token is invalid. Purging cache and fetching a new one...")
                state.pop("wstoken", None)
                with open(SESSION_FILE, "w") as f:
                    json.dump(state, f, indent=2)

                wstoken = _get_official_app_token(session, state)
                if not wstoken:
                    return {"status": "NO_TOKEN"}
                site_info = _ws_call(session, wstoken, "core_webservice_get_site_info")
            else:
                raise e

        print(f"🔑 wstoken valid for user: {site_info.get('fullname')}")

        # Fetch courses based on the filter ('inprogress', 'future', 'past', 'all')
        courses_res = _ws_call(
            session, wstoken,
            "core_course_get_enrolled_courses_by_timeline_classification",
            classification=classification, limit=0, offset=0,
        )
        course_list = courses_res.get("courses", [])

        formatted_courses = []

        for course in course_list:
            cid = course.get("id")
            fullname = course.get("fullname", f"Course {cid}")
            if not cid:
                continue

            try:
                sections = _ws_call(session, wstoken, "core_course_get_contents", courseid=cid)
            except RuntimeError as e:
                print(f"⚠️ Could not fetch contents for '{fullname}': {e}")
                formatted_courses.append({"id": cid, "fullname": fullname, "files": []})
                continue

            files = []
            for section in sections:
                section_name = section.get("name") or "General"

                for module in section.get("modules", []):
                    modname = module.get("modname")
                    mod_title = module.get("name")

                    module_contents = module.get("contents") or []
                    if module_contents:
                        for c in module_contents:
                            fileurl = c.get("fileurl")
                            if fileurl:
                                fileurl = _attach_token(fileurl, wstoken)
                            files.append({
                                "title": c.get("filename") or mod_title,
                                "fileurl": fileurl,
                                "section": section_name,
                                "type": modname,
                            })
                    else:
                        mod_url = module.get("url")
                        if mod_url:
                            files.append({
                                "title": mod_title,
                                "fileurl": mod_url,
                                "section": section_name,
                                "type": modname,
                            })

            print(f"🔍 [{fullname}]: Found {len(files)} items via Mobile API.")

            formatted_courses.append({
                "id": cid,
                "fullname": fullname,
                "files": files,
            })

        return {
            "status": "SUCCESS",
            "courses": formatted_courses,
            "upcoming": [],
        }

    except Exception as e:
        print(f"⚠️ Web service API error: {e}")
        return {"status": "FAILED", "error": str(e)}

if __name__ == "__main__":
    result = fetch_ebwise_data()
    print(json.dumps(result, indent=2))