import customtkinter as ctk
import threading
import webbrowser
import math
from datetime import datetime, timedelta

from home_backend import (
    get_home_data,
    get_cached_home_data,
    save_cached_home_data,
    dismiss_notification,
    add_custom_task,
    delete_custom_task,
    get_custom_tasks,
    _parse_flexible_datetime
)
from outlook_backend import OutlookBackend
import ebwise_backend

THEME = {
    "bg_dark": "#121216",
    "card_bg": "#1E1E2A",
    "card_hover": "#2B2B3D",
    "header_bg": "#181822",
    "border": "#323246",
    "border_hover": "#6366F1",
    "text_primary": "#F1F5F9",
    "text_secondary": "#94A3B8",
    "accent_indigo": "#6366F1",
    "danger": "#EF4444",
    "success": "#10B981",
    "warning": "#EAB308",
    "teams_purple": "#5B5FC7",
    "outlook_blue": "#0078D4"
}


class HomeView(ctk.CTkFrame):
    def __init__(self, master, on_navigate_callback=None):
        super().__init__(master, fg_color=THEME["bg_dark"])
        self.on_navigate_callback = on_navigate_callback

        self.assignments_visible = True
        self.raw_feed = []
        self.current_assignments = []

        self.filter_states = {
            "Outlook": True,
            "Teams": True,
            "eBwise": True
        }

        # --- Live Meeting Banner ---
        self.banner_frame = ctk.CTkFrame(self, fg_color=THEME["teams_purple"], corner_radius=8)
        self.banner_title = ctk.CTkLabel(
            self.banner_frame,
            text="🎥 Live Meeting Now:",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#FFFFFF"
        )
        self.banner_title.pack(side="left", padx=15, pady=10)

        self.banner_join_btn = ctk.CTkButton(
            self.banner_frame,
            text="Join Meeting",
            fg_color="#FFFFFF",
            text_color=THEME["teams_purple"],
            hover_color="#E0E0E0",
            font=ctk.CTkFont(weight="bold")
        )
        self.banner_join_btn.pack(side="right", padx=15, pady=10)

        # --- Main Body Split ---
        self.body_container = ctk.CTkFrame(self, fg_color="transparent")
        self.body_container.pack(fill="both", expand=True, padx=20, pady=20)

        # Left Column: Activity Feed & Filters
        self.feed_col = ctk.CTkFrame(self.body_container, fg_color="transparent")
        self.feed_col.pack(side="left", fill="both", expand=True, padx=(0, 10))

        self.filter_frame = ctk.CTkFrame(self.feed_col, fg_color="transparent")
        self.filter_frame.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            self.filter_frame,
            text="Recent Activity",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=THEME["text_primary"]
        ).pack(side="left", padx=(0, 15))

        # Localized Loading Indicator
        self.loading_indicator = ctk.CTkProgressBar(self.filter_frame, mode="indeterminate", width=80, height=4,
                                                    fg_color=THEME["bg_dark"])

        # Illuminated Toggle Filter Pills
        self.btn_outlook = ctk.CTkButton(
            self.filter_frame, text="Outlook", width=80, height=28, corner_radius=14,
            font=ctk.CTkFont(size=12, weight="bold"), command=lambda: self.toggle_filter("Outlook")
        )
        self.btn_outlook.pack(side="left", padx=4)

        self.btn_teams = ctk.CTkButton(
            self.filter_frame, text="Teams", width=80, height=28, corner_radius=14,
            font=ctk.CTkFont(size=12, weight="bold"), command=lambda: self.toggle_filter("Teams")
        )
        self.btn_teams.pack(side="left", padx=4)

        self.btn_ebwise = ctk.CTkButton(
            self.filter_frame, text="eBwise", width=80, height=28, corner_radius=14,
            font=ctk.CTkFont(size=12, weight="bold"), command=lambda: self.toggle_filter("eBwise")
        )
        self.btn_ebwise.pack(side="left", padx=4)

        # Clean Assignments Toggle Button (Just an Arrow)
        self.toggle_assignments_btn = ctk.CTkButton(
            self.filter_frame, text="▶", width=30, height=28, corner_radius=14,
            font=ctk.CTkFont(size=14, weight="bold"), fg_color="transparent", text_color=THEME["text_secondary"],
            hover_color=THEME["card_hover"], command=self.toggle_assignments_panel
        )
        self.toggle_assignments_btn.pack(side="right", padx=(10, 0))

        self.update_filter_button_styles()

        self.feed_scroll = ctk.CTkScrollableFrame(self.feed_col, fg_color="transparent")
        self.feed_scroll.pack(fill="both", expand=True)

        # Right Column: Assignments Panel (Fully Hideable)
        self.assign_col = ctk.CTkFrame(self.body_container, width=320, fg_color=THEME["card_bg"], corner_radius=10,
                                       border_width=1, border_color=THEME["border"])
        self.assign_col.pack(side="right", fill="y")
        self.assign_col.pack_propagate(False)

        self.assign_header_frame = ctk.CTkFrame(self.assign_col, fg_color="transparent")
        self.assign_header_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(
            self.assign_header_frame,
            text="Upcoming Tasks",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=THEME["text_primary"]
        ).pack(side="left", padx=5)

        self.add_task_btn = ctk.CTkButton(
            self.assign_header_frame,
            text="+",
            width=28,
            height=28,
            corner_radius=14,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=THEME["accent_indigo"],
            hover_color=THEME["border_hover"],
            command=self.open_add_task_modal
        )
        self.add_task_btn.pack(side="right")

        self.assign_scroll = ctk.CTkScrollableFrame(self.assign_col, fg_color="transparent")
        self.assign_scroll.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        # Snapshot cache loading before fetching fresh data
        self.load_snapshot()
        self.refresh_data()

    def load_snapshot(self):
        """Instantly load cached data so the UI doesn't appear empty while fetching."""
        cached_data = get_cached_home_data()
        if cached_data.get("feed") or cached_data.get("assignments"):
            self._update_ui(cached_data, is_snapshot=True)

    def toggle_filter(self, source: str):
        self.filter_states[source] = not self.filter_states[source]
        self.update_filter_button_styles()
        self.apply_filters()

    def update_filter_button_styles(self):
        if self.filter_states["Outlook"]:
            self.btn_outlook.configure(fg_color=THEME["outlook_blue"], text_color="#FFFFFF", hover_color="#005A9E")
        else:
            self.btn_outlook.configure(fg_color="#181822", text_color=THEME["text_secondary"],
                                       hover_color=THEME["card_hover"])

        if self.filter_states["Teams"]:
            self.btn_teams.configure(fg_color=THEME["teams_purple"], text_color="#FFFFFF", hover_color="#4649A6")
        else:
            self.btn_teams.configure(fg_color="#181822", text_color=THEME["text_secondary"],
                                     hover_color=THEME["card_hover"])

        if self.filter_states["eBwise"]:
            self.btn_ebwise.configure(fg_color=THEME["accent_indigo"], text_color="#FFFFFF", hover_color="#4F46E5")
        else:
            self.btn_ebwise.configure(fg_color="#181822", text_color=THEME["text_secondary"],
                                      hover_color=THEME["card_hover"])

    def toggle_assignments_panel(self):
        self.assignments_visible = not self.assignments_visible
        if self.assignments_visible:
            self.toggle_assignments_btn.configure(text="▶")
            self.assign_col.pack(side="right", fill="y")
        else:
            self.toggle_assignments_btn.configure(text="◀")
            self.assign_col.pack_forget()

    def refresh_data(self):
        self.loading_indicator.pack(side="left", padx=10)
        self.loading_indicator.start()
        threading.Thread(target=self._worker_fetch, daemon=True).start()

    def _worker_fetch(self):
        data = get_home_data()
        self.after(0, lambda: self._update_ui(data, is_snapshot=False))

    def apply_filters(self):
        for widget in self.feed_scroll.winfo_children():
            widget.destroy()

        active_sources = [src for src, active in self.filter_states.items() if active]
        filtered_feed = [item for item in self.raw_feed if item["source"] in active_sources]

        if not filtered_feed:
            ctk.CTkLabel(self.feed_scroll, text="No active notifications for the selected filters.",
                         text_color=THEME["text_secondary"]).pack(pady=30)
        else:
            for item in filtered_feed:
                self._create_feed_card(item)

    def _update_ui(self, data, is_snapshot=False):
        if not is_snapshot:
            self.loading_indicator.stop()
            self.loading_indicator.pack_forget()
            threading.Thread(target=save_cached_home_data, args=(data,), daemon=True).start()

        live = data.get("live_meeting")
        if live:
            self.banner_frame.pack(fill="x", padx=20, pady=(20, 0), before=self.body_container)
            self.banner_title.configure(text=f"🎥 Live Now: {live['subject']} ({live['time']})")
            self.banner_join_btn.configure(command=lambda u=live['url']: webbrowser.open(u))
        else:
            self.banner_frame.pack_forget()

        self.raw_feed = data.get("feed", [])
        self.apply_filters()

        self.current_assignments = data.get("assignments", [])
        self._render_assignments()

    def _render_assignments(self):
        for widget in self.assign_scroll.winfo_children(): widget.destroy()

        if not self.current_assignments:
            ctk.CTkLabel(self.assign_scroll, text="No upcoming deadlines.", text_color=THEME["text_secondary"]).pack(
                pady=20)
        else:
            for assign in self.current_assignments:
                self._create_assignment_card(assign)

    def _create_feed_card(self, item):
        card = ctk.CTkFrame(
            self.feed_scroll, fg_color=THEME["card_bg"], corner_radius=10,
            border_width=1, border_color=THEME["border"], cursor="hand2"
        )
        card.pack(fill="x", pady=6, padx=4)

        top_row = ctk.CTkFrame(card, fg_color="transparent")
        top_row.pack(fill="x", padx=12, pady=(10, 2))

        source_color = THEME["accent_indigo"] if item["source"] == "eBwise" else THEME["teams_purple"] if item[
                                                                                                              "source"] == "Teams" else \
        THEME["outlook_blue"]

        source_frame = ctk.CTkFrame(top_row, fg_color="transparent")
        source_frame.pack(side="left")

        ctk.CTkLabel(source_frame, text=item["source"].upper(), font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=source_color).pack(side="left")

        if item["source"] == "eBwise" and item.get("course_tag"):
            badge = ctk.CTkLabel(
                source_frame,
                text=item["course_tag"],
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color=THEME["accent_indigo"],
                text_color="#FFFFFF",
                corner_radius=4,
                height=16
            )
            badge.pack(side="left", padx=(8, 0))

        if isinstance(item["time"], datetime):
            time_str = item["time"].strftime("%b %d, %I:%M %p")
        else:
            time_str = item["time"]

        ctk.CTkLabel(top_row, text=time_str, font=ctk.CTkFont(size=10), text_color=THEME["text_secondary"]).pack(
            side="right")

        ctk.CTkLabel(card, text=item["title"], font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=THEME["text_primary"], anchor="w").pack(fill="x", padx=12, pady=(2, 0))

        if item.get("subtitle"):
            ctk.CTkLabel(card, text=item["subtitle"], font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"],
                         anchor="w").pack(fill="x", padx=12, pady=(0, 10))

        def on_enter(e):
            card.configure(fg_color=THEME["card_hover"], border_color=THEME["border_hover"])

        def on_leave(e):
            card.configure(fg_color=THEME["card_bg"], border_color=THEME["border"])

        def on_click(e):
            dismiss_notification(item["id"])
            card.destroy()

            src = item["source"]
            payload = {}
            if src == "Outlook":
                threading.Thread(target=lambda: OutlookBackend().mark_as_read(item.get("msg_id")), daemon=True).start()
                payload = {"msg_id": item.get("msg_id")}
                self._navigate_to_view("Outlook", payload)
            elif src == "Teams":
                payload = {
                    "type": item.get("type"),
                    "chat_id": item.get("chat_id"),
                    "team_id": item.get("team_id"),
                    "channel_id": item.get("channel_id"),
                    "chat_title": item.get("chat_title")
                }
                self._navigate_to_view("Teams", payload)
            elif src == "eBwise":
                url = item.get("url")
                if url:
                    ebwise_backend.open_ebwise_url_authenticated(url)
                else:
                    self._navigate_to_view("Ebwise")

        for widget in [card] + card.winfo_children() + top_row.winfo_children() + source_frame.winfo_children():
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)
            widget.bind("<Button-1>", on_click)

    def _navigate_to_view(self, view_name: str, payload: dict = None):
        if self.on_navigate_callback:
            self.on_navigate_callback(view_name, payload=payload)

    def _create_assignment_card(self, assign):
        now = datetime.now()
        due_date = assign["due_date"]
        if isinstance(due_date, str):
            due_date = _parse_flexible_datetime(due_date)

        time_left = due_date - now
        days = time_left.days
        hours = math.floor(time_left.seconds / 3600)

        if days == 0 and hours < 24:
            color = THEME["danger"]
            countdown_text = f"Due in {hours}h" if hours > 0 else "Due within 1 hour!"
        elif days <= 3:
            color = THEME["warning"]
            countdown_text = f"Due in {days}d {hours}h"
        else:
            color = THEME["success"]
            countdown_text = f"Due in {days} days"

        card = ctk.CTkFrame(self.assign_scroll, fg_color=THEME["bg_dark"], corner_radius=8, border_width=1,
                            border_color=color)
        card.pack(fill="x", pady=5, padx=5)

        header_row = ctk.CTkFrame(card, fg_color="transparent")
        header_row.pack(fill="x", padx=10, pady=(8, 2))

        ctk.CTkLabel(header_row, text=countdown_text, font=ctk.CTkFont(size=11, weight="bold"), text_color=color,
                     anchor="w").pack(side="left")

        if assign.get("is_custom"):
            del_btn = ctk.CTkButton(
                header_row, text="✕", width=20, height=20, fg_color="transparent", text_color=THEME["danger"],
                hover_color=THEME["card_bg"], command=lambda tid=assign["id"]: self._delete_custom_task(tid)
            )
            del_btn.pack(side="right")

        ctk.CTkLabel(card, text=assign["title"], font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=THEME["text_primary"], anchor="w", wraplength=250).pack(fill="x", padx=10)
        ctk.CTkLabel(card, text=assign["course"], font=ctk.CTkFont(size=11), text_color=THEME["text_secondary"],
                     anchor="w", wraplength=250).pack(fill="x", padx=10, pady=(0, 8))

        if assign.get("url"):
            card.configure(cursor="hand2")
            for w in [card] + card.winfo_children():
                w.bind("<Button-1>", lambda e, u=assign["url"]: ebwise_backend.open_ebwise_url_authenticated(u))

    def _delete_custom_task(self, task_id: str):
        delete_custom_task(task_id)
        self.refresh_tasks_only()

    def refresh_tasks_only(self):
        custom_tasks = get_custom_tasks()
        now = datetime.now()

        new_assigns = [a for a in self.current_assignments if not a.get("is_custom")]
        for task in custom_tasks:
            due_dt = _parse_flexible_datetime(task.get("due_date"))
            if due_dt and due_dt >= now:
                new_assigns.append({
                    "id": task.get("id"),
                    "title": task.get("title"),
                    "course": task.get("course", "Personal"),
                    "due_date": due_dt,
                    "url": "",
                    "source": "Custom",
                    "is_custom": True
                })

        new_assigns.sort(key=lambda x: x["due_date"])
        self.current_assignments = new_assigns
        self._render_assignments()

    def open_add_task_modal(self):
        modal = ctk.CTkToplevel(self)
        modal.title("Add Custom Task")
        modal.geometry("400x350")
        modal.configure(fg_color=THEME["bg_dark"])
        modal.transient(self.winfo_toplevel())
        modal.grab_set()

        ctk.CTkLabel(
            modal,
            text="Create Assigned Task",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=THEME["text_primary"]
        ).pack(pady=(15, 10))

        title_entry = ctk.CTkEntry(modal, placeholder_text="Task Title (e.g. Lab Report 2)", width=320)
        title_entry.pack(pady=8)

        course_entry = ctk.CTkEntry(modal, placeholder_text="Course / Category (e.g. CSP1123)", width=320)
        course_entry.pack(pady=8)

        datetime_frame = ctk.CTkFrame(modal, fg_color="transparent", width=320)
        datetime_frame.pack(pady=8)

        now = datetime.now() + timedelta(days=2)

        date_entry = ctk.CTkEntry(datetime_frame, placeholder_text="End Date (YYYY-MM-DD)", width=180)
        date_entry.insert(0, now.strftime("%Y-%m-%d"))
        date_entry.pack(side="left", padx=(0, 5))

        time_entry = ctk.CTkEntry(datetime_frame, placeholder_text="End Time (HH:MM)", width=135)
        time_entry.insert(0, "23:59")
        time_entry.pack(side="right")

        status_lbl = ctk.CTkLabel(modal, text="", font=ctk.CTkFont(size=11), text_color=THEME["danger"])
        status_lbl.pack(pady=2)

        def save():
            t = title_entry.get().strip()
            c = course_entry.get().strip()
            end_date = date_entry.get().strip()
            end_time = time_entry.get().strip()

            if not t or not end_date or not end_time:
                status_lbl.configure(text="Title, End Date, and End Time are required!")
                return

            combined_datetime = f"{end_date} {end_time}"

            if add_custom_task(t, c, combined_datetime):
                modal.destroy()
                self.refresh_tasks_only()
            else:
                status_lbl.configure(text="Invalid format! Use YYYY-MM-DD and HH:MM")

        ctk.CTkButton(
            modal,
            text="Add Task",
            fg_color=THEME["accent_indigo"],
            hover_color=THEME["border_hover"],
            font=ctk.CTkFont(weight="bold"),
            command=save
        ).pack(pady=15)