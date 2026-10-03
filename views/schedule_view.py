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
    "accent_hover": "#4F46E5"
}

DAYS_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class ScheduleView(ctk.CTkFrame):
    # Main view for displaying the weekly schedule including a refresh button and a scrollable list of classes
    def __init__(self, parent):
        super().__init__(parent, fg_color=THEME["bg_dark"])

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.top_bar = ctk.CTkFrame(self, fg_color="transparent", height=50)
        self.top_bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(15, 10))
        self.top_bar.grid_propagate(False)

        self.header_title = ctk.CTkLabel(
            self.top_bar, text="Weekly Schedule", font=ctk.CTkFont(size=22, weight="bold"),
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

    #  Loads schedule data in a separate thread to avoid blocking the UI and displays a loading message while fetching
    def load_data(self):
        if hasattr(self, "refresh_btn"):
            self.refresh_btn.configure(state="disabled", text="Syncing...")

        for child in self.schedule_list_frame.winfo_children():
            child.destroy()

        ctk.CTkLabel(
            self.schedule_list_frame, text="⏳ Simulating calendar navigation to extract full week...",
            font=ctk.CTkFont(size=14),
            text_color=THEME["text_secondary"]
        ).pack(pady=40)

        threading.Thread(target=self._fetch_and_render, daemon=True).start()

    # Creates a new asyncio event loop to fetch the raw schedule data and then renders the UI with the results or shows an error if fetching fails
    def _fetch_and_render(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            res = loop.run_until_complete(schedule_backend.fetch_raw_schedule())
            self.after(0, lambda: self._render_ui(res))
        except Exception:
            self.after(0, lambda: self._render_error())

    # Renders a card indicating that no classes were found for the selected period, along with a refresh button
    def _render_no_classes(self, message: str):
        """Shown when CLIC itself reports no classes for this period — a normal
        state (holidays, term break, light week), not a sync/connection problem,
        so it gets its own calmer card instead of the 'Sync Needed' one."""
        for child in self.schedule_list_frame.winfo_children():
            child.destroy()

        if hasattr(self, "refresh_btn"):
            self.refresh_btn.configure(state="normal", text="↻ Refresh")

        card = ctk.CTkFrame(self.schedule_list_frame, fg_color=THEME["card_bg"], border_color=THEME["border"],
                            border_width=1, corner_radius=10)
        card.pack(fill="x", padx=10, pady=15, ipady=10)

        ctk.CTkLabel(card, text="📅 No Classes Found", font=ctk.CTkFont(weight="bold", size=15),
                     text_color=THEME["text_primary"]).pack(pady=(15, 5))

        ctk.CTkLabel(card, text=message, font=ctk.CTkFont(size=12),
                     text_color=THEME["text_secondary"], justify="center", wraplength=320).pack(pady=5)

        refresh_btn = ctk.CTkButton(
            card, text="↻ Refresh", width=140, height=32,
            fg_color=THEME["accent_indigo"], hover_color=THEME["accent_hover"], text_color=THEME["text_primary"],
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.load_data
        )
        refresh_btn.pack(pady=(10, 15))

    # Creates a card indicating a connection problem and prompts the user to refresh 
    def _render_error(self):
        for child in self.schedule_list_frame.winfo_children():
            child.destroy()

        if hasattr(self, "refresh_btn"):
            self.refresh_btn.configure(state="normal", text="↻ Refresh")

        card = ctk.CTkFrame(self.schedule_list_frame, fg_color=THEME["card_bg"], border_color=THEME["border"],
                            border_width=1, corner_radius=10)
        card.pack(fill="x", padx=10, pady=15, ipady=10)

        ctk.CTkLabel(card, text="🔌 Sync Needed", font=ctk.CTkFont(weight="bold", size=15),
                     text_color=THEME["text_primary"]).pack(pady=(15, 5))

        ctk.CTkLabel(card, text="Bad internet connection, please refresh.", font=ctk.CTkFont(size=12),
                     text_color=THEME["text_secondary"], justify="center").pack(pady=5)

        refresh_btn = ctk.CTkButton(
            card, text="↻ Please Refresh", width=140, height=32,
            fg_color=THEME["accent_indigo"], hover_color=THEME["accent_hover"], text_color=THEME["text_primary"],
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.load_data
        )
        refresh_btn.pack(pady=(10, 15))

    # Reenables the refresh button and displays an error card indicating a connection problem when fetching schedule data fails
    def _render_ui(self, result: dict):
        if hasattr(self, "refresh_btn"):
            self.refresh_btn.configure(state="normal", text="↻ Refresh")

        for child in self.schedule_list_frame.winfo_children():
            child.destroy()

        if result.get("status") == "empty":
            self._render_no_classes(result.get("message", "No scheduled classes were found."))
            return

        if "error" in result:
            self._render_error()
            return

        raw_data = result.get("data", "")
        classes = self.parse_data(raw_data)

        if not classes:
            # Reaching here means CLIC's page loaded and parsed fine, but nothing
            # matched — no known "no data" phrase triggered either. That's still not
            # evidence of a connection problem, so it gets the calm card too, not
            # the alarming "Sync Needed" one.
            self._render_no_classes("No scheduled classes were found for this period.")
            return

        # 5 Columns for List View: Day, Time, Code, Session, Venue
        col_weights = [1, 1, 3, 1, 2]
        for idx, w in enumerate(col_weights):
            self.schedule_list_frame.grid_columnconfigure(idx, weight=w)

        headers = ["Day", "Time", "Course Info", "Session", "Venue"]

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

            row_data = [day_text, c["time"], c["code"], c["session"], c["venue"]]

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
                    justify="left", wraplength=220
                )
                lbl.pack(padx=12, pady=12, fill="x", expand=True)

    # Scans the ClIC 'By Date' linear list view and groups the 5 data points (Day, Time, Course Code, Session, Venue) into structured dictionaries, deduplicates them, and sorts them chronologically for display in the UI.
    def parse_data(self, raw_text):
        """Scans the 'By Date' linear list view and groups the 5 data points."""
        classes = []
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

        current_day = ""
        days_pattern = re.compile(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)", re.IGNORECASE)
        # Matches time like "12:00PM" or "12:00 PM - 2:00 PM"
        time_pattern = re.compile(r"^(\d{1,2}:\d{2}\s*[APM]{2}(?:\s*-\s*\d{1,2}:\d{2}\s*[APM]{2})?)", re.IGNORECASE)
        room_pattern = re.compile(r"^Room:\s*(.*)", re.IGNORECASE)

        i = 0
        while i < len(lines):
            line = lines[i]

            # Day Header
            day_match = days_pattern.match(line)
            if day_match:
                current_day = day_match.group(1).capitalize()
                i += 1
                continue

            # Time Block
            time_match = time_pattern.match(line)
            if time_match and current_day:
                time_str = time_match.group(1)

                code = "Unknown Course"
                session = "Class"
                venue = "TBA"

                # Next line contains Course Code + Session (e.g. 'C MT1134 Tutorial')
                if i + 1 < len(lines):
                    info_line = lines[i + 1]
                    sess_match = re.search(r'\b(Lecture|Tutorial|Lab|Laboratory|Clinical)$', info_line, re.IGNORECASE)
                    if sess_match:
                        session = sess_match.group(1).capitalize()
                        code = info_line[:sess_match.start()].strip()
                    else:
                        code = info_line

                # Look For 'Room:'
                for offset in range(1, 4):
                    if i + offset < len(lines):
                        rm = room_pattern.match(lines[i + offset])
                        if rm:
                            # Trim out the building designation if desired, or keep it whole
                            venue = rm.group(1).split('-')[0].strip()
                            break

                        # Sometimes space separation causes the line to look like 'C MT1134 Tutorial Room: CQCR...'
                        inline_room = re.search(r'Room:\s*(.*)', lines[i + offset], re.IGNORECASE)
                        if inline_room:
                            venue = inline_room.group(1).split('-')[0].strip()
                            break

                classes.append({
                    "day": current_day,
                    "time": time_str,
                    "code": code,
                    "session": session,
                    "venue": venue
                })
                i += 2  # Skip over the time and info line we just processed
                continue

            i += 1

        # Deduplicate
        unique_classes = []
        seen = set()
        for c in classes:
            identifier = f"{c['day']}-{c['time']}-{c['code']}-{c['session']}"
            if identifier not in seen:
                seen.add(identifier)
                unique_classes.append(c)

        # Sort chronologically
        def day_sort_key(c):
            d_idx = DAYS_ORDER.index(c["day"]) if c["day"] in DAYS_ORDER else 98
            t_val = 0
            t_match = re.search(r'(\d{1,2}):(\d{2})\s*([APM]{2})', c["time"], re.IGNORECASE)
            if t_match:
                h, m, ampm = int(t_match.group(1)), int(t_match.group(2)), t_match.group(3).upper()
                if ampm == "PM" and h != 12: h += 12
                if ampm == "AM" and h == 12: h = 0
                t_val = h * 60 + m
            return (d_idx, t_val)

        unique_classes.sort(key=day_sort_key)
        return unique_classes