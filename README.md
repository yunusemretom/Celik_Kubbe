# Çelik Kubbe

Pars Takımı için oluşturulmuş çelik kubbe hava savunma sistemi.

---

# YKI — Yer Kontrol İstasyonu

**TEKNOFEST Çelik Kubbe Hava Savunma Sistemi | Pars Takımı**

QGroundControl tarzı, web tabanlı yer kontrol istasyonu. Webcam / RTSP / MJPEG kamera desteği, gerçek zamanlı JSON telemetri, uçuş enstrümanları (yapay ufuk + pusula) ve TCP komut kanalı içerir.

---

## Hızlı Başlangıç

```bash
# 1. Node.js, npm ve FFmpeg kur
sudo apt install -y nodejs npm ffmpeg

# 2. Bağımlılıkları yükle
cd ~/Documents/Projeler/Pars_Takimi/YKI/backend
npm install

# 3. Sunucuyu başlat
node server.js

# 4. Tarayıcıda aç
http://localhost:3000
```

---

## Sistem Mimarisi

```
[Tarayıcı / Operatör PC]
        ↕  WebSocket (ws://localhost:3000)
[YKI Backend — Node.js :3000]
        ↕  TCP :5000  →  Komut gönderme
        ↕  UDP :5001  ←  Telemetri alma
        ↕  Video WS :8081  ←  FFmpeg RTSP relay
[Raspberry Pi 5 — Araç Bilgisayarı]
        ↕  UART / GPIO
    [ESP32 — Alt Kontrolcü]
```

---

## Sayfalar

| Sayfa | Açıklama |
|-------|----------|
| **Dashboard** | Kamera görüntüsü (tam ekran), TAKİP AKTİF badge, FPS/gecikme overlay, uçuş enstrümanları |
| **Telemetri** | Batarya/irtifa/hız/RSSI grafikleri (Chart.js), CSV export |
| **Ayarlar** | Kamera kaynağı, bağlantı ayarları, video kalitesi |
| **Hakkında** | Takım ve sistem bilgileri |

---

## Kamera Kaynağı Seçimi

Ayarlar → Kamera Kaynağı bölümünden üç mod:

| Mod | Açıklama |
|-----|----------|
| **Web Kamera** | Tarayıcı üzerinden yerel USB/dahili kamera. Cihaz listesi butonu ile seçim yapılır. |
| **RTSP Stream** | `rtsp://IP:PORT/yol` formatında. Backend üzerinden FFmpeg ile iletilir. |
| **MJPEG Stream** | `http://IP:PORT/video` formatında. Doğrudan tarayıcıdan çekilir. |

---

## Uçuş Enstrümanları

Dashboard'da **Enstrümanlar** butonuna tıklayarak açılır:

- **Yapay Ufuk (Attitude Indicator)**: Roll ve Pitch açılarını gösterir. Mavi = gökyüzü, kahverengi = yer.
- **Pusula (Heading Indicator)**: Yaw/Heading açısını gösterir, N/E/S/W yönleri ile.

Enstrümanlar telemetri verisindeki `pitch`, `roll`, `yaw`/`heading` alanlarını kullanır.

---

## Telemetri Protokolü (UDP → Port 5001)

RPi5'ten her saniye gönderilecek JSON paketi:

```json
{
  "seq": 1234,
  "timestamp": 1700000000000,
  "battery": 85.5,
  "altitude": 150.3,
  "speed": 12.1,
  "pitch": 5.2,
  "roll": -3.1,
  "yaw": 270.0,
  "heading": 270.0,
  "mode": "TRACKING",
  "tracking": true,
  "rssi": -65
}
```

---

## Komut Protokolü (TCP → Port 5000)

Backend → RPi5 yönünde JSON satırları:

```json
{"id": "abc123", "cmd": "arm", "params": {}, "timestamp": 1700000000000}
```

RPi5'ten ACK:
```json
{"ack": "abc123", "status": "ok"}
```

> **Not:** RPi5 bağlı olmadığında `EHOSTUNREACH` hatası görünür — bu normaldir. Sistem her 5 saniyede otomatik yeniden bağlanmayı dener. Sadece ilk denemede uyarı gösterilir.

---

## Yapılandırma

İlk çalıştırmada `backend/yki_config.json` otomatik oluşturulur.
Arayüz üzerinden (Ayarlar sayfası) veya dosyayı elle düzenleyerek yapılandırılabilir:

```json
{
  "rpi": {
    "ip": "192.168.1.100",
    "tcpPort": 5000,
    "udpPort": 5001
  },
  "video": {
    "rtspUrl": "rtsp://192.168.1.100:8554/camera",
    "resolution": "1280x720",
    "fps": 30,
    "bitrate": 800
  },
  "server": {
    "httpPort": 3000,
    "videoWsPort": 8081
  },
  "vehicle": {
    "name": "Çelik Kubbe",
    "teamName": "Pars Takımı"
  }
}
```

---

## Proje Klasör Yapısı

Ana dizin yapımız şu şekildedir:

- **`YKI/`**: Yer Kontrol İstasyonu projesi. (Node.js arka uç, HTML/JS/CSS ön uç ve simülasyon kodları)
- **`Object_detection/`**: YOLO tabanlı hedef tespiti, model eğitimi ve TensorRT dönüştürme betikleri.
- **`control_code/`**: İHA veya sistemin alt uçuş denetleyicisi ile haberleşme, komut işleme ve MQTT haberleşmesi.

---

### YKI Klasör Yapısı

```
YKI/
├── backend/
│   ├── server.js           ← Ana sunucu (Express + WebSocket)
│   ├── telemetryBridge.js  ← UDP JSON alıcı (port 5001)
│   ├── commandBridge.js    ← TCP JSON gönderici (port 5000)
│   ├── videoRelay.js       ← FFmpeg RTSP → WebSocket (port 8081)
│   ├── config.js           ← Kalıcı yapılandırma
│   ├── yki_config.json     ← Ayarlar dosyası (otomatik oluşur)
│   └── package.json
├── frontend/
│   ├── index.html
│   ├── css/style.css       ← QGC tarzı dark tema
│   ├── js/
│   │   ├── app.js          ← Sayfa yönetimi, status bar
│   │   ├── websocket.js    ← WS bağlantı yöneticisi
│   │   ├── dashboard.js    ← Kamera + yapay ufuk + pusula
│   │   ├── telemetry.js    ← Grafik sayfası
│   │   ├── settings.js     ← Ayarlar sayfası
│   │   └── about.js        ← Hakkında
│   └── lib/
│       └── jsmpeg.min.js   ← RTSP video oynatıcı
├── telemetry_sim.py        ← Test simülatörü
└── README.md
```

---

## Test (RPi5 Olmadan)

### Telemetri simülatörü (pitch/roll/yaw dahil)

```bash
python3 ~/Documents/Projeler/Pars_Takimi/YKI/telemetry_sim.py
# veya uzak IP ile:
python3 telemetry_sim.py 192.168.1.50 5001
```

### Test RTSP stream

```bash
# Test deseni ile:
ffmpeg -re -f lavfi -i testsrc=size=1280x720:rate=30 \
  -f rtsp rtsp://localhost:8554/camera

# Video dosyasından:
ffmpeg -re -i video.mp4 -f rtsp rtsp://localhost:8554/camera
```

---

## Sistem Gereksinimleri

| Bileşen | Versiyon |
|---------|----------|
| Node.js | v12+ (v18+ önerilir) |
| FFmpeg | v4+ |
| Python | v3.6+ (sadece simülatör için) |
| Tarayıcı | Chrome / Firefox / Edge |