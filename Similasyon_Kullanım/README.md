# Çelik Kubbe — TEKNOFEST 2026 Hava Savunma Simülasyonu

Unity içinde şartname ve parkur çizimine göre kurulmuş bir poligon, iki eksenli
taret, namlusuna monteli kamera; Python tarafında görüntü işleme ile kapalı
çevrim hedef takibi ve ateş kontrolü.

Kaynak dokümanlar:
`2026 Şartname TR v1.5` ve `Parkur ve Poligon Yerleşimi (PLG26-A-001-002-00)`.

## Parkur

Ölçüler çizimden alındı (mm → m):

| Öğe | Çizim | Simülasyon |
|---|---|---|
| Saha | 18000 × 14000 | X ∈ [-7, +7], Z ∈ [-1, +17] |
| Poligon | 16000 × 10000 | X ∈ [-5, +5], Z ∈ [1, 17] |
| Yükseklik | 2950 | 2.95 m |
| Taret namlu ekseni | 1300 | y = 1.28 m |
| Ray dalgası | ~460 tepe-tepe, ~1530 adım | genlik 0.23, dalga boyu 1.53 |

**Her kol kapalı bir ray halkasıdır** — köşeleri yuvarlatılmış bir dikdörtgen.
Tarete bakan uzun kenar **dalgalıdır**: hedef yılan gibi salınarak yaklaşır.
Karşı uzun kenar düzdür ve dönüş koşusudur. Arabalar bu halkanın etrafında
sürekli tur atar; şartnamedeki **"A'dan B'ye = 1 tam tur"** bir devirdir.

Üç halka iç içe geçer, çizimdeki gibi (12.76 mm/piksel ölçeğiyle okundu):

| Kol | Dalgalı koşu X | Düz dönüş X | Z aralığı | Çevre |
|---|---|---|---|---|
| Kol-1 (Sağ) | +2.87 | +5.60 | 1.98 … 16.27 | 33.7 m |
| Kol-2 (Orta) | 0.00 | −6.75 | 1.53 … 16.91 | 43.8 m |
| Kol-3 (Sol) | −2.68 | −5.61 | 1.98 … 16.27 | 33.9 m |

Kol-3'ün halkası Kol-2'nin içine yerleşir, kesişmezler — çizimdeki düzen budur.
Orta kol taretin nişan ekseni üzerindedir.

Menzil bantları 5 / 10 / 15 m'de zemine **yay** olarak çizildi, düz çizgi değil:
menzil gerçek 3B mesafedir, yandaki kollarda düz bir çizgi yanıltır.

Parkurdaki her şey nötr gri; **doygun kırmızı ve mavi yalnızca hedeflere ait**.
Aksi halde Python tarafındaki renk eşikleme yanlış pozitif üretir.

## Hedefler

Yarışma tarafından verilen 4 OBJ maketi (`Assets/SteelDome/Models/`):
balistik füze, helikopter, F16, mini/mikro İHA. Hepsi gerçek maket ölçeğinde
(0.3–0.6 m), burnu +Z, füze dik duruyor.

Her hedef Şekil 3'teki düzende: direkte üstte maket, altında **kırmızı balon**.

> **Şartnamenin kurduğu tuzak:** dost maketler mavi, düşman maketler kırmızıdır —
> ama balonlar **hepsinde kırmızıdır** ve imha yalnızca balondan sayılır.
> "Kırmızı leke = düşman" varsayımı doğrudan dost ateşine götürür.
> `BalloonTargetDetector` önce yuvarlak kırmızı balonları bulur, sonra her
> balonun **üstündeki** pencerede maket rengini ölçüp tarafı belirler.

## Aşamalar (`ParkurManager.asama`)

| Aşama | Şartname | Kurulum |
|---|---|---|
| 1 | 6.1 | 5/10/15 m'de duran 12 hedef, zarfla verilen imha sırası, manuel mod |
| 2 | 6.2 | 4 tur, turda 9 kırmızı hedef (şartname 3), otonom |
| 3 | 6.3 | 8 tur, turda 3 düşman + 7 dost (şartname 1+2), tipe göre imha menzili |

Hedef sayıları `ParkurManager` üzerinden ayarlanabilir; şartname değerleri
3 / 3 / 1'dir. Hedefler kollara dağıtılır ve halkada rastgele — ama üst üste
binmeyecek şekilde — konumlanır.

Puanlama, ceza ve başarısızlık koşulları (Tablo 5/6/7) `ParkurManager` içinde
kodlanmıştır: yanlış sıra -5, dost vurma -10, tur başına ceza tavanı 10,
4 ardışık turda düşman vurulamaması → aşama başarısız.

Aşama-2'nin puan tablosu (5 / 15 / 30) `30·k(k+1) / n(n+1)` formülünün n=3
özel hali; hedef sayısı değişince turun tam temizlenmesi yine 30 puan eder.

## Mimari

```
┌─────────────────── Unity (SteelDomeSim sahnesi) ───────────────────┐
│  Parkur ── Kollar(3 × LanePath) ── Hedefler(TargetUnit+TargetMover) │
│                                                                     │
│  Turret ── YawPivot ── PitchPivot ── Barrel ── MuzzleCam            │
│     │        (pan)      (tilt)                    │                 │
│  TurretController   ParkurManager   FireControl   ▼                 │
│         ▲                 ▲              ▲   RenderTexture          │
│         └──────── PythonBridge (TCP 8765) ┘       (640×480)         │
└─────────────────────────────┬───────────────────────────────────────┘
                              │  JPEG kare + telemetri  ▼
                              │  yön / ateş komutu      ▲
┌─────────────────────────────┴───────────────────────────────────────┐
│  Python:  bridge.py  ──►  tracker.py  ──►  run.py                   │
│           (soket, menzil)  (balon+maket, PID)  (ana döngü)          │
└─────────────────────────────────────────────────────────────────────┘
```

**Kamera namluyla eş eksenlidir (boresight, sapma 0°)** — görüntü merkezi tam
olarak namlunun baktığı noktadır, ayrı kalibrasyon gerekmez. Görüş açısı 30°:
nişan optiği dar olmalı, 15 m'de 0.28 m'lik balon ancak böyle ~17 piksel kalır.

Menzil, balonun piksel yüksekliğinden kestirilir (`bridge.estimate_range`) —
gerçek çapı bilindiği için tek kamera yeter. 15 m'de 1 piksellik ölçüm hatası
~1 m menzil hatası demektir.

## Çalıştırma

Adım adım kullanım için **[KULLANIM.md](KULLANIM.md)** dosyasına bakın.
Kısaca: Unity'de `Assets/SteelDome/Scenes/SteelDomeSim.unity` → Play, sonra:

```bash
pip install opencv-python numpy

python3 test_connection.py     # köprüyü doğrula (OpenCV gerekmez)
python3 run.py                 # otonom: balon bul, dost/düşman ayır, ateş et
python3 run.py --no-fire       # sadece takip
python3 run.py --min-range 10  # F16 penceresi (10-15 m)
python3 run.py --legacy-color  # eski düz renk dedektörü
```

## Kontroller (Unity Game penceresi)

| Tuş | İşlev |
|---|---|
| **1 / 2 / 3** | **Aşama seç** (puan ve tur sayacı sıfırlanır) |
| **R** | Bulunulan aşamayı baştan başlat |
| Ok tuşları / WASD | Manuel nişan alma |
| M | Manuel ↔ otomatik geçiş |
| Boşluk | Ateş |
| Esc | Acil durdur (aç/kapa) |

Aynı geçiş Python'dan da yapılabilir: `client.set_stage(3)`.

## Protokol

Her mesaj: `[1 bayt tip][4 bayt uzunluk, big-endian][gövde]`

| Tip | Yön | Gövde |
|---|---|---|
| `0x01` FRAME | Unity → Python | `[2 bayt json uzunluğu][telemetri json][jpeg]` |
| `0x10` COMMAND | Python → Unity | utf8 json |

```json
{"mode": "rate",  "yaw": 0.4, "pitch": -0.1, "fire": true}
{"mode": "angle", "yaw": 45,  "pitch": 12}
{"mode": "stage", "stage": 3}
{"mode": "stop"}
```

### Güvenlik davranışı (şartname 4.2)

İki ayrı kısıtlama vardır ve aynı şey değildir:

- **harekete yasak bölge** — `TurretController` açı limitleri (yaw ±95°)
- **atışa yasak bölge** — `FireControl.fireYawMin/Max`, `firePitchMin/Max`

Taret bir yöne dönebilir ama oraya ateş edemeyebilir. Acil durdur (Esc) ikisini
birden keser.

`rate` modunda 0.5 saniye komut gelmezse taret durur — ölü bir kontrolcü tareti
savrulmaya bırakmasın diye. `angle` modunda watchdog uygulanmaz: hedef sabit bir
nokta olduğu için taret zaten oraya varıp durur.

## Dosyalar

| Dosya | İşlev |
|---|---|
| `Assets/SteelDome/Scripts/TurretController.cs` | Yaw/pitch sürüşü, açı limitleri, ivme rampası |
| `Assets/SteelDome/Scripts/PythonBridge.cs` | TCP sunucusu, kare akışı, komut uygulaması |
| `Assets/SteelDome/Scripts/LanePath.cs` | Bir kolun dalgalı A→B yolu |
| `Assets/SteelDome/Scripts/TargetMover.cs` | Hedefi ray üzerinde taşır, tur bitişini bildirir |
| `Assets/SteelDome/Scripts/TargetUnit.cs` | Hedef kimliği, balon, menzil pencereleri, puanlar |
| `Assets/SteelDome/Scripts/ParkurManager.cs` | 3 aşamanın tur/spawn/puan mantığı |
| `Assets/SteelDome/Scripts/FireControl.cs` | Namlu ışını, balon isabeti, atışa yasak bölge |
| `Assets/SteelDome/Scripts/TurretHud.cs` | Operatör ekranı |
| `bridge.py` | Soket istemcisi, piksel→açı, menzil kestirimi |
| `tracker.py` | Balon/maket dedektörü, PID, kilitlenme durum makinesi |
| `run.py` | Ana kontrol döngüsü |
| `test_connection.py` | Köprü doğrulama testi (yalnızca stdlib) |

## Bilinen eksik

**Hedef tipi sınıflandırması yok.** Şartname Aşama-3'te tipe göre farklı imha
penceresi istiyor (F16 10-15 m, helikopter/füze 5-15 m, mini İHA 0-15 m) ve
Yetenek 6 arayüzde sınıflandırma gösterilmesini bekliyor. Python şu an yalnızca
dost/düşman ayrımı yapıyor, tip ayrımı yapmıyor; bu yüzden `--min-range` tek bir
sabit eşikle çalışıyor. Çözüm bir YOLO dedektörü: `tracker.py` içindeki
`BalloonTargetDetector.detect()` metodunu aynı imzayla değiştirmek yeterli,
kontrol katmanına dokunmaya gerek yok.
