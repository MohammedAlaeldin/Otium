import os
import json
import threading
import requests
import subprocess
import customtkinter as ctk
from PIL import Image, ImageTk
import webbrowser
import storage

# CRITICAL: Set the custom Playwright browser path before any other modules load it.
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(storage.get_app_dir(), "pw-browsers")

from storage import SESSION_FILE
from auto_login import run_daily_login
from dashboard import DashboardWindow
from login_frontend import OtiumLoginApp

# Quick patch for CustomTkinter destroy bug on shutdown
from customtkinter.windows.widgets.ctk_button import CTkButton

_original_destroy = CTkButton.destroy


def _safe_destroy(self):
    try:
        _original_destroy(self)
    except AttributeError as e:
        if "_font" not in str(e):
            raise


CTkButton.destroy = _safe_destroy
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

        # --- FIX: Force Windows to use the logo for the Taskbar ---
        try:
            if os.name == 'nt':
                myappid = 'otium.academic.commandcenter.1.0'
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass


        try:
            # Check if the app is running as a PyInstaller executable
            if getattr(sys, 'frozen', False):
                base_dir = sys._MEIPASS
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))

            ico_path = os.path.join(base_dir, "logo.ico")
            png_path = os.path.join(base_dir, "logo.png")

            if os.path.exists(ico_path):
                self.iconbitmap(ico_path)
            elif os.path.exists(png_path):
                self._window_icon = ImageTk.PhotoImage(Image.open(png_path))
                self.iconphoto(False, self._window_icon)
            else:
                print("⚠️ Could not find logo.ico or logo.png to set as window icon.")
        except Exception as e:
            print(f"Window icon warning: {e}")

        self.current_frame = None
        self.after(50, self.run_startup_setup)

    def run_startup_setup(self):
        """Runs Playwright browser installation in a background thread and streams progress."""
        self.show_loading_screen("Setting up Otium for the first time...")
        self.status_label.configure(text="Initializing browser engine download (this may take a few minutes)...")

        def bg_setup():
            try:
                import storage
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(storage.get_app_dir(), "pw-browsers")

                from playwright._impl._driver import compute_driver_executable, get_driver_env
                driver_executable = compute_driver_executable()
                env = get_driver_env()

                if isinstance(driver_executable, tuple):
                    cmd = list(driver_executable) + ["install", "chromium"]
                else:
                    cmd = [driver_executable, "install", "chromium"]

                # Use Popen to stream the installation output live
                process = subprocess.Popen(
                    cmd,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )

                # Read output line-by-line and update the status label on the UI
                for line in process.stdout:
                    clean_line = line.strip()
                    if clean_line and hasattr(self, 'status_label') and self.status_label.winfo_exists():
                        # Truncate long lines so they fit nicely on the screen
                        display_text = clean_line if len(clean_line) < 80 else clean_line[:77] + "..."
                        self.after(0, lambda t=display_text: self.status_label.configure(text=t))

                process.wait()

            except Exception as e:
                print(f"Browser setup error: {e}")

            # Once complete, proceed to the standard authentication check
            self.after(0, self.check_initial_auth_state)

        threading.Thread(target=bg_setup, daemon=True).start()

    def check_initial_auth_state(self):
        """Runs all network checks in a background thread to prevent UI freezing."""
        self.show_loading_screen("Authenticating...")
        if hasattr(self, 'status_label') and self.status_label.winfo_exists():
            self.status_label.configure(text="Verifying secure session...")

        def bg_auth_flow():
            # 1. Fast check now runs in the background so the UI doesn't freeze
            if check_cookie_session_fast():
                self.after(0, self.show_dashboard)
                return

            # 2. Check for saved credentials
            import storage
            creds = storage.load_credentials()
            if not creds:
                self.after(0, self.show_login)
                return

            # 3. Fallback to Playwright refresh
            if hasattr(self, 'status_label') and self.status_label.winfo_exists():
                self.after(0, lambda: self.status_label.configure(text="Refreshing background session..."))

            status = run_daily_login(creds)
            if status is True or status == "SUCCESS":
                self.after(0, self.show_dashboard)
            elif status == "AUTH_FAILED":
                self.after(0, self.handle_auth_failure)
            else:
                self.after(0, self.show_network_error)

        # Start the background thread
        threading.Thread(target=bg_auth_flow, daemon=True).start()

    def handle_auth_failure(self):
        """Clears outdated credentials and redirects to login."""
        print("❌ Saved credentials are no longer valid. Purging data...")
        if hasattr(storage, "clear_all_saved_data"):
            storage.clear_all_saved_data()
        self.show_login()

    def show_loading_screen(self, message="Loading..."):
        """Displays a loading state during session refresh or setup."""
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

        # --- NEW: A label to display live background tasks ---
        self.status_label = ctk.CTkLabel(
            self.current_frame,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="#94A3B8"
        )
        self.status_label.place(relx=0.5, rely=0.6, anchor="center")

    def show_network_error(self):
        """Displays an error screen with a retry button if the background auto-login fails."""
        if self.current_frame is not None:
            self.current_frame.destroy()

        self.current_frame = ctk.CTkFrame(self)
        self.current_frame.pack(fill="both", expand=True)

        lbl = ctk.CTkLabel(
            self.current_frame,
            text="⚠️ No Internet Connection",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color="#F87171"
        )
        lbl.place(relx=0.5, rely=0.4, anchor="center")

        sub_lbl = ctk.CTkLabel(
            self.current_frame,
            text="We couldn't reach the servers after 3 attempts.\nPlease check your connection or manually log in.",
            font=ctk.CTkFont(size=14),
            text_color="#94A3B8",
            justify="center"
        )
        sub_lbl.place(relx=0.5, rely=0.48, anchor="center")

        btn_frame = ctk.CTkFrame(self.current_frame, fg_color="transparent")
        btn_frame.place(relx=0.5, rely=0.6, anchor="center")

        retry_btn = ctk.CTkButton(
            btn_frame,
            text="🔄 Retry",
            width=120,
            height=32,
            font=ctk.CTkFont(weight="bold"),
            command=self.check_initial_auth_state
        )
        retry_btn.pack(side="left", padx=10)

        login_btn = ctk.CTkButton(
            btn_frame,
            text="Back to Login",
            width=120,
            height=32,
            fg_color="transparent",
            border_width=1,
            hover_color="#333333",
            command=self.show_login
        )
        login_btn.pack(side="left", padx=10)

        login_btn.pack(side="left", padx=10)
        #bug report button
        bug_btn = ctk.CTkButton(
            self.current_frame,
            text="🐞 Report an Issue",
            font=ctk.CTkFont(size=12, underline=True),
            fg_color="transparent",
            text_color="#94A3B8",
            hover_color="#1E1E2A",
            command=lambda: webbrowser.open("https://github.com/MohammedAlaeldin/Otium/issues/new")
        )
        bug_btn.place(relx=0.5, rely=0.8, anchor="center")

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