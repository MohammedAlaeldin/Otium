import threading
import asyncio
import re
import customtkinter as ctk
import schedule_backend

THEME = {
    "bg_dark": "#121216",
    "card_bg": "#1E1E2A",
    "card_hover": "#262638",
    "card_alt": "#171721",
    "header_bg": "#181822",
    "header_blue": "#1E3A8A",
    "border": "#323246",
    "border_hover": "#4B4B66",
    "text_primary": "#F1F5F9",
    "text_secondary": "#94A3B8",
    "accent_indigo": "#6366F1",
    "accent_hover": "#4F46E5",
    "error_text": "#FFA3A3",
    "danger": "#EF4444"
}

DAYS_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class ScheduleView(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color=THEME["bg_dark"])

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.top_bar = ctk.CTkFrame(self, fg_color="transparent", height=50)
        self.top_bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(15, 10))
        self.top_bar.grid_propagate(False)

        self.header_title = ctk.CTkLabel(
            self.top_bar, text="Schedule", font=ctk.CTkFont(size=22, weight="bold"),
            text_color=THEME["text_primary"]
        )
        self.header_title.pack(side="left")

        self.refresh_btn = ctk.CTkButton(
            self.top_bar, text="↻ Refresh", width=100, height=32,
            fg_color=THEME["card_bg"], hover_color=THEME["border_hover"], text_color=THEME["text_primary"],
            border_width=1, border_color=THEME["border"], font=ctk.CTkFont(size=12, weight="bold"),
            command=self.load_data
        )
        self.refresh_btn.pack(side="right", pady=9)

        self.schedule_list_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=THEME["border"], scrollbar_button_hover_color=THEME["border_hover"]
        )
        self.schedule_list_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))

        self.load_data()

    def load_data(self):
        if hasattr(self, "refresh_btn"):
            self.refresh_btn.configure(state="disabled", text="Syncing...")

        for child in self.schedule_list_frame.winfo_children():
            child.destroy()

        ctk.CTkLabel(
            self.schedule_list_frame, text="⏳ Launching background browser to extract Clic schedule...",
            font=ctk.CTkFont(size=14),
            text_color=THEME["text_secondary"]
        ).pack(pady=40)

        threading.Thread(target=self._fetch_and_render, daemon=True).start()

    def _fetch_and_render(self):
        try:
            # Create a new event loop inside the background thread for Playwright
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            res = loop.run_until_complete(schedule_backend.fetch_raw_schedule())
            self.after(0, lambda: self._render_ui(res))
        except Exception as e:
            self.after(0, lambda: self._render_ui({"error": str(e)}))

    def _render_error(self, frame, error_msg=None):
        for child in frame.winfo_children():
            child.destroy()

        card = ctk.CTkFrame(frame, fg_color=THEME["card_bg"], border_color=THEME["border"], border_width=1,
                            corner_radius=10)
        card.pack(fill="x", padx=10, pady=15, ipady=10)

        ctk.CTkLabel(card, text="🔌 Sync Needed / Connection Issue", font=ctk.CTkFont(weight="bold", size=15),
                     text_color=THEME["text_primary"]).pack(pady=(15, 5))

        msg = "Unable to connect or fetch your schedule right now.\nPlease click refresh below to try sync again."
        if error_msg and "No scheduled events found" not in error_msg:
            msg += f"\n\nDetails: {error_msg}"

        ctk.CTkLabel(card, text=msg, font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"],
                     justify="center").pack(pady=5)

        refresh_btn = ctk.CTkButton(
            card, text="↻ Please Refresh", width=140, height=32,
            fg_color=THEME["accent_indigo"], hover_color=THEME["accent_hover"], text_color=THEME["text_primary"],
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.load_data
        )
        refresh_btn.pack(pady=(10, 15))

    def _render_ui(self, result: dict):
        if hasattr(self, "refresh_btn"):
            self.refresh_btn.configure(state="normal", text="↻ Refresh")

        for child in self.schedule_list_frame.winfo_children():
            child.destroy()

        if "error" in result:
            self._render_error(self.schedule_list_frame, result["error"])
            return

        raw_data = result.get("data", "")
        classes = self.parse_data(raw_data)

        if not classes:
            self._render_error(self.schedule_list_frame, "No scheduled events found.")
            return

        self.schedule_list_frame.grid_columnconfigure(0, weight=1)
        self.schedule_list_frame.grid_columnconfigure(1, weight=1)
        self.schedule_list_frame.grid_columnconfigure(2, weight=2)
        self.schedule_list_frame.grid_columnconfigure(3, weight=1)
        self.schedule_list_frame.grid_columnconfigure(4, weight=3)

        headers = ["Day", "Time", "Subject Code", "Session", "Venue"]

        for col_idx, col_name in enumerate(headers):
            cell = ctk.CTkFrame(
                self.schedule_list_frame, fg_color=THEME["header_blue"], corner_radius=0, border_width=1,
                border_color=THEME["border"]
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
                    self.schedule_list_frame, fg_color=bg_color, corner_radius=0, border_color=THEME["border"],
                    border_width=1
                )
                cell.grid(row=row_idx, column=col_idx, sticky="nsew")

                font_weight = "bold" if col_idx in [0, 2] else "normal"
                text_col = THEME["accent_indigo"] if col_idx == 0 else (
                    THEME["text_primary"] if col_idx == 2 else THEME["text_secondary"]
                )

                lbl = ctk.CTkLabel(
                    cell, text=text, font=ctk.CTkFont(size=12, weight=font_weight), text_color=text_col, anchor="w",
                    justify="left"
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