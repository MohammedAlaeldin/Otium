import webbrowser
import customtkinter as ctk


class CollapsibleFrame(ctk.CTkFrame):
    """Custom expandable card component with a toggle icon."""

    def __init__(self, master, title="Section", **kwargs):
        super().__init__(master, fg_color="#2B2B2B", **kwargs)
        self.is_expanded = True

        # Header bar (clickable to toggle)
        self.header_frame = ctk.CTkFrame(self, fg_color="#1E1E1E", cursor="hand2")
        self.header_frame.pack(fill="x", expand=True)
        self.header_frame.bind("<Button-1>", lambda e: self.toggle())

        self.title_lbl = ctk.CTkLabel(
            self.header_frame,
            text=title,
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.title_lbl.pack(side="left", padx=15, pady=10)
        self.title_lbl.bind("<Button-1>", lambda e: self.toggle())

        self.toggle_lbl = ctk.CTkLabel(
            self.header_frame,
            text="▲",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.toggle_lbl.pack(side="right", padx=15, pady=10)
        self.toggle_lbl.bind("<Button-1>", lambda e: self.toggle())

        # Container for internal elements
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


class EbwiseView(ctk.CTkFrame):
    def __init__(self, master, fetch_callback=None, **kwargs):
        super().__init__(master, **kwargs)
        self.fetch_callback = fetch_callback  # Function to request new backend data
        self.cached_data = {}

        # Main Scrollable Container
        self.scroll_container = ctk.CTkScrollableFrame(self)
        self.scroll_container.pack(fill="both", expand=True, padx=20, pady=20)

        # Default loading state
        self.show_loading()

    def show_loading(self):
        for widget in self.scroll_container.winfo_children():
            widget.destroy()
        lbl = ctk.CTkLabel(self.scroll_container, text="⏳ Loading live eBwise data...", font=ctk.CTkFont(size=14))
        lbl.pack(pady=40)

    def update_data(self, data: dict, selected_filter: str = "In Progress"):
        """Entry point called when backend returns updated course payload."""
        self.cached_data = data
        status = data.get("status")

        if status != "SUCCESS":
            for widget in self.scroll_container.winfo_children():
                widget.destroy()
            error_label = ctk.CTkLabel(
                self.scroll_container,
                text=f"⚠️ Failed to load data (Status: {status})",
                text_color="#F44336",
                font=ctk.CTkFont(size=14, weight="bold")
            )
            error_label.pack(pady=20)
            return

        # Pass selected_filter down to render_course_grid
        self.render_course_grid(selected_filter=selected_filter)

    # --- SCREEN 1: COURSE GRID & TIMELINE FILTER ---
    def render_course_grid(self, selected_filter: str = "In Progress"):
        for widget in self.scroll_container.winfo_children():
            widget.destroy()

        top_bar = ctk.CTkFrame(self.scroll_container, fg_color="transparent")
        top_bar.pack(fill="x", pady=(0, 20))

        filter_options = ["In Progress", "Future", "Past", "All"]
        self.filter_dropdown = ctk.CTkOptionMenu(
            top_bar,
            values=filter_options,
            command=self._on_filter_change,
            width=160
        )
        self.filter_dropdown.set(selected_filter)
        self.filter_dropdown.pack(side="left")

        courses = self.cached_data.get("courses", [])

        if not courses:
            no_courses_lbl = ctk.CTkLabel(
                self.scroll_container,
                text="No courses found for this filter classification."
            )
            no_courses_lbl.pack(anchor="w", pady=20)
            return

        grid_frame = ctk.CTkFrame(self.scroll_container, fg_color="transparent")
        grid_frame.pack(fill="both", expand=True)

        grid_frame.columnconfigure((0, 1, 2), weight=1, uniform="course_cols")

        for idx, course in enumerate(courses):
            row = idx // 3
            col = idx % 3

            card = ctk.CTkFrame(grid_frame, fg_color="#2B2B2B", height=180, cursor="hand2")
            card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
            card.grid_propagate(False)

            card.bind("<Button-1>", lambda e, c=course: self.render_course_details(c))

            title_lbl = ctk.CTkLabel(
                card,
                text=course.get("fullname", "Unknown Course"),
                font=ctk.CTkFont(size=15, weight="bold"),
                wraplength=180,
                justify="center"
            )
            title_lbl.pack(expand=True, padx=15, pady=15)
            title_lbl.bind("<Button-1>", lambda e, c=course: self.render_course_details(c))

    def _on_filter_change(self, selected_value: str):
        mapping = {
            "In Progress": "inprogress",
            "Future": "future",
            "Past": "past",
            "All": "all"
        }
        target_class = mapping.get(selected_value, "inprogress")

        if self.fetch_callback:
            self.show_loading()
            # Pass both target classification and the display filter string
            self.fetch_callback(classification=target_class, selected_filter=selected_value)
    # --- SCREEN 2: EXPANDABLE COURSE DETAILS ---
    def render_course_details(self, course: dict):
        for widget in self.scroll_container.winfo_children():
            widget.destroy()

        # Navigation / Header
        nav_bar = ctk.CTkFrame(self.scroll_container, fg_color="transparent")
        nav_bar.pack(fill="x", pady=(0, 15))

        back_btn = ctk.CTkButton(
            nav_bar,
            text="← Back to Courses",
            width=120,
            fg_color="#3B82F6",
            hover_color="#2563EB",
            command=self.render_course_grid
        )
        back_btn.pack(side="left")

        course_title = ctk.CTkLabel(
            self.scroll_container,
            text=course.get("fullname", "Course Details"),
            font=ctk.CTkFont(size=20, weight="bold")
        )
        course_title.pack(anchor="center", pady=(0, 20))

        # Separate items into announcements vs standard resources
        announcements = []
        materials = []

        for item in course.get("files", []):
            if item.get("type") in ["forum", "news"]:
                announcements.append(item)
            else:
                materials.append(item)

        # 1. Announcements Collapsible Card
        ann_card = CollapsibleFrame(self.scroll_container, title="📢 Announcements")
        ann_card.pack(fill="x", pady=10)

        if announcements:
            for ann in announcements:
                self._build_item_row(ann_card.content_frame, ann)
        else:
            empty_lbl = ctk.CTkLabel(ann_card.content_frame, text="No announcements posted.", text_color="#888888")
            empty_lbl.pack(anchor="w", padx=10, pady=5)

        # 2. Course Materials Collapsible Card
        mat_card = CollapsibleFrame(self.scroll_container, title="📁 Course Materials")
        mat_card.pack(fill="x", pady=10)

        if materials:
            for mat in materials:
                self._build_item_row(mat_card.content_frame, mat)
        else:
            empty_lbl = ctk.CTkLabel(mat_card.content_frame, text="No materials found.", text_color="#888888")
            empty_lbl.pack(anchor="w", padx=10, pady=5)

    def _build_item_row(self, parent_container, item: dict):
        row = ctk.CTkFrame(parent_container, fg_color="transparent")
        row.pack(fill="x", padx=5, pady=4)

        raw_name = item.get("title") or "Item Resource"
        url = item.get("fileurl") or ""

        lbl = ctk.CTkLabel(row, text=f"• {raw_name}", font=ctk.CTkFont(size=12), anchor="w")
        lbl.pack(side="left", padx=5)

        if url:
            btn = ctk.CTkButton(
                row,
                text="Open",
                width=60,
                height=22,
                font=ctk.CTkFont(size=11),
                fg_color="#3B82F6",
                hover_color="#2563EB",
                command=lambda u=url: webbrowser.open(u)
            )
            btn.pack(side="right", padx=5)
