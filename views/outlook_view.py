import os
import threading
import tempfile
import sys
from tkinter import filedialog, messagebox
from typing import List, Dict, Any, Optional
import customtkinter as ctk

# Ensure the app can find outlook_backend in the parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from outlook_backend import OutlookBackend

OUTLOOK_BLUE = "#0078D4"
OUTLOOK_BLUE_HOVER = "#106EBE"
BG_DARK = "#1E1E1E"
BG_PANEL = "#252526"
BG_SIDEBAR = "#202020"
BG_CARD_HOVER = "#2A2A2A"
TEXT_WHITE = "#FFFFFF"
TEXT_GRAY = "#A0A0A0"


class ComposeEmailModal(ctk.CTkToplevel):
    def __init__(self, master, backend_instance):
        super().__init__(master)
        self.backend = backend_instance
        self.title("New Message - Outlook")
        self.geometry("600x560")
        self.resizable(False, False)
        self.attributes('-topmost', True)
        self.attachment_paths = []
        self._build_compose_ui()

    def _build_compose_ui(self):
        header = ctk.CTkFrame(self, height=50, fg_color=BG_PANEL, corner_radius=0)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        ctk.CTkLabel(header, text="New Message", font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT_WHITE).pack(side="left", padx=20, pady=10)

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=20, pady=15)

        ctk.CTkLabel(form, text="To:", font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT_GRAY).pack(anchor="w", pady=(0, 2))
        self.to_entry = ctk.CTkEntry(form, placeholder_text="recipient@mmu.edu.my", height=35, fg_color=BG_DARK, border_color="#333333")
        self.to_entry.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(form, text="Subject:", font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT_GRAY).pack(anchor="w", pady=(0, 2))
        self.subject_entry = ctk.CTkEntry(form, placeholder_text="Add a subject", height=35, fg_color=BG_DARK, border_color="#333333")
        self.subject_entry.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(form, text="Message Body:", font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT_GRAY).pack(anchor="w", pady=(0, 2))
        self.body_textbox = ctk.CTkTextbox(form, height=180, fg_color=BG_DARK, border_color="#333333", text_color=TEXT_WHITE, wrap="word")
        self.body_textbox.pack(fill="both", expand=True, pady=(0, 10))

        self.att_lbl = ctk.CTkLabel(form, text="No files attached", text_color=TEXT_GRAY, anchor="w")
        self.att_lbl.pack(fill="x", pady=(0, 5))

        footer = ctk.CTkFrame(self, height=60, fg_color=BG_PANEL, corner_radius=0)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        attach_btn = ctk.CTkButton(footer, text="📎 Attach Files", width=120, height=35, fg_color="#333333", hover_color="#444444", command=self._attach_files)
        attach_btn.pack(side="left", padx=20, pady=12)

        self.send_btn = ctk.CTkButton(footer, text="Send Email", width=120, height=35, fg_color=OUTLOOK_BLUE, hover_color=OUTLOOK_BLUE_HOVER, font=ctk.CTkFont(weight="bold"), command=self._handle_send)
        self.send_btn.pack(side="right", padx=20, pady=12)

    def _attach_files(self):
        self.attributes('-topmost', False)
        files = filedialog.askopenfilenames(title="Select Attachments to Send")
        if files:
            self.attachment_paths.extend(files)
            self.att_lbl.configure(text=f"📎 {len(self.attachment_paths)} file(s) attached ready to send.", text_color=OUTLOOK_BLUE)
        self.attributes('-topmost', True)

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
        super().__init__(master, **kwargs)
        self.backend = OutlookBackend()

        self.folders_map: Dict[str, Dict[str, Any]] = {}
        self.current_folder_id = "inbox"
        self.current_skip = 0
        self.selected_message = None

        self._build_main_layout()
        self.load_data()

    def _build_main_layout(self):
        self.ribbon = ctk.CTkFrame(self, height=55, fg_color=BG_PANEL, corner_radius=0)
        self.ribbon.pack(fill="x", side="top")
        self.ribbon.pack_propagate(False)

        ctk.CTkLabel(self.ribbon, text="Outlook", font=ctk.CTkFont(size=20, weight="bold"), text_color=TEXT_WHITE).pack(side="left", padx=20, pady=12)

        self.compose_btn = ctk.CTkButton(self.ribbon, text="+ New mail", width=110, height=32, fg_color=OUTLOOK_BLUE, hover_color=OUTLOOK_BLUE_HOVER, font=ctk.CTkFont(size=13, weight="bold"), command=lambda: ComposeEmailModal(self, self.backend))
        self.compose_btn.pack(side="left", padx=10, pady=12)

        self.delete_btn = ctk.CTkButton(self.ribbon, text="🗑 Delete", width=90, height=32, fg_color="#D32F2F", hover_color="#9A0007", state="disabled", command=self.delete_selected)
        self.delete_btn.pack(side="left", padx=5, pady=12)

        self.sync_btn = ctk.CTkButton(self.ribbon, text="↻ Refresh", width=110, height=32, fg_color="transparent", border_width=1, border_color="#555555", text_color=TEXT_WHITE, command=lambda: self.load_data(False))
        self.sync_btn.pack(side="right", padx=15, pady=12)

        self.search_entry = ctk.CTkEntry(self.ribbon, placeholder_text="🔍 Search emails...", width=260, height=32, fg_color=BG_DARK, border_color="#333333")
        self.search_entry.pack(side="right", padx=10, pady=12)
        self.search_entry.bind("<Return>", self.execute_search)

        container = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        container.pack(fill="both", expand=True)

        self.sidebar_pane = ctk.CTkScrollableFrame(container, width=200, fg_color=BG_SIDEBAR, corner_radius=0, label_text="Favorites", label_font=ctk.CTkFont(size=12, weight="bold"), label_fg_color=BG_SIDEBAR)
        self.sidebar_pane.pack(side="left", fill="y")

        self.list_pane = ctk.CTkScrollableFrame(container, width=350, fg_color=BG_PANEL, corner_radius=0)
        self.list_pane.pack(side="left", fill="y", padx=2)

        self.reading_pane = ctk.CTkFrame(container, fg_color=BG_DARK, corner_radius=0)
        self.reading_pane.pack(side="left", fill="both", expand=True)

        self._build_reading_pane_content()

    def _build_reading_pane_content(self):
        self.rp_subject = ctk.CTkLabel(self.reading_pane, text="Select an item to read", font=ctk.CTkFont(size=24, weight="bold"), text_color=TEXT_WHITE, anchor="w", wraplength=650)
        self.rp_subject.pack(fill="x", padx=30, pady=(30, 15))

        self.rp_meta_frame = ctk.CTkFrame(self.reading_pane, fg_color="transparent")

        self.rp_avatar = ctk.CTkButton(self.rp_meta_frame, text="👤", width=46, height=46, corner_radius=23, fg_color=OUTLOOK_BLUE, text_color=TEXT_WHITE, font=ctk.CTkFont(size=20))
        self.rp_avatar.pack(side="left")

        meta_text = ctk.CTkFrame(self.rp_meta_frame, fg_color="transparent")
        meta_text.pack(side="left", fill="x", expand=True, padx=15)
        self.rp_sender_name = ctk.CTkLabel(meta_text, text="", font=ctk.CTkFont(size=15, weight="bold"), text_color=TEXT_WHITE, anchor="w")
        self.rp_sender_name.pack(fill="x")
        self.rp_sender_email = ctk.CTkLabel(meta_text, text="", font=ctk.CTkFont(size=12), text_color=TEXT_GRAY, anchor="w")
        self.rp_sender_email.pack(fill="x")

        self.rp_date = ctk.CTkLabel(self.rp_meta_frame, text="", font=ctk.CTkFont(size=12), text_color=TEXT_GRAY)
        self.rp_date.pack(side="right", anchor="n")

        self.rp_attach_btn = ctk.CTkButton(self.reading_pane, text="🖼️ Open Images / Attachments", fg_color="#333333", hover_color="#444444", command=self.open_attachments)

        self.rp_body_box = ctk.CTkTextbox(self.reading_pane, state="disabled", fg_color="transparent", font=ctk.CTkFont(size=14), text_color="#E0E0E0", wrap="word")
        self.rp_body_box.pack(fill="both", expand=True, padx=25, pady=(10, 20))

    def _show_error_ui(self, error_msg):
        """Displays errors safely inside the UI instead of freezing or using popups."""
        for w in self.list_pane.winfo_children(): w.destroy()
        ctk.CTkLabel(self.list_pane, text=f"⚠️ Connection Error:\n\n{error_msg}", text_color="#D32F2F", wraplength=280).pack(pady=40)
        self.sync_btn.configure(state="normal", text="↻ Refresh")

    def load_data(self, is_load_more=False):
        if not is_load_more:
            self.current_skip = 0
            self.sync_btn.configure(state="disabled", text="Syncing...")
            for w in self.sidebar_pane.winfo_children() + self.list_pane.winfo_children():
                w.destroy()
            ctk.CTkLabel(self.list_pane, text="⏳ Syncing mailbox...", text_color=TEXT_GRAY).pack(pady=40)
        else:
            self.current_skip += 20
            for w in self.list_pane.winfo_children():
                if isinstance(w, ctk.CTkButton) and "Load More" in w.cget("text"):
                    w.destroy()

        threading.Thread(target=self._bg_load, args=(is_load_more,), daemon=True).start()

    def _bg_load(self, is_load_more):
        try:
            folders = self.backend.fetch_mail_folders() if not is_load_more else None
            emails = self.backend.fetch_messages_in_folder(self.current_folder_id, limit=20, skip=self.current_skip)
            self.after(0, lambda: self.render_ui(folders, emails, is_load_more))
        except Exception as e:
            # Safely route the crash to the UI instead of freezing
            self.after(0, lambda err=str(e): self._show_error_ui(err))

    def render_ui(self, folders, emails, is_load_more):
        self.sync_btn.configure(state="normal", text="↻ Refresh")

        if folders:
            for w in self.sidebar_pane.winfo_children(): w.destroy()
            for fname, info in folders.items():
                fid = info.get("id")
                count = info.get("unread", 0)
                display_text = f"📁 {fname} ({count})" if count > 0 else f"📁 {fname}"
                is_active = (fid == self.current_folder_id)

                btn = ctk.CTkButton(
                    self.sidebar_pane, text=display_text, anchor="w", height=35,
                    fg_color=OUTLOOK_BLUE if is_active else "transparent",
                    hover_color=OUTLOOK_BLUE_HOVER if is_active else BG_CARD_HOVER,
                    text_color=TEXT_WHITE, font=ctk.CTkFont(size=12, weight="bold" if is_active else "normal"),
                    command=lambda folder_id=fid: self.switch_folder(folder_id)
                )
                btn.pack(fill="x", padx=5, pady=2)

        if not is_load_more:
            for w in self.list_pane.winfo_children(): w.destroy()

        if not emails and not is_load_more:
            ctk.CTkLabel(self.list_pane, text="This folder is empty.", text_color=TEXT_GRAY).pack(pady=40)
            return

        for msg in emails:
            self._create_email_card(msg)

        if emails and len(emails) >= 20:
            btn_load = ctk.CTkButton(self.list_pane, text="⏬ Load More", fg_color=BG_PANEL, hover_color=BG_CARD_HOVER, text_color=OUTLOOK_BLUE, command=lambda: self.load_data(is_load_more=True))
            btn_load.pack(pady=15)

    def _create_email_card(self, msg):
        is_read = msg.get("is_read", True)
        card_bg = "transparent" if is_read else "#2D2D2D"

        card = ctk.CTkFrame(self.list_pane, fg_color=card_bg, corner_radius=6, cursor="hand2")
        card.pack(fill="x", padx=5, pady=2, ipady=4)

        card.bind("<Enter>", lambda e, c=card: c.configure(fg_color=BG_CARD_HOVER))
        card.bind("<Leave>", lambda e, c=card, r=is_read: c.configure(fg_color="transparent" if r else "#2D2D2D"))

        sender = msg.get("sender_name", "Unknown")
        subj = msg.get("subject", "(No Subject)")
        if msg.get("has_attachments", False): subj = f"📎 {subj}"
        preview = msg.get("preview", "").replace("\n", " ")[:45] + "..."

        font_weight = "normal" if is_read else "bold"
        subj_color = TEXT_GRAY if is_read else OUTLOOK_BLUE

        ctk.CTkLabel(card, text=sender, font=ctk.CTkFont(size=13, weight=font_weight), text_color=TEXT_WHITE, anchor="w").pack(fill="x", padx=10, pady=(4, 0))
        ctk.CTkLabel(card, text=subj, font=ctk.CTkFont(size=12, weight=font_weight), text_color=subj_color, anchor="w").pack(fill="x", padx=10)
        ctk.CTkLabel(card, text=preview, font=ctk.CTkFont(size=11), text_color=TEXT_GRAY, anchor="w").pack(fill="x", padx=10, pady=(0, 4))

        for child in card.winfo_children():
            child.bind("<Button-1>", lambda e, m=msg, c=card: self.open_email(m, c))
        card.bind("<Button-1>", lambda e, m=msg, c=card: self.open_email(m, c))

    def switch_folder(self, folder_id):
        self.current_folder_id = folder_id
        self.load_data(is_load_more=False)

    def open_email(self, msg, card_widget=None):
        self.selected_message = msg
        self.delete_btn.configure(state="normal")

        if card_widget:
            card_widget.configure(fg_color="transparent")
            card_widget.bind("<Leave>", lambda e, c=card_widget: c.configure(fg_color="transparent"))
            for child in card_widget.winfo_children():
                if child.cget("font").cget("weight") == "bold":
                    child.configure(font=ctk.CTkFont(size=child.cget("font").cget("size"), weight="normal"))

        if not msg.get("is_read", True):
            threading.Thread(target=self.backend.mark_as_read, args=(msg.get("id"),), daemon=True).start()

        sender_name = msg.get("sender_name", "Unknown")
        self.current_sender_email = msg.get("sender_email", "Unknown")

        self.rp_subject.configure(text=msg.get("subject", "(No Subject)"))
        self.rp_sender_name.configure(text=sender_name)
        self.rp_sender_email.configure(text=self.current_sender_email)
        self.rp_date.configure(text=msg.get("time", ""))
        self.rp_avatar.configure(text=sender_name[0].upper() if sender_name else "👤")

        if msg.get("has_attachments", False):
            self.rp_attach_btn.pack(anchor="w", padx=25, pady=(0, 10))
        else:
            self.rp_attach_btn.pack_forget()

        self.rp_body_box.configure(state="normal")
        self.rp_body_box.delete("1.0", "end")
        self.rp_body_box.insert("1.0", msg.get("body", msg.get("preview", "")))
        self.rp_body_box.configure(state="disabled")

    def open_attachments(self):
        if not self.selected_message: return
        msg_id = self.selected_message.get("id")
        temp_dir = tempfile.gettempdir()
        self.rp_attach_btn.configure(text="⏳ Downloading...", state="disabled")

        def _bg_open():
            try:
                files = self.backend.download_attachments(msg_id, temp_dir)
                for f in files: os.startfile(f)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", f"Could not open file: {e}"))
            finally:
                self.after(0, lambda: self.rp_attach_btn.configure(text="🖼️ Open Images / Attachments", state="normal"))

        threading.Thread(target=_bg_open, daemon=True).start()

    def delete_selected(self):
        if not self.selected_message: return
        msg_id = self.selected_message.get("id")
        self.delete_btn.configure(state="disabled", text="Deleting...")

        def _bg_delete():
            try:
                if self.backend.delete_email(msg_id):
                    self.after(0, lambda: self.load_data(is_load_more=False))
                    self.after(0, lambda: self.rp_subject.configure(text="Select an item to read"))
                    self.after(0, self.rp_attach_btn.pack_forget)
                    self.after(0, lambda: [self.rp_body_box.configure(state="normal"), self.rp_body_box.delete("1.0", "end"), self.rp_body_box.configure(state="disabled")])
                else:
                    self.after(0, lambda: messagebox.showerror("Error", "Backend deletion failed."))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", f"Failed to delete: {e}"))
            finally:
                self.after(0, lambda: self.delete_btn.configure(text="🗑 Delete", state="normal"))

        threading.Thread(target=_bg_delete, daemon=True).start()

    def execute_search(self, event=None):
        query = self.search_entry.get().strip()
        if not query:
            self.load_data(is_load_more=False)
            return

        self.sync_btn.configure(state="disabled")
        for w in self.list_pane.winfo_children(): w.destroy()
        ctk.CTkLabel(self.list_pane, text=f"🔍 Searching for '{query}'...", text_color=TEXT_GRAY).pack(pady=40)

        def _bg_search():
            try:
                results = self.backend.search_emails(query)
                self.after(0, lambda: self.render_ui(folders=None, emails=results, is_load_more=False))
            except Exception as e:
                self.after(0, lambda: self._show_error_ui(str(e)))
            finally:
                self.after(0, lambda: self.sync_btn.configure(state="normal"))

        threading.Thread(target=_bg_search, daemon=True).start()