# Modbus RTU HMI Control Panel

Modern ve şık bir arayüze ("Matrix" teması) sahip, Python ile geliştirilmiş Modbus RTU kontrol paneli uygulaması. Birden fazla Modbus cihazını (slave) seri port (RS485/RS232) üzerinden izlemenize ve kontrol etmenize olanak tanır.

## Özellikler

- **Çoklu Cihaz Desteği**: Birden fazla Modbus node'u ekleyip eşzamanlı olarak durumlarını takip edebilirsiniz.
- **Sıralı ve Öncelikli Polling**: Arka planda çalışan polling (sorgulama) mekanizması ile veriler düzenli olarak güncellenir. Kullanıcı komutları (yazma işlemleri) kuyrukta önceliklendirilir.
- **Detaylı Hata İzleme**: Cihaz bağlantı hataları, gecikmeler (lag) ve Modbus iletişim hataları arayüzde anlık olarak gösterilir.
- **Özelleştirilebilir Parametreler**: Her cihaz için açılış/kapanış hızı, tork veya süre gibi Modbus register'larına kolay erişim arayüzü içerir.
- **Matrix Teması**: `CustomTkinter` kullanılarak koyu arka plan ve yeşil fosforlu vurgulara dayalı terminal stili modern arayüz tasarımı (Matrix filmi estetiği).

## Gereksinimler

Proje, Python 3.10 veya daha güncel bir sürümle çalışacak şekilde tasarlanmıştır.

Gerekli Python kütüphanelerini kurmak için projeyi klonladıktan sonra aşağıdaki komutu çalıştırın:

```bash
pip install -r requirements.txt
```

Kullanılan başlıca kütüphaneler şunlardır:
- `customtkinter`: Modern arayüz için.
- `minimalmodbus`: Modbus RTU haberleşmesi için.
- `pyserial`: Seri port erişimi için.

## Kurulum ve Kullanım

1. Repoyu bilgisayarınıza indirin (klonlayın):
   ```bash
   git clone <repo-url>
   cd MODBUS
   ```

2. Gerekli kütüphaneleri yükleyin:
   ```bash
   pip install -r requirements.txt
   ```

3. Uygulamayı başlatın:
   ```bash
   python modbus_panel.py
   ```

4. **Kullanım Adımları**:
   - Üst kısımdaki araç çubuğundan (Toolbar) uygun `PORT` (COMy) ve `BAUD` oranını (örn. 9600) seçin.
   - `[+ ADD NODE]` butonuna basarak kontrol etmek istediğiniz cihazların Slave ID'lerini (örn. 1, 2) ve isimlerini (etiketlerini) girin.
   - `[ EXEC CONNECT ]` butonuna basarak seri haberleşmeyi (polling) başlatın. Cihazlarınız çevrimiçi olduğunda durumları ("ONLINE") yeşil renkle güncellenecektir.
   - Cihaz kartları üzerindeki butonlarla (AÇ/KAPAT) komut gönderebilir veya `[SETTINGS]` menüsünden daha detaylı register değerlerini güncelleyebilirsiniz.

## Dosya Yapısı

- `modbus_panel.py`: Uygulamanın ana kaynak kodu (arayüz ve haberleşme mantığı).
- `devices.json`: Eklenen cihazların (slave ID ve etiketleri) uygulamaya kaydedildiği yapılandırma dosyası (uygulama çalıştıkça otomatik oluşur/güncellenir).
- `requirements.txt`: Python bağımlılıklarının listesi.

## Lisans

Bu proje kişisel/geliştirme kullanımı amacıyla oluşturulmuştur.
