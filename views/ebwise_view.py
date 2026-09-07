import webbrowser
import customtkinter as ctk


class EbwiseView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        # Title Header
        self.header_label = ctk.CTkLabel(
            self,
            text="eBwise Dashboard",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        self.header_label.pack(anchor="w", padx=20, pady=(20, 10))

        # Main Scrollable Container
        self.scroll_container = ctk.CTkScrollableFrame(self)
        self.scroll_container.pack(fill="both", expand=True, padx=20, pady=10)

        # Default Placeholder
        self.status_card = ctk.CTkFrame(self.scroll_container, fg_color="#2B2B2B")
        self.status_card.pack(fill="x", pady=10, padx=5)

        self.placeholder_label = ctk.CTkLabel(
            self.status_card,
            text="⏳ Loading live eBwise data...",
            font=ctk.CTkFont(size=14)
        )
        self.placeholder_label.pack(pady=15)

    def update_data(self, data: dict):
        """Populates UI dynamically with courses, files, and deadlines."""
        # Clear placeholder or old widgets
        for widget in self.scroll_container.winfo_children():
            widget.destroy()

        status = data.get("status")

        if status != "SUCCESS":
            error_label = ctk.CTkLabel(
                self.scroll_container,
                text=f"⚠️ Failed to load data (Status: {status})",
                text_color="#F44336",
                font=ctk.CTkFont(size=14, weight="bold")
            )
            error_label.pack(pady=20)
            return

        courses = data.get("courses", [])
        upcoming = data.get("upcoming", [])

        # --- Enrolled Courses Section ---
        courses_header = ctk.CTkLabel(
            self.scroll_container,
            text=f"📚 Enrolled Courses ({len(courses)})",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        courses_header.pack(anchor="w", pady=(10, 5))

        if not courses:
            no_courses_lbl = ctk.CTkLabel(self.scroll_container, text="No active courses found.")
            no_courses_lbl.pack(anchor="w", padx=10)

        for course in courses:
            # Main Course Container Card
            course_card = ctk.CTkFrame(self.scroll_container, fg_color="#2B2B2B")
            course_card.pack(fill="x", pady=8, padx=5)

            # Course Title
            lbl = ctk.CTkLabel(
                course_card,
                text=course.get("fullname", "Unknown Course"),
                font=ctk.CTkFont(size=14, weight="bold")
            )
            lbl.pack(anchor="w", padx=15, pady=(12, 6))

            files = course.get("files", [])
            print(f"🔍 DEBUG [{course.get('fullname')}]: Found {len(files)} files ->", files)

            # Render Materials Container
            if files:
                files_container = ctk.CTkFrame(course_card, fg_color="#1E1E1E")
                files_container.pack(fill="x", padx=15, pady=(0, 12))

                files_title = ctk.CTkLabel(
                    files_container,
                    text="📁 Course Materials & Resources:",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#AAAAAA"
                )
                files_title.pack(anchor="w", padx=10, pady=(8, 4))

                for file_item in files:
                    file_row = ctk.CTkFrame(files_container, fg_color="transparent")
                    file_row.pack(fill="x", padx=10, pady=2)

                    # Extract display name with robust fallbacks
                    raw_name = file_item.get("title") or file_item.get("filename") or file_item.get("name")
                    file_name = str(raw_name).strip() if raw_name else "Course Attachment"

                    # Extract link
                    file_url = file_item.get("fileurl") or file_item.get("url") or ""

                    # Resource Name Label
                    file_lbl = ctk.CTkLabel(
                        file_row,
                        text=f"📄 {file_name}",
                        font=ctk.CTkFont(size=12),
                        anchor="w"
                    )
                    file_lbl.pack(side="left", padx=5)

                    # Action Button
                    if file_url:
                        open_btn = ctk.CTkButton(
                            file_row,
                            text="Open",
                            width=60,
                            height=22,
                            font=ctk.CTkFont(size=11),
                            fg_color="#3B82F6",
                            hover_color="#2563EB",
                            command=lambda url=file_url: webbrowser.open(url)
                        )
                        open_btn.pack(side="right", padx=5)
            else:
                no_files_lbl = ctk.CTkLabel(
                    course_card,
                    text="No files or modules loaded for this course.",
                    font=ctk.CTkFont(size=11),
                    text_color="#888888"
                )
                no_files_lbl.pack(anchor="w", padx=15, pady=(0, 12))

        # --- Upcoming Deadlines Section ---
        deadlines_header = ctk.CTkLabel(
            self.scroll_container,
            text=f"⏰ Upcoming Deadlines ({len(upcoming)})",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        deadlines_header.pack(anchor="w", pady=(20, 5))

        if not upcoming:
            no_deadlines_lbl = ctk.CTkLabel(self.scroll_container, text="No upcoming tasks or deadlines.")
            no_deadlines_lbl.pack(anchor="w", padx=10)

        for item in upcoming:
            card = ctk.CTkFrame(self.scroll_container, fg_color="#332A2A")
            card.pack(fill="x", pady=5, padx=5)

            task_lbl = ctk.CTkLabel(
                card,
                text=f"{item.get('name')} - {item.get('course')}",
                font=ctk.CTkFont(size=13, weight="bold")
            )
            task_lbl.pack(anchor="w", padx=15, pady=(8, 2))

            time_lbl = ctk.CTkLabel(
                card,
                text=f"Due: {item.get('deadline')}",
                text_color="#FFA500",
                font=ctk.CTkFont(size=11)
            )
            time_lbl.pack(anchor="w", padx=15, pady=(0, 8))