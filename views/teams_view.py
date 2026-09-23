import os
import threading
import customtkinter as ctk
from datetime import datetime, timedelta, timezone
import teams_backend
from storage import SESSION_FILE

# ==========================================
# DESIGN SYSTEM & COLOR PALETTE
# ==========================================
THEME = {
    "bg_dark": "#121216",
    "card_bg": "#1E1E2A",
    "card_hover": "#262638",
    "header_bg": "#181822",
    "border": "#323246",
    "border_hover": "#4B4B66",
    "text_primary": "#F1F5F9",
    "text_secondary": "#94A3B8",
    "accent_indigo": "#6366F1",
    "accent_hover": "#4F46E5",
    # Purple Palette for Navigation Header
    "tab_purple": "#2E1B4E",
    "tab_purple_hover": "#3D246C",
    "selected_purple": "#7C3AED",
    "selected_purple_hover": "#6D28D9",
    # Status Colors for Calls
    "join_green": "#10B981",
    "join_green_hover": "#059669",
    "status_scheduled": "#10B981",  # Green
    "status_current": "#EAB308",    # Yellow
    "status_ended": "#64748B",      # Gray
    "error_bg": "#4A1515",
    "error_text": "#FFA3A3"
}


def _launch_playwright_teams(url: str):
    """Spawns an authenticated browser instance using saved session cookies to bypass desktop prompts."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, args=["--start-maximized"])
            
            context = browser.new_context(
                storage_state=SESSION_FILE,
                no_viewport=True
            )
            page = context.new_page()
            
            target_url = url.strip()
            if "web=1" not in target_url:
                target_url += ("&" if "?" in target_url else "?") + "web=1"
            target_url += "&suppressPrompt=true"
            
            page.goto(target_url)
            page.wait_for_event("close", timeout=0)
    except Exception as e:
        print(f"Playwright Teams launch error: {e}")
        import webbrowser
        webbrowser.open(url)


def open_in_browser(url: str):
    if not url: return
    threading.Thread(target=_launch_playwright_teams, args=(url,), daemon=True).start()


class CollapsibleTeamCard(ctk.CTkFrame):
    """Collapsible container card for individual Team channels."""
    def __init__(self, master, team_name, channels, on_channel_click, **kwargs):
        super().__init__(
            master, fg_color=THEME["card_bg"], border_color=THEME["border"], 
            border_width=1, corner_radius=10, **kwargs
        )
        self.is_expanded = True

        # Header Frame
        self.header = ctk.CTkFrame(self, fg_color=THEME["header_bg"], corner_radius=10, cursor="hand2")
        self.header.pack(fill="x")

        self.title_lbl = ctk.CTkLabel(
            self.header, text=f"👥 {team_name}", 
            font=ctk.CTkFont(weight="bold", size=13), text_color=THEME["text_primary"]
        )
        self.title_lbl.pack(side="left", padx=12, pady=10)

        self.toggle_lbl = ctk.CTkLabel(
            self.header, text="▲", font=ctk.CTkFont(size=11, weight="bold"),
            text_color=THEME["text_secondary"]
        )
        self.toggle_lbl.pack(side="right", padx=12, pady=10)

        # Bind toggle event to entire header bar
        for widget in (self.header, self.title_lbl, self.toggle_lbl):
            widget.bind("<Button-1>", lambda e: self.toggle())

        # Channels Container
        self.chans_container = ctk.CTkFrame(self, fg_color="transparent")
        self.chans_container.pack(fill="x", padx=8, pady=8)

        for channel in channels:
            btn = ctk.CTkButton(
                self.chans_container, 
                text=f"#  {channel.get('displayName', 'General')}",
                fg_color="transparent", 
                text_color=THEME["text_secondary"], 
                hover_color=THEME["border_hover"],
                anchor="w", 
                height=32,
                font=ctk.CTkFont(size=12),
                command=lambda c=channel: on_channel_click(c)
            )
            btn.pack(fill="x", pady=2)

    def toggle(self):
        if self.is_expanded:
            self.chans_container.pack_forget()
            self.toggle_lbl.configure(text="▼")
            self.is_expanded = False
        else:
            self.chans_container.pack(fill="x", padx=8, pady=8)
            self.toggle_lbl.configure(text="▲")
            self.is_expanded = True


class TeamsView(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color=THEME["bg_dark"])

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Selected navigation tab
        self.current_tab = "Chats"

        # --- 1. TOP HEADER BAR WITH PURPLE NAVIGATION CARD ---
        self.top_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.top_bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(15, 10))

        # Title / Branding
        self.header_title = ctk.CTkLabel(
            self.top_bar, 
            text="Microsoft Teams", 
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=THEME["text_primary"]
        )
        self.header_title.pack(side="left", padx=(0, 20))

        # Purple Navigation Tab Selector
        self.tab_selector = ctk.CTkSegmentedButton(
            self.top_bar,
            values=["Channels", "Chats", "Calls"],
            height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            selected_color=THEME["selected_purple"],
            selected_hover_color=THEME["selected_purple_hover"],
            unselected_color=THEME["tab_purple"],
            unselected_hover_color=THEME["tab_purple_hover"],
            text_color=THEME["text_primary"],
            command=self._on_tab_changed
        )
        self.tab_selector.set("Chats")
        self.tab_selector.pack(side="left", expand=True)

        # Refresh Button
        self.refresh_btn = ctk.CTkButton(
            self.top_bar, 
            text="🔄 Refresh", 
            width=95, 
            height=34,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=THEME["card_bg"],
            hover_color=THEME["selected_purple_hover"],
            border_color=THEME["border"],
            border_width=1,
            command=self.load_data
        )
        self.refresh_btn.pack(side="right")

        # --- 2. CONTENT CONTAINER (SWITCHES BETWEEN TABS) ---
        self.content_container = ctk.CTkFrame(self, fg_color="transparent")
        self.content_container.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        self.content_container.grid_columnconfigure(0, weight=1)
        self.content_container.grid_rowconfigure(0, weight=1)

        # Create the 3 distinct views
        self.view_channels = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.view_chats = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.view_calls = ctk.CTkFrame(self.content_container, fg_color="transparent")

        self._setup_channels_layout()
        self._setup_chats_layout()
        self._setup_calls_layout()

        # Show default tab
        self._show_active_tab("Chats")
        self.load_data()

    def _on_tab_changed(self, value: str):
        self.current_tab = value
        self._show_active_tab(value)

    def _show_active_tab(self, tab_name: str):
        for view in (self.view_channels, self.view_chats, self.view_calls):
            view.grid_forget()

        if tab_name == "Channels":
            self.view_channels.grid(row=0, column=0, sticky="nsew")
        elif tab_name == "Chats":
            self.view_chats.grid(row=0, column=0, sticky="nsew")
        elif tab_name == "Calls":
            self.view_calls.grid(row=0, column=0, sticky="nsew")

    # --- TAB LAYOUT SETUP ---
    def _setup_channels_layout(self):
        self.view_channels.grid_columnconfigure(0, weight=1)
        self.view_channels.grid_columnconfigure(1, weight=3)
        self.view_channels.grid_rowconfigure(0, weight=1)

        self.teams_list_frame = ctk.CTkScrollableFrame(
            self.view_channels, fg_color="transparent",
            scrollbar_button_color=THEME["border"], scrollbar_button_hover_color=THEME["border_hover"]
        )
        self.teams_list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=0)

        self.channel_content_frame = ctk.CTkScrollableFrame(
            self.view_channels, fg_color="transparent",
            scrollbar_button_color=THEME["border"], scrollbar_button_hover_color=THEME["border_hover"]
        )
        self.channel_content_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=0)

    def _setup_chats_layout(self):
        self.view_chats.grid_columnconfigure(0, weight=1)
        self.view_chats.grid_columnconfigure(1, weight=3)
        self.view_chats.grid_rowconfigure(0, weight=1)

        self.chat_list_frame = ctk.CTkScrollableFrame(
            self.view_chats, fg_color="transparent",
            scrollbar_button_color=THEME["border"], scrollbar_button_hover_color=THEME["border_hover"]
        )
        self.chat_list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=0)

        self.chat_messages_frame = ctk.CTkScrollableFrame(
            self.view_chats, fg_color="transparent",
            scrollbar_button_color=THEME["border"], scrollbar_button_hover_color=THEME["border_hover"]
        )
        self.chat_messages_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=0)

    def _setup_calls_layout(self):
        self.view_calls.grid_columnconfigure(0, weight=1)
        self.view_calls.grid_rowconfigure(0, weight=1)

        self.calls_list_frame = ctk.CTkScrollableFrame(
            self.view_calls, fg_color="transparent",
            scrollbar_button_color=THEME["border"], scrollbar_button_hover_color=THEME["border_hover"]
        )
        self.calls_list_frame.grid(row=0, column=0, sticky="nsew", pady=0)

    # --- DATA FETCHING ---
    def load_data(self):
        for frame in [self.teams_list_frame, self.chat_list_frame, self.calls_list_frame, self.channel_content_frame, self.chat_messages_frame]:
            for child in frame.winfo_children(): child.destroy()

        for frame in [self.teams_list_frame, self.chat_list_frame, self.calls_list_frame]:
            ctk.CTkLabel(
                frame, text="⏳ Syncing Teams data...", font=ctk.CTkFont(size=14),
                text_color=THEME["text_secondary"]
            ).pack(pady=40)

        threading.Thread(target=self._fetch_and_render, daemon=True).start()

    def _fetch_and_render(self):
        try:
            data = teams_backend.fetch_dashboard_data()
        except Exception as e:
            data = {"teams": [], "chats": [], "calls": [], "errors": [str(e)], "debug": {}}
        self.after(0, lambda: self._render_ui(data))

    def _render_error_diagnostics(self, frame, errors, debug_info):
        card = ctk.CTkFrame(frame, fg_color=THEME["error_bg"], border_color="#7F1D1D", border_width=1, corner_radius=10)
        card.pack(fill="x", padx=10, pady=10, ipady=8)
        
        ctk.CTkLabel(card, text="⚠️ Diagnostics / Errors Detected", font=ctk.CTkFont(weight="bold", size=14), text_color="#FCA5A5").pack(pady=5)
        status = f"Graph Token Captured: {debug_info.get('has_graph')}\nSkype Token Captured: {debug_info.get('has_skype')}"
        ctk.CTkLabel(card, text=status, text_color="#FECACA", font=ctk.CTkFont(size=11)).pack(pady=2)

        for err in errors:
            ctk.CTkLabel(card, text=f"• {err}", justify="left", wraplength=350, text_color=THEME["error_text"], font=ctk.CTkFont(size=12)).pack(anchor="w", padx=15, pady=2)

    # --- RENDERING ENGINE ---
    def _render_ui(self, data: dict):
        for frame in [self.teams_list_frame, self.chat_list_frame, self.calls_list_frame, self.channel_content_frame, self.chat_messages_frame]:
            for child in frame.winfo_children(): child.destroy()

        errors = data.get("errors", [])
        debug_info = data.get("debug", {})

        # 1. --- RENDER CHANNELS (COLLAPSIBLE CARDS) ---
        teams = data.get("teams", [])
        if not teams:
            if errors:
                self._render_error_diagnostics(self.teams_list_frame, errors, debug_info)
            else:
                ctk.CTkLabel(self.teams_list_frame, text="No joined teams found.", text_color=THEME["text_secondary"]).pack(pady=30)
        else:
            for team in teams:
                team_card = CollapsibleTeamCard(
                    self.teams_list_frame,
                    team_name=team.get('displayName', 'Team'),
                    channels=team.get('channels', []),
                    on_channel_click=lambda c, t=team: self._show_channel_content(t, c)
                )
                team_card.pack(fill="x", pady=6, padx=4)

        # 2. --- RENDER CHATS ---
        chats = data.get("chats", [])
        if not chats:
            if errors:
                self._render_error_diagnostics(self.chat_list_frame, errors, debug_info)
            else:
                ctk.CTkLabel(self.chat_list_frame, text="No recent chats found.", text_color=THEME["text_secondary"]).pack(pady=30)
        else:
            for chat in chats:
                clean_title = chat['title'].replace('\n', ' ')[:28]
                clean_msg = chat['last_message'].replace('\n', ' ')[:36]

                card = ctk.CTkFrame(self.chat_list_frame, fg_color=THEME["card_bg"], border_color=THEME["border"], border_width=1, corner_radius=10, cursor="hand2")
                card.pack(fill="x", pady=4, padx=4)

                content = ctk.CTkFrame(card, fg_color="transparent")
                content.pack(fill="both", expand=True, padx=12, pady=10)

                title_lbl = ctk.CTkLabel(content, text=f"💬 {clean_title}", font=ctk.CTkFont(size=13, weight="bold"), text_color=THEME["text_primary"], anchor="w")
                title_lbl.pack(fill="x")

                msg_lbl = ctk.CTkLabel(content, text=f"{clean_msg}...", font=ctk.CTkFont(size=11), text_color=THEME["text_secondary"], anchor="w")
                msg_lbl.pack(fill="x", pady=(2, 0))

                open_chat = lambda e, c=chat: self._show_chat_messages(c)
                for w in (card, content, title_lbl, msg_lbl):
                    w.bind("<Button-1>", open_chat)
                    w.bind("<Enter>", lambda e, c=card: c.configure(fg_color=THEME["card_hover"], border_color=THEME["border_hover"]))
                    w.bind("<Leave>", lambda e, c=card: c.configure(fg_color=THEME["card_bg"], border_color=THEME["border"]))

        # 3. --- RENDER CALLS (150-MINUTE RULE: GREEN = SCHEDULED, YELLOW = CURRENT, GRAY = ENDED) ---
        calls = data.get("calls", [])
        now_utc = datetime.now(timezone.utc)
        
        if not calls:
            if errors:
                self._render_error_diagnostics(self.calls_list_frame, errors, debug_info)
            else:
                ctk.CTkLabel(self.calls_list_frame, text="No scheduled meetings or calls found.", text_color=THEME["text_secondary"]).pack(pady=30)
        else:
            for call in calls:
                title = call.get('subject', 'Call / Online Meeting')
                
                # Parse Start Time
                start_dt_utc = datetime.min.replace(tzinfo=timezone.utc)
                ts = call.get('start_time')
                if ts:
                    try:
                        clean_str = str(ts).strip().replace("Z", "+00:00")
                        dt = datetime.fromisoformat(clean_str)
                        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                        start_dt_utc = dt.astimezone(timezone.utc)
                    except Exception:
                        pass
                        
                local_time_str = start_dt_utc.astimezone().strftime("%b %d, %I:%M %p") if start_dt_utc.year > 1 else "Scheduled Meeting"

                # Calculate State according to 150 min rule
                end_window_utc = start_dt_utc + timedelta(minutes=150)
                
                if start_dt_utc.year <= 1:
                    status = "ended"
                    status_text = "Ended"
                    status_color = THEME["status_ended"]
                    badge_bg = "#1F2937"
                elif now_utc < start_dt_utc:
                    status = "scheduled"
                    status_text = "Scheduled"
                    status_color = THEME["status_scheduled"]
                    badge_bg = "#064E3B"
                elif start_dt_utc <= now_utc <= end_window_utc:
                    status = "current"
                    status_text = "Live Now"
                    status_color = THEME["status_current"]
                    badge_bg = "#451A03"
                else:
                    status = "ended"
                    status_text = "Ended"
                    status_color = THEME["status_ended"]
                    badge_bg = "#1F2937"

                # Call Hero Card
                card = ctk.CTkFrame(
                    self.calls_list_frame, 
                    fg_color=THEME["card_bg"], 
                    border_color=status_color if status == "current" else THEME["border"], 
                    border_width=2 if status == "current" else 1, 
                    corner_radius=12
                )
                card.pack(fill="x", pady=6, padx=10, ipady=4)

                # Info Layout
                info_frame = ctk.CTkFrame(card, fg_color="transparent")
                info_frame.pack(side="left", padx=15, pady=10, fill="x", expand=True)

                title_row = ctk.CTkFrame(info_frame, fg_color="transparent")
                title_row.pack(fill="x", anchor="w")

                # Status Badge
                badge_pill = ctk.CTkFrame(title_row, fg_color=badge_bg, corner_radius=6)
                badge_pill.pack(side="left", padx=(0, 10))
                ctk.CTkLabel(
                    badge_pill, 
                    text=status_text, 
                    font=ctk.CTkFont(size=11, weight="bold"), 
                    text_color=status_color
                ).pack(padx=8, pady=2)

                title_lbl = ctk.CTkLabel(
                    title_row, 
                    text=f"📞  {title}", 
                    font=ctk.CTkFont(size=14, weight="bold"), 
                    text_color=THEME["text_primary"] if status != "ended" else THEME["text_secondary"], 
                    anchor="w"
                )
                title_lbl.pack(side="left", fill="x", expand=True)

                time_lbl = ctk.CTkLabel(info_frame, text=f"⏰  {local_time_str}", font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"], anchor="w")
                time_lbl.pack(fill="x", pady=(4, 0))

                # Hover Highlight Binding
                def _bind_hover(card_widget, is_current, s_color):
                    def _enter(e): 
                        card_widget.configure(
                            fg_color=THEME["card_hover"], 
                            border_color=s_color if is_current else THEME["border_hover"]
                        )
                    def _leave(e): 
                        card_widget.configure(
                            fg_color=THEME["card_bg"], 
                            border_color=s_color if is_current else THEME["border"]
                        )
                    
                    card_widget.bind("<Enter>", _enter)
                    card_widget.bind("<Leave>", _leave)
                    for child in card_widget.winfo_children():
                        child.bind("<Enter>", _enter)
                        child.bind("<Leave>", _leave)
                        if isinstance(child, ctk.CTkFrame):
                            for subchild in child.winfo_children():
                                subchild.bind("<Enter>", _enter)
                                subchild.bind("<Leave>", _leave)

                _bind_hover(card, status == "current", status_color)

                # Join Button Injection for Scheduled or Current calls
                join_url = call.get('join_url')
                if join_url and status in ["scheduled", "current"]:
                    btn_color = THEME["status_current"] if status == "current" else THEME["join_green"]
                    btn_hover = "#D97706" if status == "current" else THEME["join_green_hover"]
                    btn_text_color = "#000000" if status == "current" else "#FFFFFF"

                    join_btn = ctk.CTkButton(
                        card, 
                        text="🚀 Join", 
                        width=85, 
                        height=32,
                        font=ctk.CTkFont(size=12, weight="bold"),
                        fg_color=btn_color, 
                        hover_color=btn_hover,
                        text_color=btn_text_color,
                        command=lambda url=join_url: open_in_browser(url)
                    )
                    join_btn.pack(side="right", padx=15, pady=10)

        # Default Placeholders
        ctk.CTkLabel(self.channel_content_frame, text="Select a channel on the left to view posts.", text_color=THEME["text_secondary"]).pack(pady=50)
        ctk.CTkLabel(self.chat_messages_frame, text="Select a chat conversation on the left to view messages.", text_color=THEME["text_secondary"]).pack(pady=50)

    # --- CONTENT PANELS (THREAD / CHANNEL VIEWS WITH TIMESTAMPS) ---
    def _show_channel_content(self, team, channel):
        for child in self.channel_content_frame.winfo_children(): child.destroy()

        header_card = ctk.CTkFrame(self.channel_content_frame, fg_color=THEME["card_bg"], border_color=THEME["border"], border_width=1, corner_radius=10)
        header_card.pack(fill="x", pady=(0, 15), ipady=5)

        ctk.CTkLabel(header_card, text=f"# {channel.get('displayName', 'Channel')}", font=ctk.CTkFont(size=18, weight="bold"), text_color=THEME["text_primary"]).pack(anchor="w", padx=15, pady=(10, 2))
        ctk.CTkLabel(header_card, text=f"Team: {team.get('displayName')}", font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"]).pack(anchor="w", padx=15, pady=(0, 10))

        loading_lbl = ctk.CTkLabel(self.channel_content_frame, text="⏳ Loading channel posts...", text_color=THEME["text_secondary"])
        loading_lbl.pack(pady=30)

        def _load_posts():
            try:
                msgs = teams_backend.fetch_channel_messages(team['id'], channel['id'])
            except Exception as e:
                print(f"Failed to fetch posts: {e}")
                msgs = []
            self.after(0, lambda: _render_posts(msgs))

        def _render_posts(msgs):
            try:
                loading_lbl.destroy()
            except Exception:
                pass

            if not msgs:
                ctk.CTkLabel(self.channel_content_frame, text="No posts found in this channel.", text_color=THEME["text_secondary"]).pack(pady=30)
                return

            try:
                for m in (msgs):
                    msg_card = ctk.CTkFrame(self.channel_content_frame, fg_color=THEME["card_bg"], border_color=THEME["border"], border_width=1, corner_radius=10)
                    msg_card.pack(fill="x", pady=5, padx=2)
                    
                    # Header Row
                    hdr_row = ctk.CTkFrame(msg_card, fg_color="transparent")
                    hdr_row.pack(fill="x", padx=12, pady=(10, 2))

                    ctk.CTkLabel(hdr_row, text=str(m.get('sender', 'Unknown')), font=ctk.CTkFont(weight="bold", size=12), text_color=THEME["accent_indigo"]).pack(side="left")

                    date_str = ""
                    raw_ts = m.get("created_at")
                    if raw_ts:
                        try:
                            clean_ts = str(raw_ts).strip().replace("Z", "+00:00")
                            dt = datetime.fromisoformat(clean_ts)
                            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                            date_str = dt.astimezone().strftime("%b %d, %Y at %I:%M %p")
                        except Exception:
                            pass

                    if date_str:
                        ctk.CTkLabel(hdr_row, text=f"•  {date_str}", font=ctk.CTkFont(size=11), text_color=THEME["text_secondary"]).pack(side="left", padx=(8, 0))

                    # Body Text
                    if m.get('content'):
                        ctk.CTkLabel(msg_card, text=m['content'], font=ctk.CTkFont(size=13), text_color=THEME["text_primary"], anchor="w", justify="left", wraplength=480).pack(fill="x", padx=12, pady=(2, 6))

                    # Attachments Button Setup
                    attachments = m.get('attachments', [])
                    if attachments:
                        att_frame = ctk.CTkFrame(msg_card, fg_color="transparent")
                        att_frame.pack(fill="x", padx=12, pady=(0, 10))
                        
                        for att in attachments:
                            file_row = ctk.CTkFrame(att_frame, fg_color=THEME["header_bg"], corner_radius=6)
                            file_row.pack(fill="x", pady=2)
                            
                            ctk.CTkLabel(file_row, text=f"📎 {att.get('name', 'Attachment')}", font=ctk.CTkFont(size=12), text_color=THEME["text_primary"]).pack(side="left", padx=10, pady=8)
                            
                            btn = ctk.CTkButton(
                                file_row, text="Open File", width=80, height=26, font=ctk.CTkFont(size=11, weight="bold"),
                                fg_color=THEME["accent_indigo"], hover_color=THEME["accent_hover"],
                                command=lambda url=att['url']: open_in_browser(url)
                            )
                            btn.pack(side="right", padx=10, pady=8)
                    else:
                        ctk.CTkFrame(msg_card, fg_color="transparent", height=6).pack(fill="x")
            except Exception as e:
                print(f"Error rendering posts: {e}")
                ctk.CTkLabel(self.channel_content_frame, text=f"Encountered a UI render error.", text_color=THEME["error_text"]).pack(pady=10)

        threading.Thread(target=_load_posts, daemon=True).start()
    def _show_chat_messages(self, chat):
        for child in self.chat_messages_frame.winfo_children(): child.destroy()

        header_card = ctk.CTkFrame(self.chat_messages_frame, fg_color=THEME["card_bg"], border_color=THEME["border"], border_width=1, corner_radius=10)
        header_card.pack(fill="x", pady=(0, 15), ipady=5)

        ctk.CTkLabel(header_card, text=f"💬 {chat['title']}", font=ctk.CTkFont(size=18, weight="bold"), text_color=THEME["text_primary"]).pack(anchor="w", padx=15, pady=10)

        loading_lbl = ctk.CTkLabel(self.chat_messages_frame, text="⏳ Loading message history...", text_color=THEME["text_secondary"])
        loading_lbl.pack(pady=30)

        def _load_history():
            try:
                msgs = teams_backend.fetch_chat_history(chat['id'])
            except Exception as e:
                print(f"Failed to fetch history: {e}")
                msgs = []
            self.after(0, lambda: _render_history(msgs))

        def _render_history(msgs):
            loading_lbl.destroy()

            if not msgs:
                msgs = [{"sender": chat.get("sender", "Unknown"), "content": chat.get("last_message", "No content found.")}]

            for m in reversed(msgs):
                msg_card = ctk.CTkFrame(self.chat_messages_frame, fg_color=THEME["card_bg"], border_color=THEME["border"], border_width=1, corner_radius=10)
                msg_card.pack(fill="x", pady=5, padx=2)
                
                ctk.CTkLabel(msg_card, text=m['sender'], font=ctk.CTkFont(weight="bold", size=12), text_color=THEME["accent_indigo"], anchor="w").pack(fill="x", padx=12, pady=(10, 2))
                ctk.CTkLabel(msg_card, text=m['content'], font=ctk.CTkFont(size=13), text_color=THEME["text_primary"], anchor="w", justify="left", wraplength=480).pack(fill="x", padx=12, pady=(0, 10))

        threading.Thread(target=_load_history, daemon=True).start()