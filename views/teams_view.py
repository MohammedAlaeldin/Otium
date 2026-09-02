import customtkinter as ctk

class TeamsView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        ctk.CTkLabel(self, text="Teams Frontend", font=ctk.CTkFont(size=20)).pack(expand=True)