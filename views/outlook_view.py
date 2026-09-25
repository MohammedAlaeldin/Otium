import os
import threading
import tempfile
import sys
import re
import json
import ssl
from tkinter import filedialog, messagebox
from typing import List, Dict, Any, Optional
import customtkinter as ctk

try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass

# Requires: pip install tkinterweb
from tkinterweb import HtmlFrame

try:
    from PIL import Image
except ImportError:
    pass

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from outlook_backend import OutlookBackend

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
    "lock_red": "#EF4444"
}


class ComposeEmailModal(ctk.CTkToplevel):
    def __init__(self, master, backend_instance, reply_to=None):
        super().__init__(master)
        self.backend = backend_instance
        self.title("New Message - Outlook" if not reply_to else "Reply - Outlook")
        self.geometry("600x560")
        self.resizable(False, False)
        self.attributes('-topmost', True)
        self.configure(fg_color=THEME["bg_dark"])
        self.attachment_paths = []
        self._build_compose_ui(reply_to)

    def _build_compose_ui(self, reply_to):
        header = ctk.CTkFrame(self, height=50, fg_color=THEME["header_bg"], corner_radius=0)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        ctk.CTkLabel(header, text="New Message" if not reply_to else "Reply", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=THEME["text_primary"]).pack(side="left", padx=20, pady=10)

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=20, pady=15)

        ctk.CTkLabel(form, text="To:", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=THEME["text_secondary"]).pack(anchor="w", pady=(0, 2))
        self.to_entry = ctk.CTkEntry(form, placeholder_text="recipient@example.com", height=35,
                                     fg_color=THEME["card_bg"], border_color=THEME["border"],
                                     text_color=THEME["text_primary"])
        self.to_entry.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(form, text="Subject:", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=THEME["text_secondary"]).pack(anchor="w", pady=(0, 2))
        self.subject_entry = ctk.CTkEntry(form, placeholder_text="Add a subject", height=35, fg_color=THEME["card_bg"],
                                          border_color=THEME["border"], text_color=THEME["text_primary"])
        self.subject_entry.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(form, text="Message Body:", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=THEME["text_secondary"]).pack(anchor="w", pady=(0, 2))
        self.body_textbox = ctk.CTkTextbox(form, height=180, fg_color=THEME["card_bg"], border_color=THEME["border"],
                                           text_color=THEME["text_primary"], wrap="word")
        self.body_textbox.pack(fill="both", expand=True, pady=(0, 10))

        self.att_container = ctk.CTkScrollableFrame(form, height=45, orientation="horizontal", fg_color="transparent")
        self.att_container.pack(fill="x", pady=(0, 5))

        if reply_to:
            self.to_entry.insert(0, reply_to.get("sender_email", ""))
            subj = reply_to.get("subject", "")
            if not subj.lower().startswith("re:"):
                subj = "Re: " + subj
            self.subject_entry.insert(0, subj)

        footer = ctk.CTkFrame(self, height=60, fg_color=THEME["header_bg"], corner_radius=0)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        attach_btn = ctk.CTkButton(footer, text="📎 Attach Files", width=120, height=35, fg_color=THEME["card_bg"],
                                   hover_color=THEME["border_hover"], text_color=THEME["text_primary"],
                                   command=self._attach_files)
        attach_btn.pack(side="left", padx=20, pady=12)

        self.send_btn = ctk.CTkButton(footer, text="Send Email", width=120, height=35, fg_color=THEME["accent_indigo"],
                                      hover_color=THEME["accent_hover"], font=ctk.CTkFont(weight="bold"),
                                      command=self._handle_send)
        self.send_btn.pack(side="right", padx=20, pady=12)

    def _attach_files(self):
        self.attributes('-topmost', False)
        files = filedialog.askopenfilenames(title="Select Attachments to Send")
        if files:
            for f in files:
                if f not in self.attachment_paths:
                    self.attachment_paths.append(f)
                    self._render_attachment_chip(f)
        self.attributes('-topmost', True)

    def _render_attachment_chip(self, file_path):
        chip = ctk.CTkFrame(self.att_container, fg_color=THEME["header_bg"], corner_radius=6,
                            border_color=THEME["border"], border_width=1)
        chip.pack(side="left", padx=5)

        filename = os.path.basename(file_path)
        ctk.CTkLabel(chip, text=f"📎 {filename}", font=ctk.CTkFont(size=11), text_color=THEME["text_primary"]).pack(
            side="left", padx=(10, 5), pady=4)

        del_btn = ctk.CTkButton(chip, text="✖", width=24, height=24, fg_color="transparent",
                                hover_color=THEME["lock_red"], text_color=THEME["text_secondary"],
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

        if not to_addr or not subject:
            messagebox.showwarning("Validation Error", "Please fill in a recipient and subject.")
            return

        self.send_btn.configure(state="disabled", text="Sending...")

        def bg_send():
            try:
                self.backend.send_email(to_addr, subject, body, self.attachment_paths)
                self.after(0, self.destroy)
                self.after(0, lambda: messagebox.showinfo("Success", "Email sent successfully!"))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Send Error", str(e)))
                self.after(0, lambda: self.send_btn.configure(state="normal", text="Send Email"))

        threading.Thread(target=bg_send, daemon=True).start()


class OutlookView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=THEME["bg_dark"], **kwargs)
        self.backend = OutlookBackend()

        self.raw_folders_map: Dict[str, Dict[str, Any]] = {}
        self.folder_display_to_raw: Dict[str, str] = {}
        self.current_folder_name = "Inbox"
        self.current_skip = 0
        self.selected_message = None

        self.settings_file = os.path.join(tempfile.gettempdir(), "outlook_config.json")
        self.list_width = self._load_settings()
        self.list_pane_visible = True
        self._resize_timer = None

        self._build_main_layout()
        self.load_folders_and_data()

    def _load_settings(self):
        try:
            with open(self.settings_file, "r") as f:
                return json.load(f).get("list_width", 380)
        except Exception:
            return 380

    def _save_settings(self, event=None):
        try:
            with open(self.settings_file, "w") as f:
                json.dump({"list_width": self.list_width}, f)
        except Exception:
            pass

    def _build_main_layout(self):
        self.ribbon = ctk.CTkFrame(self, height=70, fg_color=THEME["header_bg"], corner_radius=0)
        self.ribbon.pack(fill="x", side="top")
        self.ribbon.pack_propagate(False)

        top_left = ctk.CTkFrame(self.ribbon, fg_color="transparent")
        top_left.pack(side="left", fill="y", padx=15, pady=15)

        ctk.CTkLabel(top_left, text="Outlook", font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=THEME["text_primary"]).pack(side="left", padx=(0, 20))
        self.compose_btn = ctk.CTkButton(top_left, text="✏️ Compose", width=110, fg_color=THEME["accent_indigo"],
                                         hover_color=THEME["accent_hover"], font=ctk.CTkFont(weight="bold"),
                                         command=lambda: ComposeEmailModal(self, self.backend))
        self.compose_btn.pack(side="left", padx=5)

        top_right = ctk.CTkFrame(self.ribbon, fg_color="transparent")
        top_right.pack(side="right", fill="y", padx=15, pady=10)

        self.sync_btn = ctk.CTkButton(top_right, text="↻ Refresh", width=110, fg_color=THEME["card_bg"],
                                      hover_color=THEME["border_hover"], text_color=THEME["text_primary"],
                                      border_width=1, border_color=THEME["border"],
                                      command=lambda: self.load_data(False))
        self.sync_btn.grid(row=0, column=1, padx=(10, 0), rowspan=2)

        self.search_entry = ctk.CTkEntry(top_right,
                                         placeholder_text="Search... (Try 'from:name' or 'received:last week')",
                                         width=280,
                                         fg_color=THEME["bg_dark"], border_color=THEME["border"],
                                         text_color=THEME["text_primary"])
        self.search_entry.grid(row=0, column=0)
        self.search_entry.bind("<Return>", self.execute_search)

        # TAB BAR
        tab_frame = ctk.CTkFrame(self, fg_color=THEME["header_bg"], corner_radius=0)
        tab_frame.pack(fill="x", side="top")

        self.toggle_list_btn = ctk.CTkButton(tab_frame, text="◀", width=36, height=32,
                                             font=ctk.CTkFont(size=14, weight="bold"), fg_color=THEME["card_bg"],
                                             hover_color=THEME["border_hover"], text_color=THEME["text_primary"],
                                             command=self.toggle_list_pane)
        self.toggle_list_btn.pack(side="left", padx=(15, 8), pady=(0, 12))

        self.folder_tabs = ctk.CTkSegmentedButton(tab_frame, values=["Inbox"], command=self.switch_folder,
                                                  selected_color=THEME["accent_indigo"],
                                                  selected_hover_color=THEME["accent_hover"],
                                                  unselected_color=THEME["card_bg"],
                                                  unselected_hover_color=THEME["header_bg"],
                                                  text_color=THEME["text_primary"])
        self.folder_tabs.pack(side="left", padx=(0, 20), pady=(0, 12))

        # MAIN SPLIT CONTAINER
        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=15, pady=10)

        # RESIZABLE LIST PANE
        self.list_pane_container = ctk.CTkFrame(self.container, fg_color="transparent", width=self.list_width)
        self.list_pane_container.pack(side="left", fill="y", padx=(0, 0))
        self.list_pane_container.pack_propagate(False)

        self.list_pane = ctk.CTkScrollableFrame(self.list_pane_container, fg_color=THEME["header_bg"], corner_radius=10,
                                                scrollbar_button_color=THEME["border"],
                                                scrollbar_button_hover_color=THEME["border_hover"])
        self.list_pane.pack(fill="both", expand=True)

        self.drag_handle = ctk.CTkFrame(self.container, width=6, fg_color="transparent", cursor="sb_h_double_arrow")
        self.drag_handle.pack(side="left", fill="y", padx=2)
        self.drag_handle.bind("<B1-Motion>", self._on_drag_motion)
        self.drag_handle.bind("<ButtonRelease-1>", self._save_settings)
        self.drag_handle.bind("<Enter>", lambda e: self.drag_handle.configure(fg_color=THEME["accent_indigo"]))
        self.drag_handle.bind("<Leave>", lambda e: self.drag_handle.configure(fg_color="transparent"))

        # READING PANE
        self.reading_pane_container = ctk.CTkFrame(self.container, fg_color=THEME["card_bg"], corner_radius=10,
                                                   border_width=1, border_color=THEME["border"])
        self.reading_pane_container.pack(side="left", fill="both", expand=True)

        self.reading_pane_scroll = ctk.CTkScrollableFrame(self.reading_pane_container, fg_color="transparent",
                                                          scrollbar_button_color=THEME["border"],
                                                          scrollbar_button_hover_color=THEME["border_hover"])
        self.reading_pane_scroll.pack(fill="both", expand=True, padx=15, pady=15)

        self.rp_subject = ctk.CTkLabel(self.reading_pane_scroll, text="Select an email to read",
                                       font=ctk.CTkFont(size=22, weight="bold"), text_color=THEME["text_primary"],
                                       anchor="w", wraplength=700)
        self.rp_subject.pack(fill="x", padx=15, pady=(10, 15))

        self.thread_container = ctk.CTkFrame(self.reading_pane_scroll, fg_color="transparent")
        self.thread_container.pack(fill="both", expand=True)

    def _on_drag_motion(self, event):
        self._pending_x = event.x_root
        if self._resize_timer is None:
            self._resize_timer = self.after(20, self._apply_resize)

    def _apply_resize(self):
        self._resize_timer = None
        if hasattr(self, "_pending_x"):
            new_width = self._pending_x - self.list_pane_container.winfo_rootx()
            new_width = max(220, min(new_width, 750))
            self.list_pane_container.configure(width=new_width)
            self.list_width = new_width

    def toggle_list_pane(self):
        if self.list_pane_visible:
            self.list_pane_container.pack_forget()
            self.drag_handle.pack_forget()
            self.toggle_list_btn.configure(text="▶")
            self.list_pane_visible = False
        else:
            self.list_pane_container.pack(side="left", fill="y", padx=(0, 0), before=self.reading_pane_container)
            self.drag_handle.pack(side="left", fill="y", padx=2, before=self.reading_pane_container)
            self.toggle_list_btn.configure(text="◀")
            self.list_pane_visible = True

    def _show_error_ui(self, error_msg):
        for w in self.list_pane.winfo_children(): w.destroy()
        ctk.CTkLabel(self.list_pane, text=f"⚠️ Connection Error:\n\n{error_msg}", text_color=THEME["lock_red"],
                     wraplength=280).pack(pady=40)
        self.sync_btn.configure(state="normal", text="↻ Refresh")

    def load_folders_and_data(self):
        self.sync_btn.configure(state="disabled", text="Syncing...")
        for w in self.list_pane.winfo_children(): w.destroy()
        ctk.CTkLabel(self.list_pane, text="⏳ Syncing folders & mail...", text_color=THEME["text_secondary"]).pack(
            pady=40)

        def _bg():
            try:
                folders = self.backend.fetch_mail_folders()
                self.after(0, lambda: self._apply_folders(folders))
            except Exception as e:
                self.after(0, lambda err=str(e): self._show_error_ui(err))

        threading.Thread(target=_bg, daemon=True).start()

    def _apply_folders(self, raw_folders):
        self.raw_folders_map = raw_folders
        self.folder_display_to_raw = {}

        rename_map = {
            "Sent Items": "Sent",
            "Deleted Items": "Deleted"
        }

        # Junk Email is blacklisted so it never displays as a tab
        blacklist = ["Conversation History", "Outbox", "Junk Email"]
        valid_folders = {k: v for k, v in raw_folders.items() if k not in blacklist}
        priority_raw = ["Inbox", "Sent Items", "Drafts", "Deleted Items", "Archive"]

        tabs = []
        for p in priority_raw:
            if p in valid_folders:
                display_name = rename_map.get(p, p)
                tabs.append(display_name)
                self.folder_display_to_raw[display_name] = p

        for raw_name in valid_folders:
            display_name = rename_map.get(raw_name, raw_name)
            if display_name not in tabs and len(tabs) < 7:
                tabs.append(display_name)
                self.folder_display_to_raw[display_name] = raw_name

        if tabs:
            self.folder_tabs.configure(values=tabs)
            if self.current_folder_name not in tabs:
                self.current_folder_name = tabs[0]
            self.folder_tabs.set(self.current_folder_name)

        self.load_data(is_load_more=False)

    def load_data(self, is_load_more=False):
        if not is_load_more:
            self.current_skip = 0
            self.sync_btn.configure(state="disabled", text="Syncing...")
            for w in self.list_pane.winfo_children(): w.destroy()
            ctk.CTkLabel(self.list_pane, text="⏳ Syncing mailbox...", text_color=THEME["text_secondary"]).pack(pady=40)
        else:
            self.current_skip += 20
            for w in self.list_pane.winfo_children():
                if isinstance(w, ctk.CTkButton) and "Load More" in w.cget("text"): w.destroy()

        raw_name = self.folder_display_to_raw.get(self.current_folder_name, "Inbox")
        folder_id = self.raw_folders_map.get(raw_name, {}).get("id", "inbox")

        def _bg_load():
            try:
                emails = self.backend.fetch_messages_in_folder(folder_id, limit=20, skip=self.current_skip)
                self.after(0, lambda: self.render_ui(emails, is_load_more))
            except Exception as e:
                self.after(0, lambda err=str(e): self._show_error_ui(err))

        threading.Thread(target=_bg_load, daemon=True).start()

    def render_ui(self, emails, is_load_more):
        self.sync_btn.configure(state="normal", text="↻ Refresh")

        if not is_load_more:
            for w in self.list_pane.winfo_children(): w.destroy()

        if not emails and not is_load_more:
            ctk.CTkLabel(self.list_pane, text="This folder is empty.", text_color=THEME["text_secondary"]).pack(pady=40)
            return

        for msg in emails:
            self._create_email_card(msg)

        if emails and len(emails) >= 20:
            btn_load = ctk.CTkButton(self.list_pane, text="⏬ Load More", fg_color=THEME["card_bg"],
                                     hover_color=THEME["border_hover"], text_color=THEME["accent_indigo"],
                                     command=lambda: self.load_data(is_load_more=True))
            btn_load.pack(pady=15)

    def _create_email_card(self, msg):
        is_read = msg.get("is_read", True)

        b_color = THEME["accent_indigo"] if not is_read else THEME["border"]
        b_width = 2 if not is_read else 1

        card = ctk.CTkFrame(self.list_pane, fg_color=THEME["card_bg"], corner_radius=8, cursor="hand2",
                            border_width=b_width, border_color=b_color)
        card.pack(fill="x", padx=10, pady=5, ipady=4)

        def _on_enter(e, c=card):
            c.configure(fg_color=THEME["border_hover"])

        def _on_leave(e, c=card):
            c.configure(fg_color=THEME["card_bg"])

        card.bind("<Enter>", _on_enter)
        card.bind("<Leave>", _on_leave)

        sender = msg.get("sender_name", "Unknown")
        subj = msg.get("subject", "(No Subject)")
        if msg.get("has_attachments", False): subj = f"📎 {subj}"
        preview = msg.get("preview", "").replace("\n", " ")[:45] + "..."

        font_weight = "normal" if is_read else "bold"
        subj_color = THEME["text_secondary"] if is_read else THEME["accent_indigo"]

        lbl_sender = ctk.CTkLabel(card, text=sender, font=ctk.CTkFont(size=13, weight=font_weight),
                                  text_color=THEME["text_primary"], anchor="w")
        lbl_sender.pack(fill="x", padx=10, pady=(4, 0))

        lbl_subj = ctk.CTkLabel(card, text=subj, font=ctk.CTkFont(size=12, weight=font_weight), text_color=subj_color,
                                anchor="w")
        lbl_subj.pack(fill="x", padx=10)

        lbl_preview = ctk.CTkLabel(card, text=preview, font=ctk.CTkFont(size=11), text_color=THEME["text_secondary"],
                                   anchor="w")
        lbl_preview.pack(fill="x", padx=10, pady=(0, 4))

        for child in [lbl_sender, lbl_subj, lbl_preview]:
            child.bind("<Enter>", _on_enter)
            child.bind("<Leave>", _on_leave)
            child.bind("<Button-1>", lambda e, m=msg, c=card: self.open_email(m, c))
        card.bind("<Button-1>", lambda e, m=msg, c=card: self.open_email(m, c))

    def switch_folder(self, display_name):
        self.current_folder_name = display_name
        self.load_data(is_load_more=False)

    def open_email(self, msg, card_widget=None):
        self.selected_message = msg

        if card_widget:
            card_widget.configure(border_color=THEME["border"], border_width=1)
            for child in card_widget.winfo_children():
                if child.cget("font").cget("weight") == "bold":
                    child.configure(font=ctk.CTkFont(size=child.cget("font").cget("size"), weight="normal"))
                if child.cget("text_color") == THEME["accent_indigo"]:
                    child.configure(text_color=THEME["text_secondary"])

        if not msg.get("is_read", True):
            threading.Thread(target=self.backend.mark_as_read, args=(msg.get("id"),), daemon=True).start()

        self.rp_subject.configure(text=msg.get("subject", "(No Subject)"))
        self.render_email_thread(msg)

    def render_email_thread(self, root_msg):
        for w in self.thread_container.winfo_children(): w.destroy()

        full_html = root_msg.get("body", "")

        separator_pattern = r'(?i)(<hr[^>]*tabindex="-1"[^>]*>|<div[^>]*id="divRplyFwdMsg"[^>]*>|<div[^>]*style="[^"]*border-top:solid\s+#B5C4DF[^"]*"[^>]*>|_{20,})'
        raw_parts = re.split(separator_pattern, full_html)

        blocks = [raw_parts[0]]
        for i in range(1, len(raw_parts), 2):
            blocks.append(raw_parts[i] + raw_parts[i + 1])

        blocks.reverse()

        for idx, html_block in enumerate(blocks):
            if not html_block.strip() or len(html_block.strip()) < 5:
                continue

            plain_text = re.sub(r'<[^>]+>', ' ', html_block)
            plain_text = re.sub(r'\s+', ' ', plain_text)

            sender = root_msg.get("sender_name", "Unknown")
            date_str = root_msg.get("time", "")
            to_str = ", ".join(root_msg.get("to_recipients", [])) or "Undisclosed"

            match = re.search(r'(?:From|De):\s*(.*?)\s*(?:Sent|Date):\s*(.*?)\s*(?:To|A):\s*(.*?)\s*(?:Subject|Cc):',
                              plain_text, re.IGNORECASE)
            if match:
                sender = match.group(1).strip()
                date_str = match.group(2).strip()
                to_str = match.group(3).strip()

            is_latest_reply = (idx == len(blocks) - 1)

            self._build_single_message_card(
                sender_name=sender,
                sender_email=root_msg.get("sender_email", ""),
                date_str=date_str,
                to_str=to_str,
                body_html=html_block,
                msg_id=root_msg.get("id") if is_latest_reply else None,
                root_msg=root_msg
            )

    def _build_single_message_card(self, sender_name, sender_email, date_str, to_str, body_html, msg_id, root_msg):
        card = ctk.CTkFrame(self.thread_container, fg_color=THEME["header_bg"], border_width=1,
                            border_color=THEME["border"], corner_radius=10)
        card.pack(fill="x", pady=(0, 15))

        header_frame = ctk.CTkFrame(card, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(12, 8))

        avatar_initial = sender_name[0].upper() if sender_name else "👤"
        avatar = ctk.CTkLabel(header_frame, text=avatar_initial, width=40, height=40, corner_radius=20,
                              fg_color=THEME["accent_indigo"], text_color=THEME["text_primary"],
                              font=ctk.CTkFont(size=16, weight="bold"))
        avatar.pack(side="left", anchor="n")

        info_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        info_frame.pack(side="left", fill="x", expand=True, padx=12)

        ctk.CTkLabel(info_frame, text=sender_name, font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=THEME["text_primary"], anchor="w").pack(anchor="w")
        ctk.CTkLabel(info_frame, text=f"To: {to_str[:70]}", font=ctk.CTkFont(size=11), text_color=THEME["text_muted"],
                     anchor="w").pack(anchor="w")

        right_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        right_frame.pack(side="right", anchor="n")

        ctk.CTkLabel(right_frame, text=date_str, font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=THEME["text_primary"]).pack(
            anchor="e", pady=(0, 4))

        reply_data = dict(root_msg)
        reply_data["sender_name"] = sender_name
        reply_data["sender_email"] = sender_email or root_msg.get("sender_email")

        ctk.CTkButton(right_frame, text="↩ Reply", fg_color=THEME["card_bg"], hover_color=THEME["border_hover"],
                      text_color=THEME["text_primary"], width=75, height=26, font=ctk.CTkFont(size=12),
                      command=lambda m=reply_data: ComposeEmailModal(self, self.backend, reply_to=m)).pack(anchor="e")

        ctk.CTkFrame(card, height=1, fg_color=THEME["border"]).pack(fill="x", padx=15, pady=4)

        # Force attachment fetching for the main email regardless of 'has_attachments' flag
        if msg_id:
            att_frame = ctk.CTkFrame(card, fg_color="transparent")
            att_frame.pack(fill="x", padx=15, pady=5)
            self.load_attachments_ui(msg_id, att_frame)

        # Aggressively rip out hardcoded white/bright backgrounds
        safe_html = re.sub(r'(?i)bgcolor\s*=\s*["\']?[^"\'>\s]+["\']?', '', body_html)
        safe_html = re.sub(r'(?i)background\s*=\s*["\']?[^"\'>\s]+["\']?', '', safe_html)

        text_len = len(re.sub(r'<[^>]+>', '', body_html))
        br_count = body_html.lower().count('<br') + body_html.lower().count('<p')
        estimated_lines = (text_len // 80) + br_count
        calc_height = max(120, min(estimated_lines * 22 + 50, 650))

        html_container = ctk.CTkFrame(card, height=calc_height)
        html_container.pack(fill="both", expand=True, padx=15, pady=(5, 12))
        html_container.pack_propagate(False)

        box = HtmlFrame(html_container, messages_enabled=False)
        box.pack(fill="both", expand=True)

        injected_css_and_html = f"""
        <html>
        <head>
        <style>
            * {{
                background-color: transparent !important;
                color: {THEME["text_primary"]} !important;
            }}
            body {{
                background-color: {THEME["header_bg"]} !important;
                font-family: 'Segoe UI', sans-serif;
                font-size: 14px;
                margin: 0; padding: 10px;
            }}
            a, a * {{ color: {THEME["accent_indigo"]} !important; text-decoration: none !important; }}
            a:hover {{ text-decoration: underline !important; }}
            img {{ 
                max-width: 100% !important; 
                height: auto !important; 
                display: block; 
            }}
            blockquote {{ 
                border-left: 3px solid {THEME["accent_indigo"]}; 
                margin: 10px 0; 
                padding-left: 10px; 
                color: {THEME["text_secondary"]} !important; 
            }}
            table, td, tr, th, tbody, thead {{ 
                border-collapse: collapse; 
                background: transparent !important; 
                border: none !important; 
            }}
        </style>
        </head>
        <body>
        {safe_html}
        </body>
        </html>
        """
        box.load_html(injected_css_and_html)

    def load_attachments_ui(self, msg_id, parent_frame):
        lbl = ctk.CTkLabel(parent_frame, text="⏳ Checking for attachments...", text_color=THEME["text_secondary"])
        lbl.pack(pady=2, anchor="w")

        def bg_fetch():
            try:
                atts = self.backend.fetch_attachments_metadata(msg_id)
                self.after(0, lambda: self.render_attachments_metadata(msg_id, atts, lbl, parent_frame))
            except Exception as e:
                self.after(0, lambda: lbl.configure(text=f"⚠️ Error: {e}", text_color=THEME["lock_red"]))

        threading.Thread(target=bg_fetch, daemon=True).start()

    def render_attachments_metadata(self, msg_id, atts, loading_lbl, parent_frame):
        loading_lbl.destroy()
        if not atts:
            return  # Silent if none exist

        ctk.CTkLabel(parent_frame, text=f"📎 {len(atts)} Attachment(s):", font=ctk.CTkFont(weight="bold", size=12),
                     text_color=THEME["text_primary"]).pack(anchor="w", pady=(0, 6))

        grid = ctk.CTkFrame(parent_frame, fg_color="transparent")
        grid.pack(fill="x")

        for idx, att in enumerate(atts):
            name = att.get("Name", "Unknown")
            size = att.get("Size", 0) // 1024
            att_id = att.get("Id")
            content_type = att.get("ContentType", "")

            card = ctk.CTkFrame(grid, fg_color=THEME["bg_dark"], border_color=THEME["border"], border_width=1,
                                corner_radius=6, width=170, height=70)
            card.grid(row=idx // 3, column=idx % 3, padx=4, pady=4, sticky="nsew")
            card.grid_propagate(False)

            btn = ctk.CTkButton(card, text=f"⬇️ {name[:14]}...\n{size} KB", fg_color="transparent",
                                hover_color=THEME["border_hover"], text_color=THEME["text_primary"],
                                command=lambda m=msg_id, a=att_id, n=name, ct=content_type,
                                               c=card: self.download_and_open_attachment(m, a, n, ct, c))
            btn.pack(expand=True, fill="both")

    def download_and_open_attachment(self, msg_id, att_id, name, content_type, card):
        for w in card.winfo_children(): w.destroy()
        ctk.CTkLabel(card, text="⏳ Fetching...", text_color=THEME["accent_indigo"]).pack(expand=True)

        def _bg():
            try:
                path = self.backend.download_single_attachment(msg_id, att_id, tempfile.gettempdir())
                self.after(0, lambda: self._show_attachment_preview(path, name, content_type, card))
            except Exception as e:
                self.after(0, lambda err=str(e): ctk.CTkLabel(card, text="⚠️ Error", text_color=THEME["lock_red"]).pack(
                    expand=True))

        threading.Thread(target=_bg, daemon=True).start()

    def _show_attachment_preview(self, path, name, content_type, card):
        for w in card.winfo_children(): w.destroy()
        is_image = content_type.startswith("image/") or name.lower().endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"))

        if is_image and path:
            try:
                img = Image.open(path)
                img.thumbnail((150, 60))
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
                lbl = ctk.CTkLabel(card, image=ctk_img, text="", cursor="hand2")
                lbl.pack(expand=True, pady=2)
                lbl.bind("<Button-1>", lambda e: os.startfile(path))
                return
            except Exception:
                pass

        ext = name.split(".")[-1].upper() if "." in name else "FILE"
        ctk.CTkButton(card, text=f"📄 {ext} File\nOpen {name[:8]}", fg_color="transparent",
                      hover_color=THEME["border_hover"], command=lambda: os.startfile(path)).pack(expand=True,
                                                                                                  fill="both")

    def execute_search(self, event=None):
        query = self.search_entry.get().strip()
        if not query:
            self.load_data(is_load_more=False)
            return

        self.sync_btn.configure(state="disabled")
        for w in self.list_pane.winfo_children(): w.destroy()
        ctk.CTkLabel(self.list_pane, text=f"🔍 Searching for '{query}'...", text_color=THEME["text_secondary"]).pack(
            pady=40)

        def _bg_search():
            try:
                results = self.backend.search_emails(query)
                self.after(0, lambda: self.render_ui(emails=results, is_load_more=False))
            except Exception as e:
                self.after(0, lambda err=str(e): self._show_error_ui(err))
            finally:
                self.after(0, lambda: self.sync_btn.configure(state="normal"))

        threading.Thread(target=_bg_search, daemon=True).start()