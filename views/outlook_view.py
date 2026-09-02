import customtkinter as ctk

class OutlookView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        ctk.CTkLabel(self, text="Outlook Frontend", font=ctk.CTkFont(size=20)).pack(expand=True)