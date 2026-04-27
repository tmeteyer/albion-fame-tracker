"""
Interface graphique principale — Albion Online Fame/Silver Tracker
"""
import os
import collections
import queue
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox

# Chemin vers le dossier parent pour les imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.albion import load_config, save_config, is_fame_event, is_silver_event, extract_fame, extract_silver
from core.capture import CaptureThread
from core.tracker import SessionTracker
from core.photon import MSG_EVENT, MSG_OP_RESPONSE

# ─── Couleurs (thème sombre Albion) ──────────────────────────────────────────
BG_DARK     = "#1a1a2e"
BG_PANEL    = "#16213e"
BG_CARD     = "#0f3460"
ACCENT      = "#e94560"
ACCENT2     = "#f5a623"
TEXT_MAIN   = "#e0e0e0"
TEXT_DIM    = "#8888aa"
TEXT_FAME   = "#7ecfff"
TEXT_SILVER = "#ffd700"
GREEN       = "#4ade80"
RED         = "#f87171"

FONT_TITLE  = ("Segoe UI", 18, "bold")
FONT_BIG    = ("Segoe UI", 26, "bold")
FONT_MED    = ("Segoe UI", 12)
FONT_SMALL  = ("Segoe UI", 10)
FONT_MONO   = ("Consolas", 9)

REFRESH_MS  = 500   # mise à jour de l'UI toutes les 500 ms
QUEUE_DRAIN = 50    # événements max à lire par tick


class AlbionTrackerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Albion Fame Tracker")
        self.geometry("900x650")
        self.minsize(780, 560)
        self.configure(bg=BG_DARK)
        self.resizable(True, True)

        self.cfg = load_config()
        self.tracker = SessionTracker()
        self.pkt_queue: queue.Queue = queue.Queue()
        self.capture_thread: CaptureThread | None = None
        self._raw_buffer: collections.deque = collections.deque(maxlen=2000)

        self._build_ui()
        self._schedule_refresh()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─── Construction UI ──────────────────────────────────────────────────────

    def _build_ui(self):
        # Titre
        header = tk.Frame(self, bg=BG_DARK)
        header.pack(fill="x", padx=16, pady=(12, 0))

        tk.Label(header, text="⚔  Albion Fame Tracker",
                 font=FONT_TITLE, bg=BG_DARK, fg=ACCENT).pack(side="left")

        self._lbl_status = tk.Label(header, text="● Inactif",
                                    font=FONT_SMALL, bg=BG_DARK, fg=TEXT_DIM)
        self._lbl_status.pack(side="right", padx=8)

        # Notebook (onglets)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook", background=BG_DARK, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG_PANEL, foreground=TEXT_DIM,
                        padding=[12, 6], font=FONT_SMALL)
        style.map("TNotebook.Tab",
                  background=[("selected", BG_CARD)],
                  foreground=[("selected", TEXT_MAIN)])

        # Barre de contrôle (bas) — doit être packée AVANT le notebook
        # pour rester visible quelle que soit la taille de la fenêtre
        self._build_controls()

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=8)

        self._tab_stats = tk.Frame(self.nb, bg=BG_DARK)
        self._tab_log   = tk.Frame(self.nb, bg=BG_DARK)
        self._tab_disc  = tk.Frame(self.nb, bg=BG_DARK)
        self._tab_cfg   = tk.Frame(self.nb, bg=BG_DARK)

        self.nb.add(self._tab_stats, text="  Statistiques  ")
        self.nb.add(self._tab_log,   text="  Événements  ")
        self.nb.add(self._tab_disc,  text="  Découverte  ")
        self.nb.add(self._tab_cfg,   text="  Config  ")

        self._build_stats_tab()
        self._build_log_tab()
        self._build_discovery_tab()
        self._build_config_tab()

    def _card(self, parent, row, col, rowspan=1, colspan=1) -> tk.Frame:
        f = tk.Frame(parent, bg=BG_CARD, bd=0, relief="flat")
        f.grid(row=row, column=col, rowspan=rowspan, columnspan=colspan,
               padx=6, pady=6, sticky="nsew")
        return f

    def _build_stats_tab(self):
        p = self._tab_stats
        for i in range(3):
            p.columnconfigure(i, weight=1)
        for i in range(2):
            p.rowconfigure(i, weight=1)

        # ── Fame ──
        f_fame = self._card(p, 0, 0)
        tk.Label(f_fame, text="Fame / heure", font=FONT_MED,
                 bg=BG_CARD, fg=TEXT_DIM).pack(pady=(12, 2))
        self._lbl_fame_rate = tk.Label(f_fame, text="—", font=FONT_BIG,
                                       bg=BG_CARD, fg=TEXT_FAME)
        self._lbl_fame_rate.pack()
        tk.Label(f_fame, text="(fenêtre 5 min)", font=FONT_SMALL,
                 bg=BG_CARD, fg=TEXT_DIM).pack(pady=(0, 4))
        self._lbl_fame_inst = tk.Label(f_fame, text="Session: —",
                                       font=FONT_SMALL, bg=BG_CARD, fg=TEXT_FAME)
        self._lbl_fame_inst.pack(pady=(0, 12))

        # ── Silver ──
        f_silv = self._card(p, 0, 1)
        tk.Label(f_silv, text="Silver / heure", font=FONT_MED,
                 bg=BG_CARD, fg=TEXT_DIM).pack(pady=(12, 2))
        self._lbl_silv_rate = tk.Label(f_silv, text="—", font=FONT_BIG,
                                       bg=BG_CARD, fg=TEXT_SILVER)
        self._lbl_silv_rate.pack()
        tk.Label(f_silv, text="(fenêtre 5 min)", font=FONT_SMALL,
                 bg=BG_CARD, fg=TEXT_DIM).pack(pady=(0, 4))
        self._lbl_silv_inst = tk.Label(f_silv, text="Session: —",
                                       font=FONT_SMALL, bg=BG_CARD, fg=TEXT_SILVER)
        self._lbl_silv_inst.pack(pady=(0, 12))

        # ── Timer ──
        f_time = self._card(p, 0, 2)
        tk.Label(f_time, text="Durée session", font=FONT_MED,
                 bg=BG_CARD, fg=TEXT_DIM).pack(pady=(12, 2))
        self._lbl_timer = tk.Label(f_time, text="00:00:00", font=FONT_BIG,
                                   bg=BG_CARD, fg=TEXT_MAIN)
        self._lbl_timer.pack()
        tk.Label(f_time, text="", bg=BG_CARD).pack(expand=True)

        # ── Totaux ──
        f_total = self._card(p, 1, 0, colspan=3)
        f_total.columnconfigure(0, weight=1)
        f_total.columnconfigure(1, weight=1)

        tk.Label(f_total, text="Fame total (session)", font=FONT_SMALL,
                 bg=BG_CARD, fg=TEXT_DIM).grid(row=0, column=0, pady=(10, 2))
        tk.Label(f_total, text="Silver total (session)", font=FONT_SMALL,
                 bg=BG_CARD, fg=TEXT_DIM).grid(row=0, column=1, pady=(10, 2))

        self._lbl_fame_total = tk.Label(f_total, text="0", font=("Segoe UI", 20, "bold"),
                                        bg=BG_CARD, fg=TEXT_FAME)
        self._lbl_fame_total.grid(row=1, column=0, pady=(0, 12))

        self._lbl_silv_total = tk.Label(f_total, text="0", font=("Segoe UI", 20, "bold"),
                                        bg=BG_CARD, fg=TEXT_SILVER)
        self._lbl_silv_total.grid(row=1, column=1, pady=(0, 12))

    def _build_log_tab(self):
        p = self._tab_log
        p.columnconfigure(0, weight=1)
        p.rowconfigure(0, weight=1)

        cols = ("Heure", "Type", "Code", "Montant", "Détails")
        self._tree = ttk.Treeview(p, columns=cols, show="headings", height=20)

        style = ttk.Style()
        style.configure("Treeview", background=BG_PANEL, foreground=TEXT_MAIN,
                        fieldbackground=BG_PANEL, font=FONT_MONO, rowheight=22)
        style.configure("Treeview.Heading", background=BG_CARD, foreground=TEXT_MAIN,
                        font=FONT_SMALL)
        style.map("Treeview", background=[("selected", BG_CARD)])

        widths = [70, 70, 50, 90, 380]
        for col, w in zip(cols, widths):
            self._tree.heading(col, text=col)
            self._tree.column(col, width=w, anchor="w")

        self._tree.tag_configure("fame",   foreground=TEXT_FAME)
        self._tree.tag_configure("silver", foreground=TEXT_SILVER)
        self._tree.tag_configure("other",  foreground=TEXT_DIM)

        sb = ttk.Scrollbar(p, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)

        self._tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        sb.grid(row=0, column=1, sticky="ns", pady=8)

        tk.Button(p, text="Vider le journal", bg=BG_PANEL, fg=TEXT_DIM,
                  font=FONT_SMALL, relief="flat", cursor="hand2",
                  command=self._clear_log).grid(row=1, column=0, pady=(0, 6))

    def _build_discovery_tab(self):
        p = self._tab_disc
        p.columnconfigure(0, weight=1)
        p.rowconfigure(1, weight=1)

        info = (
            "Tue un mob  →  clique immédiatement sur 'Capturer'  →  le tableau affiche "
            "seulement les paquets des 3 dernières secondes (S→C = serveur vers toi)."
        )
        tk.Label(p, text=info, font=FONT_SMALL, bg=BG_DARK, fg=TEXT_DIM,
                 justify="left", wraplength=820).pack(anchor="w", padx=12, pady=(8, 4))

        btn_frame = tk.Frame(p, bg=BG_DARK)
        btn_frame.pack(fill="x", padx=8, pady=4)

        self._btn_capture = tk.Button(
            btn_frame, text="Capturer (3 sec)",
            bg=ACCENT, fg="white", font=("Segoe UI", 10, "bold"),
            relief="flat", cursor="hand2", padx=14,
            command=self._snapshot_discovery
        )
        self._btn_capture.pack(side="left", padx=4)

        tk.Button(btn_frame, text="Vider", bg=BG_PANEL, fg=TEXT_DIM,
                  font=FONT_SMALL, relief="flat", cursor="hand2",
                  command=self._clear_discovery).pack(side="left", padx=4)

        self._lbl_snap_info = tk.Label(btn_frame, text="",
                                       font=FONT_SMALL, bg=BG_DARK, fg=ACCENT2)
        self._lbl_snap_info.pack(side="left", padx=12)

        cols = ("Heure", "Dir", "Code", "Params (résumé)")
        self._disc_tree = ttk.Treeview(p, columns=cols, show="headings", height=20)
        for col in cols:
            self._disc_tree.heading(col, text=col)
        self._disc_tree.column("Heure", width=70,  anchor="center")
        self._disc_tree.column("Dir",   width=50,  anchor="center")
        self._disc_tree.column("Code",  width=55,  anchor="center")
        self._disc_tree.column("Params (résumé)", width=670)

        sb2 = ttk.Scrollbar(p, orient="vertical", command=self._disc_tree.yview)
        self._disc_tree.configure(yscrollcommand=sb2.set)

        self._disc_tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=4)
        sb2.pack(side="left", fill="y", pady=4)

    def _build_config_tab(self):
        p = self._tab_cfg
        p.columnconfigure(1, weight=1)

        def row_entry(label, row, var_getter, var_setter, hint=""):
            tk.Label(p, text=label, font=FONT_MED, bg=BG_DARK,
                     fg=TEXT_MAIN).grid(row=row, column=0, sticky="w", padx=16, pady=6)
            entry = tk.Entry(p, font=FONT_MED, bg=BG_PANEL, fg=TEXT_MAIN,
                             insertbackground=TEXT_MAIN, relief="flat", width=30)
            entry.insert(0, var_getter())
            entry.grid(row=row, column=1, sticky="ew", padx=8, pady=6)
            if hint:
                tk.Label(p, text=hint, font=FONT_SMALL, bg=BG_DARK,
                         fg=TEXT_DIM).grid(row=row, column=2, sticky="w", padx=4)
            return entry

        self._entry_fame_codes = row_entry(
            "Codes événement Fame", 0,
            lambda: ", ".join(str(x) for x in self.cfg.get("fame_event_codes", [])),
            None,
            hint="ex: 174, 207"
        )
        self._entry_silv_codes = row_entry(
            "Codes événement Silver", 1,
            lambda: ", ".join(str(x) for x in self.cfg.get("silver_event_codes", [])),
            None,
            hint="ex: 3, 14"
        )
        self._entry_fame_keys = row_entry(
            "Clés param Fame", 2,
            lambda: ", ".join(str(x) for x in self.cfg.get("fame_param_keys", [1])),
            None,
            hint="ex: 1, 2  (numéros de paramètre)"
        )
        self._entry_silv_keys = row_entry(
            "Clés param Silver", 3,
            lambda: ", ".join(str(x) for x in self.cfg.get("silver_param_keys", [3])),
            None,
            hint="ex: 3"
        )

        # Mode debug
        self._var_debug = tk.BooleanVar(value=self.cfg.get("debug_mode", True))
        tk.Checkbutton(p, text="Mode découverte activé (log tous les événements)",
                       variable=self._var_debug,
                       bg=BG_DARK, fg=TEXT_MAIN, selectcolor=BG_PANEL,
                       font=FONT_MED, activebackground=BG_DARK,
                       activeforeground=TEXT_MAIN).grid(
            row=4, column=0, columnspan=3, sticky="w", padx=16, pady=10)

        tk.Button(p, text="Sauvegarder la configuration", bg=ACCENT, fg="white",
                  font=FONT_MED, relief="flat", cursor="hand2",
                  command=self._save_config).grid(
            row=5, column=0, columnspan=3, pady=12)

        self._lbl_cfg_status = tk.Label(p, text="", font=FONT_SMALL,
                                        bg=BG_DARK, fg=GREEN)
        self._lbl_cfg_status.grid(row=6, column=0, columnspan=3)

        tk.Label(p, text=f"Fichier config : {os.path.abspath('config.json')}",
                 font=FONT_SMALL, bg=BG_DARK, fg=TEXT_DIM).grid(
            row=7, column=0, columnspan=3, pady=4)
        tk.Label(p,
                 text="Fichier discovery_log.jsonl : contient tous les paquets capturés en mode découverte",
                 font=FONT_SMALL, bg=BG_DARK, fg=TEXT_DIM).grid(
            row=8, column=0, columnspan=3)

        tk.Button(p, text="Diagnostic réseau (5 sec)", bg=BG_CARD, fg=TEXT_MAIN,
                  font=FONT_SMALL, relief="flat", cursor="hand2",
                  command=self._run_diag).grid(row=9, column=0, columnspan=3, pady=(16, 4))

        self._lbl_diag = tk.Label(p, text="", font=FONT_SMALL, bg=BG_DARK, fg=TEXT_DIM,
                                  wraplength=700, justify="left")
        self._lbl_diag.grid(row=10, column=0, columnspan=3, padx=16)

    def _build_controls(self):
        bar = tk.Frame(self, bg=BG_PANEL, height=50)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        self._btn_toggle = tk.Button(
            bar, text="▶  Démarrer la capture",
            bg=GREEN, fg="#111", font=("Segoe UI", 11, "bold"),
            relief="flat", cursor="hand2", padx=20,
            command=self._toggle_capture
        )
        self._btn_toggle.pack(side="left", padx=12, pady=8)

        tk.Button(bar, text="↺  Réinitialiser session",
                  bg=BG_CARD, fg=TEXT_MAIN, font=FONT_SMALL,
                  relief="flat", cursor="hand2", padx=12,
                  command=self._reset_session).pack(side="left", padx=4, pady=8)

        self._lbl_pkt_count = tk.Label(bar, text="Reçus: 0  Parsés: 0  File: 0",
                                       font=FONT_SMALL, bg=BG_PANEL, fg=TEXT_DIM)
        self._lbl_pkt_count.pack(side="right", padx=16)

        self._pkt_count = 0

    # ─── Actions ──────────────────────────────────────────────────────────────

    def _toggle_capture(self):
        if self.capture_thread and self.capture_thread.is_alive():
            self._stop_capture()
        else:
            self._start_capture()

    def _start_capture(self):
        self.cfg = load_config()
        debug = self.cfg.get("debug_mode", True)
        self.capture_thread = CaptureThread(self.pkt_queue, debug_mode=debug)
        self.capture_thread.start()
        self.tracker.start()
        self._btn_toggle.configure(text="⏹  Arrêter la capture", bg=RED)
        # Afficher l'interface après un court délai (le thread a besoin de démarrer)
        self.after(800, self._update_iface_status)

    def _update_iface_status(self):
        if self.capture_thread and self.capture_thread.is_alive():
            iface = self.capture_thread.iface_name or "interface par défaut"
            self._lbl_status.configure(text=f"● Capture active  [{iface}]", fg=GREEN)

    def _stop_capture(self):
        if self.capture_thread:
            self.capture_thread.stop()
            self.capture_thread = None
        self.tracker.stop()
        self._btn_toggle.configure(text="▶  Démarrer la capture", bg=GREEN)
        self._lbl_status.configure(text="● Inactif", fg=TEXT_DIM)

    def _reset_session(self):
        self.tracker.reset()
        self._clear_log()
        self._pkt_count = 0
        self._lbl_pkt_count.configure(text="Paquets Albion traités : 0")

    def _clear_log(self):
        for item in self._tree.get_children():
            self._tree.delete(item)

    def _clear_discovery(self):
        for item in self._disc_tree.get_children():
            self._disc_tree.delete(item)

    def _run_diag(self):
        """Capture tous les paquets UDP pendant 5 secondes via raw socket."""
        self._lbl_diag.configure(text="Capture en cours (5 sec)...", fg=TEXT_DIM)
        self.update_idletasks()

        import threading
        import socket as _socket
        import struct as _struct
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
                        if len(data) < 20:
                            continue
                        if data[9] != 17:
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

        t = threading.Thread(target=_diag, daemon=True)
        t.start()
        self.after(5500, lambda: self._show_diag(result))

    def _show_diag(self, result: dict):
        if result["error"]:
            self._lbl_diag.configure(
                text=f"Erreur : {result['error']}", fg=RED)
        elif result["udp_total"] == 0:
            self._lbl_diag.configure(
                text="0 paquet UDP capturé — vérifiez que le tracker est lancé en administrateur.",
                fg=RED)
        elif result["port_5056"] == 0:
            self._lbl_diag.configure(
                text=f"{result['udp_total']} paquets UDP capturés, mais 0 sur le port 5056.\n"
                     "La capture fonctionne. Albion n'envoie peut-être pas encore de trafic "
                     "(connectez-vous à un monde) ou utilise un port différent.",
                fg=ACCENT2)
        else:
            self._lbl_diag.configure(
                text=f"OK — {result['udp_total']} paquets UDP dont {result['port_5056']} "
                     f"sur le port 5056 (Albion). La capture fonctionne correctement.",
                fg=GREEN)

    def _save_config(self):
        def parse_ints(s):
            try:
                return [int(x.strip()) for x in s.split(",") if x.strip()]
            except ValueError:
                return []

        self.cfg["fame_event_codes"] = parse_ints(self._entry_fame_codes.get())
        self.cfg["silver_event_codes"] = parse_ints(self._entry_silv_codes.get())
        self.cfg["fame_param_keys"] = parse_ints(self._entry_fame_keys.get())
        self.cfg["silver_param_keys"] = parse_ints(self._entry_silv_keys.get())
        self.cfg["debug_mode"] = self._var_debug.get()
        save_config(self.cfg)
        self._lbl_cfg_status.configure(text="✓ Configuration sauvegardée")
        self.after(3000, lambda: self._lbl_cfg_status.configure(text=""))

    def _refresh_config_tab(self):
        self._entry_fame_codes.delete(0, "end")
        self._entry_fame_codes.insert(0, ", ".join(str(x) for x in self.cfg.get("fame_event_codes", [])))
        self._entry_silv_codes.delete(0, "end")
        self._entry_silv_codes.insert(0, ", ".join(str(x) for x in self.cfg.get("silver_event_codes", [])))
        self._entry_fame_keys.delete(0, "end")
        self._entry_fame_keys.insert(0, ", ".join(str(x) for x in self.cfg.get("fame_param_keys", [1])))
        self._entry_silv_keys.delete(0, "end")
        self._entry_silv_keys.insert(0, ", ".join(str(x) for x in self.cfg.get("silver_param_keys", [3])))

    # ─── Boucle de rafraîchissement ───────────────────────────────────────────

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
            cmds = " ".join(f"t{k}:{v}" for k, v in sorted(t.cmd_type_counts.items()))
            self._lbl_pkt_count.configure(
                text=f"Reçus: {t.raw_count}  Parsés: {t.parsed_count}  "
                     f"Frags: {t.frag_count}/{t.frag_done}  [{cmds}]")

    def _process_entry(self, entry: dict):
        mode = entry.get('mode', 'photon')

        if mode == 'raw':
            # Paquet brut non parsé : afficher dans l'onglet Découverte
            self._update_discovery_raw(entry)
            return

        code = entry.get('code', 0)
        msg_type = entry.get('type', 0)
        params = entry.get('params', {})

        is_event = msg_type == MSG_EVENT

        # Le vrai code applicatif Albion est dans params[252] si présent
        app_code = params.get(252, code)

        if is_event:
            self._update_discovery(app_code, params, entry.get('dir', 'S→C'))

        if is_event and is_fame_event(app_code, self.cfg):
            amount = extract_fame(params, self.cfg)
            if amount > 0:
                self.tracker.add_fame(amount, source=f"event {app_code}")
                self._log_row("fame", app_code, amount, params)

        if is_event and is_silver_event(app_code, self.cfg):
            amount = extract_silver(params, self.cfg)
            if amount > 0:
                self.tracker.add_silver(amount, source=f"event {app_code}")
                self._log_row("silver", app_code, amount, params)

    def _log_row(self, kind: str, code: int, amount: int, params: dict):
        ts = time.strftime("%H:%M:%S")
        label = "Fame" if kind == "fame" else "Silver"
        details = str(params)[:80]
        tag = kind
        self._tree.insert("", 0, values=(ts, label, code, f"+{amount:,}", details),
                          tags=(tag,))
        # Limiter à 200 lignes
        children = self._tree.get_children()
        if len(children) > 200:
            self._tree.delete(children[-1])

    def _update_discovery(self, code: int, params: dict, direction: str = "S→C"):
        self._raw_buffer.append({
            'ts': time.time(),
            'dir': direction,
            'code': code,
            'params': params,
        })

    def _update_discovery_raw(self, entry: dict):
        self._raw_buffer.append(entry)

    def _snapshot_discovery(self):
        """Affiche seulement les événements des 3 dernières secondes."""
        cutoff = time.time() - 3.0
        recent = [e for e in self._raw_buffer if e.get('ts', 0) >= cutoff]

        for item in self._disc_tree.get_children():
            self._disc_tree.delete(item)

        for e in recent:
            ts_str = time.strftime("%H:%M:%S", time.localtime(e.get('ts', 0)))
            direction = e.get('dir', '?')
            code = e.get('code', '?')
            params = e.get('params', {})
            summary = "  ".join(f"{k}:{v}" for k, v in list(params.items())[:8])[:120]
            self._disc_tree.insert("", "end", values=(ts_str, direction, code, summary))

        self._lbl_snap_info.configure(
            text=f"{len(recent)} événement(s) dans les 3 dernières secondes"
        )

    def _update_stats(self):
        t = self.tracker
        self._lbl_timer.configure(text=t.elapsed_str)

        def fmt(n: float) -> str:
            if n >= 1_000_000:
                return f"{n/1_000_000:.2f}M"
            if n >= 1_000:
                return f"{n/1_000:.1f}K"
            return f"{int(n)}"

        self._lbl_fame_rate.configure(text=fmt(t.instant_fame_per_hour) if t.running else "—")
        self._lbl_fame_inst.configure(text=f"Session: {fmt(t.fame_per_hour)}/h")
        self._lbl_silv_rate.configure(text=fmt(t.instant_silver_per_hour) if t.running else "—")
        self._lbl_silv_inst.configure(text=f"Session: {fmt(t.silver_per_hour)}/h")
        self._lbl_fame_total.configure(text=f"{t.total_fame:,}")
        self._lbl_silv_total.configure(text=f"{t.total_silver:,}")

    def _check_capture_error(self):
        if self.capture_thread and self.capture_thread.error:
            err = self.capture_thread.error
            self.capture_thread = None
            self.tracker.stop()
            self._btn_toggle.configure(text="▶  Démarrer la capture", bg=GREEN)
            self._lbl_status.configure(text="● Erreur", fg=RED)
            messagebox.showerror("Erreur de capture", err)

    def _on_close(self):
        self._stop_capture()
        self.destroy()
