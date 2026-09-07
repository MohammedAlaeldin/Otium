import json
import os
from playwright.sync_api import sync_playwright
from storage import SESSION_FILE

EBWISE_BASE_URL = "https://ebwise.mmu.edu.my"


def fetch_ebwise_data() -> dict:
    """Fetches active in-progress courses and their resources via authenticated Playwright browser navigation."""
    if not os.path.exists(SESSION_FILE):
        return {"status": "EXPIRED"}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state=SESSION_FILE)
            page = context.new_page()

            # 1. Navigate to dashboard to validate session
            res = page.goto(f"{EBWISE_BASE_URL}/my/", timeout=20000)
            if not res or "login" in res.url or "microsoftonline.com" in res.url:
                browser.close()
                return {"status": "EXPIRED"}

            # 2. Extract sesskey for timeline API
            sesskey = page.evaluate("() => (window.M && window.M.cfg && window.M.cfg.sesskey) || null")

            # 3. Fetch ONLY in-progress enrolled courses to optimize speed
            courses_payload = [
                {
                    "index": 0,
                    "methodname": "core_course_get_enrolled_courses_by_timeline_classification",
                    "args": {"classification": "inprogress", "limit": 0, "offset": 0}
                }
            ]

            courses_res = page.evaluate(f"""async () => {{
                const response = await fetch('{EBWISE_BASE_URL}/lib/ajax/service.php?sesskey={sesskey}', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({json.dumps(courses_payload)})
                }});
                return await response.json();
            }}""")

            courses = []
            if isinstance(courses_res, list) and len(courses_res) > 0 and not courses_res[0].get("error"):
                courses = courses_res[0].get("data", {}).get("courses", [])

            formatted_courses = []

            # 4. Visit each in-progress course page natively to extract files
            for course in courses:
                cid = course.get("id")
                fullname = course.get("fullname", f"Course {cid}")
                if not cid:
                    continue

                try:
                    page.goto(f"{EBWISE_BASE_URL}/course/view.php?id={cid}", timeout=15000)
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    continue

                # Extract files and resource links rendered on the course page DOM
                extracted_files = page.evaluate("""() => {
                    const files = [];
                    // Target Moodle activity module links
                    const activityLinks = document.querySelectorAll('li.activity a, .activityinstance a');

                    activityLinks.forEach(a => {
                        const href = a.href;
                        const title = a.innerText.replace(/\\s+/g, ' ').trim();

                        if (href && title && !href.includes('#') && !href.includes('javascript:')) {
                            // Find section container name
                            let sectionName = "General";
                            const sectionNode = a.closest('section.section, li.section');
                            if (sectionNode) {
                                const secTitle = sectionNode.querySelector('.sectionname');
                                if (secTitle) {
                                    sectionName = secTitle.innerText.trim();
                                }
                            }

                            files.push({
                                "title": title,
                                "fileurl": href,
                                "section": sectionName,
                                "type": href.includes('/mod/resource/') ? 'resource' : 'link'
                            });
                        }
                    });
                    return files;
                }""")

                # Deduplicate files by URL
                seen_urls = set()
                unique_files = []
                for f in extracted_files:
                    if f["fileurl"] not in seen_urls:
                        seen_urls.add(f["fileurl"])
                        unique_files.append(f)

                print(f"🔍 DEBUG [{fullname}]: Found {len(unique_files)} files.")

                formatted_courses.append({
                    "id": cid,
                    "fullname": fullname,
                    "files": unique_files
                })

            browser.close()
            return {
                "status": "SUCCESS",
                "courses": formatted_courses,
                "upcoming": []
            }

    except Exception as e:
        print(f"⚠️ Playwright navigation error: {e}")
        return {"status": "FAILED", "error": str(e)}


if __name__ == "__main__":
    result = fetch_ebwise_data()
    print(json.dumps(result, indent=2))