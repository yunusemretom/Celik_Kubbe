# Çelikkubbe ESP32 Firmware

ESP32-S3 tabanlı, iki eksenli (azimut/elevasyon) bir taretin hareket, tetikleme,
menzil ölçüm ve haberleşme kontrolünü yürüten FreeRTOS gömülü yazılımı. Sistem
bir Raspberry Pi (SBC) ile UART üzerinden konuşur, ayrıca YKI web arayüzünden
gelen bir joystick sinyalini de doğrudan WiFi/UDP üzerinden kabul edebilir.

## İçindekiler

- [Genel Mimari](#genel-mimari)
- [Dosya Yapısı](#dosya-yapısı)
- [Donanım / Pin Haritası](#donanım--pin-haritası)
- [Görevler (FreeRTOS Tasks)](#görevler-freertos-tasks)
- [Kontrol Modları](#kontrol-modları)
- [Güvenlik Katmanı](#güvenlik-katmanı)
- [UART Protokolü (RPi ↔ ESP32)](#uart-protokolü-rpi--esp32)
- [Joystick (WiFi/UDP) Girişi](#joystick-wifiudp-girişi)
- [LiDAR](#lidar)
- [Encoder (AS5600)](#encoder-as5600)
- [Tetik Aktüatörü](#tetik-aktüatörü)
- [Derleme Notları](#derleme-notları)
- [Bilinen Sınırlamalar / Dikkat Edilecekler](#bilinen-sınırlamalar--dikkat-edilecekler)

## Genel Mimari

Firmware dört FreeRTOS görevine bölünmüştür ve iki çekirdeğe pinlenmiştir:

| Görev | Çekirdek | Öncelik | Görev |
|---|---|---|---|
| `CommRPi` | 0 | 2 | RPi UART protokolünü işler, telemetri gönderir, bağlantı kopma failsafe'ini izler |
| `MotorCtrl` | 1 | 2 | `safety_update()` + `pid_update()` — eksen kontrolü ve güvenlik durum makinesi |
| `Lidar` | 0 | 1 | TF03-180 LiDAR'dan mesafe okur |
| `Joystick` | 0 | 2 | YKI arayüzünden UDP/seri joystick paketlerini işler, manuel modda eksenleri ve tetiği sürer |

İki "efendi" (RPi ve joystick) aynı anda motoru sürmesin diye kontrol tek bir
moda bağlıdır: `PROTO_MODE_MANUAL` iken joystick söz sahibidir ve RPi'den gelen
`CMD_AIM`/`CMD_FIRE` yok sayılır; diğer modlarda tam tersi geçerlidir.

## Dosya Yapısı

```
esp32_firmware.ino     setup()/loop() giriş noktası
config.h                Tüm pinler, sabitler, sistem modu/durumu enumları
uart_protocol.h/.cpp    RPi <-> ESP32 çerçeve protokolü (CRC-16/CCITT-FALSE)
tasks.h/.cpp            FreeRTOS görevleri + protokol callback'lerinin bağlanması
pid_control.h/.cpp      Azimut/elevasyon eksen kontrolü (pozisyon PID + açık çevrim hız modu)
encoder.h/.cpp          AS5600 manyetik encoder okuma (I2C, Wire/Wire1)
safety.h/.cpp           Tek yetkili güvenlik katmanı: E-Stop, mühimmat, yasak bölge, menzil kapısı
trigger.h/.cpp          İp/servo ile tüfek tetiği aktüatörü
lidar.h/.cpp            TF03-180 LiDAR UART çerçeve ayrıştırıcı
joystick.h/.cpp         WiFi/UDP + USB seri joystick girişi (YKI arayüzü)
```

## Donanım / Pin Haritası

Tüm pin tanımları `config.h` içinde toplanmıştır.

**Step motor sürücüleri (step/dir/enable):**
| Eksen | STEP | DIR | EN |
|---|---|---|---|
| Azimut | 6 | 7 | 9 |
| Elevasyon | 4 | 5 | 8 |

**AS5600 encoder I2C hatları:**
| Hat | SDA | SCL |
|---|---|---|
| Azimut (`Wire`) | 1 | 2 |
| Elevasyon (`Wire1`) | 41 | 42 |

**UART hatları:**
| Hat | RX | TX | Baud |
|---|---|---|---|
| RPi (`Serial1`) | 16 | 17 | 115200 |
| LiDAR (`Serial2`) | 18 | 15 | 115200 |

**MOSFET çıkışları:** Lazer (12), mühimmat besleme motoru (13), ikaz kulesi/beacon (14).

**Diğer:** Tetik servosu (10), E-Stop girişi (3, `INPUT_PULLUP` + kesme ile debounce).

> Not: `config.h` içindeki motor sürücü I2C pinleri (47/48) şu anda kod
> tarafından kullanılmıyor — step/dir arayüzlü MKS Servo42C sürücüye geçildiği
> için sadece geçerli bir pine taşınmış durumda.

## Görevler (FreeRTOS Tasks)

`tasks_startAll()` (`esp32_firmware.ino > setup()` içinden çağrılır) dört
görevi başlatır ve açılış modunu (`DEFAULT_BOOT_MODE_MANUAL`) kontrolcüye
uygular. Her görev periyodik olarak (`TASK_LOOP_DELAY_MS = 2 ms` veya
joystick için 20 ms / 50 Hz) çalışır; hiçbiri bloklamaz.

- **CommRPi:** `uartProtocolPoll()` çağırır, RPi sessizliğini
  (`UART_FAILSAFE_MS = 200 ms`) izler, 50 Hz'de `TLM_STATE` telemetrisi yollar,
  `lost_pkts` sayacını 1 saniyelik pencerelerde tutar.
- **MotorCtrl:** `safety_update()` (E-Stop debounce, mühimmat/homing kontrolü,
  tetik servosu durum makinesi) ve `pid_update()` (eksen kontrol döngüsü).
- **Lidar:** Sürekli `lidar_read()` çağırır, 1 saniyeden eski veri varsa
  `ERR_LIDAR_TIMEOUT` gönderir (tek seferlik, tekrar tetiklenene kadar susar).
- **Joystick:** Sadece `PROTO_MODE_MANUAL` iken aktif; paket bayatsa
  (`JOYSTICK_TIMEOUT_MS = 300 ms`) eksenleri durdurur ve tetiği bırakır.

## Kontrol Modları

`pid_control` iki ayrı çalışma modu sunar (`PidControlMode`):

- **`PID_MODE_POSITION`** — Encoder geri beslemeli kapalı çevrim PID. RPi'nin
  `CMD_AIM` ile gönderdiği hedef açılara gider. Katsayılar `PID_KP/KI/KD`
  (`config.h`), `CMD_PID` ile RPi tarafından da güncellenebilir.
- **`PID_MODE_VELOCITY`** — Açık çevrim hız modu. Encoder takılı değilken
  (`encoder_getAzimuthDeg()` sürekli 0 dönerdi, PID tavan hızda kaçardı)
  kullanılır. Joystick doğrudan derece/saniye hız komut eder; pozisyon,
  komut edilen hızın rampalı integrali ile **tahmin edilir** (gerçek ölçüm
  değildir — kaçan adımlar birikebilir).

Mod seçimi `SystemMode`/`PROTO_MODE_*` değerine göre `tasks.cpp` içindeki
`applyModeToController()` tarafından otomatik yapılır: `PROTO_MODE_MANUAL` →
hız modu, diğer tüm modlar → pozisyon modu.

## Güvenlik Katmanı

`safety.cpp`, sistemdeki **tek yetkili** güvenlik katmanıdır. Ateşleme kapısı
sırayla şu kontrollerden geçer (`safety_canFire`):

1. `CTRL_ARM` biti açık mı (emniyet mandalı)
2. E-Stop aktif mi (fiziksel veya yazılımsal)
3. Mühimmat bitmiş mi
4. Taret ateşe yasak bölgede mi (`NOFIRE_ZONE_MIN/MAX_DEG`)
5. Hedef dost mu
6. Tetik servosu meşgul mü
7. *(REQUIRE_LIDAR_FOR_FIRE=1 ise)* LiDAR verisi taze mi, sinyal güvenilir mi,
   menzil hedef tipine uygun mu (`RANGE_F16_*`, `RANGE_HELI_MISSILE_*`, `RANGE_UAV_*`)
8. Taret hedefte kilitli mi (`pid_isAtTarget`)

Durum makinesi (`SystemState`): `ST_INIT → ST_STANDBY → ST_TRACKING →
ST_ENGAGING`, herhangi bir yerden `ST_SAFE_STOP` (mühimmat bitti / RPi
`CMD_SAFE`) veya `ST_EMERGENCY_SHUTDOWN` (fiziksel E-Stop) tetiklenebilir.
E-Stop pini kesme (`ISR`) ile yakalanır, 50 ms yazılımsal debounce uygulanır.

## UART Protokolü (RPi ↔ ESP32)

`uart_protocol.h/.cpp`, PARS SBC↔MCU protokolü v1.3'ü uygular.

- **Çerçeve:** `0xAA 0x55 | MSG_ID | LEN | PAYLOAD[LEN] | CRC16_LO | CRC16_HI`
- **CRC:** CRC-16/CCITT-FALSE (poly `0x1021`, init `0xFFFF`), `MSG_ID+LEN+PAYLOAD`
  üzerinden hesaplanır.
- **Senkron bozulursa:** Sadece ilk bayt atılıp geri kalan tampon yeniden
  beslenir (`resyncAfterFailedFrame`), ardışık `CRC_BURST_LIMIT` (20) hatada
  `ERR_CRC_BURST` gönderilir.

**RPi → ESP32:** `CMD_HEARTBEAT`, `CMD_AIM` (seq+az+el+ctrl), `CMD_FIRE`
(shotCount+targetId), `CMD_MODE`, `CMD_SAFE`, `CMD_HOME`, `CMD_PID`.

**ESP32 → RPi:** `TLM_STATE` (50 Hz; durum, açılar, LiDAR mm, mühimmat,
flag'ler, kayıp paket sayısı), `ACK_FIRE`, `ACK`, `ERR`.

`CMD_AIM.ctrl` bit alanları: `CTRL_ARM`, `CTRL_LASER`, `CTRL_MOTOR_EN`,
`CTRL_NO_FIRE`. `TLM_STATE.flags`: `FLAG_ARMED`, `FLAG_MOTORS_ON`,
`FLAG_LOCKED`, `FLAG_ESTOP`, `FLAG_AZ_LIMIT`, `FLAG_EL_LIMIT`,
`FLAG_LASER_ON`, `FLAG_AMMO_EMPTY`.

## Joystick (WiFi/UDP) Girişi

YKI web arayüzündeki sanal joystick, tarayıcı → `joystickBridge.js` →
UDP `"pitch,yaw,fire,arm\n"` satırı olarak ESP32'ye ulaşır
(`JOYSTICK_UDP_PORT = 5005`, mDNS: `celikkubbe.local`).

- `pitch`: elevasyon (-1..+1, yukarı = +), `yaw`: azimut (-1..+1, sağ = +)
- `fire`: tetik basılı mı, `arm`: emniyet mandalı açık mı
- 3 alanlı eski format da kabul edilir; bu durumda `arm=0` varsayılır (ateş yok)
- Ölü bölge: `JOYSTICK_DEADZONE = 0.08`
- USB seri üzerinden aynı satır formatı da kabul edilir (tezgah testi için,
  `JOYSTICK_ALLOW_SERIAL`)
- Paket akışı kesilirse (`JOYSTICK_TIMEOUT_MS = 300 ms`) tüm eksenler durur ve
  tetik anında bırakılır — son paket `fire=1` olsa bile

Joystick tetik mantığı basılı tutma sırasında her paket için değil,
`SHOT_INTERVAL_MS` aralıklarla tekrar ateşler (`JOYSTICK_FIRE_AUTOREPEAT`).

## LiDAR

TF03-180 uyumlu, 9 baytlık çerçeve (`0x59 0x59` header + checksum) UART
üzerinden ayrıştırılır (`lidar.cpp`). `lidar_isDataFresh()` ve
`lidar_isSignalReliable()` ateşleme kapısında menzil doğrulaması için
kullanılır (min. sinyal gücü eşiği, 65535 = ortam ışığı doygunluğu → güvensiz).

## Encoder (AS5600)

İki AS5600 manyetik encoder, ayrı I2C hatlarında (`Wire`=azimut,
`Wire1`=elevasyon) 12-bit ham açı okur. `encoder_calibrateZero()` taret fiziksel
0°/0° referans konumundayken çağrılmalıdır; offset ham açıdan çıkarılır ve
sonuç -180°..+180° aralığına sarılır.

## Tetik Aktüatörü

Eski solenoid valfin (kaldırılan MOSFET4) yerini, ipe bağlı bir tetik servosu
almıştır (`trigger.cpp`, ESP32Servo kütüphanesi). Durum makinesi:
`TRG_IDLE → TRG_PULLING (TRIGGER_PULL_MS) → TRG_RELEASING (TRIGGER_RELEASE_MS)
→ TRG_IDLE`. Bloklamaz; `trigger_pull()` hemen döner, ilerlemeyi
`trigger_update()` periyodik olarak yapar. `RIFLE_IS_SEMI_AUTO=1` iken bir
tetik çekişi = bir mermi sayımı doğrudur.

## Derleme Notları

- Hedef: ESP32-S3 (Arduino core), FreeRTOS özellikleri (`xTaskCreatePinnedToCore`,
  `vTaskDelay` vb.) kullanılıyor.
- Gerekli kütüphaneler: `WiFi`, `WiFiUdp`, `ESPmDNS` (joystick WiFi modu için),
  `ESP32Servo` (Kevin Harrington) — tetik servosu için.
- `config.h` içindeki `AZ_ENCODER_I2C_ADDR` / `ELEV_ENCODER_I2C_ADDR` tanımları
  yüklenen dosyada yorum satırı halinde (`0x36`); bu makrolar `encoder.cpp`
  tarafından kullanıldığı için derlemeden önce tanımlanmış olmaları gerekir.
- Sahaya çıkmadan önce `config.h` içindeki şu bayraklar gözden geçirilmeli:
  `REQUIRE_LIDAR_FOR_FIRE` (sahada **1** olmalı), `DEFAULT_BOOT_MODE_MANUAL`,
  `RIFLE_IS_SEMI_AUTO`, `MAX_AMMO_COUNT`.

## Bilinen Sınırlamalar / Dikkat Edilecekler

- Açık çevrim hız modunda pozisyon **tahmindir**; encoder bağlıyken
  `PID_MODE_POSITION`'a geçilmesi önerilir.
- `JOYSTICK_AZ_RATE_DEG_S` / `JOYSTICK_EL_RATE_DEG_S` başlangıç için güvenli
  ayarlanmıştır; sahada test edilerek artırılmalıdır (kod içi not).
- `MOTOR_I2C_SDA_PIN`/`MOTOR_I2C_SCL_PIN` şu an kullanılmıyor, gelecekte
  kaldırılabilir.
- E-Stop'un fiziksel butonu bırakılması sistemi **kendiliğinden** çalışır hale
  getirmez; RPi tarafından yazılımsal olarak (`CMD_SAFE` sonrası temizleme
  akışı) devreye alınması gerekir.
