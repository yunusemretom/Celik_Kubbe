# YKI — Yer Kontrol İstasyonu

**TEKNOFEST Çelik Kubbe Hava Savunma Sistemi | Pars Takımı**

QGroundControl tarzı, web tabanlı yer kontrol istasyonu. RTSP kamera stream, gerçek zamanlı JSON telemetri ve TCP komut kanalı destekler.

---

## 🚀 Hızlı Başlangıç

### 1. Gereksinimler

```bash
# Node.js v18+ kur
sudo apt install -y nodejs npm

# FFmpeg kur (video stream için şart)
sudo apt install -y ffmpeg

# Kurulumu doğrula
node --version   # v18+
ffmpeg -version
```

### 2. Bağımlılıkları Yükle

```bash
cd YKI/backend
npm install
```

### 3. Çalıştır

```bash
node server.js
# veya geliştirme modunda (otomatik yeniden başlatma):
npm run dev
```

Tarayıcıda açın: **http://localhost:3000**

---

## ⚙️ Yapılandırma

İlk başlatmada `backend/yki_config.json` otomatik oluşturulur. **Ayarlar** sayfasından da değiştirebilirsiniz.

```json
{
  "rpi": {
    "ip": "192.168.1.100",    ← RPi5 IP adresi
    "tcpPort": 5000,           ← Komut kanalı (TCP)
    "udpPort": 5001            ← Telemetri (UDP)
  },
  "video": {
    "rtspUrl": "rtsp://192.168.1.100:8554/camera",
    "resolution": "1280x720",
    "fps": 30,
    "bitrate": 800
  }
}
```

---

## 📡 İletişim Protokolleri

### Telemetri (UDP → Backend, Port 5001)

RPi5'ten her saniye gönderilecek JSON paketi örneği:

```json
{
  "seq": 1234,
  "timestamp": 1700000000000,
  "battery": 85.5,
  "altitude": 150.3,
  "speed": 12.1,
  "mode": "TRACKING",
  "tracking": true,
  "rssi": -65,
  "gps": {
    "lat": 39.925533,
    "lon": 32.866287,
    "fix": true
  }
}
```

### Komut (TCP, Port 5000)

Backend → RPi5 yönünde JSON satırları:

```json
{"id": "abc123", "cmd": "arm", "params": {}, "timestamp": 1700000000000}
{"id": "def456", "cmd": "set_mode", "params": {"mode": "TRACK"}, "timestamp": 1700000000000}
```

RPi5'ten ACK beklenir:
```json
{"ack": "abc123", "status": "ok"}
```

---

## 📁 Klasör Yapısı

```
YKI/
├── backend/
│   ├── server.js           ← Ana sunucu (Express + WebSocket)
│   ├── telemetryBridge.js  ← UDP telemetri alıcı
│   ├── commandBridge.js    ← TCP komut gönderici
│   ├── videoRelay.js       ← FFmpeg RTSP → WebSocket
│   ├── config.js           ← Yapılandırma yöneticisi
│   ├── yki_config.json     ← Kalıcı ayarlar (otomatik oluşur)
│   └── package.json
└── frontend/
    ├── index.html
    ├── css/style.css
    ├── js/
    │   ├── app.js          ← Sayfa yönetimi, status bar
    │   ├── websocket.js    ← WS bağlantı yöneticisi
    │   ├── dashboard.js    ← Kamera + overlay
    │   ├── telemetry.js    ← Grafik sayfası
    │   ├── settings.js     ← Ayarlar sayfası
    │   └── about.js        ← Hakkında
    └── lib/
        └── jsmpeg.min.js   ← Video oynatıcı
```

---

## 🔧 Test (RPi5 Olmadan)

### Simüle Telemetri Gönder
```bash
python3 telemetry_sim.py --mode fake
```
Sinüs dalgalarıyla sahte telemetri üretip `127.0.0.1:5001`'e yollar.

### Unity Simülasyonundan Gerçek Veri (`telemetry_sim.py --mode sim`)

Aynı betik, `Similasyon_Kullanım/` altındaki köprüyü kullanarak Unity
simülasyonuna bağlanır, `run.py`'deki takip döngüsünün aynısını çalıştırır ve
gerçek taret/hedef verisini YKI'ya yollar:

```bash
# Unity'de SteelDomeSim sahnesi Play modundayken:
python3 telemetry_sim.py                       # otomatik: Unity yoksa sahte veriye düşer
python3 telemetry_sim.py --mode sim --no-fire  # takip et, ateş etme
python3 telemetry_sim.py --mode sim --mjpeg-port 8090   # namlu kamerasını da yayınla
python3 telemetry_sim.py --mode sim --yolo --weights ../Object_detection/best.pt
```

Kamera görüntüsü için: **Ayarlar > Kamera > MJPEG HTTP Stream** →
`http://127.0.0.1:8090/stream`

Simülasyon alanlarının YKI göstergelerine karşılığı:

| YKI alanı | Simülasyondaki karşılığı |
|---|---|
| `mode` | Takip durumu: `ARAMA` / `TAKIP` / `KILITLI` |
| `tracking` | Seçili hedef var mı |
| `altitude` | Hedefin menzil + namlu açısından kestirilen irtifası (m) |
| `speed` | Taretin dönüş hızı (°/s) |
| `rssi` | Köprünün kare hızından türetilen bağlantı kalitesi |
| `battery` | Modellenmiş tüketim (süre + atış sayısı) — simülasyonda batarya yok |
| `pitch` / `yaw` | Taret açıları (`roll` sabit gövdede daima 0) |
| `gps` | Sabit mevzi konumu (`--lat` / `--lon` ile değiştirilir) |

Paket ayrıca `target` (sınıf, taraf, menzil, iz kimliği, nişan hatası),
`turret` (açı/hız/komut) ve `fps`, `shots`, `fire`, `detections` alanlarını taşır.

`run.py` ayrı bir terminalde çalışıyorsa `--passive` ile köprü tarete komut
göndermez, yalnızca kareleri okuyup telemetri yayınlar (Unity'nin ikinci bir
istemciye izin vermesi gerekir).

### Kamera Kaynakları

**Ayarlar > Kamera Kaynağı** altında dört kaynak var; seçim `yki_config.json`'a
yazılır ve sayfa yenilenince korunur.

| Kaynak | Nasıl çalışır | Not |
|---|---|---|
| 🎥 Web Kamera | Tarayıcı `getUserMedia` | Yalnızca `localhost` ya da HTTPS'te açılır — ağ üzerinden IP ile girildiğinde tarayıcı izin vermez |
| 📷 V4L2 Cihaz | Sunucuda FFmpeg → WebSocket (jsmpeg) | `🔍 V4L2 Cihazları Listele` `/api/devices/video`'dan cihazları çeker |
| 📡 RTSP | Sunucuda FFmpeg → WebSocket | RTSP URL girilmeli |
| 🌐 MJPEG | Tarayıcı doğrudan `<img>` ile çeker | Simülasyon köprüsü için: `http://127.0.0.1:8090/stream` |

Kaynak açılamazsa hata artık arayüzde bildirilir (FFmpeg'in son hata satırıyla
birlikte); eskiden sessizce boş ekran kalıyordu.

### Simüle RTSP Stream
```bash
# Test video dosyası varsa:
ffmpeg -re -i test.mp4 -f rtsp -rtsp_transport tcp rtsp://localhost:8554/camera

# Yoksa test pattern:
ffmpeg -re -f lavfi -i testsrc=size=1280x720:rate=30 -f rtsp rtsp://localhost:8554/camera
```

---

## 🌐 Ağ Yapılandırması

```
[Operatör PC] ──── internet ────► [RPi5 Sabit IP]
      │                                   │
   Tarayıcı                          ESP32 (UART)
      │                                   │
   :3000 HTTP                        Motor/Servo
   :8081 Video WS                         │
      │                             Kamera (RTSP)
      └── YKI Backend ◄── UDP :5001 (Telemetri)
              └─────────── TCP :5000 (Komut)
```

---

## 📋 Sayfalar

| Sayfa | Açıklama |
|-------|----------|
| **Dashboard** | RTSP kamera görüntüsü, TAKİP AKTİF badge, FPS/gecikme overlay |
| **Telemetri** | Chart.js grafikleri (batarya, irtifa, hız, RSSI), CSV export |
| **Ayarlar** | IP/port, RTSP URL, çözünürlük yapılandırması |
| **Hakkında** | Takım ve sistem bilgileri |
