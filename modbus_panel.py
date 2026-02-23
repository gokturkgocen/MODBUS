import customtkinter as ctk
import minimalmodbus
import serial
import serial.tools.list_ports
import threading
import time
import json
import os
import queue

# --- ARAYÜZ AYARLARI ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

STATUS_TEXT = {0: "[IDLE]", 1: "AÇIK", 2: "KAPALI"}

# --- MATRIX THEME PALETTE ---
COLORS = {
    'bg_dark':       "#000000", # Pure Black
    'bg_mid':        "#000D00", # Deep Matrix Green
    'bg_card':       "#000000", # Cards are black
    'bg_card_hover': "#001A00", # Subtle green lift
    
    # Status Colors (Neon Matrix)
    'matrix_green':  "#00FF41", # Classic Matrix Green
    'matrix_glow':   "#00FF41", 
    'matrix_dark':   "#003B00", # Deep Forest Green
    
    'border':        "#003B00", # Dark Green Border
    'border_glow':   "#00FF41", # Bright Green Glow
    
    'toolbar_bg':    "#000000",
    'toolbar_border':"#003B00",
    
    'accent':        "#00FF41", 
    'accent_dim':    "#008F11", # Dimmer green
    
    'green':         "#00FF41", 
    'red':           "#FF0000", # Red strictly for critical errors
    'yellow':        "#FFFF00", # Yellow for warnings
    
    'text':          "#00FF41", # Standard Matrix Text (Green)
    'text_dim':      "#008F11", # Muted Terminal Green
    'text_label':    "#003B00", # Dark label text
    'text_white':    "#E8F5E9", # Slightly tinted white for high contrast
    
    'transparent':   "transparent",
    'dim_icon':      "#003B00",
    'btn_dim':       "#000D00",
}

class CTkToolTip(ctk.CTkToplevel):
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        super().__init__()
        self.withdraw()
        self.overrideredirect(True)
        
        self.label = ctk.CTkLabel(self, text=self.text, fg_color="#181818", text_color="#E8E8E8",
                                  corner_radius=6, padx=10, pady=5, font=("Segoe UI", 11))
        self.label.pack()
        
        self.widget.bind("<Enter>", self.show_tip)
        self.widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        x, y, cx, cy = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 20
        self.geometry(f"+{x}+{y}")
        self.deiconify()
        self.lift()

    def hide_tip(self, event=None):
        self.withdraw()

# --- REGISTER HARİTASI ---
REG_COMMAND     = 0   # WO
REG_STATUS      = 1   # RO
REG_ERRORS      = 2   # RO
REG_WARNINGS    = 3   # RO
REG_OPEN_SPEED  = 4   # RW
REG_CLOSE_SPEED = 5   # RW
REG_DURATION    = 6   # RW
REG_OPEN_TORQUE = 7   # RW
REG_CLOSE_TORQUE= 8   # RW
REG_SAMPLE_VAL  = 9   # RW
REGS_PER_DEVICE = 10

STATUS_TEXT  = {0: "⏸ Duruyor", 1: "● Açık", 2: "● Kapalı"}

# Bitwise Hata/Uyarı Tanımları
ERR_CODES = {
    0: "Acil Durum Hatası",
    1: "Yüksek Gerilim",
    2: "Düşük Gerilim",
    3: "Aşırı Akım",
    4: "Sensör Hatası",
    5: "Motor Sıkışması",
    6: "Haberleşme Hatası",
    7: "EEPROM Hatası"
}

WARN_CODES = {
    0: "Yüksek Sıcaklık",
    1: "Bakım Gerekli",
    2: "Fan Arızası",
    3: "Giriş Voltajı Dengesiz",
    4: "Uyarı 5",
    5: "Uyarı 6"
}

PARAM_DEFS = [
    {'reg': REG_OPEN_SPEED,   'label': 'Açılış Hızı',    'min': 0, 'max': 1000, 'unit': ''},
    {'reg': REG_CLOSE_SPEED,  'label': 'Kapanış Hızı',   'min': 0, 'max': 1000, 'unit': ''},
    {'reg': REG_DURATION,     'label': 'Süre',            'min': 0, 'max': 3600, 'unit': 's'},
    {'reg': REG_OPEN_TORQUE,  'label': 'Açılış Torku',    'min': 0, 'max': 1000, 'unit': ''},
    {'reg': REG_CLOSE_TORQUE, 'label': 'Kapanış Torku',   'min': 0, 'max': 1000, 'unit': ''},
    {'reg': REG_SAMPLE_VAL,   'label': 'Örnek Değer',     'min': 0, 'max': 1000, 'unit': ''},
]

# ============================================================================
#  ANA UYGULAMA
# ============================================================================
class HMIApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Modbus RTU — HMI Kontrol Paneli")
        self.geometry("1200x800")
        self.minsize(960, 640)
        self.configure(fg_color=COLORS['bg_dark'])

        # --- Veri Modeli ---
        self.devices = []           # [{'id':int, 'name':str}, ...]
        self.data_store = {}        # Veri saklama (Cache, Metrics)
        self.instrument = None
        self.polling = False
        self.poll_lock = threading.Lock()
        self.connected = False
        
        # Priority Queue
        self.command_queue = queue.Queue()

        # UI Referansları
        self.device_cards_ui = {}
        self.grid_frame = None
        self.selected_device_id = None
        self.detail_open_for = None 

        self._load_config()
        self._build_toolbar()
        self._build_grid_area()
        self._sync_grid_layout()

    def _load_config(self):
        try:
            if os.path.exists("devices.json"):
                with open("devices.json", "r", encoding="utf-8") as f:
                    self.devices = json.load(f)
                
                # Data store'u başlat
                for d in self.devices:
                    sid = d['id']
                    self.data_store[sid] = {
                        'cache': {}, 'pending': {}, 'online': True, 'errors': 0, 'last_update': '',
                        'latency': 0, 'success_count': 0, 'total_count': 0,
                        'cmd_latency': 0, 'last_cmd_ts': 0,
                        'slave_resp_time': 0, 'loop_time': 0, 'last_poll_ts': 0,
                        'slave_resp_history': [], 'loop_time_history': [] # ORTALAMA İÇİN
                    }
        except Exception as e:
            print(f"Config Yükleme Hatası: {e}")

    def _save_config(self):
        try:
            with open("devices.json", "w", encoding="utf-8") as f:
                json.dump(self.devices, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Config Kaydetme Hatası: {e}")

    # ========================================================================
    #  TOOLBAR
    # ========================================================================
    def _build_toolbar(self):
        toolbar = ctk.CTkFrame(self, height=60, corner_radius=0, fg_color=COLORS['toolbar_bg'],
                               border_width=1, border_color=COLORS['toolbar_border'])
        toolbar.pack(fill="x", side="top")
        toolbar.pack_propagate(False)

        inner = ctk.CTkFrame(toolbar, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(inner, text="☢", font=("Consolas", 18), text_color=COLORS['accent']).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(inner, text="MODBUS SYSTEM", font=("Consolas", 14, "bold"), text_color=COLORS['text']).pack(side="left", padx=(0, 16))

        sep = ctk.CTkFrame(inner, width=1, height=28, fg_color=COLORS['border'])
        sep.pack(side="left", padx=(0, 16))

        ctk.CTkLabel(inner, text="PORT:", font=("Consolas", 9, "bold"), text_color=COLORS['text_dim']).pack(side="left", padx=(0, 4))
        ports = [p.device for p in serial.tools.list_ports.comports()] or ["Port Yok"]
        self.combo_port = ctk.CTkComboBox(inner, values=ports, width=115, height=30,
                                          font=("Consolas", 11), corner_radius=0,
                                          fg_color=COLORS['bg_dark'], border_color=COLORS['border'],
                                          button_color=COLORS['border'], button_hover_color=COLORS['matrix_dark'],
                                          dropdown_fg_color=COLORS['bg_dark'], dropdown_text_color=COLORS['text'])
        self.combo_port.pack(side="left", padx=(0, 10))

        ctk.CTkLabel(inner, text="BAUD:", font=("Consolas", 9, "bold"), text_color=COLORS['text_dim']).pack(side="left", padx=(0, 4))
        self.combo_baud = ctk.CTkComboBox(inner, values=["9600","19200","38400","57600","115200","230400","250000"],
                                          width=90, height=30,
                                          font=("Consolas", 11), corner_radius=0,
                                          fg_color=COLORS['bg_dark'], border_color=COLORS['border'],
                                          button_color=COLORS['border'], button_hover_color=COLORS['matrix_dark'],
                                          dropdown_fg_color=COLORS['bg_dark'], dropdown_text_color=COLORS['text'])
        self.combo_baud.set("9600")
        self.combo_baud.pack(side="left", padx=(0, 16))

        sep2 = ctk.CTkFrame(inner, width=1, height=28, fg_color=COLORS['border'])
        sep2.pack(side="left", padx=(0, 16))

        self.btn_add = ctk.CTkButton(inner, text="[+ ADD NODE]", width=100, height=32,
                                     font=("Consolas", 11, "bold"), corner_radius=0,
                                     fg_color="transparent", border_width=1, border_color=COLORS['border'],
                                     hover_color=COLORS['matrix_dark'],
                                     command=self._open_add_device_dialog)
        self.btn_add.pack(side="left", padx=3)

        self.btn_del = ctk.CTkButton(inner, text="[X REMOVE]", width=90, height=32,
                                     font=("Consolas", 11, "bold"), corner_radius=0,
                                     fg_color="transparent", border_width=1, border_color="#3D0000",
                                     hover_color="#3D0000", text_color=COLORS['red'],
                                     command=self._delete_selected_device)
        self.btn_del.pack(side="left", padx=3)

        # Matrix Connect Button
        self.btn_connect = ctk.CTkButton(inner, text="[ EXEC CONNECT ]", width=140, height=34,
                                         font=("Consolas", 12, "bold"), corner_radius=0,
                                         fg_color="transparent", border_width=1, border_color=COLORS['matrix_green'],
                                         hover_color=COLORS['matrix_dark'],
                                         command=self._toggle_connection)
        self.btn_connect.pack(side="left", padx=(12, 0))

        self.lbl_toolbar_status = ctk.CTkLabel(inner, text=":: OFFLINE ::",
                                               font=("Consolas", 10, "bold"), text_color=COLORS['text_dim'])
        self.lbl_toolbar_status.pack(side="right", padx=8)

    # ========================================================================
    #  GRID ALANI
    # ========================================================================
    def _build_grid_area(self):
        self.grid_container = ctk.CTkScrollableFrame(self, fg_color=COLORS['bg_dark'],
                                                     corner_radius=0,
                                                     scrollbar_button_color=COLORS['border'],
                                                     scrollbar_button_hover_color=COLORS['matrix_dark'])
        self.grid_container.pack(fill="both", expand=True, padx=20, pady=(12, 20))

        self.grid_frame = ctk.CTkFrame(self.grid_container, fg_color="transparent")
        self.grid_frame.pack(fill="both", expand=True)

        self.lbl_empty = ctk.CTkLabel(self.grid_frame,
                                      text="[ SYSTEM_IDLE: NO_NODES_DETECTED ]\n[ EXECUTE (+ ADD NODE) TO INITIALIZE ]",
                                      font=("Consolas", 14), text_color=COLORS['text_dim'])
        self.lbl_empty.pack(pady=100)

    def _sync_grid_layout(self):
        existing_ids = list(self.device_cards_ui.keys())
        target_ids = [d['id'] for d in self.devices]

        for sid in existing_ids:
            if sid not in target_ids:
                self.device_cards_ui[sid]['frame'].destroy()
                del self.device_cards_ui[sid]

        for sid in target_ids:
            if sid not in self.device_cards_ui:
                device = next(d for d in self.devices if d['id'] == sid)
                self._create_device_card(sid, device['name'])

        if not self.devices:
            self.lbl_empty.pack(pady=80)
        else:
            self.lbl_empty.pack_forget()

        cols = max(1, min(6, len(self.devices)))
        for i, (sid, ui) in enumerate(self.device_cards_ui.items()):
            r, c = divmod(i, cols)
            ui['frame'].grid(row=r, column=c, padx=10, pady=10, sticky="nsew")
            self.grid_frame.columnconfigure(c, weight=1)

    def _create_device_card(self, sid, name):
        # Matrix Terminal Frame
        card = ctk.CTkFrame(self.grid_frame, fg_color=COLORS['bg_dark'],
                            corner_radius=0, border_width=1,
                            border_color=COLORS['border'],
                            width=230, height=210)
        card.pack_propagate(False)

        # Content Layer
        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=12, pady=10)

        # Device Header (Terminal Style)
        header_frame = ctk.CTkFrame(content, fg_color="transparent")
        header_frame.pack(fill="x")
        
        id_tag = ctk.CTkLabel(header_frame, text=f"NODE:0{sid}" if sid < 10 else f"NODE:{sid}", 
                              font=("Consolas", 11, "bold"), text_color=COLORS['text_dim'])
        id_tag.pack(side="left")

        # Online Status Indicator (LED)
        status_led = ctk.CTkLabel(header_frame, text="[ONLINE]", font=("Consolas", 9, "bold"), text_color=COLORS['dim_icon'])
        status_led.pack(side="right")

        # Name Entry (Terminal Prompt Style)
        name_frame = ctk.CTkFrame(content, fg_color="transparent")
        name_frame.pack(fill="x", pady=(5, 0))
        ctk.CTkLabel(name_frame, text=">", font=("Consolas", 12, "bold"), text_color=COLORS['text']).pack(side="left")
        
        name_entry = ctk.CTkEntry(name_frame, font=("Consolas", 12, "bold"), height=25,
                                  fg_color="transparent", border_width=0,
                                  text_color=COLORS['text_white'])
        name_entry.insert(0, name)
        name_entry.pack(side="left", fill="x", expand=True, padx=5)
        name_entry.bind("<FocusOut>", lambda e, s=sid, ent=name_entry: self._update_device_name(s, ent.get()))
        name_entry.bind("<Return>", lambda e, s=sid, ent=name_entry: (self._update_device_name(s, ent.get()), self.focus()))

        # Separator (Green Line)
        ctk.CTkFrame(content, height=1, fg_color=COLORS['border']).pack(fill="x", pady=8)

        # --- DOOR STATUS (KAPI DURUMU) ---
        status_box = ctk.CTkFrame(content, fg_color="transparent")
        status_box.pack(fill="x")

        ctk.CTkLabel(status_box, text="KAPI DURUMU:", font=("Consolas", 10, "bold"), 
                     text_color=COLORS['text_dim']).pack(side="left")
        
        lbl_status = ctk.CTkLabel(status_box, text="[ .... ]", 
                                  font=("Consolas", 13, "bold"),
                                  text_color=COLORS['text'])
        lbl_status.pack(side="left", padx=10)

        # --- CONTROLS ---
        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(15, 5))
        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)

        btn_on = ctk.CTkButton(btn_frame, text="[ AÇ ]",
                      font=("Consolas", 11, "bold"), height=28,
                      fg_color="transparent", hover_color=COLORS['matrix_dark'],
                      border_width=1, border_color=COLORS['border'],
                      corner_radius=0,
                      command=lambda s=sid: self._send_command(s, 1)
                      )
        btn_on.grid(row=0, column=0, padx=(0, 2), sticky="ew")

        btn_off = ctk.CTkButton(btn_frame, text="[ KAPAT ]",
                      font=("Consolas", 11, "bold"), height=28,
                      fg_color="transparent", hover_color=COLORS['matrix_dark'],
                      border_width=1, border_color=COLORS['border'],
                      corner_radius=0,
                      command=lambda s=sid: self._send_command(s, 2)
                      )
        btn_off.grid(row=0, column=1, padx=(2, 0), sticky="ew")

        # Footer (Stats & Settings)
        footer = ctk.CTkFrame(content, fg_color="transparent")
        footer.pack(fill="x", pady=(10, 0))

        icon_err = ctk.CTkLabel(footer, text="[ERR]", font=("Consolas", 9, "bold"), text_color=COLORS['bg_dark'])
        icon_warn = ctk.CTkLabel(footer, text="[WRN]", font=("Consolas", 9, "bold"), text_color=COLORS['bg_dark'])
        
        btn_set = ctk.CTkLabel(footer, text="[SETTINGS]", font=("Consolas", 9), text_color=COLORS['text_dim'], cursor="hand2")
        btn_set.pack(side="right")
        btn_set.bind("<Button-1>", lambda e, s=sid: self._open_detail_popup(s))

        # --- MATRIX HOVER ---
        def on_enter(e):
            card.configure(border_color=COLORS['border_glow'], border_width=2)
            id_tag.configure(text_color=COLORS['text'])
        
        def on_leave(e):
            card.configure(border_color=COLORS['border'], border_width=1)
            id_tag.configure(text_color=COLORS['text_dim'])

        card.bind("<Enter>", on_enter)
        card.bind("<Leave>", on_leave)
        
        # Hitbox Fix
        def bind_recursive(w, s):
            if isinstance(w, (ctk.CTkButton, ctk.CTkEntry)): return
            try:
                w.bind("<Button-1>", lambda e, sid=s: self._select_device(sid))
                w.bind("<Enter>", on_enter)
                w.bind("<Leave>", on_leave)
            except: pass
            for child in w.winfo_children():
                bind_recursive(child, s)
        
        bind_recursive(card, sid)

        self.device_cards_ui[sid] = {
            'frame': card, 'icon_err': icon_err, 'icon_warn': icon_warn,
            'name_entry': name_entry, 'led': status_led,
            'btn_on': btn_on, 'btn_off': btn_off, 'lbl_status': lbl_status,
            'id_tag': id_tag
        }

    def _update_ui_data(self):
        with self.poll_lock:
            for sid, ui in self.device_cards_ui.items():
                if sid not in self.data_store: continue
                
                try:
                    data = self.data_store[sid]
                    online = data['online']
                    cache = data['cache']
                    status = cache.get(REG_STATUS, 0)
                    
                    # Highlight selection
                    if sid == self.selected_device_id:
                        ui['frame'].configure(border_color=COLORS['border_glow'], border_width=2)
                    else:
                        ui['frame'].configure(border_color=COLORS['border'], border_width=1)
                    
                    # Status Display
                    status_text = STATUS_TEXT.get(status, "[UNK]")
                    ui['lbl_status'].configure(text=status_text)
                    
                    # Connection status (Card LED)
                    last_ts = data.get('timestamp', 0)
                    is_stale = (time.time() - last_ts > 15.0 and self.polling)
                    
                    if not online: 
                        ui['led'].configure(text="[OFFLINE]", text_color=COLORS['red'])
                    elif is_stale: 
                        ui['led'].configure(text="[LAGGING]", text_color=COLORS['yellow'])
                    else: 
                        ui['led'].configure(text="[ONLINE]", text_color=COLORS['matrix_green'])

                    # Errors & Warnings
                    err_val = cache.get(REG_ERRORS, 0)
                    warn_val = cache.get(REG_WARNINGS, 0)
                    
                    if err_val > 0:
                        ui['icon_err'].pack(side="left")
                        ui['icon_err'].configure(text_color=COLORS['red'])
                    else:
                        ui['icon_err'].pack_forget()

                    if online and warn_val > 0:
                        ui['icon_warn'].pack(side="left", padx=5)
                        ui['icon_warn'].configure(text_color=COLORS['yellow'])
                    else:
                        ui['icon_warn'].pack_forget()
                    
                except Exception as e:
                    print(f"UI Update Error (SID {sid}): {e}") 

    # ========================================================================
    #  OPERASYONLAR
    # ========================================================================
    def _open_add_device_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("SYSTEM: ADD NODE")
        dialog.geometry("380x420")
        dialog.configure(fg_color=COLORS['bg_dark'])
        dialog.transient(self)
        dialog.grab_set()

        # Header
        ctk.CTkLabel(dialog, text="☢", font=("Consolas", 32), text_color=COLORS['accent']).pack(pady=(25, 0))
        ctk.CTkLabel(dialog, text="INITIALIZE NEW NODE", font=("Consolas", 14, "bold"), text_color=COLORS['text']).pack(pady=(0, 20))

        # Inputs
        ctk.CTkLabel(dialog, text=":: SLAVE ID ::", font=("Consolas", 9, "bold"), text_color=COLORS['text_dim']).pack()
        ent_id = ctk.CTkEntry(dialog, width=140, height=36, corner_radius=0, 
                              fg_color=COLORS['bg_dark'], border_color=COLORS['border'], 
                              font=("Consolas", 14), justify="center")
        ent_id.pack(pady=(4, 15))
        ent_id.insert(0, "1")

        ctk.CTkLabel(dialog, text=":: DEVICE LABEL ::", font=("Consolas", 9, "bold"), text_color=COLORS['text_dim']).pack()
        ent_name = ctk.CTkEntry(dialog, width=240, height=36, corner_radius=0, 
                                fg_color=COLORS['bg_dark'], border_color=COLORS['border'], 
                                font=("Consolas", 12), justify="center")
        ent_name.pack(pady=(4, 20))
        ent_name.insert(0, "NODE_NEW")

        lbl_err = ctk.CTkLabel(dialog, text="", font=("Consolas", 10))
        lbl_err.pack(pady=2)

        def add():
            try:
                sid_str = ent_id.get().strip()
                if not sid_str:
                    lbl_err.configure(text="! ID_NULL", text_color=COLORS['red'])
                    return
                try: sid = int(sid_str)
                except ValueError: 
                    lbl_err.configure(text="! ID_TYPE_ERROR", text_color=COLORS['red'])
                    return

                if any(d['id'] == sid for d in self.devices):
                    lbl_err.configure(text=f"! NODE_{sid}_EXISTS", text_color=COLORS['red'])
                    return
                
                name = ent_name.get().strip()
                if not name:
                    lbl_err.configure(text="! NAME_NULL", text_color=COLORS['red'])
                    return

                self.devices.append({'id': sid, 'name': name})
                self.data_store[sid] = {
                    'cache': {}, 'pending': {}, 'online': True, 'errors': 0, 'last_update': '',
                    'latency': 0, 'success_count': 0, 'total_count': 0,
                    'cmd_latency': 0, 'last_cmd_ts': 0,
                    'slave_resp_time': 0, 'loop_time': 0, 'last_poll_ts': 0,
                    'slave_resp_history': [], 'loop_time_history': []
                }
                self._save_config()
                self._update_grid_area()
                dialog.destroy()
            except Exception as e:
                lbl_err.configure(text=f"! FATAL: {e}", text_color=COLORS['red'])

        ctk.CTkButton(dialog, text="[ EXEC ADD ]", font=("Consolas", 12, "bold"),
                      height=40, corner_radius=0, fg_color="transparent",
                      border_width=1, border_color=COLORS['border'],
                      hover_color=COLORS['matrix_dark'], command=add).pack(pady=10, padx=40, fill="x")
        
        ctk.CTkButton(dialog, text="[ ABORT ]", font=("Consolas", 11),
                      height=32, corner_radius=0, fg_color="transparent",
                      hover_color="#3D0000", border_width=0,
                      command=dialog.destroy).pack(padx=40, fill="x")

    def _delete_selected_device(self):
        if self.selected_device_id:
            self.devices = [d for d in self.devices if d['id'] != self.selected_device_id]
            self.data_store.pop(self.selected_device_id, None)
            self._save_config()
            self.selected_device_id = None
            self._sync_grid_layout()

    def _select_device(self, sid):
        self.selected_device_id = sid
        self._update_ui_data()

    def _send_command(self, sid, val):
        """Komut kuyruğa ekle — polling thread anında işler (Öncelikli)."""
        if sid not in self.data_store: return
        self.command_queue.put((sid, REG_COMMAND, val, time.time()))

    def _update_device_name(self, sid, name):
        for d in self.devices:
            if d['id'] == sid: 
                d['name'] = name
                self._save_config() # KAYIT ET
                break

    # ========================================================================
    #  MODBUS POLL MOTOR
    # ========================================================================
    def _toggle_connection(self):
        if self.connected:
            self.polling = False
            self.connected = False
            if self.instrument and self.instrument.serial:
                try: self.instrument.serial.close()
                except: pass
            self.instrument = None
            self.btn_connect.configure(text="[ EXEC CONNECT ]", fg_color="transparent", border_color=COLORS['matrix_green'])
            self.lbl_toolbar_status.configure(text=":: OFFLINE ::", text_color=COLORS['text_dim'])
        else:
            if not self.devices:
                self.lbl_toolbar_status.configure(text="Önce cihaz ekleyin!", text_color=COLORS['red'])
                return
            try:
                port = self.combo_port.get()
                baud = int(self.combo_baud.get())

                self.instrument = minimalmodbus.Instrument(port, 1)  # dummy sid
                self.instrument.serial.baudrate = baud
                self.instrument.serial.timeout  = 0.5
                self.instrument.close_port_after_each_call = False

                self.connected = True
                self.polling = True

                for sid in self.data_store:
                    self.data_store[sid]['online'] = True
                    self.data_store[sid]['errors'] = 0

                self.btn_connect.configure(text="[ TERMINATE ]", fg_color="transparent", border_color=COLORS['red'])
                self.lbl_toolbar_status.configure(text=f":: ONLINE :: {port} ::", text_color=COLORS['matrix_green'])
                threading.Thread(target=self._polling_worker, daemon=True).start()
            except Exception as e:
                self.lbl_toolbar_status.configure(text=f"!! ERR_INIT: {e}", text_color=COLORS['red'])

    def _polling_worker(self):
        """Polling döngüsü: Öncelikli komut kuyruğu ve periyodik sorgu."""
        device_index = 0
        
        while self.polling:
            # 1. ÖNCELİK: Komut Kuyruğu
            had_command = False
            processed_cmds = 0
            
            while not self.command_queue.empty() and processed_cmds < 5: # Max 5 komut üst üste
                try:
                    cmd = self.command_queue.get_nowait()
                    sid, reg, val, ts = cmd
                    had_command = True
                    processed_cmds += 1
                    
                    # RETRY LOGIC (3 Deneme)
                    cmd_success = False
                    for attempt in range(3):
                        with self.poll_lock:
                            try:
                                # Buffer Temizliği (Her denemede)
                                self.instrument.serial.reset_input_buffer()
                                if attempt > 0: time.sleep(0.1) # Retry ise bekle
                                
                                self.instrument.address = sid
                                
                                # Timeout Ayarı (Yazma işlemi için)
                                # Başarı genelde 0.2s sürüyor. 0.4s timeout yeterli.
                                # Hata olursa hızlıca retry'a düşsün (0.7s bekletmesin).
                                old_timeout = self.instrument.serial.timeout
                                self.instrument.serial.timeout = 0.6
                                
                                start_time = time.time() # METRICS: Start timer here
                                try:
                                    # Öncesinde sessizlik (Bus stabilization)
                                    # Polling'den hemen sonra geliyorsa cihazın toparlaması için biraz daha süre ver
                                    time.sleep(0.1)
                                    
                                    # Function code 6 (Write Single Register)
                                    print(f"DEBUG: Cmd {sid} -> Reg:{reg} Val:{val} (Try {attempt+1})")
                                    self.instrument.write_register(reg, val, 0, functioncode=6)
                                    print(f"DEBUG: Success! took {time.time() - start_time:.3f}s")
                                finally:
                                    self.instrument.serial.timeout = old_timeout
                                
                                # Metrics Update
                                end_time = time.time()
                                resp_time = (end_time - start_time) * 1000
                                
                                if sid in self.data_store:
                                    self.data_store[sid]['slave_resp_time'] = resp_time
                                    # History Update
                                    hist = self.data_store[sid].get('slave_resp_history', [])
                                    hist.append(resp_time)
                                    if len(hist) > 20: hist.pop(0)
                                    self.data_store[sid]['slave_resp_history'] = hist

                                    if ts > 0:
                                        self.data_store[sid]['cmd_latency'] = (end_time - ts) * 1000
                                    self.data_store[sid]['online'] = True
                                    self.data_store[sid]['errors'] = 0
                                    
                                    # CACHE UPDATE
                                    if reg != REG_COMMAND:
                                        self.data_store[sid]['cache'][reg] = val
                                
                                cmd_success = True
                                break # Başarılı, döngüden çık
                                
                            except Exception as e:
                                err_msg = str(e)
                                if "No communication" in err_msg:
                                    print(f"Meşgul, tekrar deneniyor ({attempt+1}/3)...")
                                else:
                                    print(f"Komut Hatası (ID {sid}, Try {attempt+1}): {e}")
                        
                        # Loop dışında bekleme (Lock serbestken)
                        if not cmd_success: time.sleep(0.1)

                    time.sleep(0.05) # Komutlar arası minik boşluk
                except queue.Empty:
                    pass
            
            if had_command:
                self.after(0, self._update_ui_data)
                continue

            # 2. Periyodik Sorgu
            if not self.devices:
                time.sleep(0.5)
                continue
            
            if device_index >= len(self.devices):
                device_index = 0
            
            device = self.devices[device_index]
            sid = device['id']
            
            # Loop Time Hesabı
            now = time.time()
            if sid in self.data_store:
                last_poll = self.data_store[sid].get('last_poll_ts', 0)
                if last_poll > 0:
                    loop_time = (now - last_poll) * 1000
                    if loop_time < 20000: # Filtre: mantıksız değerleri ele
                        self.data_store[sid]['loop_time'] = loop_time
                        # History Update
                        hist = self.data_store[sid].get('loop_time_history', [])
                        hist.append(loop_time)
                        if len(hist) > 20: hist.pop(0)
                        self.data_store[sid]['loop_time_history'] = hist
                self.data_store[sid]['last_poll_ts'] = now

            # Sorgula
            self._query_periodic(sid)
            
            device_index += 1
            # Döngü Hızı
            time.sleep(0.05)
            self.after(0, self._update_ui_data)

    def _query_periodic(self, sid):
        if sid not in self.data_store: return
        success = False
        self.data_store[sid]['total_count'] += 1

        for attempt in range(2): # 2 Burst Retry
            with self.poll_lock:
                try:
                    t_start = time.time()
                    
                    # Buffer Temizliği
                    self.instrument.serial.reset_input_buffer()
                    if attempt > 0: # Retry ise output da temizle
                         self.instrument.serial.reset_output_buffer()
                         time.sleep(0.05)
                    
                    self.instrument.address = sid
                    
                    # Read
                    count = 9 if self.detail_open_for == sid else 3
                    vals = self.instrument.read_registers(1, count, 3) # Reg 1..N
                    
                    t_end = time.time()
                    latency = (t_end - t_start) * 1000
                    
                    self.data_store[sid]['latency'] = latency
                    self.data_store[sid]['timestamp'] = t_end
                    self.data_store[sid]['online'] = True
                    self.data_store[sid]['errors'] = 0
                    self.data_store[sid]['success_count'] += 1
                    
                    for i, v in enumerate(vals):
                        self.data_store[sid]['cache'][1 + i] = v
                    
                    success = True
                    break
                except Exception:
                    pass
            
            if not success: time.sleep(0.1) # Retry arası bekleme artırıldı
        
        if not success:
            self.data_store[sid]['errors'] += 1
            
        # Polling bitti, biraz bekle ki sonraki komut veya sorgu için hat rahatlasın
        time.sleep(0.05)
        if self.data_store[sid]['errors'] >= 1:
            self.data_store[sid]['online'] = False

    # ========================================================================
    #  DETAY POPUP
    # ========================================================================
    # ========================================================================
    #  SETTINGS POPUP (SEXY REDESIGN)
    # ========================================================================
    def _open_detail_popup(self, slave_id):
        device = next((d for d in self.devices if d['id'] == slave_id), None)
        if not device: return

        self.detail_open_for = slave_id
        popup = ctk.CTkToplevel(self)
        popup.title(f"SYSTEM: NODE_MGMT [{slave_id}]")
        popup.geometry("460x640")
        popup.configure(fg_color=COLORS['bg_dark'])
        popup.transient(self)
        popup.grab_set()

        def on_close():
            self.detail_open_for = None
            popup.destroy()

        popup.protocol("WM_DELETE_WINDOW", on_close)

        # Header Section
        header = ctk.CTkFrame(popup, fg_color="transparent")
        header.pack(fill="x", pady=(25, 10))
        
        ctk.CTkLabel(header, text="☢", font=("Consolas", 32), text_color=COLORS['accent']).pack()
        ctk.CTkLabel(header, text=device['name'].upper(), font=("Consolas", 18, "bold"), text_color=COLORS['text']).pack()
        ctk.CTkLabel(header, text=f"INTERFACE_ID: {slave_id:02d}", font=("Consolas", 10), text_color=COLORS['text_dim']).pack()

        # Separator
        ctk.CTkFrame(popup, height=1, fg_color=COLORS['border']).pack(fill="x", padx=40, pady=10)

        # Parameters Area
        scroll_area = ctk.CTkScrollableFrame(popup, fg_color="transparent", height=320, corner_radius=0)
        scroll_area.pack(fill="both", expand=True, padx=25)

        entries = []
        value_labels = []
        for p in PARAM_DEFS:
            row = ctk.CTkFrame(scroll_area, fg_color=COLORS['bg_dark'], corner_radius=0, border_width=1, border_color=COLORS['border'])
            row.pack(fill="x", pady=2)
            
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="both", expand=True, padx=15, pady=8)

            ctk.CTkLabel(inner, text=f"> {p['label']}", anchor="w", font=("Consolas", 11, "bold"), text_color=COLORS['text']).pack(side="left")
            
            e = ctk.CTkEntry(inner, width=80, height=28, corner_radius=0, 
                              fg_color=COLORS['bg_dark'], border_color=COLORS['border'], 
                              font=("Consolas", 12), justify="center")
            e.pack(side="right")
            
            lbl_val = ctk.CTkLabel(inner, text="---", width=40, text_color=COLORS['matrix_green'], font=("Consolas", 13, "bold"))
            lbl_val.pack(side="right", padx=10)
            
            value_labels.append((p, lbl_val))
            entries.append((p, e))

        # Bottom Panel
        bottom = ctk.CTkFrame(popup, fg_color=COLORS['bg_dark'], corner_radius=0, border_width=1, border_color=COLORS['border'])
        bottom.pack(fill="x", pady=(10, 0))

        # Stats Overlay
        stats_box = ctk.CTkFrame(bottom, fg_color="transparent")
        stats_box.pack(fill="x", padx=40, pady=15)
        
        def create_stat(parent, label, key, side="left"):
            f = ctk.CTkFrame(parent, fg_color="transparent")
            f.pack(side=side, fill="both", expand=True)
            ctk.CTkLabel(f, text=label, font=("Consolas", 8, "bold"), text_color=COLORS['text_dim']).pack()
            l_val = ctk.CTkLabel(f, text="-- ms", font=("Consolas", 11, "bold"), text_color=COLORS['text'])
            l_val.pack()
            l_avg = ctk.CTkLabel(f, text="(Avg: --)", font=("Consolas", 9), text_color=COLORS['text_dim'])
            l_avg.pack()
            return l_val, l_avg

        lbl_ping, _ = create_stat(stats_box, ":: PING ::", 'latency')
        lbl_slave, lbl_slave_avg = create_stat(stats_box, ":: SLAVE_RESP ::", 'slave_resp_time', "right")

        lbl_err = ctk.CTkLabel(bottom, text="", font=("Consolas", 10))
        lbl_err.pack(pady=5)

        def refresh_values():
            if self.detail_open_for != slave_id: return
            d = self.data_store.get(slave_id, {})
            cache = d.get('cache', {})

            for p, lbl in value_labels:
                raw = cache.get(p['reg'], 0)
                cur = raw - 10 if p.get('offset') else raw
                lbl.configure(text=str(cur))
            
            lbl_ping.configure(text=f"{d.get('latency',0):.0f} ms")
            lbl_slave.configure(text=f"{d.get('slave_resp_time',0):.0f} ms")
            
            hist_s = d.get('slave_resp_history', [])
            avg_s = sum(hist_s)/len(hist_s) if hist_s else 0
            lbl_slave_avg.configure(text=f"(Avg: {avg_s:.0f})")
            
            popup.after(500, refresh_values)

        refresh_values()

        def apply():
            errors = []
            for p, e in entries:
                val_str = e.get().strip()
                if not val_str: continue
                try:
                    val = int(val_str)
                    if val < p['min'] or val > p['max']:
                        errors.append(f"{p['label']}_RANGE_ERR")
                        continue
                    self._send_command_settings(slave_id, p['reg'], val + 10 if p.get('offset') else val)
                except ValueError: errors.append(f"{p['label']}_TYPE_ERR")
            
            if errors: lbl_err.configure(text=" | ".join(errors), text_color=COLORS['red'])
            else: 
                lbl_err.configure(text=":: SET_QUEUE_CONFIRMED ::", text_color=COLORS['accent'])
                for _, e in entries: e.delete(0, 'end')

        # Action Buttons
        btn_box = ctk.CTkFrame(bottom, fg_color="transparent")
        btn_box.pack(fill="x", padx=35, pady=(5, 25))

        btn_apply = ctk.CTkButton(btn_box, text="[ EXEC APPLY ]", font=("Consolas", 12, "bold"), 
                                  height=40, corner_radius=0, fg_color="transparent",
                                  border_width=1, border_color=COLORS['accent'],
                                  hover_color=COLORS['matrix_dark'], command=apply)
        btn_apply.pack(fill="x", pady=5)

        btn_close = ctk.CTkButton(btn_box, text="[ TERMINATE WINDOW ]", font=("Consolas", 11), 
                                  height=32, corner_radius=0, fg_color="transparent",
                                  hover_color="#3D0000", command=on_close)
        btn_close.pack(fill="x")

    def _send_command_settings(self, sid, reg, val):
        """Ayar değişikliği için genel komut gönderici (aynı kuyruğu kullanır)."""
        if sid not in self.data_store: return
        self.command_queue.put((sid, reg, val, 0)) # Settings için TS önemli değil

if __name__ == "__main__":
    app = HMIApp()
    app.mainloop()
