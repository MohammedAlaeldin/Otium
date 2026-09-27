import os
import threading
import customtkinter as ctk
import storage

from views.home_view import HomeView
from views.outlook_view import OutlookView
from views.teams_view import TeamsView
from views.ebwise_view import EbwiseView

from ebwise_backend import fetch_ebwise_data
from storage import clear_all_saved_data

THEME = {
    "bg_dark": "#121216",
    "card_bg": "#1E1E2A",
    "card_hover": "#262638",
    "header_bg": "#181822",
    "border": "#323246",
    "border_hover": "#4B4B66",
    "text_primary": "#F1F5F9",
    "text_secondary": "#94A3B8",
    "accent_indigo": "#6366F1",
    "accent_hover": "#4F46E5",
    "danger": "#EF4444",
    "success": "#10B981",
    "warning": "#EAB308"
}


class DashboardWindow(ctk.CTkFrame):
    def __init__(self, master, on_logout_callback=None):
        super().__init__(master, fg_color=THEME["bg_dark"])
        self.pack(fill="both", expand=True)
        self.on_logout_callback = on_logout_callback

        self.sidebar_visible = False
        self.sidebar_width = 180
        self.current_view = None
        self.sidebar_buttons = {}

        # --- Top Header Bar ---
        self.header = ctk.CTkFrame(self, height=55, corner_radius=0, fg_color=THEME["header_bg"],
                                   border_color=THEME["border"], border_width=1)
        self.header.pack(fill="x", side="top")
        self.header.pack_propagate(False)

        self.burger_btn = ctk.CTkButton(
            self.header,
            text="☰",
            width=40,
            height=35,
            font=ctk.CTkFont(size=20, weight="bold"),
            fg_color="transparent",
            text_color=THEME["text_primary"],
            hover_color=THEME["card_hover"],
            command=self.toggle_sidebar
        )
        self.burger_btn.pack(side="left", padx=10, pady=10)

        self.title_label = ctk.CTkLabel(
            self.header,
            text="Home",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=THEME["text_primary"]
        )
        self.title_label.pack(side="left", padx=10)

        # --- Main Body Area ---
        self.body = ctk.CTkFrame(self, corner_radius=0, fg_color=THEME["bg_dark"])
        self.body.pack(fill="both", expand=True, side="bottom")

        # Container occupies full width permanently (avoids view reflow on toggle)
        self.container = ctk.CTkFrame(self.body, corner_radius=0, fg_color="transparent")
        self.container.pack(fill="both", expand=True)

        # Overlay Sidebar (placed absolutely over body without affecting container)
        self.sidebar = ctk.CTkFrame(self.body, width=self.sidebar_width, corner_radius=0, fg_color=THEME["header_bg"],
                                    border_color=THEME["border"], border_width=1)

        # Initialize Views
        self.views = {
            "Home": HomeView(self.container, on_navigate_callback=self.show_view),
            "Ebwise": EbwiseView(self.container, fetch_callback=self.refresh_live_data),
            "Outlook": OutlookView(self.container),
            "Teams": TeamsView(self.container),
        }

        self._build_sidebar_menu()
        self.show_view("Home")
        self.refresh_live_data()

    def toggle_sidebar(self):
        """Flips sidebar visibility using absolute placement to bypass layout reflows."""
        if self.sidebar_visible:
            self.sidebar.place_forget()
        else:
            # CustomTkinter forbids setting width/height inside place()
            self.sidebar.place(x=0, y=0, relheight=1.0)
            self.sidebar.tkraise()
        self.sidebar_visible = not self.sidebar_visible

    def refresh_live_data(self, classification: str = "inprogress", selected_filter: str = "In Progress"):
        threading.Thread(
            target=self._worker_fetch_data,
            args=(classification, selected_filter),
            daemon=True
        ).start()

    def _worker_fetch_data(self, classification: str, selected_filter: str):
        data = fetch_ebwise_data(classification=classification)
        self.after(0, lambda: self._update_ui_with_data(data, selected_filter=selected_filter))

    def _update_ui_with_data(self, data: dict, selected_filter: str = "In Progress"):
        status = data.get("status")

        if status == "SUCCESS":
            ebwise_view = self.views.get("Ebwise")
            if ebwise_view and hasattr(ebwise_view, "update_data"):
                ebwise_view.update_data(data, selected_filter=selected_filter)
        elif status == "EXPIRED":
            self.logout()

    def _build_sidebar_menu(self):
        nav_items = ["Home", "Ebwise", "Outlook", "Teams"]

        for item in nav_items:
            btn = ctk.CTkButton(
                self.sidebar,
                text=item,
                anchor="w",
                height=40,
                font=ctk.CTkFont(size=14, weight="bold"),
                fg_color="transparent",
                text_color=THEME["text_primary"],
                hover_color=THEME["card_hover"],
                command=lambda name=item: self.show_view(name)
            )
            btn.pack(fill="x", padx=10, pady=2)
            self.sidebar_buttons[item] = btn

        spacer = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        spacer.pack(fill="both", expand=True)

        logout_btn = ctk.CTkButton(
            self.sidebar,
            text="Log Out",
            anchor="w",
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="transparent",
            text_color=THEME["danger"],
            hover_color="#3B1820",
            command=self.logout
        )
        logout_btn.pack(fill="x", padx=10, pady=20)

    def show_view(self, view_name: str, payload: dict = None):
        """Switches active view and dismisses sidebar cleanly."""
        self.title_label.configure(text=view_name)

        for name, btn in self.sidebar_buttons.items():
            if name == view_name:
                btn.configure(fg_color=THEME["card_hover"], text_color=THEME["accent_indigo"])
            else:
                btn.configure(fg_color="transparent", text_color=THEME["text_primary"])

        if self.sidebar_visible:
            self.toggle_sidebar()

        for view in self.views.values():
            view.pack_forget()

        active_view = self.views.get(view_name)
        if active_view:
            active_view.pack(fill="both", expand=True)

            if payload and hasattr(active_view, "handle_navigation_payload"):
                self.after(50, lambda: active_view.handle_navigation_payload(payload))

    def logout(self):
        clear_all_saved_data()
        if self.on_logout_callback:
            self.on_logout_callback()