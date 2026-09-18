import customtkinter as ctk
import threading
import webbrowser
import tempfile
import os
from datetime import datetime, timedelta, timezone
import teams_backend


def parse_teams_time(ts):
    if not ts:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        ts_str = str(ts).strip()
        if ts_str.isdigit() or isinstance(ts, (int, float)):
            val = float(ts)
            if val > 1e11:
                val /= 1000
            return datetime.fromtimestamp(val, tz=timezone.utc)
        clean_str = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def open_in_browser(url: str):
    """Open a URL through a temp HTML bounce file so the OS browser (not an embedded view) handles it."""
    if not url:
        return
    html = f"""
    <!DOCTYPE html><html><head><title>Joining Teams...</title><script>
    let target = "{url.strip()}";
    if (!target.includes("web=1")) target += (target.includes("?") ? "&" : "?") + "web=1";
    target += "&suppressPrompt=true";
    window.location.href = target;
    </script></head>
    <body style="background:#111;color:#fff;font-family:sans-serif;text-align:center;padding-top:20%">
    <h2>Routing to Teams Web...</h2>
    <p>If nothing happens, <a href="#" onclick="window.location.href=target" style="color:#4da6ff">click here</a>.</p>
    </body></html>
    """
    path = os.path.join(tempfile.gettempdir(), "otium_teams_join.html")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        webbrowser.open(f"file://{path}")
    except Exception:
        webbrowser.open(url)


class AccordionChat(ctk.CTkFrame):
    """Expandable chat card. Click header to toggle history; button opens the DM in Teams."""
    def __init__(self, master, conv_data, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.is_open = False
        self.conv_data = conv_data
        self.teams_url = conv_data.get("teams_url")

        # ---- Header ----
        self.header = ctk.CTkFrame(self, fg_color="#44067a", corner_radius=6, cursor="hand2")
        self.header.pack(fill="x", pady=2)

        row1 = ctk.CTkFrame(self.header, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=(6, 0))

        self.chevron = ctk.CTkLabel(row1, text="▶", width=14,
                                    font=ctk.CTkFont(size=10), cursor="hand2")
        self.chevron.pack(side="left")

        name = conv_data.get("name", "Chat")
        self.name_label = ctk.CTkLabel(
            row1, text=f"💬 {name}",
            font=ctk.CTkFont(weight="bold", size=12),
            anchor="w", justify="left", cursor="hand2",
        )
        self.name_label.pack(side="left", padx=(4, 0))

        ts_obj = parse_teams_time(conv_data.get("latest_time"))
        ts_str = ts_obj.astimezone().strftime("%b %d, %I:%M %p") if ts_obj.year > 1 else ""
        self.time_label = ctk.CTkLabel(row1, text=ts_str,
                                       text_color="#bbbbbb",
                                       font=ctk.CTkFont(size=10),
                                       cursor="hand2")
        self.time_label.pack(side="right")

        sender = conv_data.get("last_sender", "")
        preview = conv_data.get("last_message", "") or "No messages"
        full = f"{sender}: {preview}" if sender else preview
        if len(full) > 110:
            full = full[:107] + "..."
        self.preview_label = ctk.CTkLabel(
            self.header, text=full, text_color="#dddddd",
            anchor="w", justify="left", cursor="hand2",
        )
        self.preview_label.pack(fill="x", padx=10, pady=(0, 6))

        # ---- History ----
        self.history = ctk.CTkFrame(self, fg_color="#2a024f", corner_radius=6)

        if self.teams_url:
            btn_row = ctk.CTkFrame(self.history, fg_color="transparent")
            btn_row.pack(fill="x", padx=10, pady=(8, 2))
            ctk.CTkButton(
                btn_row, text="🔗 Open in Teams", width=150, height=26,
                fg_color="#1f6aa5", hover_color="#155a8a",
                command=lambda u=self.teams_url: open_in_browser(u),
            ).pack(side="right")

        msgs = conv_data.get("messages", [])
        if not msgs:
            ctk.CTkLabel(self.history, text="No message history loaded.",
                         text_color="gray").pack(pady=10)
        else:
            for msg in msgs:
                box = ctk.CTkFrame(self.history, fg_color="#1a1a1a", corner_radius=6)
                box.pack(fill="x", padx=10, pady=4)

                m_ts = parse_teams_time(msg.get("timestamp"))
                m_ts_str = m_ts.astimezone().strftime("%b %d, %I:%M %p") if m_ts.year > 1 else ""

                top = ctk.CTkFrame(box, fg_color="transparent")
                top.pack(fill="x", padx=10, pady=(4, 0))
                ctk.CTkLabel(top, text=f"👤 {msg.get('sender', 'Unknown')}",
                             font=ctk.CTkFont(weight="bold", size=11),
                             text_color="#a8c7e8").pack(side="left")
                ctk.CTkLabel(top, text=m_ts_str,
                             font=ctk.CTkFont(size=10),
                             text_color="#888888").pack(side="right")

                ctk.CTkLabel(box, text=msg.get("message", ""),
                             text_color="#ffffff", wraplength=700,
                             justify="left", anchor="w").pack(
                    padx=10, pady=(2, 6), fill="x")

        # ---- Bindings ----
        for w in (self.header, self.chevron, self.name_label,
                  self.time_label, self.preview_label):
            w.bind("<Button-1>", self.toggle)

    def toggle(self, event=None):
        if self.is_open:
            self.history.pack_forget()
            self.header.configure(fg_color="#44067a")
            self.chevron.configure(text="▶")
            self.is_open = False
        else:
            self.history.pack(fill="x", pady=(0, 2))
            self.header.configure(fg_color="#5a0a9e")
            self.chevron.configure(text="▼")
            self.is_open = True


class TeamsView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="#83669f", **kwargs)
        self.loading_label = ctk.CTkLabel(
            self,
            text="Syncing Microsoft Teams Data...\nThis takes about 15-30 seconds.",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#030506",
        )
        self.loading_label.place(relx=0.5, rely=0.5, anchor="center")
        self.data_loaded = False

    def pack(self, **kwargs):
        super().pack(**kwargs)
        if not self.data_loaded:
            threading.Thread(target=self.fetch_and_render, daemon=True).start()

    def fetch_and_render(self):
        data = teams_backend.fetch_teams_data_clean()
        self.after(0, lambda: self.build_dashboard(data))

    def build_dashboard(self, data):
        self.loading_label.destroy()
        self.data_loaded = True

        main_container = ctk.CTkFrame(self, fg_color="transparent")
        main_container.place(relx=0.02, rely=0.02, relwidth=0.96, relheight=0.96)

        CARD_H = 0.235

        # ===== CARD 1: ANNOUNCEMENTS =====
        ann_card = ctk.CTkFrame(main_container, fg_color="#55089d", corner_radius=10)
        ann_card.place(relx=0, rely=0.0, relwidth=1.0, relheight=CARD_H)
        ctk.CTkLabel(ann_card, text="ACTIVITY / ANNOUNCEMENTS",
                     font=ctk.CTkFont(size=16, weight="bold")).place(relx=0.02, rely=0.05)
        ann_scroll = ctk.CTkScrollableFrame(ann_card, fg_color="transparent")
        ann_scroll.place(relx=0.02, rely=0.25, relwidth=0.96, relheight=0.7)

        if data.get("announcements"):
            for msg in data["announcements"]:
                box = ctk.CTkFrame(ann_scroll, fg_color="#333333", corner_radius=6)
                box.pack(fill="x", pady=3)

                ts_obj = parse_teams_time(msg.get("timestamp"))
                ts_str = ts_obj.astimezone().strftime("%b %d, %I:%M %p") if ts_obj.year > 1 else "Recent"

                top = ctk.CTkFrame(box, fg_color="transparent")
                top.pack(fill="x", padx=10, pady=(6, 0))
                ctk.CTkLabel(top, text=f"📢 {msg.get('channel_name', 'Activity')}",
                             font=ctk.CTkFont(weight="bold", size=11),
                             text_color="#ffd479").pack(side="left")
                ctk.CTkLabel(top, text=f"  👤 {msg.get('sender', 'Unknown')}",
                             font=ctk.CTkFont(size=11),
                             text_color="#aaaaaa").pack(side="left")
                ctk.CTkLabel(top, text=ts_str,
                             font=ctk.CTkFont(size=10),
                             text_color="#888888").pack(side="right")

                ctk.CTkLabel(box, text=msg.get("message", ""),
                             text_color="#ffffff", wraplength=800,
                             justify="left", anchor="w").pack(
                    padx=10, pady=(2, 6), fill="x")
        else:
            ctk.CTkLabel(ann_scroll, text="No recent activity.",
                         text_color="gray").pack(pady=10)

        # ===== CARD 2: CHATS =====
        chats_card = ctk.CTkFrame(main_container, fg_color="#55089d", corner_radius=10)
        chats_card.place(relx=0, rely=0.255, relwidth=1.0, relheight=CARD_H)
        ctk.CTkLabel(chats_card, text="RECENT CHATS",
                     font=ctk.CTkFont(size=16, weight="bold")).place(relx=0.02, rely=0.05)
        chat_scroll = ctk.CTkScrollableFrame(chats_card, fg_color="transparent")
        chat_scroll.place(relx=0.02, rely=0.25, relwidth=0.96, relheight=0.7)

        if data.get("chats"):
            for conv in data["chats"]:
                AccordionChat(chat_scroll, conv).pack(fill="x", pady=2)
        else:
            ctk.CTkLabel(chat_scroll, text="No recent chats.",
                         text_color="gray").pack(pady=10)

        # ===== CARD 3: MEETINGS (unchanged) =====
        meetings_card = ctk.CTkFrame(main_container, fg_color="#55089d", corner_radius=10)
        meetings_card.place(relx=0, rely=0.51, relwidth=1.0, relheight=CARD_H)
        ctk.CTkLabel(meetings_card, text="MEETINGS & CALLS",
                     font=ctk.CTkFont(size=16, weight="bold")).place(relx=0.02, rely=0.05)
        meet_scroll = ctk.CTkScrollableFrame(meetings_card, fg_color="transparent")
        meet_scroll.place(relx=0.02, rely=0.25, relwidth=0.96, relheight=0.7)

        now_utc = datetime.now(timezone.utc)
        if data.get("meetings"):
            sorted_meetings = sorted(
                data["meetings"],
                key=lambda x: parse_teams_time(x.get("start_time")),
                reverse=True,
            )
            for meet in sorted_meetings:
                start_dt = parse_teams_time(meet.get("start_time"))
                local_str = start_dt.astimezone().strftime("%I:%M %p, %b %d") if start_dt.year > 1 else "Time Unknown"

                if start_dt > now_utc:
                    f = ctk.CTkFrame(meet_scroll, fg_color="#b57a14", corner_radius=6)
                    f.pack(fill="x", pady=2)
                    ctk.CTkLabel(f, text=f"⏳ SCHEDULED: {meet['title']} ({local_str})",
                                 font=ctk.CTkFont(weight="bold")).pack(side="left", padx=10, pady=10)
                    ctk.CTkButton(f, text="JOIN CALL", fg_color="#82560d",
                                  width=90, height=28,
                                  command=lambda u=meet['join_url']: open_in_browser(u)).pack(side="right", padx=10)
                elif now_utc <= start_dt + timedelta(minutes=150):
                    f = ctk.CTkFrame(meet_scroll, fg_color="#1f6aa5", corner_radius=6)
                    f.pack(fill="x", pady=2)
                    ctk.CTkLabel(f, text=f"🔴 LIVE: {meet['title']} ({local_str})",
                                 font=ctk.CTkFont(weight="bold")).pack(side="left", padx=10, pady=10)
                    ctk.CTkButton(f, text="JOIN CALL", fg_color="#144870",
                                  width=90, height=28,
                                  command=lambda u=meet['join_url']: open_in_browser(u)).pack(side="right", padx=10)
                else:
                    f = ctk.CTkFrame(meet_scroll, fg_color="#222222", corner_radius=6)
                    f.pack(fill="x", pady=2)
                    ctk.CTkLabel(f, text=f"☑ ENDED: {meet['title']} ({local_str})",
                                 text_color="gray",
                                 font=ctk.CTkFont(weight="bold")).pack(side="left", padx=10, pady=10)
        else:
            ctk.CTkLabel(meet_scroll, text="No meetings found.",
                         text_color="gray").pack(pady=10)

        # ===== CARD 4: ASSIGNMENTS (unchanged) =====
        assignments_card = ctk.CTkFrame(main_container, fg_color="#55089d", corner_radius=10)
        assignments_card.place(relx=0, rely=0.765, relwidth=1.0, relheight=CARD_H)
        ctk.CTkLabel(assignments_card, text="ASSIGNMENTS",
                     font=ctk.CTkFont(size=16, weight="bold")).place(relx=0.02, rely=0.05)
        ctk.CTkLabel(assignments_card, text="No assignments due! 🎉",
                     text_color="gray").place(relx=0.5, rely=0.5, anchor="center")