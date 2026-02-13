import customtkinter as ctk
import minimalmodbus
import serial
import serial.tools.list_ports
import threading
import time
import json
import os

# --- ARAYÜZ AYARLARI ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# --- LIQUID GLASS RENK PALETİ ---
COLORS = {
    # Derinlik Katmanları (Arka plandan öne doğru)
    'bg_dark':       "#06070D",   # En derin katman — neredeyse siyah
    'bg_mid':        "#0D0F1A",   # Orta katman
    'bg_card':       "#141825",   # Kart yüzeyi — cam gibi koyu
    'bg_card_hover': "#1C2033",   # Kart hover
    'bg_card_open':  "#102A20",   # Açık durumu (Yeşilimsi tint)
    'bg_card_closed':"#2A1515",   # Kapalı durumu (Kırmızımsı tint)

    # Cam Kenarları ve Yüzeyler
    'glass_border':  "#2A3350",   # Cam kenar hissiyatı
    'glass_glow':    "#4A6CF7",   # Seçili kenar: mavi ışıltı
    'glass_surface': "#181D2E",   # İç yüzey
    'glass_input':   "#111526",   # Input arka planı

    # Toolbar
    'toolbar_bg':    "#0A0C14",   # Toolbar — en koyu yüzey
    'toolbar_border':"#1E2340",   # Toolbar alt çizgi

    # Vurgu Renkleri
    'accent':        "#5B8DEF",   # Ana mavi — yumuşak, parlak
    'accent_dark':   "#3D6FD9",   # Mavi hover
    'accent_glow':   "#7AABFF",   # Mavi ışıltı

    # Durum Renkleri (Yumuşak, cam üzerinde parlayan)
    'green':         "#34D399",   # Yeşil — mint tonu
    'green_dark':    "#059669",   # Yeşil koyu
    'red':           "#F87171",   # Kırmızı — yumuşak mercan
    'red_dark':      "#DC2626",   # Kırmızı koyu
    'yellow':        "#FBBF24",   # Sarı — sıcak amber
    'orange':        "#FB923C",   # Turuncu

    # Yazı
    'text':          "#E8ECF4",   # Ana metin — soğuk beyaz
    'text_dim':      "#6B7A99",   # Soluk metin
    'text_label':    "#8B9BC0",   # Etiket metni
    'text_label':    "#8B9BC0",   # Etiket metni
    'transparent':   "transparent",
    'dim_icon':      "#333842",   # Sönük ikon rengi
    'btn_dim':       "#222633",   # Sönük buton rengi
    
    # Genel
    'border':        "#2A3350",   # Varsayılan kenar
    'surface':       "#181D2E",   # Genel yüzey
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
STATUS_COLOR = {0: COLORS['text_dim'], 1: COLORS['green'], 2: COLORS['red']}

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
        self.data_store = {}        # {slave_id: {'cache':{reg:val}, 'pending':{reg:val}, 'online':bool, 'errors':int, ...}}
        self.instrument = None
        self.polling = False
        self.poll_lock = threading.Lock()
        self.connected = False
        
        # UI Referansları
        self.device_cards_ui = {}   # {slave_id: {'frame': ..., 'badge': ..., 'badge_lbl': ..., 'warn_icon': ...}}
        self.grid_frame = None
        self.selected_device_id = None
        self.detail_open_for = None  # Detay popup açık olan cihazın ID'si

        self._load_config()  # Kayıtlı cihazları yükle
        self._build_toolbar()
        self._build_grid_area()
        self._sync_grid_layout()  # Yüklenen cihazları ekrana bas

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
                        'cmd_latency': 0, 'last_cmd_ts': 0
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
        # Toolbar — Liquid Glass üst çubuk
        toolbar = ctk.CTkFrame(self, height=60, corner_radius=0, fg_color=COLORS['toolbar_bg'],
                               border_width=1, border_color=COLORS['toolbar_border'])
        toolbar.pack(fill="x", side="top")
        toolbar.pack_propagate(False)

        inner = ctk.CTkFrame(toolbar, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=10)

        # Logo / Başlık
        ctk.CTkLabel(inner, text="◆", font=("Segoe UI", 18), text_color=COLORS['accent']).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(inner, text="HMI", font=("Segoe UI", 14, "bold"), text_color=COLORS['text']).pack(side="left", padx=(0, 16))

        # Ayraç
        sep = ctk.CTkFrame(inner, width=1, height=28, fg_color=COLORS['glass_border'])
        sep.pack(side="left", padx=(0, 16))

        # Port
        ctk.CTkLabel(inner, text="PORT", font=("Segoe UI", 9, "bold"), text_color=COLORS['text_dim']).pack(side="left", padx=(0, 4))
        ports = [p.device for p in serial.tools.list_ports.comports()] or ["Port Yok"]
        self.combo_port = ctk.CTkComboBox(inner, values=ports, width=115, height=30,
                                          font=("Consolas", 11), corner_radius=8,
                                          fg_color=COLORS['glass_input'], border_color=COLORS['glass_border'],
                                          button_color=COLORS['glass_border'], button_hover_color=COLORS['accent_dark'],
                                          dropdown_fg_color=COLORS['bg_card'])
        self.combo_port.pack(side="left", padx=(0, 10))

        # Baudrate
        ctk.CTkLabel(inner, text="BAUD", font=("Segoe UI", 9, "bold"), text_color=COLORS['text_dim']).pack(side="left", padx=(0, 4))
        self.combo_baud = ctk.CTkComboBox(inner, values=["9600","19200","38400","57600","115200","230400","250000"],
                                          width=90, height=30,
                                          font=("Consolas", 11), corner_radius=8,
                                          fg_color=COLORS['glass_input'], border_color=COLORS['glass_border'],
                                          button_color=COLORS['glass_border'], button_hover_color=COLORS['accent_dark'],
                                          dropdown_fg_color=COLORS['bg_card'])
        self.combo_baud.set("9600")
        self.combo_baud.pack(side="left", padx=(0, 16))

        # Ayraç
        sep2 = ctk.CTkFrame(inner, width=1, height=28, fg_color=COLORS['glass_border'])
        sep2.pack(side="left", padx=(0, 16))

        # Butonlar — Glass pill style
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

        # Status — sağ taraf
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
        """Cihaz listesine göre grid layout'unu senkronize et (Ekleme/Silme durumunda)."""
        existing_ids = list(self.device_cards_ui.keys())
        target_ids = [d['id'] for d in self.devices]

        # Silinecekler
        for sid in existing_ids:
            if sid not in target_ids:
                self.device_cards_ui[sid]['frame'].destroy()
                del self.device_cards_ui[sid]

        # Eklenecekler
        for sid in target_ids:
            if sid not in self.device_cards_ui:
                device = next(d for d in self.devices if d['id'] == sid)
                self._create_device_card(sid, device['name'])

        # Boş mesajı kontrolü
        if not self.devices:
            self.lbl_empty.pack(pady=80)
        else:
            self.lbl_empty.pack_forget()

        # Grid yerleşimi
        cols = max(1, min(6, len(self.devices)))
        for i, (sid, ui) in enumerate(self.device_cards_ui.items()):
            r, c = divmod(i, cols)
            ui['frame'].grid(row=r, column=c, padx=10, pady=10, sticky="nsew")
            self.grid_frame.columnconfigure(c, weight=1)

    def _create_device_card(self, sid, name):
        """Liquid Glass cihaz kartı — cam yüzey efekti."""
        card = ctk.CTkFrame(self.grid_frame, fg_color=COLORS['bg_card'],
                            corner_radius=16, border_width=1,
                            border_color=COLORS['glass_border'],
                            width=250, height=290)
        card.pack_propagate(False)

        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=16, pady=14)

        # ── Başlık ──
        # İsim Girişi
        name_entry = ctk.CTkEntry(content, font=("Segoe UI", 14, "bold"), height=34,
                                  fg_color=COLORS['glass_input'],
                                  border_color=COLORS['glass_border'],
                                  corner_radius=10, justify="center",
                                  text_color=COLORS['text'])
        name_entry.insert(0, name)
        name_entry.pack(fill="x", pady=(0, 6))
        name_entry.bind("<FocusOut>", lambda e, s=sid, ent=name_entry: self._update_device_name(s, ent.get()))
        name_entry.bind("<Return>", lambda e, s=sid, ent=name_entry: (self._update_device_name(s, ent.get()), self.focus()))

        # ── Status LED (Sağ Üst Köşe) - ARTIK KULLANILMIYOR (Görünmez yapabiliriz veya kaldırabiliriz) ──
        # Kullanıcı arkaplan rengini istiyor, ama kod hatası olmasın diye widget'ı tutuyoruz, siliyoruz.
        status_led = ctk.CTkLabel(content, text="", font=("Arial", 1), width=0, height=0) 
        # Pack etmiyoruz, görünmez.
        
        # ── İkon Alanı (Hata/Uyarı Üçgenleri) ──
        icon_frame = ctk.CTkFrame(content, fg_color="transparent", height=40)
        icon_frame.pack(pady=5)
        
        # Hata İkonu (Sol)
        icon_err = ctk.CTkLabel(icon_frame, text="▲", font=("Arial", 24), text_color=COLORS['bg_card']) # Başlangıçta Görünmez
        # icon_err.pack(side="left", padx=10) # Başlangıçta pack etme
        tooltip_err = CTkToolTip(icon_err, "Hata Yok")

        # Uyarı İkonu (Sağ)
        icon_warn = ctk.CTkLabel(icon_frame, text="▲", font=("Arial", 24), text_color=COLORS['bg_card']) # Başlangıçta Görünmez
        # icon_warn.pack(side="right", padx=10) # Başlangıçta pack etme
        tooltip_warn = CTkToolTip(icon_warn, "Uyarı Yok")
        
        # ── Durum Yazısı (AÇIK/KAPALI) ──
        lbl_status = ctk.CTkLabel(content, text="Bekleniyor...", 
                                  font=("Segoe UI", 16, "bold"),
                                  text_color=COLORS['text_dim'])
        lbl_status.pack(pady=(5, 5))

        # ── Kontrol Butonları (Glass pill) ──
        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(6, 6))
        # Grid düzeni ile %50 - %50 paylaşım
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

        # ── Detay Butonu (Glass surface) ──
        ctk.CTkButton(content, text="⚙  Ayarlar",
                      font=("Segoe UI", 10), height=28,
                      fg_color=COLORS['glass_surface'],
                      hover_color=COLORS['bg_card_hover'],
                      corner_radius=10, border_width=1,
                      border_color=COLORS['glass_border'],
                      command=lambda s=sid: self._open_detail_popup(s)
                      ).pack(fill="x", pady=(2, 0))

        # Tıklama ile Seçim
        card.bind("<Button-1>", lambda e, s=sid: self._select_device(s))

        self.device_cards_ui[sid] = {
            'frame': card,
            'icon_err': icon_err, 'tooltip_err': tooltip_err,
            'icon_warn': icon_warn, 'tooltip_warn': tooltip_warn,
            'name_entry': name_entry,
            'led': status_led,
            'btn_on': btn_on,
            'btn_off': btn_off,
            'lbl_status': lbl_status
        }
        
        # Hitbox Fix: Kart içindeki tüm widget'lara tıklama eventi ekle
        def bind_recursive(w, s):
            if isinstance(w, ctk.CTkButton): return # Butonların fonksiyonunu bozma
            try:
                w.bind("<Button-1>", lambda e, sid=s: self._select_device(sid))
            except: pass
            for child in w.winfo_children():
                bind_recursive(child, s)
        
        bind_recursive(card, sid)

    def _update_ui_data(self):
        """Mevcut kartların verilerini KIRPIŞMADAN güncelle (Sadece Label configure eder)."""
        with self.poll_lock:
            for sid, ui in self.device_cards_ui.items():
                if sid not in self.data_store: continue
                
                try:
                    data = self.data_store[sid]
                    online = data['online']
                    cache = data['cache']
                    status = cache.get(REG_STATUS, 0)
                    
                    # Highlight selection (Seçili kart: mavi ışıltı kenar)
                    border = COLORS['glass_glow'] if sid == self.selected_device_id else COLORS['glass_border']
                    if ui['frame'].cget("border_color") != border:
                        ui['frame'].configure(border_color=border)
                    
                    
                    
                    # Durum Yazısı Güncelleme - Nötr Renk
                    status_text = STATUS_TEXT.get(status, "Bilinmiyor")
                    ui['lbl_status'].configure(text=status_text, text_color=COLORS['text'])
                    
                    # Bağlantı Durumu Arka Planı (Online/Offline)
                    if not online:
                        # Offline -> Kırmızımsı Arka Plan
                        if ui['frame'].cget("fg_color") != COLORS['bg_card_closed']:
                            ui['frame'].configure(fg_color=COLORS['bg_card_closed'])
                    else:
                        # Online -> Normal Arka Plan
                        if ui['frame'].cget("fg_color") != COLORS['bg_card']:
                            ui['frame'].configure(fg_color=COLORS['bg_card'])

                    # Butonların rengini sabitle (Artık aktif renk yok, sadece basınca çalışır)
                    ui['btn_on'].configure(fg_color=COLORS['green_dark'])
                    ui['btn_off'].configure(fg_color=COLORS['red_dark'])

                    # Watchdog: Veri bayatladıysa (15 sn) offline varsay
                    last_ts = self.data_store[sid].get('timestamp', 0)
                    if time.time() - last_ts > 15.0 and self.polling:
                        online = False
                        is_stale = True
                    else:
                        is_stale = False

                    # Connection LED Durumu
                    if not online: 
                        led_color = COLORS['red']
                    elif is_stale:
                        led_color = COLORS['yellow']
                    else:
                        led_color = COLORS['green']
                    
                    if ui['led'].cget("text_color") != led_color:
                        ui['led'].configure(text_color=led_color)

                    # Hata ve Uyarı Kontrolü (Reg 2 ve 3)
                    err_val = cache.get(REG_ERRORS, 0)
                    warn_val = cache.get(REG_WARNINGS, 0)
                    
                    # Bitwise Hata Çözümleme
                    active_errors = []
                    if err_val > 0:
                        for bit, msg in ERR_CODES.items():
                            if (err_val >> bit) & 1:
                                active_errors.append(f"• {msg}")
                        if not active_errors: # Tanımsız bitler varsa
                            active_errors.append(f"• Kod: {err_val}")

                    # Bitwise Uyarı Çözümleme
                    active_warnings = []
                    if warn_val > 0:
                        for bit, msg in WARN_CODES.items():
                            if (warn_val >> bit) & 1:
                                active_warnings.append(f"• {msg}")
                        if not active_warnings:
                            active_warnings.append(f"• Kod: {warn_val}")
                    
                    # İkon Durumları (Hata/Uyarı yoksa görünmez olsun - pack_forget)
                    # Kırmızı Üçgen (Hata)
                    if active_errors:
                        # Hata Var -> Görünür Kırmızı
                        if not ui['icon_err'].winfo_ismapped():
                            ui['icon_err'].pack(side="left", padx=10)
                        ui['icon_err'].configure(text_color=COLORS['red']) 
                        ui['tooltip_err'].label.configure(text="\n".join(active_errors))
                    else:
                        # Hata Yok -> Görünmez (pack_forget)
                        ui['icon_err'].pack_forget()
                        # Tooltip'i boşalt
                        ui['tooltip_err'].label.configure(text="")

                    # Sarı Üçgen (Uyarı)
                    if online and active_warnings:
                        # Uyarı Var -> Görünür Sarı
                        if not ui['icon_warn'].winfo_ismapped():
                            ui['icon_warn'].pack(side="right", padx=10)
                        ui['icon_warn'].configure(text_color=COLORS['yellow']) 
                        ui['tooltip_warn'].label.configure(text="\n".join(active_warnings))
                    elif online and is_stale:
                        if not ui['icon_warn'].winfo_ismapped():
                            ui['icon_warn'].pack(side="right", padx=10)
                        ui['icon_warn'].configure(text_color=COLORS['yellow'])
                        ui['tooltip_warn'].label.configure(text="VERİ GECİKMESİ")
                    else:
                        # Uyarı Yok -> Görünmez
                        ui['icon_warn'].pack_forget()
                        # Tooltip'i boşalt
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

        ctk.CTkLabel(dialog, text="Yeni Cihaz Ekle", font=("Segoe UI", 16, "bold"),
                     text_color=COLORS['text']).pack(pady=(24, 16))

        ctk.CTkLabel(dialog, text="SLAVE ID", font=("Segoe UI", 9, "bold"),
                     text_color=COLORS['text_dim']).pack()
        ent_id = ctk.CTkEntry(dialog, width=120, height=34, corner_radius=10,
                              fg_color=COLORS['glass_input'], border_color=COLORS['glass_border'],
                              font=("Consolas", 13), justify="center")
        ent_id.pack(pady=(4, 10))
        ent_id.insert(0, "1")

        ctk.CTkLabel(dialog, text="CİHAZ ADI", font=("Segoe UI", 9, "bold"),
                     text_color=COLORS['text_dim']).pack()
        ent_name = ctk.CTkEntry(dialog, width=220, height=34, corner_radius=10,
                                fg_color=COLORS['glass_input'], border_color=COLORS['glass_border'],
                                font=("Segoe UI", 12), justify="center")
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
                
                try:
                    sid = int(sid_str)
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
                    'cmd_latency': 0, 'last_cmd_ts': 0
                }
                
                try:
                    self._save_config()
                except Exception as e:
                    lbl_err.configure(text=f"Kayıt Hatası: {e}")
                    # Kayıt hatası olsa bile eklemeye devam et (runtime)
                
                self._sync_grid_layout()
                dialog.destroy()
            except Exception as e:
                lbl_err.configure(text=f"Beklenmeyen Hata: {e}")
                print(f"Ekleme Hatası: {e}")

        ctk.CTkButton(dialog, text="EKLE", height=36, corner_radius=12,
                      font=("Segoe UI", 12, "bold"),
                      fg_color=COLORS['accent'], hover_color=COLORS['accent_dark'],
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
        """Komut kuyruğa ekle — polling thread sonraki turda gönderir."""
        if sid not in self.data_store: return
        self.data_store[sid]['pending'][REG_COMMAND] = val
        self.data_store[sid]['last_cmd_ts'] = time.time() # Komut başlangıç zamanı

    def _update_device_name(self, sid, name):
        for d in self.devices:
            if d['id'] == sid: d['name'] = name; break

    # ========================================================================
    #  MODBUS MOTORU  (ORİJİNAL ÇALIŞAN PATTERN)
    # ========================================================================
    def _toggle_connection(self):
        if self.connected:
            self.polling = False
            self.connected = False
            if self.instrument and self.instrument.serial:
                try:
                    self.instrument.serial.close()
                except:
                    pass
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
                self.instrument.serial.timeout  = 1.0
                self.instrument.close_port_after_each_call = False  # Port açık kalsın

                self.connected = True
                self.polling = True

                # Hata sayaçlarını sıfırla
                for sid in self.data_store:
                    self.data_store[sid]['online'] = True
                    self.data_store[sid]['errors'] = 0

                self.btn_connect.configure(text="⏹  Durdur", fg_color=COLORS['red_dark'])
                self.lbl_toolbar_status.configure(text=f"● Bağlı: {port} @ {baud}", text_color=COLORS['green'])
                threading.Thread(target=self._polling_worker, daemon=True).start()
            except Exception as e:
                self.lbl_toolbar_status.configure(text=f"✕ Hata: {e}", text_color=COLORS['red'])

    def _polling_worker(self):
        """Polling döngüsü: optimize edilmiş, latency ölçümlü."""
        while self.polling:
            for device in self.devices:
                if not self.polling:
                    break

                sid = device['id']
                if sid not in self.data_store: continue # Safety check

                try: # Thread Crash Protection
                    success = False

                    # İstatistik başlat
                    self.data_store[sid]['total_count'] = self.data_store[sid].get('total_count', 0) + 1

                    for attempt in range(3):  # 3 kez arka arkaya dene (Burst Retries)
                        with self.poll_lock:
                            try:
                                start_time = time.time()  # Latency başlangıç

                                # Buffer temizle
                                self.instrument.serial.reset_input_buffer()
                                self.instrument.serial.reset_output_buffer()
                                time.sleep(0.05) 

                                self.instrument.address = sid

                                # 1. Bekleyen yazmaları gönder
                                pending = self.data_store[sid]['pending']
                                if pending:
                                    for reg, val in sorted(pending.items()):
                                        self.instrument.write_register(reg, val, functioncode=6)
                                    self.data_store[sid]['pending'] = {}

                                # 2. Register oku (Register 0 WO olduğu için 1'den başla)
                                # Detay açıkken Reg 1-9 arası (9 adet), değilse Reg 1-3 arası (Status, Err, Warn)
                                start_reg = 1
                                if self.detail_open_for == sid:
                                    read_count = 9 # Reg 1..9
                                else:
                                    read_count = 3 # Reg 1..3 (Status, Error, Warning)
                                
                                values = self.instrument.read_registers(start_reg, read_count, functioncode=3)

                                # Latency hesapla
                                end_time = time.time()
                                latency_ms = (end_time - start_time) * 1000
                                self.data_store[sid]['latency'] = int(latency_ms)

                                # Komut Latency (Eğer beklenen bir komut varsa)
                                if self.data_store[sid].get('last_cmd_ts', 0) > 0:
                                    cmd_dur = (end_time - self.data_store[sid]['last_cmd_ts']) * 1000
                                    self.data_store[sid]['cmd_latency'] = int(cmd_dur)
                                    self.data_store[sid]['last_cmd_ts'] = 0 # Sıfırla

                                # 3. Cache güncelle (Reg 0'ı atla, okunanları 1'den itibaren yerleştir)
                                for i, v in enumerate(values):
                                    self.data_store[sid]['cache'][start_reg + i] = v

                                self.data_store[sid]['online'] = True
                                self.data_store[sid]['errors'] = 0
                                self.data_store[sid]['last_update'] = time.strftime("%H:%M:%S")
                                self.data_store[sid]['timestamp'] = time.time() 
                                self.data_store[sid]['success_count'] = self.data_store[sid].get('success_count', 0) + 1
                                
                                success = True
                                break  # Başarılı

                            except Exception:
                                pass  # Retry

                        if attempt < 2: # Son deneme hariç bekle
                            time.sleep(0.1)  # Retry arası bekleme

                    if not success:
                        # 3 denemenin hepsi başarısızsa ANINDA offline yap
                        self.data_store[sid]['errors'] = 99
                        self.data_store[sid]['online'] = False

                    # Cihazlar arası minimal boşluk (Stabilite için eski ayar)
                    time.sleep(0.1)

                except Exception as e:
                    print(f"Thread Loop Error (SID {sid}): {e}")

            # UI güncelle
            self.after(0, self._update_ui_data)
            # Sistem stabilitesi için ana döngü beklemesi (ESKİ HALİ)
            time.sleep(0.5)

    # ========================================================================
    #  DETAY POPUP
    # ========================================================================
    def _open_detail_popup(self, slave_id):
        device = next((d for d in self.devices if d['id'] == slave_id), None)
        if not device: return

        self.detail_open_for = slave_id  # Tam okuma başlat

        popup = ctk.CTkToplevel(self)
        popup.title(f"Detaylar — {device['name']}")
        popup.geometry("480x580")
        popup.configure(fg_color=COLORS['bg_mid'])
        popup.transient(self)
        popup.grab_set()

        def on_close():
            self.detail_open_for = None
            popup.destroy()

        popup.protocol("WM_DELETE_WINDOW", on_close)

        data = self.data_store.get(slave_id, {})
        cache = data.get('cache', {})

        # Başlık
        ctk.CTkLabel(popup, text=f"⚙  {device['name']}",
                     font=("Segoe UI", 18, "bold"), text_color=COLORS['text']).pack(pady=(20, 2))
        ctk.CTkLabel(popup, text=f"Slave ID: {slave_id}",
                     font=("Consolas", 10), text_color=COLORS['text_dim']).pack(pady=(0, 12))

        # Ayraç
        ctk.CTkFrame(popup, height=1, fg_color=COLORS['glass_border']).pack(fill="x", padx=30, pady=(0, 12))

        entries = []
        value_labels = []
        for p in PARAM_DEFS:
            row = ctk.CTkFrame(popup, fg_color=COLORS['bg_card'], corner_radius=10, height=40)
            row.pack(fill="x", padx=28, pady=3)
            row.pack_propagate(False)

            inner_row = ctk.CTkFrame(row, fg_color="transparent")
            inner_row.pack(fill="both", expand=True, padx=12, pady=4)

            ctk.CTkLabel(inner_row, text=p['label'], width=130, anchor="w",
                         font=("Segoe UI", 11), text_color=COLORS['text_label']).pack(side="left")

            lbl_val = ctk.CTkLabel(inner_row, text="---", width=55,
                                   text_color=COLORS['accent_glow'],
                                   font=("Consolas", 13, "bold"))
            lbl_val.pack(side="left")
            value_labels.append((p, lbl_val))

            e = ctk.CTkEntry(inner_row, width=90, height=28, corner_radius=8,
                             fg_color=COLORS['glass_input'],
                             border_color=COLORS['glass_border'],
                             font=("Consolas", 11), justify="center")
            e.pack(side="right")
            entries.append((p, e))

        lbl_err = ctk.CTkLabel(popup, text="", font=("Segoe UI", 10))
        lbl_err.pack(pady=6)

        # İstatistik Paneli
        stats_frame = ctk.CTkFrame(popup, fg_color="transparent")
        stats_frame.pack(fill="x", padx=30, pady=(0, 6))
        
        lbl_latency = ctk.CTkLabel(stats_frame, text="Ping: -- ms", font=("Consolas", 10), text_color=COLORS['text_dim'])
        lbl_latency.pack(side="left")

        lbl_cmd_lat = ctk.CTkLabel(stats_frame, text="Komut: -- ms", font=("Consolas", 10), text_color=COLORS['text_dim'])
        lbl_cmd_lat.pack(side="left", padx=10)
        
        lbl_success = ctk.CTkLabel(stats_frame, text="Başarı: --%", font=("Consolas", 10), text_color=COLORS['text_dim'])
        lbl_success.pack(side="right")

        # Canlı güncelleme döngüsü
        def refresh_values():
            if self.detail_open_for != slave_id:
                return
            
            d_data = self.data_store.get(slave_id, {})
            cache = d_data.get('cache', {})
            
            # Değerleri güncelle
            for p, lbl in value_labels:
                raw = cache.get(p['reg'], 0)
                cur = raw - 10 if p.get('offset') else raw
                if lbl.cget("text") != str(cur):
                    lbl.configure(text=str(cur))
            
            # İstatistikleri güncelle
            lat = d_data.get('latency', 0)
            cmd_lat = d_data.get('cmd_latency', 0)
            suc = d_data.get('success_count', 0)
            tot = d_data.get('total_count', 1) # div0 koruması
            rate = (suc / tot) * 100 if tot > 0 else 0
            
            lbl_latency.configure(text=f"Ping: {lat} ms")
            lbl_cmd_lat.configure(text=f"Komut: {cmd_lat} ms" if cmd_lat > 0 else "Komut: --")
            lbl_success.configure(text=f"Başarı: {rate:.1f}%")

            popup.after(250, refresh_values) # Daha hızlı UI update

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
                        errors.append(f"{p['label']}: {p['min']}..{p['max']} aralığında olmalı!")
                        continue
                    writes[p['reg']] = val + 10 if p.get('offset') else val
                except ValueError:
                    errors.append(f"{p['label']}: Sayısal değer girin!")

            if errors:
                lbl_err.configure(text="\n".join(errors), text_color=COLORS['red'])
                return

            if writes:
                self.data_store[slave_id]['pending'].update(writes)
                lbl_err.configure(text=f"✓ {len(writes)} parametre kuyruğa alındı", text_color=COLORS['green'])
                for _, e in entries:
                    e.delete(0, 'end')

        # Ayraç
        ctk.CTkFrame(popup, height=1, fg_color=COLORS['glass_border']).pack(fill="x", padx=30, pady=(6, 0))

        ctk.CTkButton(popup, text="UYGULA", font=("Segoe UI", 12, "bold"), height=38,
                      corner_radius=12,
                      fg_color=COLORS['green_dark'], hover_color=COLORS['green'],
                      command=apply).pack(pady=(14, 6), padx=28, fill="x")
        ctk.CTkButton(popup, text="KAPAT", font=("Segoe UI", 11), height=32,
                      corner_radius=10,
                      fg_color=COLORS['glass_surface'], hover_color=COLORS['bg_card_hover'],
                      border_width=1, border_color=COLORS['glass_border'],
                      command=on_close).pack(padx=28, fill="x")


if __name__ == "__main__":
    app = HMIApp()
    app.mainloop()
