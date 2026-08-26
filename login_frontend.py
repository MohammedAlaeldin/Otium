import sys
import os
import threading
import webbrowser
import customtkinter as ctk

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

#  1. SETTING UP CUSTOMTKINTER APPEARANCE
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

app = ctk.CTk()
app.geometry("900x650")
app.title("Otium - Login")
app.minsize(700, 500)

#  GLOBAL STATE VARIABLES 
totp_timer_job = None
active_secret = ""

#  2. THE MAIN LOGIN CARD 
login_frame = ctk.CTkFrame(app, corner_radius=15, fg_color="#2b2b2b")
login_frame.place(relx=0.5, rely=0.5, relwidth=0.48, relheight=0.75, anchor="center")

#  3. TEXT ELEMENTS 
title_label = ctk.CTkLabel(
    login_frame,
    text="OTIUM",
    font=ctk.CTkFont(family="League Spartan", size=45, weight="bold"),
    text_color="#D4BE18"
)
title_label.pack(pady=(30, 5))

motto_label = ctk.CTkLabel(
    login_frame,
    text="Your Academic Command Center",
    font=ctk.CTkFont(family="Helvetica", size=14, slant="italic"),
    text_color="#A9A9A9"
)
motto_label.pack(pady=(0, 20))

#4. INPUTS
email_entry = ctk.CTkEntry(login_frame, placeholder_text="Student Email Address", height=45)
email_entry.pack(pady=8, fill="x", padx=60)

password_entry = ctk.CTkEntry(login_frame, placeholder_text="Password", show="*", height=45)
password_entry.pack(pady=8, fill="x", padx=60)

#5. SECURE KEY & TOOLTIP 
key_frame = ctk.CTkFrame(login_frame, fg_color="transparent")
key_frame.pack(pady=8, fill="x", padx=60)

secure_key_entry = ctk.CTkEntry(key_frame, placeholder_text="Secure Secret Key", height=45)
secure_key_entry.pack(side="left", fill="x", expand=True)

info_icon = ctk.CTkLabel(key_frame, text=" ❓ ", width=40, height=40, cursor="hand2")
info_icon.pack(side="left", padx=(5, 0))

#Tooltip Box
tooltip_box = ctk.CTkFrame(app, fg_color="#2b2b2b", border_width=1, border_color="gray", corner_radius=8)

desc_text = ctk.CTkLabel(
    tooltip_box,
    text="Click this link to view a guide on how to obtain your 2FA Secret Key:",
    wraplength=230,
    justify="left"
)
desc_text.pack(padx=15, pady=(10, 0))

link_text = ctk.CTkLabel(
    tooltip_box,
    text="GUIDE",
    text_color="#1f6aa5",
    font=ctk.CTkFont(underline=True),
    cursor="hand2"
)
link_text.pack(padx=15, pady=(0, 10))

is_tooltip_visible = False
animation_job = None
current_y = 0
target_y = 0
target_x = 0


def animate_slide_down():
    global current_y, animation_job
    if current_y < target_y:
        current_y += 5
        tooltip_box.place(x=target_x, y=current_y)
        animation_job = app.after(15, animate_slide_down)


def animate_slide_up():
    global current_y, animation_job
    if current_y > target_y - 30:
        current_y -= 5
        tooltip_box.place(x=target_x, y=current_y)
        animation_job = app.after(15, animate_slide_up)
    else:
        tooltip_box.place_forget()


def toggle_tooltip(event):
    global is_tooltip_visible, animation_job, current_y, target_y, target_x
    if animation_job is not None:
        app.after_cancel(animation_job)

    if is_tooltip_visible:
        animate_slide_up()
        is_tooltip_visible = False
    else:
        app.update_idletasks()
        target_x = info_icon.winfo_rootx() - app.winfo_rootx() + info_icon.winfo_width() - 245
        target_y = info_icon.winfo_rooty() - app.winfo_rooty() - 125
        current_y = target_y - 30
        tooltip_box.tkraise()
        animate_slide_down()
        is_tooltip_visible = True


info_icon.bind("<Button-1>", toggle_tooltip)


def open_youtube_link(event):
    webbrowser.open_new("https://youtu.be/QDia3e12czc?si=fnOB68m7FaxGoJIG")


link_text.bind("<Button-1>", open_youtube_link)

# Status label
status_label = ctk.CTkLabel(
    login_frame,
    text="",
    font=ctk.CTkFont(size=13, weight="bold"),
    text_color="#E74C3C"
)
status_label.pack(pady=5)


def copy_code_to_clipboard(event):
    """Copies current TOTP code to system clipboard on click."""
    current_text = status_label.cget("text")
    if "TOTP:" in current_text:
        code = current_text.split("TOTP:")[1].split("(")[0].strip()
        app.clipboard_clear()
        app.clipboard_append(code)
        note_label.configure(text=f"📋 Copied code {code} to clipboard!", text_color="#2ECC71")


status_label.bind("<Button-1>", copy_code_to_clipboard)


#  6. WORKFLOW & THREADING LOGIC 

def update_totp_live():
    """Polls backend for a fresh TOTP and updates UI every second."""
    global totp_timer_job, active_secret
    if not active_secret:
        return

    code, time_left = login_backend.generate_current_totp(active_secret)
    status_label.configure(
        text=f"🔑 Your TOTP: {code} ({time_left}s) [Click to Copy]",
        text_color="#F1C40F",
        cursor="hand2"
    )
    totp_timer_job = app.after(1000, update_totp_live)


def reset_to_login_screen(error_msg):
    """Restores login UI state and displays stage-specific error message."""
    global totp_timer_job, active_secret

    if totp_timer_job:
        app.after_cancel(totp_timer_job)
        totp_timer_job = None

    active_secret = ""

    # failure labels
    clean_msg = error_msg
    if "EMAIL_ERROR:" in error_msg:
        clean_msg = "❌ Email Error: Check student email address."
    elif "PASSWORD_ERROR:" in error_msg:
        clean_msg = "❌ Password Error: Incorrect password."
    elif "TOTP_ERROR:" in error_msg:
        clean_msg = "❌ 2FA Error: Secret key invalid or not activated on Microsoft."

    status_label.configure(text=clean_msg, text_color="#E74C3C", cursor="")
    login_button.configure(
        state="normal",
        text="Log In",
        fg_color="#1f6aa5",
        hover_color="#144870",
        command=handle_login_click
    )


def open_next_screen():
    """Transitions GUI to dashboard view upon successful login."""
    global totp_timer_job
    if totp_timer_job:
        app.after_cancel(totp_timer_job)

    login_frame.place_forget()

    next_label = ctk.CTkLabel(
        app,
        text="Welcome to Otium Dashboard!",
        font=ctk.CTkFont(size=28, weight="bold")
    )
    next_label.pack(expand=True)


def execute_login_attempt(email, password, secret):
    """Worker thread running Playwright end-to-end login check."""
    success, message = login_backend.attempt_full_ebwise_login(email, password, secret)

    # success boolean
    if success is True:
        app.after(0, open_next_screen)
    else:
        app.after(0, lambda: reset_to_login_screen(message))


def handle_next_click():
    """Triggered when user clicks 'Next ➔' after key setup."""
    user_email = email_entry.get().strip()
    user_password = password_entry.get().strip()

    status_label.configure(text="⏳ Verifying secret key & logging into eBwise...", text_color="#3498DB", cursor="")
    login_button.configure(state="disabled", text="Verifying...")

    # Open Playwright in background 
    threading.Thread(
        target=execute_login_attempt,
        args=(user_email, user_password, active_secret),
        daemon=True
    ).start()


def handle_login_click():
    """Initial action when user clicks 'Log In'."""
    global active_secret

    user_email = email_entry.get().strip()
    user_password = password_entry.get().strip()
    user_secret = secure_key_entry.get().strip()

    # 1.Format Check
    is_valid, msg = login_backend.validate_credentials_format(user_email, user_password, user_secret)
    if not is_valid:
        status_label.configure(text=f"❌ {msg}", text_color="#E74C3C")
        return

    # 2. Store key show TOTP
    active_secret = user_secret
    update_totp_live()

    # 3. Morph Log In button into Next button
    login_button.configure(
        text="Next ➔",
        fg_color="#27AE60",
        hover_color="#1E8449",
        command=handle_next_click
    )


#  7. LOGIN BUTTON 
login_button = ctk.CTkButton(
    login_frame,
    text="Log In",
    font=ctk.CTkFont(size=15, weight="bold"),
    height=45,
    fg_color="#1f6aa5",
    hover_color="#144870",
    corner_radius=8,
    cursor="hand2",
    command=handle_login_click
)
login_button.pack(pady=(5, 10), fill="x", padx=60)

#  8. BOTTOM NOTES  
note_label = ctk.CTkLabel(app, text="All credentials are securely stored and locally encrypted on your device.", text_color="yellow")
note_label.pack(side="bottom", pady=15)

app.mainloop()