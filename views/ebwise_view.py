import re
import customtkinter as ctk
from ebwise_backend import open_ebwise_url_authenticated

# ==========================================
# DESIGN SYSTEM & COLOR PALETTE
# ==========================================
THEME = {
    "bg_dark": "#121216",  # Base page background
    "card_bg": "#1E1E2A",  # Elevated container surface
    "header_bg": "#181822",  # Secondary dark surface for accordions
    "border": "#323246",  # Subtle frame border
    "border_hover": "#4B4B66",  # Highlighted border on hover
    "text_primary": "#F1F5F9",  # Soft off-white
    "text_secondary": "#94A3B8",  # Muted gray-blue
    "accent_indigo": "#6366F1",  # Primary brand color
    "accent_hover": "#4F46E5",  # Accent hover state
}

# Resource pill styling: (Icon, Label, Text Color, Tinted BG Color)
RESOURCE_STYLES = {
    "pdf": ("📄", "PDF", "#F87171", "#2D1D24"),
    "ppt": ("📊", "PPT", "#FBBF24", "#2D261B"),
    "excel": ("📈", "EXCEL", "#34D399", "#182C23"),
    "zip": ("📦", "ARCHIVE", "#C084FC", "#261E33"),
    "github": ("🐙", "GITHUB", "#E2E8F0", "#22272E"),
    "chat": ("💬", "CHAT", "#4ADE80", "#182A20"),
    "url": ("🔗", "LINK", "#60A5FA", "#1C2638"),
    "default": ("📌", "ITEM", "#94A3B8", "#222530")
}


def parse_course_title(fullname: str):
    """Splits 'CSP1123-MINI IT PROJECT' into ('CSP1123', 'Mini IT Project')."""
    match = re.match(r"^([A-Z]{3,4}\d{4})\s*[-:]?\s*(.*)$", fullname, re.IGNORECASE)
    if match:
        code, title = match.groups()
        clean_title = title.strip().title()
        return code.upper(), clean_title if clean_title else fullname.title()
    return "COURSE", fullname.title()


def detect_resource_style(item: dict):
    """Parses item title/URL to pick contextual icons and badge colors."""
    title = (item.get("title") or "").lower()
    url = (item.get("fileurl") or "").lower()

    if "github.com" in url or "git" in title:
        return RESOURCE_STYLES["github"]
    if any(k in url or k in title for k in ["whatsapp", "telegram", "chat", "discord"]):
        return RESOURCE_STYLES["chat"]
    if ".pdf" in url or "pdf" in title:
        return RESOURCE_STYLES["pdf"]
    if any(k in url or k in title for k in [".ppt", ".pptx", "presentation", "slides"]):
        return RESOURCE_STYLES["ppt"]
    if any(k in url or k in title for k in [".xls", ".xlsx", "excel", "spreadsheet"]):
        return RESOURCE_STYLES["excel"]
    if any(k in url or k in title for k in [".zip", ".rar", ".7z", "folder", "archive"]):
        return RESOURCE_STYLES["zip"]
    if url.startswith("http"):
        return RESOURCE_STYLES["url"]

    return RESOURCE_STYLES["default"]


# ==========================================
# CUSTOM COMPONENTS
# ==========================================
class CollapsibleFrame(ctk.CTkFrame):
    """Custom accordion component with chevron toggle and elevated surface styling."""

    def __init__(self, master, title="Section", **kwargs):
        super().__init__(
            master,
            fg_color=THEME["card_bg"],
            border_color=THEME["border"],
            border_width=1,
            corner_radius=10,
            **kwargs
        )
        self.is_expanded = True

        # Accordion Header
        self.header_frame = ctk.CTkFrame(
            self,
            fg_color=THEME["header_bg"],
            corner_radius=10,
            cursor="hand2"
        )
        self.header_frame.pack(fill="x", expand=True)

        self.title_lbl = ctk.CTkLabel(
            self.header_frame,
            text=title,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=THEME["text_primary"]
        )
        self.title_lbl.pack(side="left", padx=15, pady=12)

        self.toggle_lbl = ctk.CTkLabel(
            self.header_frame,
            text="▲",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=THEME["text_secondary"]
        )
        self.toggle_lbl.pack(side="right", padx=15, pady=12)

        # Event Bindings for Toggle
        for widget in (self.header_frame, self.title_lbl, self.toggle_lbl):
            widget.bind("<Button-1>", lambda e: self.toggle())

        # Content Container
        self.content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.content_frame.pack(fill="x", expand=True, padx=10, pady=10)

    def toggle(self):
        if self.is_expanded:
            self.content_frame.pack_forget()
            self.toggle_lbl.configure(text="▼")
            self.is_expanded = False
        else:
            self.content_frame.pack(fill="x", expand=True, padx=10, pady=10)
            self.toggle_lbl.configure(text="▲")
            self.is_expanded = True


# ==========================================
# MAIN VIEW CONTROLLER
# ==========================================
class EbwiseView(ctk.CTkFrame):
    def __init__(self, master, fetch_callback=None, **kwargs):
        super().__init__(master, fg_color=THEME["bg_dark"], **kwargs)
        self.fetch_callback = fetch_callback
        self.cached_data = {}

        self.scroll_container = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=THEME["border"],
            scrollbar_button_hover_color=THEME["border_hover"]
        )
        self.scroll_container.pack(fill="both", expand=True, padx=20, pady=20)

        self.show_loading()

    def show_loading(self):
        for widget in self.scroll_container.winfo_children():
            widget.destroy()
        lbl = ctk.CTkLabel(
            self.scroll_container,
            text="⏳ Loading live eBwise dashboard...",
            font=ctk.CTkFont(size=14),
            text_color=THEME["text_secondary"]
        )
        lbl.pack(pady=60)

    def update_data(self, data: dict, selected_filter: str = "In Progress"):
        self.cached_data = data
        if data.get("status") != "SUCCESS":
            for widget in self.scroll_container.winfo_children():
                widget.destroy()
            ctk.CTkLabel(
                self.scroll_container,
                text=f"⚠️ Failed to load data (Status: {data.get('status')})",
                text_color="#F87171",
                font=ctk.CTkFont(size=14, weight="bold")
            ).pack(pady=40)
            return

        self.render_course_grid(selected_filter=selected_filter)

    # --- SCREEN 1: DASHBOARD CARD GRID & TAB BAR ---
    def render_course_grid(self, selected_filter: str = "In Progress"):
        for widget in self.scroll_container.winfo_children():
            widget.destroy()

        top_bar = ctk.CTkFrame(self.scroll_container, fg_color="transparent")
        top_bar.pack(fill="x", pady=(0, 20))

        # Title Label
        ctk.CTkLabel(
            top_bar,
            text="My Courses",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=THEME["text_primary"]
        ).pack(side="left")

        # Segmented Tab Bar
        filter_options = ["In Progress", "Future", "Past", "All"]
        self.tab_bar = ctk.CTkSegmentedButton(
            top_bar,
            values=filter_options,
            command=self._on_filter_change,
            selected_color=THEME["accent_indigo"],
            selected_hover_color=THEME["accent_hover"],
            unselected_color=THEME["card_bg"],
            unselected_hover_color=THEME["header_bg"],
            text_color=THEME["text_primary"]
        )
        self.tab_bar.set(selected_filter)
        self.tab_bar.pack(side="right")

        courses = self.cached_data.get("courses", [])
        if not courses:
            ctk.CTkLabel(
                self.scroll_container,
                text="No courses found for this filter classification.",
                text_color=THEME["text_secondary"],
                font=ctk.CTkFont(size=14)
            ).pack(anchor="w", pady=30)
            return

        # 3-Column Grid setup
        grid_frame = ctk.CTkFrame(self.scroll_container, fg_color="transparent")
        grid_frame.pack(fill="both", expand=True)
        grid_frame.columnconfigure((0, 1, 2), weight=1, uniform="course_cols")

        for idx, course in enumerate(courses):
            row = idx // 3
            col = idx % 3
            self._build_course_card(grid_frame, course, row, col)

    def _build_course_card(self, parent, course: dict, row: int, col: int):
        code, title = parse_course_title(course.get("fullname", "Unknown Course"))

        card = ctk.CTkFrame(
            parent,
            fg_color=THEME["card_bg"],
            border_color=THEME["border"],
            border_width=1,
            corner_radius=12,
            height=200,
            cursor="hand2"
        )
        card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
        card.grid_propagate(False)

        # Top Accent Line
        accent_line = ctk.CTkFrame(card, fg_color=THEME["accent_indigo"], height=4, corner_radius=2)
        accent_line.pack(fill="x", side="top")

        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=15, pady=12)

        # Top Code Pill
        code_badge = ctk.CTkFrame(content, fg_color="#272738", corner_radius=6)
        code_badge.pack(anchor="w", pady=(0, 8))
        ctk.CTkLabel(
            code_badge,
            text=code,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=THEME["accent_indigo"]
        ).pack(padx=8, pady=2)

        # Course Title
        title_lbl = ctk.CTkLabel(
            content,
            text=title,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=THEME["text_primary"],
            wraplength=210,
            justify="left",
            anchor="w"
        )
        title_lbl.pack(fill="x", expand=True, anchor="w")

        # Bottom Lecturer Info
        lecturer = course.get("instructor", "Faculty Academic Team")
        ctk.CTkLabel(
            content,
            text=f"👤 {lecturer}",
            font=ctk.CTkFont(size=11),
            text_color=THEME["text_secondary"],
            anchor="w"
        ).pack(fill="x", side="bottom")

        # Click & Hover bindings
        open_details = lambda e, c=course: self.render_course_details(c)
        for w in (card, content, title_lbl, code_badge):
            w.bind("<Button-1>", open_details)

        card.bind("<Enter>", lambda e: card.configure(border_color=THEME["border_hover"]))
        card.bind("<Leave>", lambda e: card.configure(border_color=THEME["border"]))

    def _on_filter_change(self, selected_value: str):
        mapping = {"In Progress": "inprogress", "Future": "future", "Past": "past", "All": "all"}
        target_class = mapping.get(selected_value, "inprogress")

        if self.fetch_callback:
            self.show_loading()
            self.fetch_callback(classification=target_class, selected_filter=selected_value)

    # --- SCREEN 2: BREADCRUMBS, HERO & EXPANDABLE DETAILS ---
    def render_course_details(self, course: dict):
        for widget in self.scroll_container.winfo_children():
            widget.destroy()

        code, title = parse_course_title(course.get("fullname", "Course Details"))

        # Breadcrumb Bar
        breadcrumb_frame = ctk.CTkFrame(self.scroll_container, fg_color="transparent")
        breadcrumb_frame.pack(fill="x", pady=(0, 10))

        dash_btn = ctk.CTkLabel(
            breadcrumb_frame,
            text="Dashboard",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=THEME["accent_indigo"],
            cursor="hand2"
        )
        dash_btn.pack(side="left")
        dash_btn.bind("<Button-1>", lambda e: self.render_course_grid())

        ctk.CTkLabel(
            breadcrumb_frame,
            text=f"  /  {code}",
            font=ctk.CTkFont(size=13),
            text_color=THEME["text_secondary"]
        ).pack(side="left")

        # Hero Banner Container
        hero_card = ctk.CTkFrame(
            self.scroll_container,
            fg_color=THEME["card_bg"],
            border_color=THEME["border"],
            border_width=1,
            corner_radius=12
        )
        hero_card.pack(fill="x", pady=(0, 20), ipady=10)

        hero_content = ctk.CTkFrame(hero_card, fg_color="transparent")
        hero_content.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(
            hero_content,
            text=title,
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=THEME["text_primary"],
            anchor="w"
        ).pack(fill="x")

        ctk.CTkLabel(
            hero_content,
            text=f"Course Code: {code}  •  Multimedia University",
            font=ctk.CTkFont(size=12),
            text_color=THEME["text_secondary"],
            anchor="w"
        ).pack(fill="x", pady=(4, 0))

        # Categorize items
        announcements, materials = [], []
        for item in course.get("files", []):
            if item.get("type") in ["forum", "news"]:
                announcements.append(item)
            else:
                materials.append(item)

        # 1. Announcements Accordion
        ann_card = CollapsibleFrame(self.scroll_container, title="📢 Announcements & News")
        ann_card.pack(fill="x", pady=8)
        if announcements:
            for ann in announcements:
                self._build_item_row(ann_card.content_frame, ann)
        else:
            ctk.CTkLabel(
                ann_card.content_frame,
                text="No announcements posted yet.",
                text_color=THEME["text_secondary"]
            ).pack(anchor="w", padx=10, pady=5)

        # 2. Materials Accordion
        mat_card = CollapsibleFrame(self.scroll_container, title="📁 Course Resources & Files")
        mat_card.pack(fill="x", pady=8)
        if materials:
            for mat in materials:
                self._build_item_row(mat_card.content_frame, mat)
        else:
            ctk.CTkLabel(
                mat_card.content_frame,
                text="No materials uploaded for this section.",
                text_color=THEME["text_secondary"]
            ).pack(anchor="w", padx=10, pady=5)

    def _build_item_row(self, parent_container, item: dict):
        url = item.get("fileurl") or ""
        raw_name = item.get("title") or "Resource File"
        icon, badge_text, text_color, bg_color = detect_resource_style(item)

        tile = ctk.CTkFrame(
            parent_container,
            fg_color="#181824",
            border_color=THEME["border"],
            border_width=1,
            corner_radius=8,
            cursor="hand2" if url else "arrow"
        )
        tile.pack(fill="x", padx=4, pady=4, ipady=4)

        # Left Icon + Name
        lbl = ctk.CTkLabel(
            tile,
            text=f"{icon}   {raw_name}",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=THEME["text_primary"],
            anchor="w"
        )
        lbl.pack(side="left", padx=15, pady=6, fill="x", expand=True)

        # Right-side Badges (Pills)
        pill = ctk.CTkFrame(tile, fg_color=bg_color, corner_radius=4)
        pill.pack(side="right", padx=12, pady=6)

        pill_lbl = ctk.CTkLabel(
            pill,
            text=badge_text,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=text_color
        )
        pill_lbl.pack(padx=8, pady=2)

        # Interactivity
        if url:
            action = lambda e, u=url: open_ebwise_url_authenticated(u)
            for element in (tile, lbl, pill, pill_lbl):
                element.bind("<Button-1>", action)

            tile.bind("<Enter>", lambda e: tile.configure(fg_color="#222232", border_color=THEME["border_hover"]))
            tile.bind("<Leave>", lambda e: tile.configure(fg_color="#181824", border_color=THEME["border"]))