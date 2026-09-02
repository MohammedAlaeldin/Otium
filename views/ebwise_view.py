import customtkinter as ctk

class EbwiseView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        ctk.CTkLabel(self, text="Ebwise Frontend", font=ctk.CTkFont(size=20)).pack(expand=True)

        # Inside views/ebwise_view.py

        def update_data(self, data: dict):
            courses = data.get("courses", [])
            upcoming = data.get("upcoming", [])

            # Example: Print or populate CTkScrollableFrame / Labels with raw eBwise data
            print("Fetched Courses:", courses)
            print("Upcoming Tasks:", upcoming)