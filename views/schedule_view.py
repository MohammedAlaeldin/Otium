import customtkinter as ctk
import threading
import asyncio
import re
from schedule_backend import fetch_raw_schedule

THEME = {
    "bg_dark": "#121216",
    "card_bg": "#1E1E2A",
    "card_alt": "#171721",
    "header_blue": "#1E3A8A",
    "border": "#323246",
    "text_primary": "#F1F5F9",
    "text_secondary": "#94A3B8",
    "accent_indigo": "#6366F1",
    "danger": "#EF4444"
}

DAYS_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

class ScheduleView(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color=THEME["bg_dark"])
        self.pack_propagate(False)

        self.header_title = ctk.CTkLabel(
            self, text="📅 Class Schedule", font=ctk.CTkFont(size=22, weight="bold"), text_color=THEME["text_primary"]
        )
        self.header_title.pack(anchor="w", padx=20, pady=15)

        self.table_frame = ctk.CTkScrollableFrame(
            self, fg_color=THEME["card_bg"], border_color=THEME["border"], border_width=1, corner_radius=0
        )
        self.table_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        self.loading_lbl = ctk.CTkLabel(
            self.table_frame,
            text="⏳ Launching background browser to extract Clic schedule...",
            text_color=THEME["text_secondary"],
            font=ctk.CTkFont(size=14)
        )
        self.loading_lbl.pack(pady=50)

        self.load_schedule()

    def load_schedule(self):
        def fetch():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                res = loop.run_until_complete(fetch_raw_schedule())
                self.after(0, lambda: self.render_table(res))
            except Exception as e:
                self.after(0, lambda: self.render_table({"error": str(e)}))
        threading.Thread(target=fetch, daemon=True).start()

    def render_table(self, result):
        for w in self.table_frame.winfo_children():
            w.destroy()

        if "error" in result:
            ctk.CTkLabel(
                self.table_frame, text=f"❌ Error: {result['error']}", text_color=THEME["danger"], font=ctk.CTkFont(size=14)
            ).pack(pady=50)
            return

        raw_data = result.get("data", "")
        classes = self.parse_data(raw_data)

        if not classes:
            ctk.CTkLabel(
                self.table_frame, text="No classes found in schedule.", text_color=THEME["text_secondary"], font=ctk.CTkFont(size=14)
            ).pack(pady=50)
            return

        self.table_frame.grid_columnconfigure(0, weight=1)
        self.table_frame.grid_columnconfigure(1, weight=1)
        self.table_frame.grid_columnconfigure(2, weight=2)
        self.table_frame.grid_columnconfigure(3, weight=1)
        self.table_frame.grid_columnconfigure(4, weight=3)

        headers = ["Day", "Time", "Subject Code", "Session", "Venue"]

        for col_idx, col_name in enumerate(headers):
            cell = ctk.CTkFrame(
                self.table_frame, fg_color=THEME["header_blue"], corner_radius=0, border_width=1, border_color=THEME["border"]
            )
            cell.grid(row=0, column=col_idx, sticky="nsew")

            lbl = ctk.CTkLabel(
                cell, text=col_name, font=ctk.CTkFont(weight="bold", size=13), text_color="#FFFFFF", anchor="w"
            )
            lbl.pack(padx=12, pady=10, fill="x")

        current_day = None
        row_color_toggle = False

        for row_idx, c in enumerate(classes, start=1):
            bg_color = THEME["card_bg"] if not row_color_toggle else THEME["card_alt"]
            row_color_toggle = not row_color_toggle

            day_text = c["day"] if c["day"] != current_day else ""
            current_day = c["day"]

            row_data = [day_text, c["time"], c["code"], c["session"], c["room"]]

            for col_idx, text in enumerate(row_data):
                cell = ctk.CTkFrame(
                    self.table_frame, fg_color=bg_color, corner_radius=0, border_color=THEME["border"], border_width=1
                )
                cell.grid(row=row_idx, column=col_idx, sticky="nsew")

                font_weight = "bold" if col_idx in [0, 2] else "normal"
                text_col = THEME["accent_indigo"] if col_idx == 0 else (
                    THEME["text_primary"] if col_idx == 2 else THEME["text_secondary"]
                )

                lbl = ctk.CTkLabel(
                    cell, text=text, font=ctk.CTkFont(size=12, weight=font_weight), text_color=text_col, anchor="w", justify="left"
                )
                lbl.pack(padx=12, pady=12, fill="x", expand=True)

    def parse_data(self, raw_text):
        classes = []
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

        current_day = ""
        i = 0
        
        days_pattern = re.compile(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)", re.IGNORECASE)
        time_pattern = re.compile(r"^(\d{1,2}:\d{2}\s*(?:AM|PM)?)", re.IGNORECASE)

        while i < len(lines):
            line = lines[i]

            day_match = days_pattern.match(line)
            if day_match:
                current_day = day_match.group(1).capitalize()
                i += 1
                continue

            time_match = time_pattern.match(line)
            if time_match and current_day:
                time_str = time_match.group(1)
                i += 1

                course_line = lines[i] if i < len(lines) else ""
                i += 1

                room = ""
                if i < len(lines) and lines[i].startswith("Room:"):
                    room = lines[i].replace("Room:", "").strip()
                    i += 1

                if i < len(lines) and lines[i].startswith("Status:"):
                    i += 1

                parts = course_line.split()
                if len(parts) >= 2:
                    session = parts[-1]
                    code = " ".join(parts[:-1])
                else:
                    code = course_line
                    session = "Class"

                classes.append({
                    "day": current_day,
                    "time": time_str,
                    "code": code,
                    "session": session,
                    "room": room
                })
                continue

            i += 1

        def day_sort_key(c):
            day_index = DAYS_ORDER.index(c["day"]) if c["day"] in DAYS_ORDER else 99
            return (day_index, c["time"])

        classes.sort(key=day_sort_key)
        return classes