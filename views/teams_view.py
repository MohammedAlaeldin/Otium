import customtkinter as ctk
import threading
from datetime import datetime, timedelta, timezone
import teams_backend

def parse_teams_time(ts):
    if not ts:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        if isinstance(ts, (int, float)):
            val = float(ts)
            if val > 1e11: val /= 1000
            return datetime.fromtimestamp(val, tz=timezone.utc)
            
        ts_str = str(ts).strip()
        if ts_str.isdigit():
            val = float(ts_str)
            if val > 1e11: val /= 1000
            return datetime.fromtimestamp(val, tz=timezone.utc)
            
        clean_str = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)

class TeamsView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        
        #Loading Screen
        self.loading_label = ctk.CTkLabel(
            self, 
            text="Syncing Microsoft Teams Data...\nThis takes about 15 seconds.", 
            font=ctk.CTkFont(size=20, weight="bold"), 
            text_color="#1f6aa5"
        )
        self.loading_label.place(relx=0.5, rely=0.5, anchor="center")

        self.data_loaded = False

    def pack(self, **kwargs):
        super().pack(**kwargs)
        # Fetch data in background only when the user clicks the Teams tab
        if not self.data_loaded:
            threading.Thread(target=self.fetch_and_render, daemon=True).start()

    def fetch_and_render(self):
        data = teams_backend.fetch_teams_data_clean()
        self.after(0, lambda: self.build_dashboard(data))

    def build_dashboard(self, data):
        self.loading_label.destroy()
        self.data_loaded = True

        left_container = ctk.CTkFrame(self, fg_color="transparent")
        left_container.place(relx=0.02, rely=0.02, relwidth=0.55, relheight=0.96)

        # 1.ACTIVITY
        activity_card = ctk.CTkFrame(left_container, fg_color="#2b2b2b", corner_radius=10)
        activity_card.place(relx=0, rely=0.0, relwidth=1.0, relheight=0.31)
        ctk.CTkLabel(activity_card, text="ACTIVITY", font=ctk.CTkFont(size=18, weight="bold")).place(relx=0.05, rely=0.05)
        
        act_scroll = ctk.CTkScrollableFrame(activity_card, fg_color="transparent")
        act_scroll.place(relx=0.05, rely=0.25, relwidth=0.9, relheight=0.7)
        
        if data.get("activity"):
            sorted_activity = sorted(data["activity"], key=lambda x: parse_teams_time(x.get("timestamp")), reverse=True)
            for msg in sorted_activity:
                msg_frame = ctk.CTkFrame(act_scroll, fg_color="#333333", corner_radius=6)
                msg_frame.pack(fill="x", pady=2)
                
                ts_obj = parse_teams_time(msg.get("timestamp"))
                ts_str = ts_obj.astimezone().strftime("%b %d, %I:%M %p") if ts_obj.year > 1 else "Recent"
                
                ctk.CTkLabel(msg_frame, text=f"[{ts_str}] 👤 {msg['sender']}:", font=ctk.CTkFont(weight="bold", size=11), text_color="#aaaaaa", anchor="w").pack(padx=10, pady=(5,0), fill="x")
                ctk.CTkLabel(msg_frame, text=f"{msg['message']}", text_color="#ffffff", wraplength=450, justify="left", anchor="w").pack(padx=10, pady=(0,5), fill="x")
        else:
            ctk.CTkLabel(act_scroll, text="No recent activity found.", text_color="gray").pack(pady=10)

        # 2.MEETINGS AND CALLS
        meetings_card = ctk.CTkFrame(left_container, fg_color="#2b2b2b", corner_radius=10)
        meetings_card.place(relx=0, rely=0.34, relwidth=1.0, relheight=0.31)
        ctk.CTkLabel(meetings_card, text="MEETINGS & CALLS", font=ctk.CTkFont(size=18, weight="bold")).place(relx=0.05, rely=0.05)
        
        meet_scroll = ctk.CTkScrollableFrame(meetings_card, fg_color="transparent")
        meet_scroll.place(relx=0.05, rely=0.25, relwidth=0.9, relheight=0.7)

        now_utc = datetime.now(timezone.utc) 

        if data.get("meetings"):
            sorted_meetings = sorted(data["meetings"], key=lambda x: parse_teams_time(x.get("start_time")), reverse=True)
            
            for meet in sorted_meetings:
                start_dt_utc = parse_teams_time(meet.get("start_time"))
                local_time_str = start_dt_utc.astimezone().strftime("%I:%M %p, %b %d") if start_dt_utc.year > 1 else "Time Unknown"

                if start_dt_utc > now_utc:
                    meet_frame = ctk.CTkFrame(meet_scroll, fg_color="#b57a14", corner_radius=6) 
                    meet_frame.pack(fill="x", pady=2)
                    ctk.CTkLabel(meet_frame, text=f"⏳ SCHEDULED: {meet['title']} ({local_time_str})", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=10, pady=10)
                    ctk.CTkButton(meet_frame, text="JOIN CALL", fg_color="#82560d", width=90, height=28, command=lambda url=meet['join_url']: print(f"Opening: {url}")).pack(side="right", padx=10)
                                  
                elif now_utc <= start_dt_utc + timedelta(minutes=150):
                    meet_frame = ctk.CTkFrame(meet_scroll, fg_color="#1f6aa5", corner_radius=6) 
                    meet_frame.pack(fill="x", pady=2)
                    ctk.CTkLabel(meet_frame, text=f"🔴 LIVE: {meet['title']} ({local_time_str})", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=10, pady=10)
                    ctk.CTkButton(meet_frame, text="JOIN CALL", fg_color="#144870", width=90, height=28, command=lambda url=meet['join_url']: print(f"Opening: {url}")).pack(side="right", padx=10)
                                  
                else:
                    meet_frame = ctk.CTkFrame(meet_scroll, fg_color="#222222", corner_radius=6) 
                    meet_frame.pack(fill="x", pady=2)
                    ctk.CTkLabel(meet_frame, text=f"☑ ENDED: {meet['title']} ({local_time_str})", text_color="gray", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=10, pady=10)
        else:
            ctk.CTkLabel(meet_scroll, text="No meetings or calls found.", text_color="gray").pack(pady=10)

        # 3.ASSIGNMENTS CARD
        assignments_card = ctk.CTkFrame(left_container, fg_color="#2b2b2b", corner_radius=10)
        assignments_card.place(relx=0, rely=0.68, relwidth=1.0, relheight=0.31)
        ctk.CTkLabel(assignments_card, text="ASSIGNMENTS", font=ctk.CTkFont(size=18, weight="bold")).place(relx=0.05, rely=0.05)
        ctk.CTkLabel(assignments_card, text="No assignments due! 🎉", text_color="gray").place(relx=0.5, rely=0.5, anchor="center")

        # 4.CALENDAR
        calendar_card = ctk.CTkFrame(self, fg_color="#2b2b2b", corner_radius=10)
        calendar_card.place(relx=0.6, rely=0.02, relwidth=0.38, relheight=0.96)
        ctk.CTkLabel(calendar_card, text="CALENDAR", font=ctk.CTkFont(size=18, weight="bold")).place(relx=0.05, rely=0.03)

        cal_scroll = ctk.CTkScrollableFrame(calendar_card, fg_color="transparent")
        cal_scroll.place(relx=0.05, rely=0.1, relwidth=0.9, relheight=0.88)

        if data.get("calendar"):
            sorted_cal = sorted(data["calendar"], key=lambda x: parse_teams_time(x.get("start_time")))
            for ev in sorted_cal:
                ev_frame = ctk.CTkFrame(cal_scroll, fg_color="#333333", corner_radius=8)
                ev_frame.pack(fill="x", pady=5)
                
                title_text = f"📅 {ev['subject']}"
                if ev.get("is_online"):
                    title_text += " 💻 (Online)"
                ctk.CTkLabel(ev_frame, text=title_text, font=ctk.CTkFont(weight="bold"), anchor="w").pack(padx=10, pady=(10, 0), fill="x")
                
                utc_cal = parse_teams_time(ev.get('start_time'))
                cal_str = utc_cal.astimezone().strftime("%A, %b %d at %I:%M %p") if utc_cal.year > 1 else "Unknown Time"
                
                if ev.get("end_time"):
                    utc_end = parse_teams_time(ev.get("end_time"))
                    if utc_end.year > 1:
                        if utc_cal.date() == utc_end.date():
                            cal_str += f" - {utc_end.astimezone().strftime('%I:%M %p')}"
                        else:
                            cal_str += f" to {utc_end.astimezone().strftime('%b %d, %I:%M %p')}"

                ctk.CTkLabel(ev_frame, text=f"🕒 {cal_str}", text_color="#aaaaaa", font=ctk.CTkFont(size=12), anchor="w").pack(padx=10, pady=(2, 5), fill="x")
                if ev.get("organizer"):
                    ctk.CTkLabel(ev_frame, text=f"👤 Organizer: {ev['organizer']}", text_color="#888888", font=ctk.CTkFont(size=11), anchor="w").pack(padx=10, pady=(0, 10), fill="x")
        else:
            ctk.CTkLabel(cal_scroll, text="No upcoming events scheduled.", text_color="gray").pack(pady=20)