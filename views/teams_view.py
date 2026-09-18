import threading
import customtkinter as ctk
import teams_backend


class TeamsView(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.top_bar = ctk.CTkFrame(self, fg_color="transparent", height=30)
        self.top_bar.grid(row=0, column=0, sticky="ew", padx=10, pady=(5, 0))

        self.refresh_btn = ctk.CTkButton(self.top_bar, text="🔄 Refresh", width=90, command=self.load_data)
        self.refresh_btn.pack(side="right")

        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        self.tab_channels = self.tabview.add("Channels")
        self.tab_chats = self.tabview.add("Chats")
        self.tab_calls = self.tabview.add("Calls")

        self._setup_channels_tab()
        self._setup_chats_tab()
        self._setup_calls_tab()

        self.load_data()

    def _setup_channels_tab(self):
        self.tab_channels.grid_columnconfigure(0, weight=1)
        self.tab_channels.grid_columnconfigure(1, weight=3)
        self.tab_channels.grid_rowconfigure(0, weight=1)

        self.teams_list_frame = ctk.CTkScrollableFrame(self.tab_channels)
        self.teams_list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5), pady=5)

        self.channel_content_frame = ctk.CTkScrollableFrame(self.tab_channels)
        self.channel_content_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0), pady=5)

    def _setup_chats_tab(self):
        self.tab_chats.grid_columnconfigure(0, weight=1)
        self.tab_chats.grid_columnconfigure(1, weight=3)
        self.tab_chats.grid_rowconfigure(0, weight=1)

        self.chat_list_frame = ctk.CTkScrollableFrame(self.tab_chats)
        self.chat_list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5), pady=5)

        self.chat_messages_frame = ctk.CTkScrollableFrame(self.tab_chats)
        self.chat_messages_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0), pady=5)

    def _setup_calls_tab(self):
        self.tab_calls.grid_columnconfigure(0, weight=1)
        self.tab_calls.grid_rowconfigure(0, weight=1)
        self.calls_list_frame = ctk.CTkScrollableFrame(self.tab_calls)
        self.calls_list_frame.grid(row=0, column=0, sticky="nsew", pady=5)

    def load_data(self):
        for frame in [self.teams_list_frame, self.chat_list_frame, self.calls_list_frame, self.channel_content_frame,
                      self.chat_messages_frame]:
            for child in frame.winfo_children(): child.destroy()

        ctk.CTkLabel(self.teams_list_frame, text="Syncing...").pack(pady=20)
        ctk.CTkLabel(self.chat_list_frame, text="Syncing...").pack(pady=20)
        ctk.CTkLabel(self.calls_list_frame, text="Syncing...").pack(pady=20)

        threading.Thread(target=self._fetch_and_render, daemon=True).start()

    def _fetch_and_render(self):
        try:
            data = teams_backend.fetch_dashboard_data()
        except Exception as e:
            data = {"teams": [], "chats": [], "calls": [], "errors": [str(e)], "debug": {}}
        self.after(0, lambda: self._render_ui(data))

    def _render_error_diagnostics(self, frame, errors, debug_info):
        card = ctk.CTkFrame(frame, fg_color="#4A1515", corner_radius=8)
        card.pack(fill="x", padx=10, pady=10, ipady=5)
        ctk.CTkLabel(card, text="⚠️ Diagnostics / Errors Detected", font=ctk.CTkFont(weight="bold")).pack(pady=5)

        status = f"Graph Token Captured: {debug_info.get('has_graph')}\nSkype Token Captured: {debug_info.get('has_skype')}"
        ctk.CTkLabel(card, text=status, text_color="#FFB3B3").pack(pady=5)

        for err in errors:
            ctk.CTkLabel(card, text=f"• {err}", justify="left", wraplength=350, text_color="#FFA3A3").pack(anchor="w",
                                                                                                           padx=15,
                                                                                                           pady=2)

    def _render_ui(self, data: dict):
        for frame in [self.teams_list_frame, self.chat_list_frame, self.calls_list_frame, self.channel_content_frame,
                      self.chat_messages_frame]:
            for child in frame.winfo_children(): child.destroy()

        errors = data.get("errors", [])
        debug_info = data.get("debug", {})

        # 1. --- Render Channels ---
        teams = data.get("teams", [])
        if not teams:
            if errors:
                self._render_error_diagnostics(self.teams_list_frame, errors, debug_info)
            else:
                ctk.CTkLabel(self.teams_list_frame, text="No teams found.", text_color="gray").pack(pady=10)
        else:
            for team in teams:
                ctk.CTkLabel(self.teams_list_frame, text=team.get('displayName', 'Team'),
                             font=ctk.CTkFont(weight="bold", size=14)).pack(anchor="w", padx=5, pady=(15, 2))
                for channel in team.get('channels', []):
                    btn = ctk.CTkButton(
                        self.teams_list_frame, text=f"# {channel.get('displayName', 'General')}",
                        fg_color="transparent", text_color="#E0E0E0", anchor="w", hover_color="#333333",
                        # We pass BOTH team and channel objects so we have their IDs to fetch content
                        command=lambda t=team, c=channel: self._show_channel_content(t, c)
                    )
                    btn.pack(fill="x", padx=10, pady=1)

        # 2. --- Render Chats ---
        chats = data.get("chats", [])
        if not chats:
            if errors:
                self._render_error_diagnostics(self.chat_list_frame, errors, debug_info)
            else:
                ctk.CTkLabel(self.chat_list_frame, text="No recent chats.", text_color="gray").pack(pady=10)
        else:
            for chat in chats:
                clean_title = chat['title'].replace('\n', ' ')[:25]
                clean_msg = chat['last_message'].replace('\n', ' ')[:35]
                chat_btn = ctk.CTkButton(
                    self.chat_list_frame, text=f"{clean_title}\n{clean_msg}...", fg_color="#2B2B2B",
                    hover_color="#3A3A3A", anchor="w", justify="left", height=55,
                    command=lambda c=chat: self._show_chat_messages(c)
                )
                chat_btn.pack(fill="x", pady=2, padx=2)

        # 3. --- Render Calls ---
        calls = data.get("calls", [])
        if not calls:
            if errors:
                self._render_error_diagnostics(self.calls_list_frame, errors, debug_info)
            else:
                ctk.CTkLabel(self.calls_list_frame, text="No recent calls found.", text_color="gray").pack(pady=10)
        else:
            for call in calls:
                card = ctk.CTkFrame(self.calls_list_frame, fg_color="#2B2B2B", corner_radius=6)
                card.pack(fill="x", pady=4, padx=10, ipady=8)
                title = call.get('subject', 'Call / Meeting')
                time_str = call.get('start_time', '')[:16].replace('T', ' ')
                ctk.CTkLabel(card, text=f"📞  {title}   |   {time_str}", font=ctk.CTkFont(size=14), anchor="w").pack(
                    side="left", padx=15, fill="x", expand=True)

        ctk.CTkLabel(self.channel_content_frame, text="Select a channel to view posts", text_color="gray").pack(pady=40)
        ctk.CTkLabel(self.chat_messages_frame, text="Select a chat to view messages", text_color="gray").pack(pady=40)

    def _show_channel_content(self, team, channel):
        for child in self.channel_content_frame.winfo_children(): child.destroy()

        header = ctk.CTkLabel(self.channel_content_frame, text=f"# {channel.get('displayName', 'Channel')}",
                              font=ctk.CTkFont(size=20, weight="bold"))
        header.pack(anchor="w", pady=(0, 15), padx=10)

        btn_frame = ctk.CTkFrame(self.channel_content_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=(0, 20))
        ctk.CTkButton(btn_frame, text="📝 Announcements / Posts", width=160, fg_color="#464EB8").pack(side="left",
                                                                                                     padx=(0, 10))
        ctk.CTkButton(btn_frame, text="📁 Files (Soon)", width=120, fg_color="#333333").pack(side="left")

        loading_lbl = ctk.CTkLabel(self.channel_content_frame, text="Loading channel posts...")
        loading_lbl.pack(pady=20)

        def _load_posts():
            try:
                msgs = teams_backend.fetch_channel_messages(team['id'], channel['id'])
            except Exception as e:
                print(f"Failed to fetch posts: {e}")
                msgs = []
            self.after(0, lambda: _render_posts(msgs))

        def _render_posts(msgs):
            loading_lbl.destroy()
            if not msgs:
                ctk.CTkLabel(self.channel_content_frame, text="No posts found in this channel.",
                             text_color="gray").pack(pady=20)
                return

            for m in reversed(msgs):
                msg_card = ctk.CTkFrame(self.channel_content_frame, fg_color="#1E1E1E", corner_radius=6)
                msg_card.pack(fill="x", pady=4, padx=10)
                ctk.CTkLabel(msg_card, text=m['sender'], font=ctk.CTkFont(weight="bold", size=12), anchor="w").pack(
                    fill="x", padx=12, pady=(8, 0))
                ctk.CTkLabel(msg_card, text=m['content'], font=ctk.CTkFont(size=13), text_color="#CCCCCC", anchor="w",
                             justify="left", wraplength=450).pack(fill="x", padx=12, pady=(0, 8))

        threading.Thread(target=_load_posts, daemon=True).start()

    def _show_chat_messages(self, chat):
        for child in self.chat_messages_frame.winfo_children(): child.destroy()

        header = ctk.CTkLabel(self.chat_messages_frame, text=chat['title'], font=ctk.CTkFont(size=18, weight="bold"))
        header.pack(anchor="w", pady=(0, 15), padx=10)

        loading_lbl = ctk.CTkLabel(self.chat_messages_frame, text="Loading history...")
        loading_lbl.pack(pady=20)

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
                msgs = [
                    {"sender": chat.get("sender", "Unknown"), "content": chat.get("last_message", "No content found.")}]

            for m in reversed(msgs):
                msg_card = ctk.CTkFrame(self.chat_messages_frame, fg_color="#1E1E1E", corner_radius=6)
                msg_card.pack(fill="x", pady=4, padx=10)
                ctk.CTkLabel(msg_card, text=m['sender'], font=ctk.CTkFont(weight="bold", size=12), anchor="w").pack(
                    fill="x", padx=12, pady=(8, 0))
                ctk.CTkLabel(msg_card, text=m['content'], font=ctk.CTkFont(size=13), text_color="#CCCCCC", anchor="w",
                             justify="left", wraplength=450).pack(fill="x", padx=12, pady=(0, 8))

        threading.Thread(target=_load_history, daemon=True).start()