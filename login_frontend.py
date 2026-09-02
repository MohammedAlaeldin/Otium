import sys
import os
import threading
import webbrowser
import customtkinter as ctk
import storage

# BACKEND IMPORT 
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
LOGIN_BACKEND_DIR = os.path.join(PARENT_DIR, "login_backend")

if LOGIN_BACKEND_DIR not in sys.path:
    sys.path.append(LOGIN_BACKEND_DIR)

try:
    import login_backend
except ImportError:
    print("⚠️ Warning: Could not locate login_backend.py automatically. Make sure the folder path is correct.")

# SETTING UP CUSTOMTKINTER APPEARANCE
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class OtiumLoginApp(ctk.CTkFrame):
    def __init__(self, master, on_success_callback=None, **kwargs):
        super().__init__(master, **kwargs)

        self.on_success_callback = on_success_callback

        # STATE VARIABLES
        self.totp_timer_job = None
        self.active_secret = ""

        # Tooltip animation variables
        self.is_tooltip_visible = False
        self.animation_job = None
        self.current_y = 0
        self.target_y = 0
        self.target_x = 0

        #  1. THE MAIN LOGIN CARD
        self.login_frame = ctk.CTkFrame(self, corner_radius=15, fg_color="#2b2b2b")
        self.login_frame.place(relx=0.5, rely=0.5, relwidth=0.48, relheight=0.75, anchor="center")

        #  2. TEXT ELEMENTS
        self.title_label = ctk.CTkLabel(
            self.login_frame,
            text="OTIUM",
            font=ctk.CTkFont(family="League Spartan", size=45, weight="bold"),
            text_color="#D4BE18"
        )
        self.title_label.pack(pady=(30, 5))

        self.motto_label = ctk.CTkLabel(
            self.login_frame,
            text="Your Academic Command Center",
            font=ctk.CTkFont(family="Helvetica", size=14, slant="italic"),
            text_color="#A9A9A9"
        )
        self.motto_label.pack(pady=(0, 20))

        # 3. INPUTS
        self.email_entry = ctk.CTkEntry(self.login_frame, placeholder_text="Student Email Address", height=45)
        self.email_entry.pack(pady=8, fill="x", padx=60)

        self.password_entry = ctk.CTkEntry(self.login_frame, placeholder_text="Password", show="*", height=45)
        self.password_entry.pack(pady=8, fill="x", padx=60)

        # 4. SECURE KEY & TOOLTIP
        self.key_frame = ctk.CTkFrame(self.login_frame, fg_color="transparent")
        self.key_frame.pack(pady=8, fill="x", padx=60)

        self.secure_key_entry = ctk.CTkEntry(self.key_frame, placeholder_text="Secure Secret Key", height=45)
        self.secure_key_entry.pack(side="left", fill="x", expand=True)

        self.info_icon = ctk.CTkLabel(self.key_frame, text=" ❓ ", width=40, height=40, cursor="hand2")
        self.info_icon.pack(side="left", padx=(5, 0))

        # Tooltip Box
        self.tooltip_box = ctk.CTkFrame(self, fg_color="#2b2b2b", border_width=1, border_color="gray", corner_radius=8)

        self.desc_text = ctk.CTkLabel(
            self.tooltip_box,
            text="Click this link to view a guide on how to obtain your 2FA Secret Key:",
            wraplength=230,
            justify="left"
        )
        self.desc_text.pack(padx=15, pady=(10, 0))

        self.link_text = ctk.CTkLabel(
            self.tooltip_box,
            text="GUIDE",
            text_color="#1f6aa5",
            font=ctk.CTkFont(underline=True),
            cursor="hand2"
        )
        self.link_text.pack(padx=15, pady=(0, 10))

        self.info_icon.bind("<Button-1>", self.toggle_tooltip)
        self.link_text.bind("<Button-1>", self.open_youtube_link)

        # Status label
        self.status_label = ctk.CTkLabel(
            self.login_frame,
            text="",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#E74C3C"
        )
        self.status_label.pack(pady=5)
        self.status_label.bind("<Button-1>", self.copy_code_to_clipboard)

        #  LOGIN BUTTON
        self.login_button = ctk.CTkButton(
            self.login_frame,
            text="Log In",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=45,
            fg_color="#1f6aa5",
            hover_color="#144870",
            corner_radius=8,
            cursor="hand2",
            command=self.handle_login_click
        )
        self.login_button.pack(pady=(5, 10), fill="x", padx=60)

        #  BOTTOM NOTES
        self.note_label = ctk.CTkLabel(
            self,
            text="All credentials are securely stored and locally encrypted on your device.",
            text_color="yellow"
        )
        self.note_label.pack(side="bottom", pady=15)

    # --- CLASS METHODS ---

    def animate_slide_down(self):
        if self.current_y < self.target_y:
            self.current_y += 5
            self.tooltip_box.place(x=self.target_x, y=self.current_y)
            self.animation_job = self.after(15, self.animate_slide_down)

    def animate_slide_up(self):
        if self.current_y > self.target_y - 30:
            self.current_y -= 5
            self.tooltip_box.place(x=self.target_x, y=self.current_y)
            self.animation_job = self.after(15, self.animate_slide_up)
        else:
            self.tooltip_box.place_forget()

    def toggle_tooltip(self, event):
        if self.animation_job is not None:
            self.after_cancel(self.animation_job)

        if self.is_tooltip_visible:
            self.animate_slide_up()
            self.is_tooltip_visible = False
        else:
            self.update_idletasks()
            self.target_x = self.info_icon.winfo_rootx() - self.winfo_rootx() + self.info_icon.winfo_width() - 245
            self.target_y = self.info_icon.winfo_rooty() - self.winfo_rooty() - 125
            self.current_y = self.target_y - 30
            self.tooltip_box.tkraise()
            self.animate_slide_down()
            self.is_tooltip_visible = True

    def open_youtube_link(self, event):
        webbrowser.open_new("https://youtu.be/QDia3e12czc?si=fnOB68m7FaxGoJIG")

    def copy_code_to_clipboard(self, event):
        current_text = self.status_label.cget("text")
        if "TOTP:" in current_text:
            code = current_text.split("TOTP:")[1].split("(")[0].strip()
            self.clipboard_clear()
            self.clipboard_append(code)
            self.note_label.configure(text=f"📋 Copied code {code} to clipboard!", text_color="#2ECC71")

    def update_totp_live(self):
        if not self.active_secret:
            return

        code, time_left = login_backend.generate_current_totp(self.active_secret)
        self.status_label.configure(
            text=f"🔑 Your TOTP: {code} ({time_left}s) [Click to Copy]",
            text_color="#F1C40F",
            cursor="hand2"
        )
        self.totp_timer_job = self.after(1000, self.update_totp_live)

    def reset_to_login_screen(self, error_msg):
        if self.totp_timer_job:
            self.after_cancel(self.totp_timer_job)
            self.totp_timer_job = None

        self.active_secret = ""

        clean_msg = error_msg
        if "EMAIL_ERROR:" in error_msg:
            clean_msg = "❌ Email Error: Check student email address."
        elif "PASSWORD_ERROR:" in error_msg:
            clean_msg = "❌ Password Error: Incorrect password."
        elif "TOTP_ERROR:" in error_msg:
            clean_msg = "❌ 2FA Error: Secret key invalid or not activated on Microsoft."

        self.status_label.configure(text=clean_msg, text_color="#E74C3C", cursor="")
        self.login_button.configure(
            state="normal",
            text="Log In",
            fg_color="#1f6aa5",
            hover_color="#144870",
            command=self.handle_login_click
        )

    def finish_login(self):
        """Triggers the success callback to switch frames in Main.py."""
        if self.totp_timer_job:
            self.after_cancel(self.totp_timer_job)

        if self.on_success_callback:
            self.on_success_callback()

    def execute_login_attempt(self, email, password, secret):
        success, message = login_backend.attempt_full_ebwise_login(email, password, secret)

        if success is True:
            try:
                storage.save_credentials(email, password, secret)
                print("🔒 Saved validated credentials to local encrypted storage.")
            except Exception as e:
                print(f"⚠️ Failed to save credentials: {e}")

            self.after(0, self.finish_login)
        else:
            self.after(0, lambda: self.reset_to_login_screen(message))

    def handle_next_click(self):
        user_email = self.email_entry.get().strip()
        user_password = self.password_entry.get().strip()

        self.status_label.configure(text="⏳ Verifying secret key & logging into eBwise...", text_color="#3498DB",
                                    cursor="")
        self.login_button.configure(state="disabled", text="Verifying...")

        threading.Thread(
            target=self.execute_login_attempt,
            args=(user_email, user_password, self.active_secret),
            daemon=True
        ).start()

    def handle_login_click(self):
        user_email = self.email_entry.get().strip()
        user_password = self.password_entry.get().strip()
        user_secret = self.secure_key_entry.get().strip()

        is_valid, msg = login_backend.validate_credentials_format(user_email, user_password, user_secret)
        if not is_valid:
            self.status_label.configure(text=f"❌ {msg}", text_color="#E74C3C")
            return

        self.active_secret = user_secret
        self.update_totp_live()

        self.login_button.configure(
            text="Next ➔",
            fg_color="#27AE60",
            hover_color="#1E8449",
            command=self.handle_next_click
        )


# Standalone runner for testing login_frontend individually
if __name__ == "__main__":
    root = ctk.CTk()
    root.geometry("900x650")
    root.title("Otium - Login Standalone Test")

    app = OtiumLoginApp(master=root, on_success_callback=lambda: print("Login Successful!"))
    app.pack(fill="both", expand=True)

    root.mainloop()