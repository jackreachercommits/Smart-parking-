
import math
import re
import sqlite3
from datetime import datetime

DB_FILE = "parking.db"
FMT = "%Y-%m-%d %H:%M:%S"

# Slot layout: prefix -> (vehicle type, number of slots)
LAYOUT = {"B": ("Bike", 10), "C": ("Car", 15), "E": ("EV", 5)}
# Hourly rates in INR (minimum charge = 1 hour)
RATES = {"Bike": 10, "Car": 30, "EV": 40}


# ======================= Core logic (no GUI) =======================
class ParkingSystem:
    def __init__(self, db_file=DB_FILE):
        self.db = sqlite3.connect(db_file)
        self.db.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS slots(
                slot_no TEXT PRIMARY KEY, vehicle_type TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tickets(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plate TEXT NOT NULL, vehicle_type TEXT NOT NULL,
                slot_no TEXT NOT NULL, entry_time TEXT NOT NULL,
                exit_time TEXT, fee REAL);
        """)
        if not self.db.execute("SELECT 1 FROM slots").fetchone():
            for prefix, (vtype, count) in LAYOUT.items():
                for i in range(1, count + 1):
                    self.db.execute("INSERT INTO slots VALUES(?,?)",
                                    (f"{prefix}{i:02d}", vtype))
        self.db.commit()

    # ---------- helpers ----------
    @staticmethod
    def valid_plate(plate):
        return bool(re.fullmatch(r"[A-Z0-9\- ]{4,13}", plate))

    @staticmethod
    def fmt_duration(delta):
        mins = int(delta.total_seconds() // 60)
        d, rem = divmod(mins, 1440)
        h, m = divmod(rem, 60)
        parts = []
        if d:
            parts.append(f"{d} day{'s' if d > 1 else ''}")
        if h:
            parts.append(f"{h} hr")
        if m or not parts:
            parts.append(f"{m} min")
        return " ".join(parts)

    @staticmethod
    def calc_fee(vehicle_type, entry, exit_):
        hours = max(1, math.ceil((exit_ - entry).total_seconds() / 3600))
        return hours, hours * RATES[vehicle_type]

    def find_active(self, plate):
        return self.db.execute(
            "SELECT * FROM tickets WHERE plate=? AND exit_time IS NULL",
            (plate,)).fetchone()

    def slot_status(self):
        """Returns list of (slot_no, vehicle_type, plate or None)."""
        return [(r["slot_no"], r["vehicle_type"], r["plate"]) for r in
                self.db.execute("""
            SELECT s.slot_no, s.vehicle_type, t.plate FROM slots s
            LEFT JOIN tickets t ON t.slot_no=s.slot_no AND t.exit_time IS NULL
            ORDER BY s.slot_no""")]

    
    def park(self, plate, vehicle_type):
        plate = plate.strip().upper()
        if not self.valid_plate(plate):
            raise ValueError("Enter a valid plate number (4-13 letters/digits).")
        if self.find_active(plate):
            raise ValueError(f"{plate} is already parked.")
        free = self.db.execute("""
            SELECT slot_no FROM slots WHERE vehicle_type=? AND slot_no NOT IN
            (SELECT slot_no FROM tickets WHERE exit_time IS NULL)
            ORDER BY slot_no LIMIT 1""", (vehicle_type,)).fetchone()
        if not free:
            raise ValueError(f"No free {vehicle_type} slots available.")
        now = datetime.now().strftime(FMT)
        cur = self.db.execute(
            "INSERT INTO tickets(plate,vehicle_type,slot_no,entry_time) "
            "VALUES(?,?,?,?)", (plate, vehicle_type, free["slot_no"], now))
        self.db.commit()
        return {"ticket": cur.lastrowid, "plate": plate,
                "slot": free["slot_no"], "entry": now}

    def preview_checkout(self, plate):
        t = self.find_active(plate.strip().upper())
        if not t:
            raise ValueError("No active parking record for that plate.")
        entry = datetime.strptime(t["entry_time"], FMT)
        now = datetime.now()
        hours, fee = self.calc_fee(t["vehicle_type"], entry, now)
        return {"ticket": t["id"], "plate": t["plate"], "slot": t["slot_no"],
                "type": t["vehicle_type"], "entry": t["entry_time"],
                "exit": now.strftime(FMT), "hours": hours, "fee": fee,
                "duration": self.fmt_duration(now - entry)}

    def checkout(self, plate):
        bill = self.preview_checkout(plate)
        self.db.execute("UPDATE tickets SET exit_time=?, fee=? WHERE id=?",
                        (bill["exit"], bill["fee"], bill["ticket"]))
        self.db.commit()
        return bill

    def history(self, search=""):
        like = f"%{search.strip().upper()}%"
        return self.db.execute("""
            SELECT id, plate, vehicle_type, slot_no, entry_time, exit_time, fee
            FROM tickets WHERE plate LIKE ? OR slot_no LIKE ?
            ORDER BY id DESC""", (like, like)).fetchall()

    def stats(self):
        status = self.slot_status()
        total, used = len(status), sum(1 for s in status if s[2])
        today = datetime.now().strftime("%Y-%m-%d")
        rev = self.db.execute(
            "SELECT COALESCE(SUM(fee),0) FROM tickets WHERE exit_time LIKE ?",
            (today + "%",)).fetchone()[0]
        total_rev = self.db.execute(
            "SELECT COALESCE(SUM(fee),0) FROM tickets").fetchone()[0]
        per_type = {}
        for _, vt, plate in status:
            a, b = per_type.get(vt, (0, 0))
            per_type[vt] = (a + (1 if plate else 0), b + 1)
        return {"total": total, "used": used, "free": total - used,
                "today_rev": rev, "total_rev": total_rev, "per_type": per_type}



def run_gui():
    import tkinter as tk
    from tkinter import ttk

    ps = ParkingSystem()

    # ---- colour palette & font ----
    BG, CARD, BORDER = "#f3f5f9", "#ffffff", "#dde2ea"
    SIDE, SIDE_ON, SIDE_TXT = "#16213a", "#2457d6", "#c4cde0"
    PRI, TXT, MUT = "#2457d6", "#18212d", "#667386"
    FREE, OCC = "#2e9e5b", "#d64545"
    F = "Segoe UI"

    root = tk.Tk()
    root.title("Smart Parking Management System")
    root.geometry("1120x720")
    root.minsize(1000, 640)
    root.configure(bg=BG)

    st = ttk.Style()
    st.theme_use("clam")
    st.configure("Treeview", rowheight=30, font=(F, 10), background=CARD,
                 fieldbackground=CARD, foreground=TXT, borderwidth=0)
    st.configure("Treeview.Heading", font=(F, 10, "bold"), background=BG,
                 foreground=MUT, relief="flat")
    st.map("Treeview", background=[("selected", PRI)],
           foreground=[("selected", "white")])
    st.configure("Horizontal.TProgressbar", troughcolor=BORDER,
                 background=OCC, thickness=10, borderwidth=0)

    # ---- small widget helpers ----
    def button(parent, text, cmd, bg=PRI, fg="white"):
        return tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                         activebackground=bg, activeforeground=fg,
                         relief="flat", bd=0, padx=18, pady=8,
                         font=(F, 10, "bold"), cursor="hand2")

    def card(parent):
        return tk.Frame(parent, bg=CARD, highlightbackground=BORDER,
                        highlightthickness=1)

    def entry(parent, var, width=22):
        return tk.Entry(parent, textvariable=var, width=width, font=(F, 12),
                        relief="flat", bg=BG, fg=TXT, insertbackground=TXT,
                        highlightthickness=1, highlightbackground=BORDER,
                        highlightcolor=PRI)

    def label(parent, text, size=10, bold=False, fg=TXT, bg=CARD, **kw):
        return tk.Label(parent, text=text, bg=bg, fg=fg,
                        font=(F, size, "bold" if bold else "normal"), **kw)

    
    side = tk.Frame(root, bg=SIDE, width=210)
    side.pack(side="left", fill="y")
    side.pack_propagate(False)
    main = tk.Frame(root, bg=BG)
    main.pack(side="left", fill="both", expand=True)

    tk.Label(side, text="🅿", font=(F, 30, "bold"), bg=SIDE, fg="white"
             ).pack(pady=(24, 0))
    tk.Label(side, text="Smart Parking", font=(F, 14, "bold"), bg=SIDE,
             fg="white").pack()
    tk.Label(side, text="Management System", font=(F, 9), bg=SIDE,
             fg=SIDE_TXT).pack(pady=(0, 24))

    pages, nav = {}, {}
    page_area = tk.Frame(main, bg=BG)
    page_area.pack(fill="both", expand=True, padx=24, pady=(20, 4))
    page_area.rowconfigure(0, weight=1)
    page_area.columnconfigure(0, weight=1)

    def show(name):
        pages[name].tkraise()
        for n, b in nav.items():
            b.configure(bg=SIDE_ON if n == name else SIDE,
                        fg="white" if n == name else SIDE_TXT)
        if name == "Records":
            refresh_records()

    for name, icon in (("Dashboard", "▦"), ("Entry / Exit", "⇄"),
                       ("Records", "☰")):
        pages[name] = tk.Frame(page_area, bg=BG)
        pages[name].grid(row=0, column=0, sticky="nsew")
        nav[name] = tk.Button(side, text=f"  {icon}   {name}", anchor="w",
                              relief="flat", bd=0, padx=20, pady=12,
                              font=(F, 11), bg=SIDE, fg=SIDE_TXT,
                              activebackground=SIDE_ON, activeforeground="white",
                              cursor="hand2", command=lambda n=name: show(n))
        nav[name].pack(fill="x", pady=2)

    clock = tk.Label(side, bg=SIDE, fg=SIDE_TXT, font=(F, 10), justify="center")
    clock.pack(side="bottom", pady=20)

    toast = tk.Label(main, text="", bg=BG, fg=PRI, font=(F, 10, "bold"),
                     anchor="w")
    toast.pack(fill="x", padx=26, pady=(0, 10))
    toast_job = [None]

    def notify(msg, color=PRI):
        toast.configure(text=msg, fg=color)
        if toast_job[0]:
            root.after_cancel(toast_job[0])
        toast_job[0] = root.after(4000, lambda: toast.configure(text=""))

    # ---- pop-up dialog (tickets, bills) ----
    def dialog(title, rows, total=None, buttons=()):
        d = tk.Toplevel(root)
        d.title(title)
        d.configure(bg=CARD)
        d.transient(root)
        d.resizable(False, False)
        label(d, title, 15, True).pack(anchor="w", padx=26, pady=(20, 8))
        body = tk.Frame(d, bg=CARD)
        body.pack(fill="x", padx=26)
        body.columnconfigure(1, weight=1)
        for i, (k, v) in enumerate(rows):
            label(body, k, fg=MUT).grid(row=i, column=0, sticky="w", pady=3)
            label(body, v, bold=True).grid(row=i, column=1, sticky="e",
                                           padx=(50, 0))
        if total:
            label(d, total, 28, True, fg=PRI).pack(pady=14)
        bar = tk.Frame(d, bg=CARD)
        bar.pack(fill="x", padx=26, pady=(8, 20))
        for text, cmd, color in reversed(buttons):
            button(bar, text, lambda c=cmd: (d.destroy(), c() if c else None),
                   bg=color).pack(side="right", padx=(8, 0))
        d.update_idletasks()
        x = root.winfo_x() + (root.winfo_width() - d.winfo_width()) // 2
        y = root.winfo_y() + (root.winfo_height() - d.winfo_height()) // 3
        d.geometry(f"+{x}+{y}")
        d.grab_set()

    # ======================= Dashboard page =======================
    dash = pages["Dashboard"]
    label(dash, "Dashboard", 20, True, bg=BG).pack(anchor="w")
    label(dash, "Live overview of every parking slot", fg=MUT, bg=BG
          ).pack(anchor="w", pady=(0, 12))

    tiles = tk.Frame(dash, bg=BG)
    tiles.pack(fill="x")
    stat_vals = {}
    for i, (key, title) in enumerate((("occ", "Occupied"), ("free", "Free slots"),
                                      ("today", "Revenue today"),
                                      ("all", "All-time revenue"))):
        tiles.columnconfigure(i, weight=1, uniform="t")
        c = card(tiles)
        c.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 10, 0))
        stat_vals[key] = label(c, "-", 22, True)
        stat_vals[key].pack(anchor="w", padx=16, pady=(12, 0))
        label(c, title, 9, fg=MUT).pack(anchor="w", padx=16, pady=(0, 12))

    bar = ttk.Progressbar(dash, maximum=100, style="Horizontal.TProgressbar")
    bar.pack(fill="x", pady=(12, 4))
    bar_text = label(dash, "", 9, fg=MUT, bg=BG)
    bar_text.pack(anchor="w")

    slot_card = card(dash)
    slot_card.pack(fill="both", expand=True, pady=(10, 0))
    grid_frame = tk.Frame(slot_card, bg=CARD)
    grid_frame.pack(fill="both", expand=True, padx=14, pady=10)
    legend = tk.Frame(slot_card, bg=CARD)
    legend.pack(anchor="w", padx=14, pady=(0, 10))
    label(legend, "■ Free", 9, True, fg=FREE).pack(side="left")
    label(legend, "   ■ Occupied (click a red slot to check out)", 9, True,
          fg=OCC).pack(side="left")

    def refresh_dashboard():
        s = ps.stats()
        stat_vals["occ"].configure(text=f"{s['used']} / {s['total']}")
        stat_vals["free"].configure(text=str(s["free"]))
        stat_vals["today"].configure(text=f"₹{s['today_rev']:.0f}")
        stat_vals["all"].configure(text=f"₹{s['total_rev']:.0f}")
        pct = s["used"] / s["total"] * 100
        bar["value"] = pct
        bar_text.configure(text=f"Lot is {pct:.0f}% full")
        for w in grid_frame.winfo_children():
            w.destroy()
        by_type = {}
        for slot, vtype, plate in ps.slot_status():
            by_type.setdefault(vtype, []).append((slot, plate))
        for vtype, items in by_type.items():
            used = sum(1 for _, p in items if p)
            label(grid_frame, f"{vtype} slots  ({used}/{len(items)} occupied)",
                  10, True).pack(anchor="w", pady=(6, 3))
            row = tk.Frame(grid_frame, bg=CARD)
            row.pack(anchor="w")
            for i, (slot, plate) in enumerate(items):
                lb = tk.Label(row, text=f"{slot}\n{plate or 'Free'}", width=10,
                              height=3, wraplength=80, fg="white",
                              bg=OCC if plate else FREE, font=(F, 8, "bold"),
                              cursor="hand2" if plate else "arrow")
                lb.grid(row=i // 10, column=i % 10, padx=3, pady=3)
                if plate:
                    lb.bind("<Button-1>", lambda e, p=plate: start_checkout(p))

    # ====================== Entry / Exit page ======================
    ops = pages["Entry / Exit"]
    label(ops, "Entry / Exit", 20, True, bg=BG).pack(anchor="w")
    label(ops, "Park a vehicle or check one out and collect payment", fg=MUT,
          bg=BG).pack(anchor="w", pady=(0, 12))
    cols = tk.Frame(ops, bg=BG)
    cols.pack(fill="x")
    cols.columnconfigure((0, 1), weight=1, uniform="c")

    # -- entry card
    ec = card(cols)
    ec.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    label(ec, "Vehicle entry", 13, True).pack(anchor="w", padx=18, pady=(16, 8))
    label(ec, "Plate number", 9, fg=MUT).pack(anchor="w", padx=18)
    plate_in = tk.StringVar()
    e1 = entry(ec, plate_in)
    e1.pack(anchor="w", padx=18, pady=(2, 10), ipady=6)
    label(ec, "Vehicle type", 9, fg=MUT).pack(anchor="w", padx=18)
    type_var = tk.StringVar(value="Car")
    seg = tk.Frame(ec, bg=CARD)
    seg.pack(anchor="w", padx=18, pady=(2, 14))
    seg_btns = {}

    def pick(t):
        type_var.set(t)
        for k, b in seg_btns.items():
            b.configure(bg=PRI if k == t else BG, fg="white" if k == t else TXT)

    for t in RATES:
        seg_btns[t] = tk.Button(seg, text=f"{t}\n₹{RATES[t]}/hr", width=9,
                                relief="flat", bd=0, pady=6, font=(F, 9, "bold"),
                                cursor="hand2", command=lambda t=t: pick(t))
        seg_btns[t].pack(side="left", padx=(0, 6))
    pick("Car")

    def do_park():
        try:
            t = ps.park(plate_in.get(), type_var.get())
        except ValueError as e:
            return notify(str(e), OCC)
        plate_in.set("")
        refresh_all()
        dialog(f"Ticket #{t['ticket']}",
               [("Plate", t["plate"]), ("Slot", t["slot"]),
                ("Entry", t["entry"])], buttons=[("Done", None, PRI)])

    button(ec, "Park vehicle", do_park).pack(anchor="w", padx=18, pady=(0, 18))
    e1.bind("<Return>", lambda e: do_park())

    # -- exit card
    xc = card(cols)
    xc.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
    label(xc, "Exit & billing", 13, True).pack(anchor="w", padx=18, pady=(16, 8))
    label(xc, "Plate number", 9, fg=MUT).pack(anchor="w", padx=18)
    plate_out = tk.StringVar()
    e2 = entry(xc, plate_out)
    e2.pack(anchor="w", padx=18, pady=(2, 10), ipady=6)
    info = label(xc, "Type a plate to see its running bill", 10, fg=MUT,
                 justify="left", wraplength=360)
    info.pack(anchor="w", padx=18, pady=(0, 14))

    def lookup(*_):
        p = plate_out.get().strip().upper()
        if not p:
            return info.configure(text="Type a plate to see its running bill",
                                  fg=MUT)
        try:
            b = ps.preview_checkout(p)
            info.configure(fg=TXT, text=f"{b['plate']} · slot {b['slot']} · "
                           f"parked {b['duration']} · ₹{b['fee']} due")
        except ValueError:
            info.configure(text="No active vehicle with that plate", fg=MUT)

    plate_out.trace_add("write", lookup)

    def start_checkout(plate):
        try:
            b = ps.preview_checkout(plate)
        except ValueError as e:
            return notify(str(e), OCC)

        def confirm():
            ps.checkout(plate)
            plate_out.set("")
            refresh_all()
            notify(f"Payment of ₹{b['fee']} received. Slot {b['slot']} is free.",
                   FREE)

        dialog(f"Bill - {b['plate']}",
               [("Slot", f"{b['slot']} ({b['type']})"), ("Entry", b["entry"]),
                ("Exit", b["exit"]),
                ("Time parked", b["duration"]),
                ("Billed hours", str(b["hours"]))],
               total=f"₹{b['fee']}",
               buttons=[("Cancel", None, "#8a95a5"),
                        ("Confirm payment", confirm, FREE)])

    button(xc, "Checkout", lambda: start_checkout(plate_out.get().strip().upper())
           ).pack(anchor="w", padx=18, pady=(0, 18))
    e2.bind("<Return>", lambda e: start_checkout(plate_out.get().strip().upper()))

    # ========================= Records page =========================
    rec = pages["Records"]
    label(rec, "Records", 20, True, bg=BG).pack(anchor="w")
    label(rec, "Complete parking history", fg=MUT, bg=BG
          ).pack(anchor="w", pady=(0, 10))
    top = tk.Frame(rec, bg=BG)
    top.pack(fill="x", pady=(0, 8))
    label(top, "Search plate / slot:", 10, bg=BG, fg=MUT).pack(side="left")
    search_var = tk.StringVar()
    entry(top, search_var, 24).pack(side="left", padx=8, ipady=4)

    wrap = card(rec)
    wrap.pack(fill="both", expand=True)
    cols_ = ("ID", "Plate", "Type", "Slot", "Entry", "Exit", "Fee", "Status")
    tree = ttk.Treeview(wrap, columns=cols_, show="headings")
    for c, w in zip(cols_, (50, 130, 70, 60, 150, 150, 70, 90)):
        tree.heading(c, text=c)
        tree.column(c, width=w, anchor="center")
    tree.tag_configure("parked", foreground=OCC)
    tree.tag_configure("done", foreground=FREE)
    sb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    tree.pack(fill="both", expand=True, padx=2, pady=2)

    def refresh_records(*_):
        tree.delete(*tree.get_children())
        for r in ps.history(search_var.get()):
            parked = r["exit_time"] is None
            tree.insert("", "end", tags=("parked" if parked else "done",),
                        values=(r["id"], r["plate"], r["vehicle_type"],
                                r["slot_no"], r["entry_time"],
                                r["exit_time"] or "-",
                                "" if r["fee"] is None else f"₹{r['fee']:.0f}",
                                "Parked" if parked else "Completed"))

    search_var.trace_add("write", refresh_records)

    
    def refresh_all():
        refresh_dashboard()
        refresh_records()
        lookup()

    def tick():
        now = datetime.now()
        clock.configure(text=now.strftime("%d %b %Y\n%I:%M:%S %p"))
        root.after(1000, tick)

    def auto_refresh():
        refresh_dashboard()
        root.after(30000, auto_refresh)

    tick()
    root.after(30000, auto_refresh)
    refresh_all()
    show("Dashboard")
    root.mainloop()


if __name__ == "__main__":
    run_gui()
