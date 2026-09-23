import re
import threading
import customtkinter as ctk
import ebwise_backend
from ebwise_backend import open_ebwise_url_authenticated
from storage import load_preferences, save_preferences

# ==========================================
# DESIGN SYSTEM & COLOR PALETTE
# ==========================================
THEME = {
    "bg_dark": "#121216",
    "card_bg": "#1E1E2A",
    "header_bg": "#181822",
    "border": "#323246",
    "border_hover": "#4B4B66",
    "text_primary": "#F1F5F9",
    "text_secondary": "#94A3B8",
    "text_muted": "#64748B",
    "accent_indigo": "#6366F1",
    "accent_hover": "#4F46E5",
    "reorder_active": "#EAB308",
    "reorder_selected": "#FFFFFF",
    "lock_red": "#EF4444"
}

RESOURCE_STYLES = {
    "pdf": ("📄", "PDF", "#F87171", "#2D1D24"),
    "ppt": ("📊", "PPT", "#FBBF24", "#2D261B"),
    "excel": ("📈", "EXCEL", "#34D399", "#182C23"),
    "word": ("📝", "DOC", "#38BDF8", "#1C2D42"),
    "zip": ("📦", "ARCHIVE", "#C084FC", "#261E33"),
    "github": ("🐙", "GITHUB", "#E2E8F0", "#22272E"),
    "chat": ("💬", "CHAT", "#4ADE80", "#182A20"),
    "assign": ("📥", "ASSIGNMENT", "#F43F5E", "#331825"),
    "forum": ("📢", "FORUM", "#38BDF8", "#1A2B3C"),
    "url": ("🔗", "LINK", "#60A5FA", "#1C2638"),
    "default": ("📌", "ITEM", "#94A3B8", "#222530")
}


def parse_course_title(fullname: str):
    match = re.match(r"^([A-Z]{3,4}\d{4})\s*[-:]?\s*(.*)$", fullname, re.IGNORECASE)
    if match:
        code, title = match.groups()
        clean_title = title.strip().title()
        return code.upper(), clean_title if clean_title else fullname.title()
    return "COURSE", fullname.title()


def detect_resource_style(item: dict):
    mod_type = (item.get("type") or "").lower()
    title = (item.get("title") or "").lower()
    url = (item.get("fileurl") or "").lower()

    if mod_type == "assign": return RESOURCE_STYLES["assign"]
    if mod_type in ["forum", "news"]: return RESOURCE_STYLES["forum"]
    if "github.com" in url or "git" in title: return RESOURCE_STYLES["github"]
    if any(k in url or k in title for k in ["whatsapp", "telegram", "chat", "discord"]): return RESOURCE_STYLES["chat"]
    if ".pdf" in url or "pdf" in title: return RESOURCE_STYLES["pdf"]
    if any(k in url or k in title for k in [".ppt", ".pptx", "presentation", "slides"]): return RESOURCE_STYLES["ppt"]
    if any(k in url or k in title for k in [".xls", ".xlsx", "excel", "spreadsheet"]): return RESOURCE_STYLES["excel"]
    if any(k in url or k in title for k in [".doc", ".docx", "word", "document"]): return RESOURCE_STYLES["word"]
    if any(k in url or k in title for k in [".zip", ".rar", ".7z", "folder", "archive"]): return RESOURCE_STYLES["zip"]
    if url.startswith("http") or mod_type == "url": return RESOURCE_STYLES["url"]
    return RESOURCE_STYLES["default"]


class CollapsibleFrame(ctk.CTkFrame):
    def __init__(self, master, title="Section", is_locked=False, availability_info="", **kwargs):
        border_col = THEME["border"] if not is_locked else "#3F252B"
        super().__init__(master, fg_color=THEME["card_bg"], border_color=border_col, border_width=1,
                         corner_radius=10, **kwargs)
        self.is_expanded = True
        self.is_locked = is_locked

        hdr_bg = THEME["header_bg"] if not is_locked else "#26171B"
        self.header_frame = ctk.CTkFrame(self, fg_color=hdr_bg, corner_radius=10, cursor="hand2")
        self.header_frame.pack(fill="x", expand=True)

        title_text = f"🔒 {title}" if is_locked else title
        title_color = THEME["text_primary"] if not is_locked else THEME["text_muted"]

        self.title_lbl = ctk.CTkLabel(self.header_frame, text=title_text, font=ctk.CTkFont(size=14, weight="bold"),
                                      text_color=title_color)
        self.title_lbl.pack(side="left", padx=15, pady=12)

        if is_locked:
            self.lock_badge = ctk.CTkFrame(self.header_frame, fg_color="#3B1820", corner_radius=4)
            self.lock_badge.pack(side="left", padx=5)
            ctk.CTkLabel(self.lock_badge, text="Restricted", font=ctk.CTkFont(size=10, weight="bold"),
                         text_color=THEME["lock_red"]).pack(padx=6, pady=2)

        self.toggle_lbl = ctk.CTkLabel(self.header_frame, text="▲", font=ctk.CTkFont(size=12, weight="bold"),
                                       text_color=THEME["text_secondary"])
        self.toggle_lbl.pack(side="right", padx=15, pady=12)

        for widget in (self.header_frame, self.title_lbl, self.toggle_lbl):
            widget.bind("<Button-1>", lambda e: self.toggle())

        self.content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.content_frame.pack(fill="x", expand=True, padx=10, pady=10)

        if is_locked and availability_info:
            notice = ctk.CTkFrame(self.content_frame, fg_color="#22171B", corner_radius=6)
            notice.pack(fill="x", padx=4, pady=(0, 8))
            ctk.CTkLabel(notice, text=f"⚠️ {availability_info}", font=ctk.CTkFont(size=11),
                         text_color=THEME["lock_red"], justify="left", wraplength=700).pack(padx=10, pady=8, anchor="w")

    def toggle(self):
        if self.is_expanded:
            self.content_frame.pack_forget()
            self.toggle_lbl.configure(text="▼")
            self.is_expanded = False
        else:
            self.content_frame.pack(fill="x", expand=True, padx=10, pady=10)
            self.toggle_lbl.configure(text="▲")
            self.is_expanded = True


class EbwiseView(ctk.CTkFrame):
    def __init__(self, master, fetch_callback=None, **kwargs):
        super().__init__(master, fg_color=THEME["bg_dark"], **kwargs)
        self.fetch_callback = fetch_callback
        self.cached_data = {}
        self.preferences = load_preferences()

        self.is_reorder_mode = False
        self.current_filter = "In Progress"

        # Request Cancellation & ID Tracking
        self.active_cancel_event = None
        self.active_request_id = 0

        self.selected_item_type = None
        self.selected_course_id = None
        self.selected_tab = None

        self.card_widgets = {}

        self.scroll_container = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                                       scrollbar_button_color=THEME["border"],
                                                       scrollbar_button_hover_color=THEME["border_hover"])
        self.scroll_container.pack(fill="both", expand=True, padx=20, pady=20)
        self.after(100, self._bind_keyboard_controls)
        self.show_loading()

    def _bind_keyboard_controls(self):
        root = self.winfo_toplevel()
        root.bind("<Up>", lambda e: self._move_selected(-3))
        root.bind("<Down>", lambda e: self._move_selected(3))
        root.bind("<Left>", lambda e: self._move_selected(-1))
        root.bind("<Right>", lambda e: self._move_selected(1))
        root.bind("<w>", lambda e: self._move_selected(-3))
        root.bind("<s>", lambda e: self._move_selected(3))
        root.bind("<a>", lambda e: self._move_selected(-1))
        root.bind("<d>", lambda e: self._move_selected(1))

    def show_loading(self):
        for widget in self.scroll_container.winfo_children(): widget.destroy()
        ctk.CTkLabel(self.scroll_container, text="⏳ Loading live eBwise dashboard...", font=ctk.CTkFont(size=14),
                     text_color=THEME["text_secondary"]).pack(pady=60)

    def update_data(self, data: dict, selected_filter: str = "In Progress"):
        self.cached_data = data
        self.current_filter = selected_filter
        if data.get("status") != "SUCCESS":
            for widget in self.scroll_container.winfo_children(): widget.destroy()
            ctk.CTkLabel(self.scroll_container, text=f"⚠️ Failed to load data (Status: {data.get('status')})",
                         text_color="#F87171", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=40)
            return
        self.render_course_grid(selected_filter=selected_filter)

    def _get_sorted_courses(self) -> list:
        courses = list(self.cached_data.get("courses", []))
        saved_order = self.preferences.get("course_orders", {}).get(self.current_filter, [])
        if not saved_order: return courses

        def get_sort_index(course):
            code, _ = parse_course_title(course.get("fullname", ""))
            cid = str(course.get("id") or code)
            return saved_order.index(cid) if cid in saved_order else 9999

        return sorted(courses, key=get_sort_index)

    # --- TOP BAR & NAVIGATION ---
    def _build_top_bar(self):
        top_bar = ctk.CTkFrame(self.scroll_container, fg_color="transparent")
        top_bar.pack(fill="x", pady=(0, 20))

        left_header = ctk.CTkFrame(top_bar, fg_color="transparent")
        left_header.pack(side="left")

        ctk.CTkLabel(left_header, text="My Courses", font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=THEME["text_primary"]).pack(side="left", padx=(0, 15))

        self.reorder_btn = ctk.CTkButton(
            left_header, text="✅ Done" if self.is_reorder_mode else "⚙️ Reorder", width=90, height=28,
            fg_color=THEME["reorder_active"] if self.is_reorder_mode else THEME["card_bg"],
            hover_color=THEME["accent_hover"],
            text_color="#000000" if self.is_reorder_mode else THEME["text_primary"],
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._toggle_reorder_mode
        )
        self.reorder_btn.pack(side="left")

        self.dpad_frame = ctk.CTkFrame(left_header, fg_color="transparent")
        if self.is_reorder_mode:
            self.dpad_frame.pack(side="left", padx=15)
            ctk.CTkButton(self.dpad_frame, text="▲", width=28, height=24, fg_color="#2A2A3A",
                          command=lambda: self._move_selected(-3)).grid(row=0, column=1, pady=1)
            ctk.CTkButton(self.dpad_frame, text="◀", width=28, height=24, fg_color="#2A2A3A",
                          command=lambda: self._move_selected(-1)).grid(row=1, column=0, padx=1)
            ctk.CTkButton(self.dpad_frame, text="▼", width=28, height=24, fg_color="#2A2A3A",
                          command=lambda: self._move_selected(3)).grid(row=1, column=1, padx=1)
            ctk.CTkButton(self.dpad_frame, text="▶", width=28, height=24, fg_color="#2A2A3A",
                          command=lambda: self._move_selected(1)).grid(row=1, column=2, padx=1)
            ctk.CTkLabel(self.dpad_frame, text="Select a Card OR Tab\nUse WASD or Arrows", justify="left",
                         font=ctk.CTkFont(size=10), text_color=THEME["text_secondary"]).grid(row=0, column=3, rowspan=2,
                                                                                             padx=10)

        right_header = ctk.CTkFrame(top_bar, fg_color="transparent")
        right_header.pack(side="right")

        tab_options = self.preferences.get("tab_order", ["In Progress", "Past", "Future", "All"])
        if self.current_filter not in tab_options: self.current_filter = tab_options[0]

        self.tab_bar = ctk.CTkSegmentedButton(
            right_header, values=tab_options, command=self._on_filter_change,
            selected_color=THEME["reorder_active"] if (self.is_reorder_mode and self.selected_item_type == "tab") else
            THEME["accent_indigo"],
            selected_hover_color=THEME["accent_hover"], unselected_color=THEME["card_bg"],
            unselected_hover_color=THEME["header_bg"],
            text_color=THEME["text_primary"]
        )
        self.tab_bar.set(self.selected_tab if (self.is_reorder_mode and self.selected_tab) else self.current_filter)
        self.tab_bar.pack(side="right")

    # --- CANCELLABLE SMOOTH RENDERING ---
    def _on_filter_change(self, selected_value: str):
        if self.is_reorder_mode:
            self.selected_item_type = "tab"
            self.selected_tab = selected_value
            self.selected_course_id = None
            self._update_card_borders()
            self.tab_bar.configure(selected_color=THEME["reorder_active"])
            return

        if self.active_cancel_event:
            self.active_cancel_event.set()

        self.active_request_id += 1
        req_id = self.active_request_id
        cancel_evt = threading.Event()
        self.active_cancel_event = cancel_evt

        self.current_filter = selected_value
        mapping = {"In Progress": "inprogress", "Future": "future", "Past": "past", "All": "all"}
        target_class = mapping.get(selected_value, "inprogress")

        self.cached_data = {"status": "SUCCESS", "courses": []}
        self.temp_courses = []
        self.fetch_complete = False

        for widget in self.scroll_container.winfo_children(): widget.destroy()
        self.card_widgets.clear()

        self._build_top_bar()
        self.grid_frame = ctk.CTkFrame(self.scroll_container, fg_color="transparent")
        self.grid_frame.pack(fill="both", expand=True)
        self.grid_frame.columnconfigure((0, 1, 2), weight=1, uniform="course_cols")

        self.loading_lbl = ctk.CTkLabel(self.grid_frame, text="⏳ Retrieving courses securely...",
                                        text_color=THEME["text_secondary"])
        self.loading_lbl.grid(row=0, column=0, columnspan=3, pady=40)

        def bg_fetch():
            def on_chunk(course_data):
                if req_id != self.active_request_id or cancel_evt.is_set():
                    return
                self.temp_courses.append(course_data)

            result = ebwise_backend.fetch_ebwise_data(target_class, progress_callback=on_chunk, cancel_event=cancel_evt)
            if req_id != self.active_request_id or cancel_evt.is_set():
                return
            self.fetch_complete = True
            self.after(0, lambda: self._finish_render(result, req_id))

        threading.Thread(target=bg_fetch, daemon=True).start()
        self.after(3000, lambda: self._render_partial(req_id))

    def _render_partial(self, req_id: int):
        if req_id != self.active_request_id or (self.active_cancel_event and self.active_cancel_event.is_set()):
            return
        if not self.fetch_complete and hasattr(self, "loading_lbl") and self.loading_lbl.winfo_exists():
            self.loading_lbl.configure(text="⏳ Fetching remaining courses... Displaying loaded items.")
            self.cached_data["courses"] = list(self.temp_courses)
            self._repopulate_grid()

    def _finish_render(self, result: dict, req_id: int):
        if req_id != self.active_request_id or (self.active_cancel_event and self.active_cancel_event.is_set()):
            return
        if hasattr(self, "loading_lbl") and self.loading_lbl.winfo_exists():
            self.loading_lbl.destroy()

        self.cached_data = result
        if not result.get("courses"):
            ctk.CTkLabel(self.grid_frame, text="No courses found for this filter classification.",
                         text_color=THEME["text_secondary"]).grid(row=0, column=0, columnspan=3, pady=30)
        else:
            self._repopulate_grid()

    def _repopulate_grid(self):
        for widget in self.grid_frame.winfo_children(): widget.destroy()
        self.card_widgets.clear()

        courses = self._get_sorted_courses()
        for idx, course in enumerate(courses):
            row = idx // 3
            col = idx % 3
            self._build_course_card(self.grid_frame, course, idx, row, col)

    def render_course_grid(self, selected_filter: str = None):
        if selected_filter: self.current_filter = selected_filter
        for widget in self.scroll_container.winfo_children(): widget.destroy()
        self.card_widgets.clear()

        self._build_top_bar()

        courses = self._get_sorted_courses()
        if not courses:
            ctk.CTkLabel(self.scroll_container, text="No courses found for this filter classification.",
                         text_color=THEME["text_secondary"], font=ctk.CTkFont(size=14)).pack(anchor="w", pady=30)
            return

        self.grid_frame = ctk.CTkFrame(self.scroll_container, fg_color="transparent")
        self.grid_frame.pack(fill="both", expand=True)
        self.grid_frame.columnconfigure((0, 1, 2), weight=1, uniform="course_cols")
        self._repopulate_grid()

    def _build_course_card(self, parent, course: dict, idx: int, row: int, col: int):
        code, title = parse_course_title(course.get("fullname", "Unknown Course"))
        cid = str(course.get("id") or code)

        is_selected = (self.is_reorder_mode and self.selected_item_type == "course" and cid == self.selected_course_id)
        border_col = THEME["reorder_selected"] if is_selected else (
            THEME["reorder_active"] if self.is_reorder_mode else THEME["border"])

        card = ctk.CTkFrame(parent, fg_color=THEME["card_bg"], border_color=border_col,
                            border_width=2 if self.is_reorder_mode else 1, corner_radius=12, height=200, cursor="hand2")
        card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
        card.grid_propagate(False)

        accent_col = THEME["reorder_selected"] if is_selected else (
            THEME["reorder_active"] if self.is_reorder_mode else THEME["accent_indigo"])
        accent_line = ctk.CTkFrame(card, fg_color=accent_col, height=4, corner_radius=2)
        accent_line.pack(fill="x", side="top")

        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=15, pady=12)

        code_badge = ctk.CTkFrame(content, fg_color="#272738", corner_radius=6)
        code_badge.pack(anchor="w", pady=(0, 8))
        ctk.CTkLabel(code_badge, text=code, font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=THEME["accent_indigo"]).pack(padx=8, pady=2)

        title_lbl = ctk.CTkLabel(content, text=title, font=ctk.CTkFont(size=14, weight="bold"),
                                 text_color=THEME["text_primary"], wraplength=210, justify="left", anchor="w")
        title_lbl.pack(fill="x", expand=True, anchor="w")

        instructors = course.get("instructors", [{"fullname": "No lecturers found", "email": "No email provided"}])

        lecturer_frame = ctk.CTkFrame(content, fg_color="transparent")
        lecturer_frame.pack(fill="x", side="bottom", pady=(5, 0))

        first_name = instructors[0].get('fullname')
        lecturer_lbl = ctk.CTkLabel(
            lecturer_frame,
            text=f"👤 {first_name}",
            font=ctk.CTkFont(size=11),
            text_color=THEME["text_secondary"],
            anchor="w",
            cursor="hand2"
        )
        lecturer_lbl.pack(fill="x", anchor="w")

        if len(instructors) > 1:
            more_lbl = ctk.CTkLabel(
                lecturer_frame,
                text=f"➕ {len(instructors) - 1} more lecturer(s)...",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=THEME["accent_indigo"],
                anchor="w",
                cursor="hand2"
            )
            more_lbl.pack(fill="x", anchor="w")
            more_lbl.bind("<Button-1>", lambda e, insts=instructors: self._show_lecturer_profile(insts))

        lecturer_lbl.bind("<Button-1>", lambda e, insts=instructors: self._show_lecturer_profile(insts))

        self.card_widgets[cid] = {"card": card, "accent": accent_line}

        if self.is_reorder_mode:
            select_action = lambda e, c=cid: self._select_card_for_reorder(c)
            for w in (card, content, title_lbl, code_badge): w.bind("<Button-1>", select_action)
        else:
            open_details = lambda e, c=course: self.render_course_details(c)
            for w in (card, content, title_lbl, code_badge): w.bind("<Button-1>", open_details)
            card.bind("<Enter>", lambda e: card.configure(border_color=THEME["border_hover"]))
            card.bind("<Leave>", lambda e: card.configure(border_color=THEME["border"]))

    def _show_lecturer_profile(self, instructors: list):
        if self.is_reorder_mode: return

        modal = ctk.CTkToplevel(self)
        modal.title("Participant Profile")
        modal.geometry("450x550")
        modal.configure(fg_color=THEME["bg_dark"])
        modal.transient(self.winfo_toplevel())
        modal.grab_set()

        scroll = ctk.CTkScrollableFrame(modal, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(scroll, text="Course Instructors", font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=THEME["text_primary"]).pack(pady=(10, 15))

        if not instructors or (len(instructors) == 1 and instructors[0].get("fullname") == "No lecturers found"):
            ctk.CTkLabel(scroll, text="No lecturers found for this course.", text_color=THEME["text_secondary"]).pack(
                pady=20)
            return

        def copy_to_clipboard(text: str, btn: ctk.CTkButton):
            self.clipboard_clear()
            self.clipboard_append(text)
            original_text = btn.cget("text")
            btn.configure(text="✅ Copied!")
            self.after(1500, lambda: btn.configure(text=original_text) if btn.winfo_exists() else None)

        for inst in instructors:
            card = ctk.CTkFrame(scroll, fg_color=THEME["card_bg"], corner_radius=12, border_color=THEME["border"],
                                border_width=1)
            card.pack(fill="x", padx=10, pady=8)

            ctk.CTkLabel(card, text="👤", font=ctk.CTkFont(size=45)).pack(pady=(15, 5))

            name = inst.get("fullname", "Unknown")
            email = inst.get("email", "No email provided")

            name_frame = ctk.CTkFrame(card, fg_color="transparent")
            name_frame.pack(pady=(0, 2))
            ctk.CTkLabel(name_frame, text=name, font=ctk.CTkFont(size=16, weight="bold"),
                         text_color=THEME["text_primary"], wraplength=280).pack(side="left", padx=(0, 10))
            if name != "No lecturers found":
                btn_copy_name = ctk.CTkButton(name_frame, text="📋 Copy", width=50, height=20, font=ctk.CTkFont(size=10),
                                              fg_color=THEME["border"], hover_color=THEME["border_hover"])
                btn_copy_name.configure(command=lambda t=name, b=btn_copy_name: copy_to_clipboard(t, b))
                btn_copy_name.pack(side="left")

            email_frame = ctk.CTkFrame(card, fg_color="transparent")
            email_frame.pack(pady=(0, 15))
            ctk.CTkLabel(email_frame, text=email, font=ctk.CTkFont(size=12), text_color=THEME["accent_indigo"]).pack(
                side="left", padx=(0, 10))
            if email and email != "No email provided":
                btn_copy_email = ctk.CTkButton(email_frame, text="📋 Copy", width=50, height=20,
                                               font=ctk.CTkFont(size=10), fg_color=THEME["border"],
                                               hover_color=THEME["border_hover"])
                btn_copy_email.configure(command=lambda t=email, b=btn_copy_email: copy_to_clipboard(t, b))
                btn_copy_email.pack(side="left")

    # --- REORDERING CONTROL ---
    def _toggle_reorder_mode(self):
        self.is_reorder_mode = not self.is_reorder_mode
        self.selected_item_type = None
        self.selected_course_id = None
        self.selected_tab = None
        self.render_course_grid(selected_filter=self.current_filter)

    def _select_card_for_reorder(self, course_id: str):
        self.selected_item_type = "course"
        self.selected_course_id = course_id
        self.selected_tab = None
        self.tab_bar.set(self.current_filter)
        self.tab_bar.configure(selected_color=THEME["accent_indigo"])
        self._update_card_borders()

    def _update_card_borders(self):
        for cid, widgets in self.card_widgets.items():
            is_selected = (self.selected_item_type == "course" and cid == self.selected_course_id)
            widgets["card"].configure(
                border_color=THEME["reorder_selected"] if is_selected else THEME["reorder_active"])
            widgets["accent"].configure(fg_color=THEME["reorder_selected"] if is_selected else THEME["reorder_active"])

    def _move_selected(self, offset: int):
        if not self.is_reorder_mode: return

        if self.selected_item_type == "tab" and self.selected_tab:
            tab_offset = 1 if offset > 0 else -1
            tabs = self.preferences.get("tab_order", ["In Progress", "Past", "Future", "All"])
            idx = tabs.index(self.selected_tab)
            new_idx = idx + tab_offset

            if 0 <= new_idx < len(tabs):
                tabs[idx], tabs[new_idx] = tabs[new_idx], tabs[idx]
                self.preferences["tab_order"] = tabs
                save_preferences(self.preferences)

                self.tab_bar.configure(values=tabs)
                self.tab_bar.set(self.selected_tab)

        elif self.selected_item_type == "course" and self.selected_course_id:
            courses = self._get_sorted_courses()
            course_ids = [str(c.get("id") or parse_course_title(c.get("fullname", ""))[0]) for c in courses]

            if self.selected_course_id in course_ids:
                idx = course_ids.index(self.selected_course_id)
                new_idx = idx + offset
                if 0 <= new_idx < len(course_ids):
                    course_ids[idx], course_ids[new_idx] = course_ids[new_idx], course_ids[idx]
                    if "course_orders" not in self.preferences: self.preferences["course_orders"] = {}
                    self.preferences["course_orders"][self.current_filter] = course_ids
                    save_preferences(self.preferences)
                    for new_pos, cid in enumerate(course_ids):
                        if cid in self.card_widgets:
                            card_frame = self.card_widgets[cid]["card"]
                            card_frame.grid(row=new_pos // 3, column=new_pos % 3, padx=10, pady=10, sticky="nsew")

    # --- SCREEN 2: DYNAMIC MOODLE SECTIONS & DETAILS ---
    def render_course_details(self, course: dict):
        for widget in self.scroll_container.winfo_children(): widget.destroy()

        code, title = parse_course_title(course.get("fullname", "Course Details"))

        breadcrumb_frame = ctk.CTkFrame(self.scroll_container, fg_color="transparent")
        breadcrumb_frame.pack(fill="x", pady=(0, 10))

        dash_btn = ctk.CTkLabel(breadcrumb_frame, text="Dashboard", font=ctk.CTkFont(size=13, weight="bold"),
                                text_color=THEME["accent_indigo"], cursor="hand2")
        dash_btn.pack(side="left")
        dash_btn.bind("<Button-1>", lambda e: self.render_course_grid(selected_filter=self.current_filter))

        ctk.CTkLabel(breadcrumb_frame, text=f"  /  {code}", font=ctk.CTkFont(size=13),
                     text_color=THEME["text_secondary"]).pack(side="left")

        hero_card = ctk.CTkFrame(self.scroll_container, fg_color="transparent",border_width=0)
        hero_card.pack(fill="x", pady=(0, 20))

        hero_content = ctk.CTkFrame(hero_card, fg_color="transparent")
        hero_content.pack(fill="x", padx=0, pady=0)

        ctk.CTkLabel(hero_content, text=title, font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=THEME["text_primary"], anchor="w").pack(fill="x")
        ctk.CTkLabel(hero_content, text=f"Course Code: {code}  •  Multimedia University", font=ctk.CTkFont(size=12),
                     text_color=THEME["text_secondary"], anchor="w").pack(fill="x", pady=(4, 0))

        sections = course.get("sections", [])

        if not sections:
            # Fallback for flat files if sections fail
            files = course.get("files", [])
            sec_card = CollapsibleFrame(self.scroll_container, title="📁 Course Resources & Files")
            sec_card.pack(fill="x", pady=8)
            if files:
                for f in files: self._build_item_row(sec_card.content_frame, f)
            else:
                ctk.CTkLabel(sec_card.content_frame, text="No items posted yet.",
                             text_color=THEME["text_secondary"]).pack(anchor="w", padx=10, pady=5)
            return

        # Render each Moodle section dynamically
        for sec in sections:
            sec_name = sec.get("name") or "General"
            sec_uservisible = sec.get("uservisible", True)
            sec_avail_info = sec.get("availabilityinfo", "")
            modules = sec.get("modules", [])

            # Skip empty hidden sections
            if not sec_uservisible and not modules and not sec_avail_info:
                continue

            sec_card = CollapsibleFrame(
                self.scroll_container,
                title=sec_name,
                is_locked=not sec_uservisible,
                availability_info=sec_avail_info
            )
            sec_card.pack(fill="x", pady=8)

            if not sec_uservisible and not modules:
                continue

            if not modules:
                ctk.CTkLabel(sec_card.content_frame, text="No activities or resources in this section.",
                             text_color=THEME["text_secondary"]).pack(anchor="w", padx=10, pady=5)
            else:
                for mod in modules:
                    mod_uservisible = mod.get("uservisible", True)
                    mod_availability = mod.get("availabilityinfo", "")

                    for item in mod.get("contents", []):
                        item_dict = dict(item)
                        item_dict["uservisible"] = mod_uservisible
                        item_dict["availabilityinfo"] = mod_availability
                        self._build_item_row(sec_card.content_frame, item_dict)

    def _build_item_row(self, parent_container, item: dict):
        url = item.get("fileurl") or ""
        raw_name = item.get("title") or "Resource File"
        is_accessible = item.get("uservisible", True)
        avail_info = item.get("availabilityinfo", "")

        icon, badge_text, text_color, bg_color = detect_resource_style(item)

        tile_bg = "#181824" if is_accessible else "#1A151A"
        tile_border = THEME["border"] if is_accessible else "#382025"

        tile = ctk.CTkFrame(parent_container, fg_color=tile_bg, border_color=tile_border, border_width=1,
                            corner_radius=8, cursor="hand2" if (url and is_accessible) else "arrow")
        tile.pack(fill="x", padx=4, pady=4, ipady=4)

        display_icon = icon if is_accessible else "🔒"
        lbl_text = f"{display_icon}   {raw_name}"
        lbl_color = THEME["text_primary"] if is_accessible else THEME["text_muted"]

        lbl = ctk.CTkLabel(tile, text=lbl_text, font=ctk.CTkFont(size=13, weight="bold"),
                           text_color=lbl_color, anchor="w")
        lbl.pack(side="left", padx=15, pady=6, fill="x", expand=True)

        pill = ctk.CTkFrame(tile, fg_color=bg_color if is_accessible else "#331C20", corner_radius=4)
        pill.pack(side="right", padx=12, pady=6)

        pill_text = badge_text if is_accessible else "LOCKED"
        pill_color = text_color if is_accessible else THEME["lock_red"]

        pill_lbl = ctk.CTkLabel(pill, text=pill_text, font=ctk.CTkFont(size=10, weight="bold"), text_color=pill_color)
        pill_lbl.pack(padx=8, pady=2)

        if not is_accessible and avail_info:
            notice_lbl = ctk.CTkLabel(tile, text=f"  ⚠️ {avail_info}", font=ctk.CTkFont(size=10),
                                      text_color=THEME["lock_red"], anchor="w")
            notice_lbl.pack(side="bottom", fill="x", padx=15, pady=(0, 4))

        if url and is_accessible:
            action = lambda e, u=url: open_ebwise_url_authenticated(u)
            for element in (tile, lbl, pill, pill_lbl): element.bind("<Button-1>", action)
            tile.bind("<Enter>", lambda e: tile.configure(fg_color="#222232", border_color=THEME["border_hover"]))
            tile.bind("<Leave>", lambda e: tile.configure(fg_color="#181824", border_color=THEME["border"]))