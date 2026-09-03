import threading
import customtkinter as ctk
from outlook_backend import SimpleOutlookBackend


class OutlookViewFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        self.backend = SimpleOutlookBackend()

        # --- UI Header ---
        self.header = ctk.CTkLabel(
            self,
            text="Inbox - Recent Emails",
            font=ctk.CTkFont(size=22, weight="bold")
        )
        self.header.pack(pady=(20, 10), padx=20, anchor="w")

        # --- Scrollable Container ---
        self.scroll_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # --- Loading State ---
        self.loading_lbl = ctk.CTkLabel(
            self.scroll_frame,
            text="⏳ Authenticating & fetching emails...\n(This takes ~5-10 seconds to securely intercept the token)",
            text_color="#A0A0A0",
            font=ctk.CTkFont(size=14)
        )
        self.loading_lbl.pack(pady=60)

        # Start fetch in a background thread so UI doesn't freeze
        threading.Thread(target=self.load_emails_in_background, daemon=True).start()

    def load_emails_in_background(self):
        try:
            emails = self.backend.fetch_recent_emails(limit=15)
            # Send data back to the main GUI thread safely
            self.after(0, lambda: self.render_email_cards(emails))
        except Exception as e:
            self.after(0, lambda: self.show_error(str(e)))

    def render_email_cards(self, emails):
        # Remove loading label
        self.loading_lbl.destroy()

        if not emails:
            ctk.CTkLabel(self.scroll_frame, text="No emails found in your inbox.").pack(pady=20)
            return

        # Create a visual card for each email
        for msg in emails:
            card = ctk.CTkFrame(self.scroll_frame, fg_color="#252526", corner_radius=8)
            card.pack(fill="x", padx=10, pady=6)

            # Extract data safely (handling both Graph and REST API key casing)
            subject = msg.get("subject") or msg.get("Subject") or "(No Subject)"
            sender_obj = (msg.get("sender") or msg.get("Sender") or {}).get("emailAddress") or {}
            sender_name = sender_obj.get("name") or sender_obj.get("Name") or "Unknown Sender"
            date_str = (msg.get("receivedDateTime") or msg.get("ReceivedDateTime") or "")[:10]

            # Clean up preview text
            preview = (msg.get("bodyPreview") or msg.get("BodyPreview") or "").replace("\n", " ")
            preview = preview[:90] + "..." if len(preview) > 90 else preview

            # --- Card Layout ---
            top_row = ctk.CTkFrame(card, fg_color="transparent")
            top_row.pack(fill="x", padx=15, pady=(10, 2))

            ctk.CTkLabel(top_row, text=sender_name, font=ctk.CTkFont(size=14, weight="bold"),
                         text_color="#FFFFFF").pack(side="left")
            ctk.CTkLabel(top_row, text=date_str, text_color="#888888", font=ctk.CTkFont(size=12)).pack(side="right")

            ctk.CTkLabel(card, text=subject, font=ctk.CTkFont(size=13), text_color="#0078D4", anchor="w").pack(fill="x",
                                                                                                               padx=15,
                                                                                                               pady=(2,
                                                                                                                     0))
            ctk.CTkLabel(card, text=preview, font=ctk.CTkFont(size=12), text_color="#A0A0A0", anchor="w").pack(fill="x",
                                                                                                               padx=15,
                                                                                                               pady=(2,
                                                                                                                     12))

    def show_error(self, err_msg):
        self.loading_lbl.configure(
            text=f"⚠️ Failed to fetch emails:\n{err_msg}",
            text_color="#F44336"
        )
