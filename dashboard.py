import os
import threading
import customtkinter as ctk
import storage

from views.home_view import HomeView
from views.outlook_view import OutlookView
from views.teams_view import TeamsView

from ebwise_backend import fetch_ebwise_data
from ebwise_frontend import EbwiseView
from storage import clear_all_saved_data

class DashboardWindow(ctk.CTkFrame):
    def __init__(self, master, on_logout_callback=None):
        super().__init__(master)
        self.pack(fill="both", expand=True)
        self.on_logout_callback = on_logout_callback

        self.sidebar_visible = False
        self.sidebar_width = 180
        self.current_width = 0

        # --- Top Header Bar ---
        self.header = ctk.CTkFrame(self, height=50, corner_radius=0)
        self.header.pack(fill="x", side="top")
        self.header.pack_propagate(False)

        self.burger_btn = ctk.CTkButton(
            self.header,
            text="☰",
            width=40,
            height=35,
            font=ctk.CTkFont(size=20, weight="bold"),
            fg_color="transparent",
            hover_color="#333333",
            command=self.toggle_sidebar
        )
        self.burger_btn.pack(side="left", padx=10, pady=5)

        self.title_label = ctk.CTkLabel(
            self.header,
            text="Home",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.title_label.pack(side="left", padx=10)

        self.sync_status_label = ctk.CTkLabel(
            self.header,
            text="Syncing eBwise...",
            font=ctk.CTkFont(size=12),
            text_color="#FFA500"
        )
        self.sync_status_label.pack(side="right", padx=15)

        # --- Main Body Area ---
        self.body = ctk.CTkFrame(self, corner_radius=0)
        self.body.pack(fill="both", expand=True, side="bottom")

        self.sidebar = ctk.CTkFrame(self.body, width=0, corner_radius=0, fg_color="#1E1E1E")
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.container = ctk.CTkFrame(self.body, corner_radius=0, fg_color="transparent")
        self.container.pack(side="right", fill="both", expand=True)

        self.views = {
            "Home": HomeView(self.container),
            "Ebwise": EbwiseView(self.container),
            "Outlook": OutlookView(self.container),
            "Teams": TeamsView(self.container),
        }

        self._build_sidebar_menu()
        self.show_view("Home")
        self.refresh_live_data()

    def refresh_live_data(self):
        """Starts background thread to pull eBwise data without freezing UI."""
        threading.Thread(target=self._worker_fetch_data, daemon=True).start()

    def _worker_fetch_data(self):
        data = fetch_ebwise_data()
        self.after(0, lambda: self._update_ui_with_data(data))

    def _update_ui_with_data(self, data: dict):
        status = data.get("status")

        if status == "SUCCESS":
            self.sync_status_label.configure(text="● Live Data Synced", text_color="#4CAF50")
            ebwise_view = self.views.get("Ebwise")
            if ebwise_view and hasattr(ebwise_view, "update_data"):
                ebwise_view.update_data(data)
        elif status == "EXPIRED":
            self.sync_status_label.configure(text="⚠️ Session Expired", text_color="#F44336")
            self.logout()
        else:
            self.sync_status_label.configure(text="⚠️ Sync Failed", text_color="#F44336")

    def _build_sidebar_menu(self):
        nav_items = ["Home", "Ebwise", "Outlook", "Teams"]

        for item in nav_items:
            btn = ctk.CTkButton(
                self.sidebar,
                text=item,
                anchor="w",
                height=40,
                fg_color="transparent",
                hover_color="#2A2A2A",
                command=lambda name=item: self.show_view(name)
            )
            btn.pack(fill="x", padx=10, pady=5)

        spacer = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        spacer.pack(fill="both", expand=True)

        logout_btn = ctk.CTkButton(
            self.sidebar,
            text="Log Out",
            anchor="w",
            height=40,
            fg_color="#D32F2F",
            hover_color="#9A0007",
            command=self.logout
        )
        logout_btn.pack(fill="x", padx=10, pady=15)

    def toggle_sidebar(self):
        if self.sidebar_visible:
            self._animate_sidebar(closing=True)
        else:
            self._animate_sidebar(closing=False)
        self.sidebar_visible = not self.sidebar_visible

    def _animate_sidebar(self, closing: bool):
        step = 15
        if closing:
            if self.current_width > 0:
                self.current_width -= step
                self.sidebar.configure(width=max(0, self.current_width))
                self.after(10, lambda: self._animate_sidebar(closing=True))
        else:
            if self.current_width < self.sidebar_width:
                self.current_width += step
                self.sidebar.configure(width=min(self.sidebar_width, self.current_width))
                self.after(10, lambda: self._animate_sidebar(closing=False))

    def show_view(self, view_name: str):
        self.title_label.configure(text=view_name)
        for view in self.views.values():
            view.pack_forget()

        if view_name in self.views:
            self.views[view_name].pack(fill="both", expand=True)

        if self.sidebar_visible:
            self.toggle_sidebar()

    def logout(self):
        clear_all_saved_data()
        if self.on_logout_callback:
            self.on_logout_callback()