import os
import sys
import threading
import tempfile
from tkinter import filedialog, messagebox
from typing import Dict, Any, Optional, List
import customtkinter as ctk

# Ensure the app can find outlook_backend
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from outlook_backend import OutlookBackend, EmailMessage, AttachmentData

# ==========================================
# DESIGN SYSTEM & COLOR PALETTE (APPLE INSPIRED)
# ==========================================
THEME = {
    "bg_dark": "#121216",
    "card_bg": "#1E1E2A",
    "card_hover": "#262638",
    "card_active": "#2D2D44",
    "header_bg": "#181822",
    "border": "#323246",
    "border_hover": "#4B4B66",
    "text_primary": "#F1F5F9",
    "text_secondary": "#94A3B8",
    "text_muted": "#64748B",
    "accent_indigo": "#6366F1",
    "accent_hover": "#4F46E5",
    "tab_purple": "#2E1B4E",
    "tab_purple_hover": "#3D246C",
    "selected_purple": "#7C3AED",
    "selected_purple_hover": "#6D28D9",
    "danger": "#EF4444",
    "success": "#10B981"
}


# ==============================================================================
# IN-APP DRAGGABLE COMPOSE OVERLAY (APPLE-STYLE SIDE-SHEET)
# ==============================================================================
class InAppComposeOverlay(ctk.CTkFrame):
    """
    A floating, draggable Compose window that lives inside the main app.
    Allows users to read other emails in the background while composing.
    """

    def __init__(self, parent_container, backend_instance: OutlookBackend, mode: str = "new",
                 msg_data: EmailMessage = None):
        super().__init__(parent_container, fg_color=THEME["bg_dark"], border_color=THEME["accent_indigo"],
                         border_width=2, corner_radius=12)
        self.parent_container = parent_container
        self.backend = backend_instance
        self.mode = mode
        self.msg_data = msg_data
        self.attachment_paths: List[str] = []

        # Calculate dynamic position (Spawn on the right side of the app)
        self.w, self.h = 720, 620
        parent_width = self.parent_container.winfo_width()
        self.x = parent_width - self.w - 40 if parent_width > self.w else 40
        self.y = 40

        self.place(x=self.x, y=self.y, width=self.w, height=self.h)
        self.lift()

        self._build_ui()
        self._populate_data()

    def _build_ui(self):
        # Draggable Header
        self.header = ctk.CTkFrame(self, height=50, fg_color=THEME["header_bg"], corner_radius=10)
        self.header.pack(fill="x", side="top", padx=2, pady=2)
        self.header.pack_propagate(False)
        self.header.configure(cursor="fleur")

        # Drag Bindings
        self.header.bind("<ButtonPress-1>", self._start_drag)
        self.header.bind("<B1-Motion>", self._do_drag)

        titles = {"new": "✉️ New Message", "reply": "↩️ Reply", "reply_all": "↪️ Reply All", "forward": "➡️ Forward"}
        lbl_title = ctk.CTkLabel(self.header, text=titles.get(self.mode, "Compose"),
                                 font=ctk.CTkFont(size=16, weight="bold"), text_color=THEME["text_primary"])
        lbl_title.pack(side="left", padx=20, pady=10)
        lbl_title.bind("<ButtonPress-1>", self._start_drag)
        lbl_title.bind("<B1-Motion>", self._do_drag)

        # Close Button
        btn_close = ctk.CTkButton(self.header, text="✖", width=30, height=30, fg_color="transparent",
                                  hover_color=THEME["danger"], text_color=THEME["text_secondary"],
                                  font=ctk.CTkFont(size=14), command=self.destroy)
        btn_close.pack(side="right", padx=10)

        # Form Area
        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=20, pady=15)

        ctk.CTkLabel(form, text="To:", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=THEME["text_secondary"]).pack(anchor="w", pady=(0, 2))
        self.to_entry = ctk.CTkEntry(form, placeholder_text="recipient@domain.com (Separate multiple with ;)",
                                     height=35, fg_color=THEME["card_bg"], border_color=THEME["border"],
                                     text_color=THEME["text_primary"])
        self.to_entry.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(form, text="Subject:", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=THEME["text_secondary"]).pack(anchor="w", pady=(0, 2))
        self.subject_entry = ctk.CTkEntry(form, placeholder_text="Add a subject", height=35, fg_color=THEME["card_bg"],
                                          border_color=THEME["border"], text_color=THEME["text_primary"])
        self.subject_entry.pack(fill="x", pady=(0, 10))

        self.body_textbox = ctk.CTkTextbox(form, fg_color=THEME["card_bg"], border_color=THEME["border"],
                                           border_width=1, text_color=THEME["text_primary"], wrap="word",
                                           font=ctk.CTkFont(size=14))
        self.body_textbox.pack(fill="both", expand=True, pady=(0, 5))

        # Attachments Container (Scrollable horizontal chips)
        self.att_container = ctk.CTkScrollableFrame(form, height=45, orientation="horizontal", fg_color="transparent")
        self.att_container.pack(fill="x", pady=(0, 5))

        # Footer Actions
        footer = ctk.CTkFrame(self, height=65, fg_color=THEME["header_bg"], corner_radius=10)
        footer.pack(fill="x", side="bottom", padx=2, pady=2)
        footer.pack_propagate(False)

        attach_btn = ctk.CTkButton(footer, text="📎 Attach Files", width=120, height=35, fg_color=THEME["card_bg"],
                                   hover_color=THEME["border_hover"], border_width=1, border_color=THEME["border"],
                                   text_color=THEME["text_primary"], command=self._attach_files)
        attach_btn.pack(side="left", padx=20, pady=15)

        self.send_btn = ctk.CTkButton(footer, text="🚀 Send", width=120, height=35, fg_color=THEME["accent_indigo"],
                                      hover_color=THEME["accent_hover"], text_color=THEME["text_primary"],
                                      font=ctk.CTkFont(weight="bold"), command=self._handle_send)
        self.send_btn.pack(side="right", padx=20, pady=15)

        discard_btn = ctk.CTkButton(footer, text="Discard", width=80, height=35, fg_color="transparent",
                                    hover_color=THEME["card_bg"], text_color=THEME["danger"], command=self.destroy)
        discard_btn.pack(side="right", padx=5, pady=15)

    def _start_drag(self, event):
        self.lift()
        self._drag_start_x = event.x
        self._drag_start_y = event.y

    def _do_drag(self, event):
        self.x = self.winfo_x() + (event.x - self._drag_start_x)
        self.y = self.winfo_y() + (event.y - self._drag_start_y)
        self.place(x=self.x, y=self.y)

    def _populate_data(self):
        if self.mode == "new" or not self.msg_data:
            return

        orig_subject = self.msg_data.subject
        orig_sender = self.msg_data.sender_email
        orig_body = self.msg_data.body

        if self.mode in ["reply", "reply_all"]:
            self.to_entry.insert(0, orig_sender)
            if self.mode == "reply_all":
                cc = "; ".join(self.msg_data.cc_recipients)
                to_all = "; ".join([orig_sender] + self.msg_data.to_recipients)
                self.to_entry.delete(0, "end")
                self.to_entry.insert(0, f"{to_all}; {cc}".strip("; "))

            subj_prefix = "Re: " if not orig_subject.lower().startswith("re:") else ""
            self.subject_entry.insert(0, f"{subj_prefix}{orig_subject}")

        elif self.mode == "forward":
            subj_prefix = "Fw: " if not orig_subject.lower().startswith("fw:") else ""
            self.subject_entry.insert(0, f"{subj_prefix}{orig_subject}")

        # Inject original message quoting cleanly
        quote_header = f"\n\n\n[ --- Original Message --- ]\nFrom: {self.msg_data.sender_name} <{orig_sender}>\nSent: {self.msg_data.time}\nSubject: {orig_subject}\n\n"
        self.body_textbox.insert("1.0", quote_header + orig_body)
        self.body_textbox.mark_set("insert", "1.0")

    def _attach_files(self):
        files = filedialog.askopenfilenames(title="Select Attachments")
        if files:
            for f in files:
                if f not in self.attachment_paths:
                    self.attachment_paths.append(f)
                    self._render_attachment_chip(f)

    def _render_attachment_chip(self, file_path: str):
        chip = ctk.CTkFrame(self.att_container, fg_color=THEME["card_active"], corner_radius=6,
                            border_color=THEME["border"], border_width=1)
        chip.pack(side="left", padx=5)

        filename = os.path.basename(file_path)
        ctk.CTkLabel(chip, text=f"📎 {filename}", font=ctk.CTkFont(size=11), text_color=THEME["text_primary"]).pack(
            side="left", padx=(10, 5), pady=4)

        del_btn = ctk.CTkButton(chip, text="✖", width=24, height=24, fg_color="transparent",
                                hover_color=THEME["danger"], text_color=THEME["text_secondary"],
                                font=ctk.CTkFont(size=12, weight="bold"))
        del_btn.pack(side="left", padx=(0, 5), pady=4)
        del_btn.configure(command=lambda c=chip, p=file_path: self._remove_attachment(c, p))

    def _remove_attachment(self, chip_widget, file_path):
        if file_path in self.attachment_paths:
            self.attachment_paths.remove(file_path)
        chip_widget.destroy()

    def _handle_send(self):
        to_addr = self.to_entry.get().strip()
        subject = self.subject_entry.get().strip()
        body = self.body_textbox.get("1.0", "end-1c").strip()

        if not to_addr and self.mode != "reply":
            messagebox.showwarning("Validation Error", "Please specify at least one recipient.")
            return

        self.send_btn.configure(state="disabled", text="Sending...")
        msg_id = self.msg_data.id if self.msg_data else None

        def bg_send():
            try:
                if self.mode == "new":
                    self.backend.send_email(to_addr, subject, body, self.attachment_paths)
                elif self.mode == "reply":
                    self.backend.reply_email(msg_id, body)
                elif self.mode == "reply_all":
                    self.backend.reply_all_email(msg_id, body)
                elif self.mode == "forward":
                    self.backend.forward_email(msg_id, to_addr.split(";"), body)

                self.after(0, self.destroy)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Send Error", str(e)))
                self.after(0, lambda: self.send_btn.configure(state="normal", text="🚀 Send"))

        threading.Thread(target=bg_send, daemon=True).start()


# ==============================================================================
# MAIN OUTLOOK APPLICATION VIEW
# ==============================================================================
class OutlookView(ctk.CTkFrame):
    """
    Main Outlook Interface featuring a 2-pane resizable layout, Apple-inspired aesthetics,
    segmented folder tabs, and interactive attachment managers.
    """

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=THEME["bg_dark"], **kwargs)
        self.backend = OutlookBackend()

        self.current_folder_id: Optional[str] = None
        self.folder_map: Dict[str, str] = {}
        self.current_skip: int = 0
        self.selected_message: Optional[EmailMessage] = None
        self.is_searching: bool = False
        self.email_cards: List[Dict[str, Any]] = []

        self._build_main_layout()
        self.load_data()

    def _build_main_layout(self):
        # 1. TOP HEADER RIBBON
        self.ribbon = ctk.CTkFrame(self, height=65, fg_color="transparent", corner_radius=0)
        self.ribbon.pack(fill="x", side="top", padx=20, pady=(15, 10))

        left_group = ctk.CTkFrame(self.ribbon, fg_color="transparent")
        left_group.pack(side="left")

        ctk.CTkLabel(left_group, text="Outlook", font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=THEME["text_primary"]).pack(side="left", padx=(0, 20))
        self.compose_btn = ctk.CTkButton(left_group, text="➕ New mail", width=110, height=36,
                                         fg_color=THEME["accent_indigo"], hover_color=THEME["accent_hover"],
                                         font=ctk.CTkFont(size=12, weight="bold"),
                                         command=lambda: InAppComposeOverlay(self, self.backend, mode="new"))
        self.compose_btn.pack(side="left", padx=(0, 10))
        self.sync_btn = ctk.CTkButton(left_group, text="🔄 Refresh", width=95, height=36, fg_color=THEME["card_bg"],
                                      border_width=1, border_color=THEME["border"], hover_color=THEME["border_hover"],
                                      text_color=THEME["text_primary"], command=lambda: self.load_data(False))
        self.sync_btn.pack(side="left")

        # Center: Folder Navigation (Teams-style Segmented Tabs)
        self.tab_selector = ctk.CTkSegmentedButton(
            self.ribbon,
            values=["Inbox", "Drafts", "Sent Items", "Archive", "Deleted Items"],
            height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            selected_color=THEME["selected_purple"],
            selected_hover_color=THEME["selected_purple_hover"],
            unselected_color=THEME["tab_purple"],
            unselected_hover_color=THEME["tab_purple_hover"],
            text_color=THEME["text_primary"],
            command=self._on_tab_changed
        )
        self.tab_selector.pack(side="left", expand=True, padx=20)

        # Right: Search Box
        self.search_entry = ctk.CTkEntry(self.ribbon, placeholder_text="🔍 Search mailbox...", width=260, height=36,
                                         fg_color=THEME["bg_dark"], border_color=THEME["border"])
        self.search_entry.pack(side="right")
        self.search_entry.bind("<Return>", self.execute_search)

        # 2. TWO-PANE SPLITTER CONTAINER
        self.container = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.container.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        # LEFT: Message List
        self.list_pane = ctk.CTkScrollableFrame(self.container, width=380, fg_color=THEME["bg_dark"], corner_radius=0,
                                                scrollbar_button_color=THEME["border"],
                                                scrollbar_button_hover_color=THEME["border_hover"])
        self.list_pane.pack(side="left", fill="y")
        self.list_pane.pack_propagate(False)

        # DRAGGABLE SLIDER HANDLE
        self.splitter = ctk.CTkFrame(self.container, width=8, fg_color="transparent", cursor="sb_h_double_arrow")
        self.splitter.pack(side="left", fill="y", padx=2)
        self.splitter.bind("<ButtonPress-1>", self._start_split_drag)
        self.splitter.bind("<B1-Motion>", self._do_split_drag)

        # RIGHT: Reading Area
        self.reading_pane = ctk.CTkFrame(self.container, fg_color=THEME["card_bg"], corner_radius=12, border_width=1,
                                         border_color=THEME["border"])
        self.reading_pane.pack(side="left", fill="both", expand=True)

        self._build_reading_pane_content()

    def _start_split_drag(self, event):
        self.splitter._drag_start_x = event.x_root

    def _do_split_drag(self, event):
        delta = event.x_root - self.splitter._drag_start_x
        current_width = self.list_pane.winfo_width()
        new_width = current_width + delta
        if 260 < new_width < 700:
            self.list_pane.configure(width=new_width)
            self.splitter._drag_start_x = event.x_root

    def _build_reading_pane_content(self):
        # Top Action Ribbon
        self.reading_actions = ctk.CTkFrame(self.reading_pane, height=55, fg_color=THEME["header_bg"], corner_radius=12)
        self.reading_actions.pack(fill="x", side="top", padx=15, pady=15)
        self.reading_actions.pack_propagate(False)

        actions = [
            ("↩️ Reply", lambda: InAppComposeOverlay(self, self.backend, mode="reply", msg_data=self.selected_message)),
            ("↪️ Reply All",
             lambda: InAppComposeOverlay(self, self.backend, mode="reply_all", msg_data=self.selected_message)),
            ("➡️ Forward",
             lambda: InAppComposeOverlay(self, self.backend, mode="forward", msg_data=self.selected_message)),
            ("📦 Archive", lambda: self.execute_message_action("archive")),
            ("🗑️ Delete", lambda: self.execute_message_action("delete")),
            ("✉️ Mark Unread", lambda: self.execute_message_action("unread"))
        ]

        self.reading_action_btns = []
        for txt, cmd in actions:
            btn = ctk.CTkButton(self.reading_actions, text=txt, width=80, height=32, fg_color="transparent",
                                hover_color=THEME["card_hover"], text_color=THEME["text_primary"],
                                font=ctk.CTkFont(size=12, weight="bold"), state="disabled", command=cmd)
            btn.pack(side="left", padx=4, pady=11)
            self.reading_action_btns.append(btn)

        # Subject Title
        self.rp_subject = ctk.CTkLabel(self.reading_pane, text="Select an email to read",
                                       font=ctk.CTkFont(size=22, weight="bold"), text_color=THEME["text_primary"],
                                       anchor="w", wraplength=700)
        self.rp_subject.pack(fill="x", padx=30, pady=(5, 10))

        # Bottom Sender Profile (Apple Style Footer)
        self.rp_meta_frame = ctk.CTkFrame(self.reading_pane, fg_color="transparent", height=60)
        self.rp_avatar = ctk.CTkButton(self.rp_meta_frame, text="👤", width=46, height=46, corner_radius=23,
                                       fg_color=THEME["selected_purple"], hover_color=THEME["selected_purple"],
                                       text_color=THEME["text_primary"], font=ctk.CTkFont(size=18, weight="bold"),
                                       state="disabled")
        self.rp_avatar.pack(side="left", padx=(0, 15))

        meta_text = ctk.CTkFrame(self.rp_meta_frame, fg_color="transparent")
        meta_text.pack(side="left", fill="x", expand=True)
        self.rp_sender_name = ctk.CTkLabel(meta_text, text="", font=ctk.CTkFont(size=16, weight="bold"),
                                           text_color=THEME["text_primary"], anchor="w")
        self.rp_sender_name.pack(fill="x")
        self.rp_sender_email = ctk.CTkLabel(meta_text, text="", font=ctk.CTkFont(size=12),
                                            text_color=THEME["text_secondary"], anchor="w")
        self.rp_sender_email.pack(fill="x")

        self.rp_date = ctk.CTkLabel(self.rp_meta_frame, text="", font=ctk.CTkFont(size=12),
                                    text_color=THEME["text_secondary"])
        self.rp_date.pack(side="right", anchor="n", pady=(5, 0))

        # Attachments Display Area
        self.rp_attachments_frame = ctk.CTkScrollableFrame(self.reading_pane, height=55, orientation="horizontal",
                                                           fg_color="transparent")

        # Formatted Body Area
        self.rp_body_box = ctk.CTkTextbox(self.reading_pane, state="disabled", fg_color="transparent",
                                          font=ctk.CTkFont(size=15), text_color=THEME["text_primary"], wrap="word")
        self.rp_body_box.pack(fill="both", expand=True, padx=25, pady=(5, 15))

        self.rp_body_box.tag_config("dimmed", foreground=THEME["text_muted"])
        self.rp_body_box.tag_config("divider", foreground=THEME["border_hover"])

    def _show_error_ui(self, error_msg: str):
        for w in self.list_pane.winfo_children(): w.destroy()
        ctk.CTkLabel(self.list_pane, text=f"⚠️ Data Error:\n\n{error_msg}", text_color=THEME["danger"],
                     font=ctk.CTkFont(size=13), wraplength=300).pack(pady=50)
        self.sync_btn.configure(state="normal", text="🔄 Refresh")

    def load_data(self, is_load_more: bool = False):
        if not is_load_more:
            self.current_skip = 0
            self.is_searching = False
            self.search_entry.delete(0, "end")
            self.sync_btn.configure(state="disabled", text="Syncing...")
            for w in self.list_pane.winfo_children(): w.destroy()
            ctk.CTkLabel(self.list_pane, text="⏳ Syncing mailbox...", text_color=THEME["text_secondary"],
                         font=ctk.CTkFont(size=14)).pack(pady=50)
        else:
            self.current_skip += 20
            for w in self.list_pane.winfo_children():
                if isinstance(w, ctk.CTkButton) and "Load More" in w.cget("text"):
                    w.destroy()

        threading.Thread(target=self._bg_load, args=(is_load_more,), daemon=True).start()

    def _bg_load(self, is_load_more: bool):
        try:
            folders = self.backend.fetch_mail_folders() if not is_load_more else None

            target_folder = self.current_folder_id
            if not target_folder and folders:
                for fname, info in folders.items():
                    if fname == "Inbox": target_folder = info.get("id")

            emails = self.backend.fetch_messages_in_folder(target_folder or "inbox", limit=20, skip=self.current_skip)
            self.after(0, lambda: self.render_ui(folders, emails, is_load_more))
        except Exception as e:
            self.after(0, lambda err=str(e): self._show_error_ui(err))

    def render_ui(self, folders: Optional[dict], emails: List[EmailMessage], is_load_more: bool):
        self.sync_btn.configure(state="normal", text="🔄 Refresh")

        if folders:
            self.folder_map.clear()
            tab_values = []
            target_tab = None

            priority = {"Inbox": 0, "Drafts": 1, "Sent Items": 2, "Archive": 3, "Deleted Items": 4}
            sorted_folders = sorted(folders.items(), key=lambda x: priority.get(x[0], 99))

            for fname, info in sorted_folders:
                if fname not in priority: continue

                fid = info.get("id")
                count = info.get("unread", 0)
                display_text = f"{fname} ({count})" if count > 0 else fname

                tab_values.append(display_text)
                self.folder_map[display_text] = fid

                if fid == self.current_folder_id or (not self.current_folder_id and fname == "Inbox"):
                    target_tab = display_text
                    self.current_folder_id = fid

            if tab_values:
                self.tab_selector.configure(values=tab_values)
                if target_tab:
                    self.tab_selector.set(target_tab)

        if not is_load_more:
            self.email_cards.clear()
            for w in self.list_pane.winfo_children(): w.destroy()

        if not emails and not is_load_more:
            ctk.CTkLabel(self.list_pane, text="This folder is empty.", text_color=THEME["text_secondary"],
                         font=ctk.CTkFont(size=14)).pack(pady=50)
            return

        for msg in emails:
            self._create_email_card(msg)

        if emails and len(emails) >= 20 and not self.is_searching:
            btn_load = ctk.CTkButton(self.list_pane, text="⏬ Load More", height=40, fg_color=THEME["card_bg"],
                                     hover_color=THEME["card_hover"], border_width=1, border_color=THEME["border"],
                                     text_color=THEME["accent_indigo"], font=ctk.CTkFont(weight="bold"),
                                     command=lambda: self.load_data(is_load_more=True))
            btn_load.pack(fill="x", padx=10, pady=15)

    def _on_tab_changed(self, selected_val: str):
        fid = self.folder_map.get(selected_val)
        if fid and fid != self.current_folder_id:
            self.current_folder_id = fid
            self.load_data(is_load_more=False)

    def _create_email_card(self, msg: EmailMessage):
        card = ctk.CTkFrame(self.list_pane, fg_color=THEME["card_bg"], corner_radius=10, border_width=1,
                            border_color=THEME["border"], cursor="hand2")
        card.pack(fill="x", padx=5, pady=4, ipady=4)

        self.email_cards.append({"id": msg.id, "widget": card})

        def _hover_enter(e, c=card):
            if c.cget("border_color") != THEME["accent_indigo"]:
                c.configure(fg_color=THEME["card_hover"], border_color=THEME["border_hover"])

        def _hover_leave(e, c=card):
            if c.cget("border_color") != THEME["accent_indigo"]:
                c.configure(fg_color=THEME["card_bg"], border_color=THEME["border"])

        font_weight = "normal" if msg.is_read else "bold"
        subj_color = THEME["text_primary"] if msg.is_read else THEME["accent_indigo"]
        subj_text = f"📎 {msg.subject}" if msg.has_attachments else msg.subject

        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=12, pady=10)

        hdr = ctk.CTkFrame(content, fg_color="transparent")
        hdr.pack(fill="x")
        lbl_sender = ctk.CTkLabel(hdr, text=msg.sender_name[:25], font=ctk.CTkFont(size=14, weight=font_weight),
                                  text_color=THEME["text_primary"] if msg.is_read else THEME["accent_indigo"],
                                  anchor="w")
        lbl_sender.pack(side="left")
        ctk.CTkLabel(hdr, text=msg.time[5:16], font=ctk.CTkFont(size=11), text_color=THEME["text_secondary"],
                     anchor="e").pack(side="right")

        lbl_subj = ctk.CTkLabel(content, text=subj_text[:40], font=ctk.CTkFont(size=13, weight=font_weight),
                                text_color=subj_color, anchor="w")
        lbl_subj.pack(fill="x", pady=(4, 2))
        ctk.CTkLabel(content, text=msg.preview[:60], font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"],
                     anchor="w").pack(fill="x")

        card.lbl_sender = lbl_sender
        card.lbl_subj = lbl_subj

        if not msg.is_read:
            dot = ctk.CTkFrame(card, fg_color=THEME["accent_indigo"], width=8, height=8, corner_radius=4)
            dot.place(x=8, y=20)
            card.dot = dot

        click_action = lambda e, m=msg, c=card: self.open_email(m, c)
        for child in content.winfo_children() + [hdr, content, card]:
            child.bind("<Button-1>", click_action)
            child.bind("<Enter>", _hover_enter)
            child.bind("<Leave>", _hover_leave)

    def open_email(self, msg: EmailMessage, card_widget=None):
        self.selected_message = msg

        # Highlight selected card
        for c_dict in self.email_cards:
            w = c_dict["widget"]
            is_active = (c_dict["id"] == msg.id)
            w.configure(fg_color=THEME["card_active"] if is_active else THEME["card_bg"],
                        border_color=THEME["accent_indigo"] if is_active else THEME["border"])

        for btn in self.reading_action_btns:
            btn.configure(state="normal")

        if not msg.is_read:
            threading.Thread(target=self.backend.mark_as_read, args=(msg.id,), daemon=True).start()
            msg.is_read = True
            if card_widget and hasattr(card_widget, "lbl_sender"):
                card_widget.lbl_sender.configure(font=ctk.CTkFont(size=14, weight="normal"),
                                                 text_color=THEME["text_primary"])
                card_widget.lbl_subj.configure(font=ctk.CTkFont(size=13, weight="normal"),
                                               text_color=THEME["text_primary"])
                if hasattr(card_widget, "dot"):
                    card_widget.dot.destroy()
                    delattr(card_widget, "dot")

        self.rp_meta_frame.pack(fill="x", side="bottom", padx=30, pady=(0, 20))
        self.rp_subject.configure(text=msg.subject)
        self.rp_sender_name.configure(text=msg.sender_name)
        self.rp_sender_email.configure(text=msg.sender_email)
        self.rp_date.configure(text=msg.time)
        self.rp_avatar.configure(
            text="".join([w[0] for w in msg.sender_name.split()[:2]]).upper() if msg.sender_name else "👤")

        # Attachments
        for child in self.rp_attachments_frame.winfo_children(): child.destroy()
        if msg.has_attachments:
            self.rp_attachments_frame.pack(fill="x", padx=30, pady=(0, 10))
            self.fetch_att_btn = ctk.CTkButton(self.rp_attachments_frame, text="📎 Fetch & View Attachments", height=32,
                                               fg_color=THEME["card_bg"], hover_color=THEME["border_hover"],
                                               border_width=1, border_color=THEME["border"],
                                               text_color=THEME["accent_indigo"], command=self.load_message_attachments)
            self.fetch_att_btn.pack(side="left", padx=5)
        else:
            self.rp_attachments_frame.pack_forget()

        # Body Text
        self.rp_body_box.configure(state="normal")
        self.rp_body_box.delete("1.0", "end")
        self.rp_body_box.insert("1.0", msg.body or "No content available.")
        self.rp_body_box.configure(state="disabled")

    def load_message_attachments(self):
        if not self.selected_message: return
        msg_id = self.selected_message.id
        self.fetch_att_btn.configure(text="⏳ Fetching metadata...", state="disabled")

        def bg_fetch():
            try:
                atts = self.backend.fetch_message_attachments(msg_id)
                self.after(0, lambda: self._render_attachment_chips(atts))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", f"Failed to load attachments: {e}"))
                self.after(0, lambda: self.fetch_att_btn.configure(text="📎 Fetch & View Attachments", state="normal"))

        threading.Thread(target=bg_fetch, daemon=True).start()

    def _render_attachment_chips(self, atts: List[AttachmentData]):
        self.fetch_att_btn.destroy()
        if not atts:
            ctk.CTkLabel(self.rp_attachments_frame, text="No downloadable files found.",
                         text_color=THEME["text_secondary"]).pack(side="left", padx=10)
            return

        for att in atts:
            chip = ctk.CTkFrame(self.rp_attachments_frame, fg_color=THEME["card_active"], corner_radius=6,
                                border_width=1, border_color=THEME["border"])
            chip.pack(side="left", padx=5)

            size_kb = max(1, att.size // 1024)
            ctk.CTkLabel(chip, text=f"📎 {att.name} ({size_kb} KB)", font=ctk.CTkFont(size=12),
                         text_color=THEME["text_primary"]).pack(side="left", padx=(10, 5), pady=6)

            download_btn = ctk.CTkButton(chip, text="Download & Open", width=110, height=24,
                                         fg_color=THEME["accent_indigo"], hover_color=THEME["accent_hover"],
                                         text_color=THEME["text_primary"], font=ctk.CTkFont(size=11, weight="bold"),
                                         command=lambda a=att: self._download_and_open_file(a))
            download_btn.pack(side="left", padx=(5, 10), pady=6)

    def _download_and_open_file(self, att: AttachmentData):
        temp_dir = tempfile.gettempdir()
        safe_name = "".join(c for c in att.name if c.isalnum() or c in (' ', '.', '_', '-')).strip()
        save_path = os.path.join(temp_dir, safe_name)

        def bg_download():
            try:
                success = self.backend.download_specific_attachment(self.selected_message.id, att.id, save_path)
                if success:
                    os.startfile(save_path)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Download Error", str(e)))

        threading.Thread(target=bg_download, daemon=True).start()

    def execute_message_action(self, action_type: str):
        if not self.selected_message: return
        msg_id = self.selected_message.id

        for btn in self.reading_action_btns: btn.configure(state="disabled")

        def _bg_action():
            try:
                if action_type == "delete":
                    self.backend.delete_email(msg_id)
                elif action_type == "archive":
                    self.backend.archive_email(msg_id)
                elif action_type == "unread":
                    self.backend.mark_as_read(msg_id, False)

                self.after(0, lambda: self.load_data(is_load_more=False))
                self.after(0, self._reset_reading_pane)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Action Failed", str(e)))
                self.after(0, lambda: [b.configure(state="normal") for b in self.reading_action_btns])

        threading.Thread(target=_bg_action, daemon=True).start()

    def _reset_reading_pane(self):
        self.selected_message = None
        self.rp_subject.configure(text="Select an email to read")
        self.rp_meta_frame.pack_forget()
        self.rp_attachments_frame.pack_forget()
        self.rp_body_box.configure(state="normal")
        self.rp_body_box.delete("1.0", "end")
        self.rp_body_box.configure(state="disabled")
        for btn in self.reading_action_btns: btn.configure(state="disabled")

    def execute_search(self, event=None):
        query = self.search_entry.get().strip()
        if not query:
            self.load_data(is_load_more=False)
            return

        self.is_searching = True
        self.sync_btn.configure(state="disabled")
        for w in self.list_pane.winfo_children(): w.destroy()
        ctk.CTkLabel(self.list_pane, text=f"🔍 Searching for '{query}'...", text_color=THEME["text_secondary"],
                     font=ctk.CTkFont(size=14)).pack(pady=50)

        def _bg_search():
            try:
                results = self.backend.search_emails(query)
                self.after(0, lambda: self.render_ui(folders=None, emails=results, is_load_more=False))
            except Exception as e:
                self.after(0, lambda: self._show_error_ui(str(e)))
            finally:
                self.after(0, lambda: self.sync_btn.configure(state="normal"))

        threading.Thread(target=_bg_search, daemon=True).start()