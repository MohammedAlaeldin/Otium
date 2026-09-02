import customtkinter as ctk


class HomeView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        label = ctk.CTkLabel(
            self,
            text="Welcome to your Dashboard!",
            font=ctk.CTkFont(size=22, weight="bold")
        )
        label.pack(expand=True)