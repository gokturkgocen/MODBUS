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

# --- LIQUID GLASS RENK PALETİ ---
COLORS = {
    'bg_dark':       "#06070D",
    'bg_mid':        "#0D0F1A",
    'bg_card':       "#141825",
    'bg_card_hover': "#1C2033",
    'bg_card_open':  "#102A20",
    'bg_card_closed':"#2A1515",
    'glass_border':  "#2A3350",
    'glass_glow':    "#4A6CF7",
    'glass_surface': "#181D2E",
    'glass_input':   "#111526",
    'toolbar_bg':    "#0A0C14",
    'toolbar_border':"#1E2340",
    'accent':        "#5B8DEF",
    'accent_dark':   "#3D6FD9",
    'accent_glow':   "#7AABFF",
    'green':         "#34D399",
    'green_dark':    "#059669",
    'red':           "#F87171",
    'red_dark':      "#DC2626",
    'yellow':        "#FBBF24",
    'orange':        "#FB923C",
    'text':          "#E8ECF4",
    'text_dim':      "#6B7A99",
    'text_label':    "#8B9BC0",
    'transparent':   "transparent",
    'dim_icon':      "#333842",
    'btn_dim':       "#222633",
    'border':        "#2A3350",
    'surface':       "#181D2E",
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

        ctk.CTkLabel(inner, text="◆", font=("Segoe UI", 18), text_color=COLORS['accent']).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(inner, text="HMI", font=("Segoe UI", 14, "bold"), text_color=COLORS['text']).pack(side="left", padx=(0, 16))

        sep = ctk.CTkFrame(inner, width=1, height=28, fg_color=COLORS['glass_border'])
        sep.pack(side="left", padx=(0, 16))

        ctk.CTkLabel(inner, text="PORT", font=("Segoe UI", 9, "bold"), text_color=COLORS['text_dim']).pack(side="left", padx=(0, 4))
        ports = [p.device for p in serial.tools.list_ports.comports()] or ["Port Yok"]
        self.combo_port = ctk.CTkComboBox(inner, values=ports, width=115, height=30,
                                          font=("Consolas", 11), corner_radius=8,
                                          fg_color=COLORS['glass_input'], border_color=COLORS['glass_border'],
                                          button_color=COLORS['glass_border'], button_hover_color=COLORS['accent_dark'],
                                          dropdown_fg_color=COLORS['bg_card'])
        self.combo_port.pack(side="left", padx=(0, 10))

        ctk.CTkLabel(inner, text="BAUD", font=("Segoe UI", 9, "bold"), text_color=COLORS['text_dim']).pack(side="left", padx=(0, 4))
        self.combo_baud = ctk.CTkComboBox(inner, values=["9600","19200","38400","57600","115200","230400","250000"],
                                          width=90, height=30,
                                          font=("Consolas", 11), corner_radius=8,
                                          fg_color=COLORS['glass_input'], border_color=COLORS['glass_border'],
                                          button_color=COLORS['glass_border'], button_hover_color=COLORS['accent_dark'],
                                          dropdown_fg_color=COLORS['bg_card'])
        self.combo_baud.set("9600")
        self.combo_baud.pack(side="left", padx=(0, 16))

        sep2 = ctk.CTkFrame(inner, width=1, height=28, fg_color=COLORS['glass_border'])
        sep2.pack(side="left", padx=(0, 16))

        self.btn_add = ctk.CTkButton(inner, text="＋  Ekle", width=90, height=30,
                                     font=("Segoe UI", 11, "bold"), corner_radius=15,
                                     fg_color=COLORS['accent'], hover_color=COLORS['accent_dark'],
                                     command=self._open_add_device_dialog)
        self.btn_add.pack(side="left", padx=3)

        self.btn_del = ctk.CTkButton(inner, text="✕  Sil", width=80, height=30,
                                     font=("Segoe UI", 11, "bold"), corner_radius=15,
                                     fg_color="#3D1520", hover_color=COLORS['red_dark'],
                                     command=self._delete_selected_device)
        self.btn_del.pack(side="left", padx=3)

        self.btn_connect = ctk.CTkButton(inner, text="⚡ Bağlan", width=110, height=30,
                                         font=("Segoe UI", 11, "bold"), corner_radius=15,
                                         fg_color=COLORS['green_dark'], hover_color=COLORS['green'],
                                         command=self._toggle_connection)
        self.btn_connect.pack(side="left", padx=(8, 0))

        self.lbl_toolbar_status = ctk.CTkLabel(inner, text="● Bağlı değil",
                                               font=("Segoe UI", 11), text_color=COLORS['text_dim'])
        self.lbl_toolbar_status.pack(side="right", padx=8)

    # ========================================================================
    #  GRID ALANI
    # ========================================================================
    def _build_grid_area(self):
        self.grid_container = ctk.CTkScrollableFrame(self, fg_color=COLORS['bg_dark'],
                                                     corner_radius=0,
                                                     scrollbar_button_color=COLORS['glass_border'],
                                                     scrollbar_button_hover_color=COLORS['accent_dark'])
        self.grid_container.pack(fill="both", expand=True, padx=20, pady=(12, 20))

        self.grid_frame = ctk.CTkFrame(self.grid_container, fg_color="transparent")
        self.grid_frame.pack(fill="both", expand=True)

        self.lbl_empty = ctk.CTkLabel(self.grid_frame,
                                      text="Henüz cihaz eklenmedi.\n＋ Ekle ile başlayın.",
                                      font=("Segoe UI", 16), text_color=COLORS['text_dim'])
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
        card = ctk.CTkFrame(self.grid_frame, fg_color=COLORS['bg_card'],
                            corner_radius=16, border_width=1,
                            border_color=COLORS['glass_border'],
                            width=250, height=290)
        card.pack_propagate(False)

        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=16, pady=14)

        # Başlık ve İsim
        name_entry = ctk.CTkEntry(content, font=("Segoe UI", 14, "bold"), height=34,
                                  fg_color=COLORS['glass_input'],
                                  border_color=COLORS['glass_border'],
                                  corner_radius=10, justify="center",
                                  text_color=COLORS['text'])
        name_entry.insert(0, name)
        name_entry.pack(fill="x", pady=(0, 6))
        name_entry.bind("<FocusOut>", lambda e, s=sid, ent=name_entry: self._update_device_name(s, ent.get()))
        name_entry.bind("<Return>", lambda e, s=sid, ent=name_entry: (self._update_device_name(s, ent.get()), self.focus()))

        # LED (Gizli)
        status_led = ctk.CTkLabel(content, text="", font=("Arial", 1), width=0, height=0)
        
        # İkon Alanı
        icon_frame = ctk.CTkFrame(content, fg_color="transparent", height=40)
        icon_frame.pack(pady=5)
        
        icon_err = ctk.CTkLabel(icon_frame, text="▲", font=("Arial", 24), text_color=COLORS['bg_card'])
        tooltip_err = CTkToolTip(icon_err, "Hata Yok")

        icon_warn = ctk.CTkLabel(icon_frame, text="▲", font=("Arial", 24), text_color=COLORS['bg_card'])
        tooltip_warn = CTkToolTip(icon_warn, "Uyarı Yok")
        
        # Durum Yazısı
        lbl_status = ctk.CTkLabel(content, text="Bekleniyor...", 
                                  font=("Segoe UI", 16, "bold"),
                                  text_color=COLORS['text_dim'])
        lbl_status.pack(pady=(5, 5))

        # Butonlar
        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(6, 6))
        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)

        btn_on = ctk.CTkButton(btn_frame, text="AÇ",
                      font=("Segoe UI", 11, "bold"), height=34,
                      fg_color=COLORS['green_dark'], hover_color=COLORS['green'],
                      corner_radius=12,
                      command=lambda s=sid: self._send_command(s, 1)
                      )
        btn_on.grid(row=0, column=0, padx=(0, 3), sticky="ew")

        btn_off = ctk.CTkButton(btn_frame, text="KAPAT",
                      font=("Segoe UI", 11, "bold"), height=34,
                      fg_color=COLORS['red_dark'], hover_color=COLORS['red'],
                      corner_radius=12,
                      command=lambda s=sid: self._send_command(s, 2)
                      )
        btn_off.grid(row=0, column=1, padx=(3, 0), sticky="ew")

        # Detaylar Button
        ctk.CTkButton(content, text="⚙  Ayarlar",
                      font=("Segoe UI", 10), height=28,
                      fg_color=COLORS['glass_surface'],
                      hover_color=COLORS['bg_card_hover'],
                      corner_radius=10, border_width=1,
                      border_color=COLORS['glass_border'],
                      command=lambda s=sid: self._open_detail_popup(s)
                      ).pack(fill="x", pady=(2, 0))

        card.bind("<Button-1>", lambda e, s=sid: self._select_device(s))

        self.device_cards_ui[sid] = {
            'frame': card, 'icon_err': icon_err, 'tooltip_err': tooltip_err,
            'icon_warn': icon_warn, 'tooltip_warn': tooltip_warn,
            'name_entry': name_entry, 'led': status_led,
            'btn_on': btn_on, 'btn_off': btn_off, 'lbl_status': lbl_status
        }
        
        # Hitbox Fix
        def bind_recursive(w, s):
            if isinstance(w, ctk.CTkButton): return
            try:
                w.bind("<Button-1>", lambda e, sid=s: self._select_device(sid))
            except: pass
            for child in w.winfo_children():
                bind_recursive(child, s)
        
        bind_recursive(card, sid)

    def _update_ui_data(self):
        with self.poll_lock:
            for sid, ui in self.device_cards_ui.items():
                if sid not in self.data_store: continue
                
                try:
                    data = self.data_store[sid]
                    online = data['online']
                    cache = data['cache']
                    status = cache.get(REG_STATUS, 0)
                    
                    border = COLORS['glass_glow'] if sid == self.selected_device_id else COLORS['glass_border']
                    if ui['frame'].cget("border_color") != border:
                        ui['frame'].configure(border_color=border)
                    
                    status_text = STATUS_TEXT.get(status, "Bilinmiyor")
                    ui['lbl_status'].configure(text=status_text, text_color=COLORS['text'])
                    
                    if not online:
                        if ui['frame'].cget("fg_color") != COLORS['bg_card_closed']:
                            ui['frame'].configure(fg_color=COLORS['bg_card_closed'])
                    else:
                        if ui['frame'].cget("fg_color") != COLORS['bg_card']:
                            ui['frame'].configure(fg_color=COLORS['bg_card'])

                    ui['btn_on'].configure(fg_color=COLORS['green_dark'])
                    ui['btn_off'].configure(fg_color=COLORS['red_dark'])

                    last_ts = data.get('timestamp', 0)
                    if time.time() - last_ts > 15.0 and self.polling:
                        online = False
                        is_stale = True
                    else:
                        is_stale = False

                    if not online: led_color = COLORS['red']
                    elif is_stale: led_color = COLORS['yellow']
                    else: led_color = COLORS['green']
                    
                    if ui['led'].cget("text_color") != led_color:
                        ui['led'].configure(text_color=led_color)

                    err_val = cache.get(REG_ERRORS, 0)
                    warn_val = cache.get(REG_WARNINGS, 0)
                    
                    active_errors = []
                    if err_val > 0:
                        for bit, msg in ERR_CODES.items():
                            if (err_val >> bit) & 1:
                                active_errors.append(f"• {msg}")
                        if not active_errors: active_errors.append(f"• Kod: {err_val}")

                    active_warnings = []
                    if warn_val > 0:
                        for bit, msg in WARN_CODES.items():
                            if (warn_val >> bit) & 1:
                                active_warnings.append(f"• {msg}")
                        if not active_warnings: active_warnings.append(f"• Kod: {warn_val}")
                    
                    if active_errors:
                        if not ui['icon_err'].winfo_ismapped(): ui['icon_err'].pack(side="left", padx=10)
                        ui['icon_err'].configure(text_color=COLORS['red']) 
                        ui['tooltip_err'].label.configure(text="\n".join(active_errors))
                    else:
                        ui['icon_err'].pack_forget()
                        ui['tooltip_err'].label.configure(text="")

                    if online and active_warnings:
                        if not ui['icon_warn'].winfo_ismapped(): ui['icon_warn'].pack(side="right", padx=10)
                        ui['icon_warn'].configure(text_color=COLORS['yellow']) 
                        ui['tooltip_warn'].label.configure(text="\n".join(active_warnings))
                    elif online and is_stale:
                        if not ui['icon_warn'].winfo_ismapped(): ui['icon_warn'].pack(side="right", padx=10)
                        ui['icon_warn'].configure(text_color=COLORS['yellow'])
                        ui['tooltip_warn'].label.configure(text="VERİ GECİKMESİ")
                    else:
                        ui['icon_warn'].pack_forget()
                        ui['tooltip_warn'].label.configure(text="")
                    
                except Exception as e:
                    print(f"UI Update Error (SID {sid}): {e}") 

    # ========================================================================
    #  OPERASYONLAR
    # ========================================================================
    def _open_add_device_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Cihaz Ekle")
        dialog.geometry("380x380")
        dialog.configure(fg_color=COLORS['bg_mid'])
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="Yeni Cihaz Ekle", font=("Segoe UI", 16, "bold"), text_color=COLORS['text']).pack(pady=(24, 16))
        ctk.CTkLabel(dialog, text="SLAVE ID", font=("Segoe UI", 9, "bold"), text_color=COLORS['text_dim']).pack()
        ent_id = ctk.CTkEntry(dialog, width=120, height=34, corner_radius=10, fg_color=COLORS['glass_input'], border_color=COLORS['glass_border'], font=("Consolas", 13), justify="center")
        ent_id.pack(pady=(4, 10))
        ent_id.insert(0, "1")

        ctk.CTkLabel(dialog, text="CİHAZ ADI", font=("Segoe UI", 9, "bold"), text_color=COLORS['text_dim']).pack()
        ent_name = ctk.CTkEntry(dialog, width=220, height=34, corner_radius=10, fg_color=COLORS['glass_input'], border_color=COLORS['glass_border'], font=("Segoe UI", 12), justify="center")
        ent_name.pack(pady=(4, 16))
        ent_name.insert(0, "Yeni Cihaz")

        lbl_err = ctk.CTkLabel(dialog, text="", font=("Segoe UI", 11), text_color=COLORS['red'])
        lbl_err.pack(pady=2)

        def add():
            try:
                sid_str = ent_id.get().strip()
                if not sid_str:
                    lbl_err.configure(text="ID boş olamaz!")
                    return
                try: sid = int(sid_str)
                except ValueError: 
                    lbl_err.configure(text="ID sayı olmalı!")
                    return

                if any(d['id'] == sid for d in self.devices):
                    lbl_err.configure(text=f"ID {sid} zaten mevcut!")
                    return
                
                name = ent_name.get().strip()
                if not name:
                    lbl_err.configure(text="İsim boş olamaz!")
                    return

                self.devices.append({'id': sid, 'name': name})
                self.data_store[sid] = {
                    'cache': {}, 'pending': {}, 'online': True, 'errors': 0, 'last_update': '',
                    'latency': 0, 'success_count': 0, 'total_count': 0,
                    'cmd_latency': 0, 'last_cmd_ts': 0,
                    'slave_resp_time': 0, 'loop_time': 0, 'last_poll_ts': 0,
                    'slave_resp_history': [], 'loop_time_history': []
                }
                
                try: self._save_config()
                except Exception as e: lbl_err.configure(text=f"Kayıt Hatası: {e}")
                
                self._sync_grid_layout()
                dialog.destroy()
            except Exception as e:
                lbl_err.configure(text=f"Beklenmeyen Hata: {e}")

        ctk.CTkButton(dialog, text="EKLE", height=36, corner_radius=12,
                      font=("Segoe UI", 12, "bold"), fg_color=COLORS['accent'], hover_color=COLORS['accent_dark'],
                      command=add).pack(pady=6, padx=60, fill="x")

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
            self.btn_connect.configure(text="⚡ Bağlan", fg_color=COLORS['green_dark'])
            self.lbl_toolbar_status.configure(text="● Bağlı değil", text_color=COLORS['text_dim'])
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

                self.btn_connect.configure(text="⏹  Durdur", fg_color=COLORS['red_dark'])
                self.lbl_toolbar_status.configure(text=f"● Bağlı: {port} @ {baud}", text_color=COLORS['green'])
                threading.Thread(target=self._polling_worker, daemon=True).start()
            except Exception as e:
                self.lbl_toolbar_status.configure(text=f"✕ Hata: {e}", text_color=COLORS['red'])

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
                                self.instrument.serial.timeout = 0.4
                                
                                start_time = time.time() # METRICS: Start timer here
                                try:
                                    # Öncesinde sessizlik (Bus stabilization)
                                    time.sleep(0.05)
                                    
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
            if self.data_store[sid]['errors'] >= 1:
                self.data_store[sid]['online'] = False

    # ========================================================================
    #  DETAY POPUP
    # ========================================================================
    def _open_detail_popup(self, slave_id):
        device = next((d for d in self.devices if d['id'] == slave_id), None)
        if not device: return

        self.detail_open_for = slave_id
        popup = ctk.CTkToplevel(self)
        popup.title(f"Detaylar — {device['name']}")
        popup.geometry("480x620")
        popup.configure(fg_color=COLORS['bg_mid'])
        popup.transient(self)
        popup.grab_set()

        def on_close():
            self.detail_open_for = None
            popup.destroy()

        popup.protocol("WM_DELETE_WINDOW", on_close)

        ctk.CTkLabel(popup, text=f"⚙  {device['name']}", font=("Segoe UI", 18, "bold"), text_color=COLORS['text']).pack(pady=(20, 2))
        ctk.CTkLabel(popup, text=f"Slave ID: {slave_id}", font=("Consolas", 10), text_color=COLORS['text_dim']).pack(pady=(0, 12))
        ctk.CTkFrame(popup, height=1, fg_color=COLORS['glass_border']).pack(fill="x", padx=30, pady=(0, 12))

        entries = []
        value_labels = []
        for p in PARAM_DEFS:
            row = ctk.CTkFrame(popup, fg_color=COLORS['bg_card'], corner_radius=10, height=40)
            row.pack(fill="x", padx=28, pady=3)
            row.pack_propagate(False)

            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="both", expand=True, padx=12, pady=4)

            ctk.CTkLabel(inner, text=p['label'], width=130, anchor="w", font=("Segoe UI", 11), text_color=COLORS['text_label']).pack(side="left")
            lbl_val = ctk.CTkLabel(inner, text="---", width=55, text_color=COLORS['accent_glow'], font=("Consolas", 13, "bold"))
            lbl_val.pack(side="left")
            value_labels.append((p, lbl_val))

            e = ctk.CTkEntry(inner, width=90, height=28, corner_radius=8, fg_color=COLORS['glass_input'], border_color=COLORS['glass_border'], font=("Consolas", 11), justify="center")
            e.pack(side="right")
            entries.append((p, e))

        lbl_err = ctk.CTkLabel(popup, text="", font=("Segoe UI", 10))
        lbl_err.pack(pady=6)

        # İstatistikler
        stats_frame = ctk.CTkFrame(popup, fg_color="transparent")
        stats_frame.pack(fill="x", padx=30, pady=5)
        
        # Sol ve Sağ Sütun
        col1 = ctk.CTkFrame(stats_frame, fg_color="transparent")
        col1.pack(side="left", fill="y")
        col2 = ctk.CTkFrame(stats_frame, fg_color="transparent")
        col2.pack(side="right", fill="y")

        lbl_ping = ctk.CTkLabel(col1, text="Ping: -- ms", font=("Consolas", 10), text_color=COLORS['text_dim'], anchor="w")
        lbl_ping.pack(fill="x")
        lbl_cmd = ctk.CTkLabel(col1, text="Cmd Lat: -- ms", font=("Consolas", 10), text_color=COLORS['text_dim'], anchor="w")
        lbl_cmd.pack(fill="x")
        
        lbl_slave = ctk.CTkLabel(col2, text="Slave Resp: -- ms", font=("Consolas", 10), text_color=COLORS['text_dim'], anchor="e")
        lbl_slave.pack(fill="x")
        lbl_slave_avg = ctk.CTkLabel(col2, text="Avg: -- ms", font=("Consolas", 9), text_color=COLORS['text_dim'], anchor="e")
        lbl_slave_avg.pack(fill="x")

        lbl_loop = ctk.CTkLabel(col2, text="Loop Time: -- ms", font=("Consolas", 10), text_color=COLORS['text_dim'], anchor="e")
        lbl_loop.pack(fill="x")
        lbl_loop_avg = ctk.CTkLabel(col2, text="Avg: -- ms", font=("Consolas", 9), text_color=COLORS['text_dim'], anchor="e")
        lbl_loop_avg.pack(fill="x")

        def refresh_values():
            if self.detail_open_for != slave_id: return
            d = self.data_store.get(slave_id, {})
            cache = d.get('cache', {})

            for p, lbl in value_labels:
                raw = cache.get(p['reg'], 0)
                cur = raw - 10 if p.get('offset') else raw
                lbl.configure(text=str(cur))
            
            lbl_ping.configure(text=f"Ping: {d.get('latency',0):.0f} ms")
            lbl_cmd.configure(text=f"Cmd Lat: {d.get('cmd_latency',0):.0f} ms")
            lbl_slave.configure(text=f"Slave Resp: {d.get('slave_resp_time',0):.0f} ms")
            
            # Avg calc
            hist_s = d.get('slave_resp_history', [])
            avg_s = sum(hist_s)/len(hist_s) if hist_s else 0
            lbl_slave_avg.configure(text=f"(Avg: {avg_s:.0f} ms)")

            lbl_loop.configure(text=f"Loop Time: {d.get('loop_time',0):.0f} ms")
            
            hist_l = d.get('loop_time_history', [])
            avg_l = sum(hist_l)/len(hist_l) if hist_l else 0
            lbl_loop_avg.configure(text=f"(Avg: {avg_l:.0f} ms)")
            
            popup.after(250, refresh_values)

        refresh_values()

        def apply():
            writes = {}
            errors = []
            for p, e in entries:
                val_str = e.get().strip()
                if not val_str: continue
                try:
                    val = int(val_str)
                    if val < p['min'] or val > p['max']:
                        errors.append(f"{p['label']}: Aralık {p['min']}-{p['max']}")
                        continue
                    # Kuyruğa at 
                    self._send_command_settings(slave_id, p['reg'], val + 10 if p.get('offset') else val)
                except ValueError: errors.append(f"{p['label']}: Sayı girin")
            
            if errors: lbl_err.configure(text="\n".join(errors), text_color=COLORS['red'])
            else: 
                lbl_err.configure(text="✓ Kuyruğa alındı", text_color=COLORS['green'])
                for _, e in entries: e.delete(0, 'end')

        ctk.CTkFrame(popup, height=1, fg_color=COLORS['glass_border']).pack(fill="x", padx=30, pady=(6, 0))
        ctk.CTkButton(popup, text="UYGULA", font=("Segoe UI", 12, "bold"), height=38, corner_radius=12,
                      fg_color=COLORS['green_dark'], hover_color=COLORS['green'], command=apply).pack(pady=(14, 6), padx=28, fill="x")
        ctk.CTkButton(popup, text="KAPAT", font=("Segoe UI", 11), height=32, corner_radius=10,
                      fg_color=COLORS['glass_surface'], hover_color=COLORS['bg_card_hover'], border_width=1, border_color=COLORS['glass_border'],
                      command=on_close).pack(padx=28, fill="x")

    def _send_command_settings(self, sid, reg, val):
        """Ayar değişikliği için genel komut gönderici (aynı kuyruğu kullanır)."""
        if sid not in self.data_store: return
        self.command_queue.put((sid, reg, val, 0)) # Settings için TS önemli değil

if __name__ == "__main__":
    app = HMIApp()
    app.mainloop()
