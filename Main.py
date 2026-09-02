import os
import json
import threading
import requests
import customtkinter as ctk

from storage import SESSION_FILE

import storage
from auto_login import run_daily_login
from dashboard import DashboardWindow
from login_frontend import OtiumLoginApp

ctk.set_appearance_mode("Dark")


def check_cookie_session_fast() -> bool:
    """Quickly tests if session.json cookies are active without launching Playwright."""
    if not os.path.exists(SESSION_FILE):
        return False

    try:
        with open(SESSION_FILE, "r") as f:
            state = json.load(f)

        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

        for cookie in state.get("cookies", []):
            domain = cookie["domain"].lstrip(".")
            session.cookies.set(
                name=cookie["name"],
                value=cookie["value"],
                domain=domain,
                path=cookie.get("path", "/")
            )

        res = session.get("https://ebwise.mmu.edu.my/my/", timeout=5, allow_redirects=True)
        if "login" not in res.url and "microsoftonline" not in res.url and res.status_code == 200:
            print("⚡ Fast Check: Active session verified! Opening Dashboard instantly.")
            return True
    except Exception as e:
        print(f"⚠️ Fast session check skipped: {e}")

    return False


class AppController(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Otium - Academic Command Center")
        self.geometry("900x650")
        self.minsize(700, 500)

        self.current_frame = None
        self.check_initial_auth_state()

    def check_initial_auth_state(self):
        """Uses fast check first; falls back to Playwright login only when expired."""

        # 1. Check existing session cookies directly via lightweight HTTP GET
        if check_cookie_session_fast():
            self.show_dashboard()
            return

        # 2. Check stored credentials if session cookie is invalid/expired
        creds = storage.load_credentials()
        if not creds:
            self.show_login()
            return

        # 3. Refresh session via Playwright in a background thread
        self.show_loading_screen("Refreshing session...")

        def bg_auth():
            success = run_daily_login(creds)
            if success:
                self.after(0, self.show_dashboard)
            else:
                self.after(0, self.show_login)

        threading.Thread(target=bg_auth, daemon=True).start()

    def show_loading_screen(self, message="Loading..."):
        """Displays a loading state during session refresh."""
        if self.current_frame is not None:
            self.current_frame.destroy()

        self.current_frame = ctk.CTkFrame(self)
        self.current_frame.pack(fill="both", expand=True)

        lbl = ctk.CTkLabel(
            self.current_frame,
            text=message,
            font=ctk.CTkFont(size=18, weight="bold")
        )
        lbl.place(relx=0.5, rely=0.45, anchor="center")

        spinner = ctk.CTkProgressBar(self.current_frame, mode="indeterminate", width=220)
        spinner.place(relx=0.5, rely=0.53, anchor="center")
        spinner.start()

    def show_login(self):
        """Presents the Login Screen."""
        if self.current_frame is not None:
            self.current_frame.destroy()

        self.current_frame = OtiumLoginApp(
            master=self,
            on_success_callback=self.show_dashboard
        )
        self.current_frame.pack(fill="both", expand=True)

    def show_dashboard(self):
        """Presents Main Dashboard."""
        if self.current_frame is not None:
            self.current_frame.destroy()

        self.current_frame = DashboardWindow(
            master=self,
            on_logout_callback=self.handle_logout
        )
        self.current_frame.pack(fill="both", expand=True)

    def handle_logout(self):
        """Clears local session and credentials on logout."""
        print("🔒 Logging out... Purging saved credentials and session cookies.")
        if hasattr(storage, "clear_all_saved_data"):
            storage.clear_all_saved_data()

        self.show_login()


if __name__ == "__main__":
    app = AppController()
    app.mainloop()