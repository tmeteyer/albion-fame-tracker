"""
Interface graphique principale — Albion Online Fame/Silver Tracker
"""
import os
import collections
import queue
import sys
import time
import threading
import socket as _socket
import struct as _struct
import tkinter as tk
from tkinter import ttk, messagebox

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.albion import load_config, save_config, is_fame_event, is_silver_event, extract_fame, extract_silver
from core.capture import CaptureThread, list_local_ips
from core.tracker import SessionTracker
from core.photon import MSG_EVENT
import core.history as history

# ─── Thème ───────────────────────────────────────────────────────────────────
BG      = "#09090f"
SURFACE = "#0f0f18"
CARD    = "#131320"
ACCENT  = "#c84b68"
FAME_C  = "#5bc4f5"
SILV_C  = "#f0c040"
TIME_C  = "#9b8ff5"
TEXT    = "#d2d2e8"
MUTED   = "#46465e"
SEP     = "#1e1e30"
GREEN   = "#3dca88"
RED     = "#d95555"

FT       = ("Segoe UI", 10)
FT_BOLD  = ("Segoe UI", 10, "bold")
FT_NUM   = ("Segoe UI", 30, "bold")
FT_ICON  = ("Segoe UI", 18)
FT_TITLE = ("Segoe UI", 12, "bold")
FT_SMALL = ("Segoe UI", 9)
FT_MONO  = ("Consolas", 9)

REFRESH_MS  = 500
QUEUE_DRAIN = 50


class AlbionTrackerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Albion Tracker")
        self.geometry("640x360")
        self.minsize(600, 320)
        self.configure(bg=BG)
        self.resizable(True, True)

        self.cfg = load_config()
        self.tracker = SessionTracker()
        self.pkt_queue: queue.Queue = queue.Queue()
        self.capture_thread: CaptureThread | None = None
        self._raw_buffer: collections.deque = collections.deque(maxlen=2000)
        self._pkt_count = 0
        self._player_id: int | None = None  # entity ID détecté via UpdateMoney (app_code=81)

        self._build_ui()
        self._schedule_refresh()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─── Construction UI ─────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()
        self._build_notebook()

    def _build_header(self):
        h = tk.Frame(self, bg=BG)
        h.pack(fill="x", padx=14, pady=(12, 0))

        tk.Label(h, text="⚔  Albion Tracker", font=FT_TITLE,
                 bg=BG, fg=TEXT).pack(side="left")

        ctrl = tk.Frame(h, bg=BG)
        ctrl.pack(side="right")

        self._lbl_status = tk.Label(ctrl, text="● Inactif",
                                    font=FT_SMALL, bg=BG, fg=MUTED)
        self._lbl_status.pack(side="left", padx=(0, 14))

        tk.Button(ctrl, text="↺", bg=SURFACE, fg=MUTED,
                  font=FT, relief="flat", cursor="hand2",
                  padx=8, pady=3,
                  command=self._reset_session).pack(side="left", padx=(0, 4))

        tk.Button(ctrl, text="💾", bg=SURFACE, fg=SILV_C,
                  font=FT, relief="flat", cursor="hand2",
                  padx=8, pady=3,
                  command=self._save_session).pack(side="left", padx=(0, 4))

        self._btn_toggle = tk.Button(
            ctrl, text="▶  Démarrer",
            bg=GREEN, fg="#060610", font=FT_BOLD,
            relief="flat", cursor="hand2", padx=14, pady=3,
            command=self._toggle_capture
        )
        self._btn_toggle.pack(side="left")

        # Séparateur
        tk.Frame(self, bg=SEP, height=1).pack(fill="x", padx=0, pady=(10, 0))

    def _build_notebook(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG, foreground=MUTED,
                        padding=[12, 5], font=FT_SMALL)
        style.map("TNotebook.Tab",
                  background=[("selected", CARD)],
                  foreground=[("selected", TEXT)])

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=8)

        self._tab_stats = tk.Frame(self.nb, bg=BG)
        self._tab_hist  = tk.Frame(self.nb, bg=BG)
        self._tab_log   = tk.Frame(self.nb, bg=BG)
        self._tab_disc  = tk.Frame(self.nb, bg=BG)
        self._tab_cfg   = tk.Frame(self.nb, bg=BG)

        self.nb.add(self._tab_stats, text="  Stats  ")
        self.nb.add(self._tab_hist,  text="  Historique  ")
        self.nb.add(self._tab_log,   text="  Journal  ")
        self.nb.add(self._tab_disc,  text="  Découverte  ")
        self.nb.add(self._tab_cfg,   text="  Config  ")

        self._build_stats_tab()
        self._build_history_tab()
        self._build_log_tab()
        self._build_discovery_tab()
        self._build_config_tab()

    def _stat_card(self, parent, row, col, icon, color, label) -> tuple:
        """Carte stat avec barre d'accent colorée, icône et labels."""
        outer = tk.Frame(parent, bg=CARD)
        outer.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")

        # Barre d'accent colorée en haut
        tk.Frame(outer, bg=color, height=3).pack(fill="x")

        inner = tk.Frame(outer, bg=CARD)
        inner.pack(fill="both", expand=True, padx=14, pady=(10, 12))

        # Icône + label sur une ligne
        hdr = tk.Frame(inner, bg=CARD)
        hdr.pack(anchor="w")
        tk.Label(hdr, text=icon, font=FT_ICON, bg=CARD, fg=color).pack(side="left")
        tk.Label(hdr, text=f"  {label}", font=FT_BOLD, bg=CARD, fg=TEXT).pack(side="left", pady=(4, 0))

        # Total (grand chiffre)
        lbl_total = tk.Label(inner, text="0", font=FT_NUM, bg=CARD, fg=color)
        lbl_total.pack(anchor="w", pady=(4, 0))

        # Taux /h
        lbl_rate = tk.Label(inner, text="— / h", font=FT, bg=CARD, fg=MUTED)
        lbl_rate.pack(anchor="w", pady=(2, 0))

        return lbl_total, lbl_rate

    def _build_stats_tab(self):
        p = self._tab_stats
        for i in range(3):
            p.columnconfigure(i, weight=1)
        p.rowconfigure(0, weight=1)
        p.rowconfigure(1, weight=0)

        self._lbl_fame_total, self._lbl_fame_rate = self._stat_card(
            p, 0, 0, "★", FAME_C, "RENOMMÉE")

        self._lbl_silv_total, self._lbl_silv_rate = self._stat_card(
            p, 0, 1, "◈", SILV_C, "ARGENT")

        # ── Timer ──
        tc = tk.Frame(p, bg=CARD)
        tc.grid(row=0, column=2, padx=5, pady=5, sticky="nsew")
        tk.Frame(tc, bg=TIME_C, height=3).pack(fill="x")
        inner_t = tk.Frame(tc, bg=CARD)
        inner_t.pack(fill="both", expand=True, padx=14, pady=(10, 12))
        hdr_t = tk.Frame(inner_t, bg=CARD)
        hdr_t.pack(anchor="w")
        tk.Label(hdr_t, text="◷", font=FT_ICON, bg=CARD, fg=TIME_C).pack(side="left")
        tk.Label(hdr_t, text="  DURÉE", font=FT_BOLD, bg=CARD, fg=TEXT).pack(side="left", pady=(4, 0))
        self._lbl_timer = tk.Label(inner_t, text="00:00:00", font=FT_NUM, bg=CARD, fg=TIME_C)
        self._lbl_timer.pack(anchor="w", pady=(4, 0))

        # Compteur paquets
        self._lbl_pkt_count = tk.Label(p, text="", font=("Consolas", 7),
                                       bg=BG, fg=MUTED)
        self._lbl_pkt_count.grid(row=1, column=0, columnspan=3, pady=(0, 2))

    def _build_log_tab(self):
        p = self._tab_log
        p.columnconfigure(0, weight=1)
        p.rowconfigure(0, weight=1)

        cols = ("Heure", "Type", "Montant", "Détails")
        self._tree = ttk.Treeview(p, columns=cols, show="headings", height=14)

        style = ttk.Style()
        style.configure("Treeview", background=CARD, foreground=TEXT,
                        fieldbackground=CARD, font=FT_MONO, rowheight=22)
        style.configure("Treeview.Heading", background=SURFACE, foreground=MUTED,
                        font=FT_SMALL)
        style.map("Treeview", background=[("selected", CARD)])

        for col, w in zip(cols, [60, 56, 76, 440]):
            self._tree.heading(col, text=col)
            self._tree.column(col, width=w, anchor="w")

        self._tree.tag_configure("fame",   foreground=FAME_C)
        self._tree.tag_configure("silver", foreground=SILV_C)

        sb = ttk.Scrollbar(p, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        sb.grid(row=0, column=1, sticky="ns", pady=6)

        tk.Button(p, text="Vider", bg=SURFACE, fg=MUTED,
                  font=FT, relief="flat", cursor="hand2",
                  command=self._clear_log).grid(row=1, column=0, pady=(0, 4))

    def _build_discovery_tab(self):
        p = self._tab_disc
        p.columnconfigure(0, weight=1)
        p.rowconfigure(1, weight=1)

        info = "Tue un mob → clique Capturer → affiche les paquets des 3 dernières secondes (S→C)."
        tk.Label(p, text=info, font=FT, bg=BG, fg=MUTED,
                 justify="left", wraplength=640).pack(anchor="w", padx=10, pady=(6, 2))

        btn_f = tk.Frame(p, bg=BG)
        btn_f.pack(fill="x", padx=6, pady=2)

        self._btn_capture = tk.Button(
            btn_f, text="Capturer (3s)",
            bg=ACCENT, fg="white", font=FT_BOLD,
            relief="flat", cursor="hand2", padx=10, pady=2,
            command=self._snapshot_discovery
        )
        self._btn_capture.pack(side="left", padx=2)

        tk.Button(btn_f, text="Vider", bg=SURFACE, fg=MUTED,
                  font=FT, relief="flat", cursor="hand2",
                  command=self._clear_discovery).pack(side="left", padx=2)

        self._lbl_snap_info = tk.Label(btn_f, text="", font=FT, bg=BG, fg=SILV_C)
        self._lbl_snap_info.pack(side="left", padx=8)

        cols = ("Heure", "Dir", "Code", "Params")
        self._disc_tree = ttk.Treeview(p, columns=cols, show="headings", height=14)
        for col, w in zip(cols, [65, 45, 50, 520]):
            self._disc_tree.heading(col, text=col)
            self._disc_tree.column(col, width=w,
                                   anchor="center" if col in ("Heure","Dir","Code") else "w")

        sb2 = ttk.Scrollbar(p, orient="vertical", command=self._disc_tree.yview)
        self._disc_tree.configure(yscrollcommand=sb2.set)
        self._disc_tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=4)
        sb2.pack(side="left", fill="y", pady=4)

    def _build_config_tab(self):
        p = self._tab_cfg
        p.columnconfigure(1, weight=1)

        def row_entry(label, row, getter, hint=""):
            tk.Label(p, text=label, font=FT, bg=BG,
                     fg=TEXT).grid(row=row, column=0, sticky="w", padx=12, pady=4)
            e = tk.Entry(p, font=FT, bg=SURFACE, fg=TEXT,
                         insertbackground=TEXT, relief="flat", width=26)
            e.insert(0, getter())
            e.grid(row=row, column=1, sticky="ew", padx=6, pady=4)
            if hint:
                tk.Label(p, text=hint, font=("Segoe UI", 8), bg=BG,
                         fg=MUTED).grid(row=row, column=2, sticky="w", padx=2)
            return e

        self._entry_fame_codes = row_entry(
            "Codes Fame", 0,
            lambda: ", ".join(str(x) for x in self.cfg.get("fame_event_codes", [])),
            hint="ex: 82")
        self._entry_silv_codes = row_entry(
            "Codes Silver", 1,
            lambda: ", ".join(str(x) for x in self.cfg.get("silver_event_codes", [])),
            hint="ex: 62")
        self._entry_fame_keys = row_entry(
            "Params Fame", 2,
            lambda: ", ".join(str(x) for x in self.cfg.get("fame_param_keys", [2])),
            hint="ex: 2")
        self._entry_silv_keys = row_entry(
            "Params Silver", 3,
            lambda: ", ".join(str(x) for x in self.cfg.get("silver_param_keys", [3])),
            hint="ex: 3")

        # ── Interface réseau ──
        tk.Label(p, text="Interface réseau", font=FT, bg=BG,
                 fg=TEXT).grid(row=4, column=0, sticky="w", padx=12, pady=4)

        iface_frame = tk.Frame(p, bg=BG)
        iface_frame.grid(row=4, column=1, columnspan=2, sticky="ew", padx=6, pady=4)

        self._iface_var = tk.StringVar(value=self.cfg.get("network_ip", "") or "auto")
        self._iface_combo = ttk.Combobox(iface_frame, textvariable=self._iface_var,
                                         font=FT, width=22, state="readonly")
        self._iface_combo.pack(side="left")
        self._refresh_ifaces()

        tk.Button(iface_frame, text="↺", bg=SURFACE, fg=MUTED,
                  font=FT, relief="flat", cursor="hand2", padx=6,
                  command=self._refresh_ifaces).pack(side="left", padx=4)

        self._var_debug = tk.BooleanVar(value=self.cfg.get("debug_mode", True))
        tk.Checkbutton(p, text="Mode découverte (log tous les événements)",
                       variable=self._var_debug,
                       bg=BG, fg=TEXT, selectcolor=SURFACE,
                       font=FT, activebackground=BG,
                       activeforeground=TEXT).grid(
            row=5, column=0, columnspan=3, sticky="w", padx=12, pady=6)

        tk.Button(p, text="Sauvegarder", bg=ACCENT, fg="white",
                  font=FT_BOLD, relief="flat", cursor="hand2",
                  command=self._save_config).grid(
            row=6, column=0, columnspan=3, pady=8)

        self._lbl_cfg_status = tk.Label(p, text="", font=FT, bg=BG, fg=GREEN)
        self._lbl_cfg_status.grid(row=7, column=0, columnspan=3)

        tk.Label(p, text=f"config : {os.path.abspath('config.json')}",
                 font=("Segoe UI", 8), bg=BG, fg=MUTED).grid(
            row=8, column=0, columnspan=3, pady=2)

        tk.Button(p, text="Diagnostic réseau (5s)", bg=SURFACE, fg=TEXT,
                  font=FT, relief="flat", cursor="hand2",
                  command=self._run_diag).grid(row=9, column=0, columnspan=3, pady=(12, 2))

        self._lbl_diag = tk.Label(p, text="", font=FT, bg=BG, fg=MUTED,
                                  wraplength=580, justify="left")
        self._lbl_diag.grid(row=10, column=0, columnspan=3, padx=12)

    # ─── Actions ─────────────────────────────────────────────────────────────

    def _build_history_tab(self):
        p = self._tab_hist
        p.columnconfigure(0, weight=1)
        p.rowconfigure(0, weight=1)

        cols = ("Titre", "Date", "Durée", "Fame", "Silver")
        self._hist_tree = ttk.Treeview(p, columns=cols, show="headings", height=12)

        widths = [180, 110, 70, 100, 100]
        for col, w in zip(cols, widths):
            self._hist_tree.heading(col, text=col)
            self._hist_tree.column(col, width=w, anchor="w" if col == "Titre" else "e")

        self._hist_tree.tag_configure("row", background=CARD, foreground=TEXT)

        sb = ttk.Scrollbar(p, orient="vertical", command=self._hist_tree.yview)
        self._hist_tree.configure(yscrollcommand=sb.set)
        self._hist_tree.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        sb.grid(row=0, column=1, sticky="ns", pady=6)

        btn_f = tk.Frame(p, bg=BG)
        btn_f.grid(row=1, column=0, columnspan=2, pady=(0, 6))
        tk.Button(btn_f, text="Supprimer la sélection", bg=SURFACE, fg=RED,
                  font=FT, relief="flat", cursor="hand2",
                  command=self._delete_history_entry).pack()

        self._refresh_history()

    def _refresh_history(self):
        for item in self._hist_tree.get_children():
            self._hist_tree.delete(item)

        def fmt(n):
            if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
            if n >= 1_000:     return f"{n/1_000:.0f}K"
            return str(n)

        def dur(s):
            h, r = divmod(int(s), 3600)
            m, sc = divmod(r, 60)
            return f"{h:02d}:{m:02d}:{sc:02d}" if h else f"{m:02d}:{sc:02d}"

        for entry in history.load():
            self._hist_tree.insert("", "end", iid=entry['id'], tags=("row",), values=(
                entry.get('title', ''),
                f"{entry.get('date','')} {entry.get('time','')}",
                dur(entry.get('duration_seconds', 0)),
                fmt(entry.get('total_fame', 0)),
                fmt(entry.get('total_silver', 0)),
            ))

    def _delete_history_entry(self):
        selected = self._hist_tree.selection()
        if not selected:
            return
        for iid in selected:
            history.delete(iid)
        self._refresh_history()

    def _save_session(self):
        t = self.tracker
        if t.total_fame == 0 and t.total_silver == 0:
            messagebox.showinfo("Session vide", "Aucune donnée à sauvegarder.")
            return

        # Dialog titre
        dialog = tk.Toplevel(self)
        dialog.title("Sauvegarder la session")
        dialog.configure(bg=BG)
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        # Centrer
        self.update_idletasks()
        x = self.winfo_x() + self.winfo_width() // 2 - 160
        y = self.winfo_y() + self.winfo_height() // 2 - 60
        dialog.geometry(f"320x120+{x}+{y}")

        tk.Label(dialog, text="Titre de la session", font=FT, bg=BG, fg=TEXT).pack(pady=(16, 4))
        default = f"Session {time.strftime('%d/%m %H:%M')}"
        entry_var = tk.StringVar(value=default)
        entry = tk.Entry(dialog, textvariable=entry_var, font=FT,
                         bg=SURFACE, fg=TEXT, insertbackground=TEXT,
                         relief="flat", width=34)
        entry.pack(padx=20)
        entry.select_range(0, "end")
        entry.focus_set()

        def confirm(event=None):
            title = entry_var.get().strip() or default
            history.add(title, t.elapsed_seconds, t.total_fame, t.total_silver)
            self._refresh_history()
            dialog.destroy()
            self.nb.select(1)  # Aller sur l'onglet Historique

        def cancel(event=None):
            dialog.destroy()

        btn_f = tk.Frame(dialog, bg=BG)
        btn_f.pack(pady=10)
        tk.Button(btn_f, text="Sauvegarder", bg=GREEN, fg="#060610",
                  font=FT_BOLD, relief="flat", cursor="hand2",
                  padx=10, command=confirm).pack(side="left", padx=4)
        tk.Button(btn_f, text="Annuler", bg=SURFACE, fg=MUTED,
                  font=FT, relief="flat", cursor="hand2",
                  padx=10, command=cancel).pack(side="left", padx=4)

        entry.bind("<Return>", confirm)
        entry.bind("<Escape>", cancel)

    def _refresh_ifaces(self):
        ips = list_local_ips()
        values = ["auto"] + ips
        self._iface_combo["values"] = values
        current = self._iface_var.get()
        if current not in values:
            self._iface_var.set("auto")

    def _toggle_capture(self):
        if self.capture_thread and self.capture_thread.is_alive():
            self._stop_capture()
        else:
            self._start_capture()

    def _start_capture(self):
        self.cfg = load_config()
        chosen = self.cfg.get("network_ip", "") or None
        self.capture_thread = CaptureThread(self.pkt_queue,
                                            debug_mode=self.cfg.get("debug_mode", True),
                                            network_ip=chosen)
        self.capture_thread.start()
        self.tracker.start()
        self._btn_toggle.configure(text="⏹  Arrêter", bg=RED, fg="white")
        self.after(800, self._update_iface_status)

    def _update_iface_status(self):
        if self.capture_thread and self.capture_thread.is_alive():
            iface = self.capture_thread.iface_name or "?"
            self._lbl_status.configure(text=f"● {iface}", fg=GREEN)

    def _stop_capture(self):
        if self.capture_thread:
            self.capture_thread.stop()
            self.capture_thread = None
        self.tracker.stop()
        self._btn_toggle.configure(text="▶  Démarrer", bg=GREEN, fg="#0a0a10")
        self._lbl_status.configure(text="● Inactif", fg=MUTED)

    def _reset_session(self):
        self.tracker.reset()
        self._clear_log()
        self._pkt_count = 0
        self._player_id = None
        self._lbl_pkt_count.configure(text="")

    def _clear_log(self):
        for item in self._tree.get_children():
            self._tree.delete(item)

    def _clear_discovery(self):
        for item in self._disc_tree.get_children():
            self._disc_tree.delete(item)

    def _run_diag(self):
        self._lbl_diag.configure(text="Capture en cours (5s)…", fg=MUTED)
        self.update_idletasks()

        result = {"udp_total": 0, "port_5056": 0, "error": None}

        def _diag():
            try:
                from core.capture import _get_local_ip, is_admin
                if not is_admin():
                    result["error"] = "Droits administrateur requis."
                    return
                local_ip = _get_local_ip()
                sock = _socket.socket(_socket.AF_INET, _socket.SOCK_RAW, _socket.IPPROTO_UDP)
                sock.bind((local_ip, 0))
                sock.setsockopt(_socket.IPPROTO_IP, _socket.IP_HDRINCL, 1)
                sock.ioctl(_socket.SIO_RCVALL, _socket.RCVALL_ON)
                sock.settimeout(1.0)
                deadline = time.time() + 5.0
                try:
                    while time.time() < deadline:
                        try:
                            data, _ = sock.recvfrom(65535)
                        except _socket.timeout:
                            continue
                        if len(data) < 20 or data[9] != 17:
                            continue
                        ihl = (data[0] & 0x0F) * 4
                        if len(data) < ihl + 8:
                            continue
                        result["udp_total"] += 1
                        sport = _struct.unpack_from('>H', data, ihl)[0]
                        dport = _struct.unpack_from('>H', data, ihl + 2)[0]
                        if sport == 5056 or dport == 5056:
                            result["port_5056"] += 1
                finally:
                    try:
                        sock.ioctl(_socket.SIO_RCVALL, _socket.RCVALL_OFF)
                    except OSError:
                        pass
                    sock.close()
            except Exception as e:
                result["error"] = str(e)

        threading.Thread(target=_diag, daemon=True).start()
        self.after(5500, lambda: self._show_diag(result))

    def _show_diag(self, result: dict):
        if result["error"]:
            self._lbl_diag.configure(text=f"Erreur : {result['error']}", fg=RED)
        elif result["udp_total"] == 0:
            self._lbl_diag.configure(
                text="0 paquet UDP capturé — lancez en administrateur.", fg=RED)
        elif result["port_5056"] == 0:
            self._lbl_diag.configure(
                text=f"{result['udp_total']} paquets UDP, mais 0 sur le port 5056. "
                     "Connectez-vous à un monde Albion.", fg=SILV_C)
        else:
            self._lbl_diag.configure(
                text=f"OK — {result['udp_total']} paquets UDP, "
                     f"{result['port_5056']} sur le port 5056.", fg=GREEN)

    def _save_config(self):
        def parse_ints(s):
            try:
                return [int(x.strip()) for x in s.split(",") if x.strip()]
            except ValueError:
                return []

        self.cfg["fame_event_codes"]   = parse_ints(self._entry_fame_codes.get())
        self.cfg["silver_event_codes"] = parse_ints(self._entry_silv_codes.get())
        self.cfg["fame_param_keys"]    = parse_ints(self._entry_fame_keys.get())
        self.cfg["silver_param_keys"]  = parse_ints(self._entry_silv_keys.get())
        chosen = self._iface_var.get()
        self.cfg["network_ip"]         = "" if chosen == "auto" else chosen
        self.cfg["debug_mode"]         = self._var_debug.get()
        save_config(self.cfg)
        self._lbl_cfg_status.configure(text="✓ Sauvegardé")
        self.after(3000, lambda: self._lbl_cfg_status.configure(text=""))

    # ─── Boucle de rafraîchissement ──────────────────────────────────────────

    def _schedule_refresh(self):
        self.after(REFRESH_MS, self._refresh)

    def _refresh(self):
        self._drain_queue()
        self._update_stats()
        self._check_capture_error()
        self._schedule_refresh()

    def _drain_queue(self):
        count = 0
        while count < QUEUE_DRAIN:
            try:
                entry = self.pkt_queue.get_nowait()
            except queue.Empty:
                break
            self._process_entry(entry)
            count += 1
        self._pkt_count += count
        if self.capture_thread:
            t = self.capture_thread
            pid = f"  id:{self._player_id}" if self._player_id else "  id:?"
            self._lbl_pkt_count.configure(
                text=f"reçus {t.raw_count}  parsés {t.parsed_count}  "
                     f"frags {t.frag_count}/{t.frag_done}{pid}")

    def _process_entry(self, entry: dict):
        if entry.get('mode') == 'raw':
            self._update_discovery_raw(entry)
            return

        code     = entry.get('code', 0)
        msg_type = entry.get('type', 0)
        params   = entry.get('params', {})
        is_event = msg_type == MSG_EVENT
        app_code = params.get(252, code)

        if is_event:
            self._update_discovery(app_code, params, entry.get('dir', 'S→C'))

        # UpdateMoney (81) : fire uniquement pour notre personnage → détection fiable de l'entity ID
        if is_event and app_code == 81 and self._player_id is None:
            eid = params.get(0)
            if isinstance(eid, int):
                self._player_id = eid

        entity_id = params.get(0)
        is_mine = self._player_id is None or entity_id == self._player_id

        if is_event and is_mine and is_fame_event(app_code, self.cfg):
            amount = extract_fame(params, self.cfg)
            if amount > 0:
                self.tracker.add_fame(amount, source=f"event {app_code}")
                self._log_row("fame", amount, params)

        if is_event and is_mine and is_silver_event(app_code, self.cfg):
            amount = extract_silver(params, self.cfg)
            if amount > 0:
                self.tracker.add_silver(amount, source=f"event {app_code}")
                self._log_row("silver", amount, params)

    def _log_row(self, kind: str, amount: int, params: dict):
        ts     = time.strftime("%H:%M:%S")
        label  = "Fame" if kind == "fame" else "Silver"
        detail = "  ".join(f"{k}:{v}" for k, v in list(params.items())[:5])[:80]
        self._tree.insert("", 0, values=(ts, label, f"+{amount:,}", detail),
                          tags=(kind,))
        children = self._tree.get_children()
        if len(children) > 200:
            self._tree.delete(children[-1])

    def _update_discovery(self, code: int, params: dict, direction: str = "S→C"):
        self._raw_buffer.append({
            'ts': time.time(), 'dir': direction,
            'code': code, 'params': params,
        })

    def _update_discovery_raw(self, entry: dict):
        self._raw_buffer.append(entry)

    def _snapshot_discovery(self):
        cutoff = time.time() - 3.0
        recent = [e for e in self._raw_buffer if e.get('ts', 0) >= cutoff]

        for item in self._disc_tree.get_children():
            self._disc_tree.delete(item)

        for e in recent:
            ts_str  = time.strftime("%H:%M:%S", time.localtime(e.get('ts', 0)))
            summary = "  ".join(f"{k}:{v}" for k, v in list(e.get('params', {}).items())[:8])[:120]
            self._disc_tree.insert("", "end", values=(
                ts_str, e.get('dir', '?'), e.get('code', '?'), summary))

        self._lbl_snap_info.configure(
            text=f"{len(recent)} événement(s)")

    def _update_stats(self):
        t = self.tracker
        self._lbl_timer.configure(text=t.elapsed_str)

        def fmt(n: float) -> str:
            if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
            if n >= 1_000:     return f"{n/1_000:.0f}K"
            return str(int(n))

        running = t.running
        self._lbl_fame_total.configure(text=f"{t.total_fame:,}")
        self._lbl_fame_rate.configure(text=f"{fmt(t.instant_fame_per_hour)} / h" if running else "— / h")

        self._lbl_silv_total.configure(text=f"{t.total_silver:,}")
        self._lbl_silv_rate.configure(text=f"{fmt(t.instant_silver_per_hour)} / h" if running else "— / h")

    def _check_capture_error(self):
        if self.capture_thread and self.capture_thread.error:
            err = self.capture_thread.error
            self.capture_thread = None
            self.tracker.stop()
            self._btn_toggle.configure(text="▶  Démarrer", bg=GREEN, fg="#0a0a10")
            self._lbl_status.configure(text="● Erreur", fg=RED)
            messagebox.showerror("Erreur de capture", err)

    def _on_close(self):
        self._stop_capture()
        self.destroy()
