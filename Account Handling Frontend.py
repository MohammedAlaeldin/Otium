import webbrowser
import customtkinter as ctk

# --- 1. APPLICATION SETUP ---
ctk.set_appearance_mode("dark")  
ctk.set_default_color_theme("blue")  

app = ctk.CTk()
app.geometry("900x600")
app.title("Otium - Login")
# Optional: Set a minimum window size so it doesn't break if shrunk too much
app.minsize(700, 450)

# --- 2. THE MAIN LOGIN CARD (Percentage Based) ---
login_frame = ctk.CTkFrame(app, corner_radius=15, fg_color="#2b2b2b") 

# relwidth=0.75 means 75% of window width. relheight=0.85 means 85% of window height
login_frame.place(relx=0.5, rely=0.5, relwidth=0.42, relheight=0.6, anchor="center")

# --- 3. TEXT ELEMENTS ---
title_label = ctk.CTkLabel(login_frame, 
                           text="OTIUM", 
                           font=ctk.CTkFont(family="League Spartan", size=45, weight="bold"), 
                           text_color="#D4BE18")
title_label.pack(pady=(40, 5)) 

motto_label = ctk.CTkLabel(login_frame, 
                           text="** INSERT MOTTO HERE **", 
                           font=ctk.CTkFont(family="Helvetica", size=14, slant="italic"), 
                           text_color="#A9A9A9")
motto_label.pack(pady=(0, 30))

# --- 4. INPUT FIELDS (Responsive Width) ---
# We remove 'width' and let the pack() manager handle the resizing via 'fill' and 'padx'
email_entry = ctk.CTkEntry(login_frame, placeholder_text="Student Email Address", height=50)
# fill="x" stretches it. padx=100 leaves a responsive margin on both sides.
email_entry.pack(pady=10, fill="x", padx=100)

password_entry = ctk.CTkEntry(login_frame, placeholder_text="Password", show="*", height=50)
password_entry.pack(pady=10, fill="x", padx=100)

# --- 5. SECURE KEY & TOOLTIP LOGIC ---
key_frame = ctk.CTkFrame(login_frame, fg_color="transparent")
key_frame.pack(pady=10, fill="x", padx=100)

secure_key_entry = ctk.CTkEntry(key_frame, placeholder_text="Secure Key", height=50)
secure_key_entry.pack(side="left", fill="x", expand=True) # expand=True lets it push the icon to the right

info_icon = ctk.CTkLabel(key_frame, text=" ❓ ", width=40, height=40, cursor="hand2")
info_icon.pack(side="left", padx=(5, 0))

# Tooltip Box
# Change login_frame back to app!
tooltip_box = ctk.CTkFrame(app, fg_color="#2b2b2b", border_width=1, border_color="gray", corner_radius=8)

desc_text = ctk.CTkLabel(tooltip_box, 
                         text="text to be figured out click this link to view a guide on how to obtain it :", 
                         wraplength=250, 
                         justify="left")
desc_text.pack(padx=15, pady=(10, 0))

link_text = ctk.CTkLabel(tooltip_box, 
                         text="GUIDE", 
                         text_color="#1f6aa5", 
                         font=ctk.CTkFont(underline=True), 
                         cursor="hand2")
link_text.pack(padx=15, pady=(0, 10))

# Dynamic Animation Logic (Restored to math so it works dynamically when window resizes)
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
        # MAGIC LINE: Forces Tkinter to refresh exact screen coordinates before doing math
        app.update_idletasks()
        
        # Calculate exactly where the icon is relative to the main app window
        # Adjust the + 5 (left/right) or - 10 (up/down) to fine-tune
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

spacer = ctk.CTkLabel(login_frame, text="")
spacer.pack(pady=5)

# --- 6. LOGIN BUTTON ---
login_button = ctk.CTkButton(login_frame, 
                             text="Log In", 
                             font=ctk.CTkFont(size=15, weight="bold"),
                             height=45,
                             fg_color="#1f6aa5",     
                             hover_color="#144870",  
                             corner_radius=8,
                             cursor="hand2",
                             command=lambda: print("Login button clicked!"))

# Fills horizontally to match inputs
login_button.pack(pady=(2, 10), fill="x", padx=100) 

# --- 7. BOTTOM NOTE ---
note_label = ctk.CTkLabel(app, text="** INSERT NOTE HERE **", text_color="gray")
note_label.pack(side="bottom", pady=20)

app.mainloop()