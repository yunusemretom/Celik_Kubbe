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
| Saha | 18000 × 14000 | X ∈ [-7, +7], **Z ∈ [-1, +23]** (24 m) |
| Poligon | 16000 × 10000 | X ∈ [-5, +5], **Z ∈ [1, 22]** |
| Salon tavan yüksekliği | 2950 (çizim) | **6.0 m** (bkz. *Görsel ortam*) |
| Taret namlu ekseni | 1300 | y = 1.28 m |
| Ray dalgası | ~460 tepe-tepe, ~1530 adım | genlik 0.23, dalga boyu 1.53 |

**Saha çizimden bilerek uzun.** Şartname 15 m'ye kadar imha istiyor. Saha 15-16 m'de
bitseydi en uzak hedef duvarın dibinde doğardı ve hedefin menzile *girişini* hiç
görmezdik — oysa gerçek angajmanın yarısı budur. `SahaOlculeri.MENZIL` = **20 m**:
hedef yaklaşma koşusuna tam 20 m'den başlar, yaklaşırken geçerli imha penceresine
(≤ 15 m) kendi hareketiyle girer. İmha penceresi değişmedi, yalnız saha uzadı.

### Menzil nereden ölçülür

**Taretin dönme merkezinden** — `Turret/YawPivot/PitchPivot`, yani (0, 1.28, 0).
Zemindeki menzil yayları da oradan çizili.

Bu bir düzeltmedir: `ParkurManager` eskiden menzili **namlu ucundan** ölçüyordu.
Namlu ucu taretle birlikte döner (40° yaw'da (1.13, 1.28, 1.34)'e gider), yani aynı
hedefin "menzili" nişan yönüne göre değişiyordu; üstelik namlu ucu referans noktadan
1.75 m ileride olduğu için 16.75 m'deki bir hedef 15.00 m okunuyor ve **menzil dışı
bir imha geçerli sayılıyordu**. Artık `ParkurManager.menzilReferansi` alanı var;
boş bırakılırsa eski davranışa düşer.

Aynı sebeple Python tarafı da düzeltildi: görüntüden çıkan mesafe *kameraya* olan
mesafedir, kamera ise namlu boyunca 1.90 m ileridedir. Unity bu farkı telemetride
`cam_off` ile bildiriyor, `estimate_range` ekliyor. Düzeltilmeseydi 15 m'lik
pencerede %13 hata olurdu.

**Her kol kapalı bir ray halkasıdır** — köşeleri yuvarlatılmış bir dikdörtgen.
Tarete bakan uzun kenar **dalgalıdır**: hedef yılan gibi salınarak yaklaşır.
Karşı uzun kenar düzdür ve dönüş koşusudur. Arabalar bu halkanın etrafında
sürekli tur atar; şartnamedeki **"A'dan B'ye = 1 tam tur"** bir devirdir.

Üç halka iç içe geçer, çizimdeki gibi (12.76 mm/piksel ölçeğiyle okundu):

| Kol | Dalgalı koşu X | Düz dönüş X | Z aralığı | Çevre | Yaklaşma başı |
|---|---|---|---|---|---|
| Kol-1 (Sağ) | +2.87 | +5.60 | 1.98 … 21.29 | 44.7 m | 20.0 m |
| Kol-2 (Orta) | 0.00 | −6.75 | 1.53 … 21.50 | 53.9 m | 20.0 m |
| Kol-3 (Sol) | −2.68 | −5.61 | 1.98 … 21.32 | 44.9 m | 20.0 m |

`farZ` elle girilmez: **SteelDome ▸ Görsel Kurulum ▸ Parkur Ölçülerini Uygula**
her kolun uzak ucunu `sqrt(MENZIL² − nearX²) + cornerRadius` ile hesaplar. İki
incelik var:

- Yaklaşma koşusu `farZ`'de değil, `farZ − cornerRadius`'ta başlar (öncesinde köşe
  yayı var). Önemli olan sayı hedefin *yaklaşmaya başladığı* mesafedir; köşe yarıçapı
  bu yüzden ekleniyor.
- Yan kollarda düz Z mesafesi menzil değildir; `nearX` çıkarılmazsa Kol-1 ve Kol-3
  20 m yerine 20.2 m'den başlardı.

> Bir tur ~11 m uzadı. `ParkurManager.targetSpeed` 1.0 m/s iken tur süresi
> 34-44 s'den **45-54 s**'ye çıktı; aşama süresi dar geliyorsa hızı artırın.

Kol-3'ün halkası Kol-2'nin içine yerleşir, kesişmezler — çizimdeki düzen budur.
Orta kol taretin nişan ekseni üzerindedir.

Menzil bantları **5 / 10 / 15 / 20 m**'de zemine **yay** olarak çizildi, düz çizgi
değil: menzil gerçek 3B mesafedir, yandaki kollarda düz bir çizgi yanıltır. Yaylar
poligon genişliğinde (|x| ≤ 5 m) kesilir; bu yüzden 20 m bandı yalnızca ±14°'lik
kısa bir yaydır — 20 m'de poligonun içinde kalan açı budur.

Raylar da artık elle değil, `LanePath`in ürettiği yoldan 20 cm'lik parçalarla
üretiliyor; kol geometrisini değiştirip kurulumu çalıştırmak yeterli.

Parkurdaki her şey nötr gri; **doygun kırmızı ve mavi yalnızca hedeflere ait**.
Aksi halde Python tarafındaki renk eşikleme yanlış pozitif üretir.

## Hedefler

Yarışma tarafından verilen 4 OBJ maketi (`Assets/SteelDome/Models/`):
balistik füze, helikopter, F16, mini/mikro İHA. Burnu +Z, füze dik duruyor.

Maketler görünürlük için **1.5 kat** büyütüldü (`Hedef_*.prefab` → `Model`
ölçeği). Ortaya çıkan boyutlar: füze 0.33 × 0.75, F16 0.45 × 0.75,
helikopter 0.59 × 0.87, İHA 0.42 × 0.56 m — gerçek maket ölçeğinin (0.3–0.6 m)
biraz üstünde. Şartname ölçeğine dönmek için `Model` ölçeğini 1'e çekin.

**Balon büyütülmedi**: çapı 0.28 m ve Python'un menzil kestirimi
(`BALLOON_DIAMETER_M`) buna bağlı. Balonu büyütürseniz o sabiti de güncelleyin.

Her hedef Şekil 3'teki düzende: direkte üstte maket, altında **kırmızı balon**.
Maketin alt kenarı balonun üstünden en az 5 cm yukarıda tutulur — büyütme
sırasında sarkarsa balonu gölgeler ve balonu vurmak imkânsız hale gelir.

> **Şartnamenin kurduğu tuzak:** dost maketler mavi, düşman maketler kırmızıdır —
> ama balonlar **hepsinde kırmızıdır** ve imha yalnızca balondan sayılır.
> "Kırmızı leke = düşman" varsayımı doğrudan dost ateşine götürür.
> `BalloonTargetDetector` önce yuvarlak kırmızı balonları bulur, sonra her
> balonun **üstündeki** pencerede maket rengini ölçüp tarafı belirler.

## Aşamalar (`ParkurManager.asama`)

| Aşama | Şartname | Kurulum |
|---|---|---|
| 1 | 6.1 | 5/10/15 m'de **ray üzerinde duran** hedefler, zarfla verilen imha sırası, manuel mod |
| 2 | 6.2 | 4 tur, turda 9 kırmızı hedef (şartname 3), otonom |
| 3 | 6.3 | 8 tur, turda 3 düşman + 7 dost (şartname 1+2), tipe göre imha menzili |

Hedef sayıları `ParkurManager` üzerinden ayarlanabilir; şartname değerleri
3 / 3 / 1'dir. Hedefler kollara dağıtılır ve halkada rastgele — ama üst üste
binmeyecek şekilde — konumlanır.

**Aşama-1 hedefleri de rayın üzerinde durur** (`staticOnLanes`), gerçekteki gibi:
maketler arabalarla ray üstündedir, bu aşamada araba hareket etmez. Konumlar
kolun 5/10/15 m menzil çemberini kestiği noktalardan seçilir, dolayısıyla menzil
tam tutar. Seçim açısal yayılıma göre yapılır ki hedefler bandın bir kenarında
kümelenmesin, ve **atışa yasak bölgeye düşen kesişimler elenir** (`staticMaxYaw`)
— orada duran bir hedef imha edilemeyeceği için zarf sırası tıkanırdı.

Bu yüzden 5 m bandında 4 değil **3 hedef** olur: ±78°'lik sektör içinde üç kol o
çemberi yalnızca üç noktada kesiyor. Toplam 11 hedef.

Puanlama, ceza ve başarısızlık koşulları (Tablo 5/6/7) `ParkurManager` içinde
kodlanmıştır: yanlış sıra -5, dost vurma -10, tur başına ceza tavanı 10,
4 ardışık turda düşman vurulamaması → aşama başarısız.

Aşama-2'nin puan tablosu (5 / 15 / 30) `30·k(k+1) / n(n+1)` formülünün n=3
özel hali; hedef sayısı değişince turun tam temizlenmesi yine 30 puan eder.

## Görsel ortam

Salon, **fuar/sergi salonu** olarak kuruldu: parlak beyaz yüzeyler, güçlü tavan
aydınlatması, cilalı zemin. Amaç sahadaki görüntü koşullarını taklit etmek —
görüntü işleme burada çalışıyorsa sahada da çalışır.

| Öğe | Değer | Not |
|---|---|---|
| Tavan yüksekliği | 6.0 m | Çizimdeki 2.95 m poligon kotu; salonun kendisi daha yüksek |
| Aydınlatma | 15 armatür (3 × 5 ızgara) | Spot + gölge, ~4500 K |
| Tavan dolgusu | 15 nokta ışığı | Gölgesiz; tavanın karanlık kalmaması için |
| Duvar | `T_Wall` dokusu, 1 m panel derzi | Mat boya, pürüzsüzlük ~0.28 |
| Zemin | `T_Floor` dokusu, 2 m kesim derzi | Cilalı beton, pürüzsüzlük ~0.70 |
| Tavan yüzeyi | `T_Ceiling` dokusu | 50 cm metal kaset panel |
| Yansıtma probu | Kutu izdüşümlü, gerçek zamanlı | Zeminin armatürleri yansıtması için |
| Post-process | Tonemapping (Neutral), bloom, beyaz ayarı, vinyet | `Assets/SteelDome/Settings/VP_Salon.asset` |

**Dokular üretilerek geliyor.** Depoda PNG tutmak yerine `araclar/doku_uret.py`
onları seamless olarak üretiyor (2 × 2 m'lik bir alanı temsil eder, Unity tarafı
tiling'i buna göre hesaplar):

```bash
python araclar/doku_uret.py           # Unity Assets/SteelDome/Textures'a yazar
```

Sonra Unity'de **SteelDome ▸ Görsel Kurulum ▸ Tümünü Uygula**. Bu menü öğesi
idempotenttir: ışıkları, çelik makasları, süpürgeliği ve kolonları silip yeniden
kurar, salonun yüksekliğini ayarlar, malzemeleri bağlar. Play modundayken
çalışmaz.

### Namlu kamerası gerçek kamera gibi

`KameraGercekcilik` bileşeni, ham render ile Python'a giden JPEG arasına giriyor.
640×480 / 30° FOV korundu (sahadaki dar açılı namlu kamerası); üzerine sahada
karşılaşılan bozulmalar bindiriliyor:

| Etki | Varsayılan | Neden |
|---|---|---|
| Fıçı distorsiyonu | k1 = 0.085, k2 = 0.02 | Kadraj kenarında ~20 px kayma |
| Kromatik aberasyon | 0.0035 | Kanal bazlı ölçek farkı |
| Vinyet | 0.26 | Kenarda kararan kırmızı balon = kaçan tespit |
| Odak yumuşaklığı | 0.28 | Ucuz objektif + JPEG öncesi yumuşama |
| Otomatik pozlama | hedef 0.20, uyum 1.8 /sn | Parlak tavan kadraja girince "pompalama" |
| Sensör gürültüsü | 0.012 (görüntü uzayında) | Eşiklemeyi zorlar |
| Sabit desen gürültüsü | 0.0025 | Sütun/satır izleri, kareler arası sabit |
| Hareket bulanıklığı | pozlama 1/90 s | Taret hızlı dönerken |
| Rolling shutter | okuma 0.012 s | Yatay eğilme; yaw hızıyla orantılı |

Bu bozulmalar **HUD'daki önizlemeye de** uygulanır — operatörün gördüğü ile
Python'un gördüğü aynı karedir.

**Distorsiyon Python'a bildirilir.** Telemetriye her karede `k1`, `k2` ve `exp`
(o anki pozlama) ekleniyor; `bridge.pixel_to_angles` hedef merkezini
`kamera_modeli.KameraModeli.nokta_duzelt` ile düzeltip açıya çeviriyor. Düzeltme
olmadan kadraj kenarındaki bir hedefte nişan hatası **0.6 dereceye** çıkar; bu
15 m'deki bir balonun yarıçapından büyüktür. Filtre Unity'de kapatılırsa
telemetride k1/k2 gelmez ve düzeltme kendiliğinden devre dışı kalır.

Tüm kareyi düzeltmek gerekmiyor: takip döngüsü yalnızca hedefin merkezini
taşıyor. Görsel doğrulama için `KameraModeli.duzelt(kare)` tüm kareyi remap eder.

Vinyet renk eşiklerini bozuyorsa:

```bash
python run.py --vinyet-telafi 0.26     # Unity'deki vinyet değeriyle aynı olmalı
```

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

> **Grafik API'si Vulkan olmalı.** Bu makinede Unity OpenGLCore ile açılıyordu ve
> Mesa/Intel sürücüsünde Scene view render'ında kırmızı kanal her pikselde 1.0'a
> kilitleniyordu (sahne değil, sürücü hatası; oyun kameraları etkilenmiyordu).
> Player Settings'te API sırası `Vulkan → OpenGLCore` yapıldı; **etkili olması için
> Unity yeniden başlatılmalı.** Ayrıntı: KULLANIM.md § 7.

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
| **Shift+Q** | **Simülasyondan çık** — sağ alttaki `CIKIS` butonuyla aynı, onay ister |

Aynı geçiş Python'dan da yapılabilir: `client.set_stage(3)`.

Çıkış `TurretHud.QuitSimulation()` üzerinden gider: önce taret durdurulur, sonra
editörde Play modu kapatılır, derlenmiş oyunda `Application.Quit()` çağrılır —
`Application.Quit()` tek başına editörde hiçbir şey yapmaz, o yüzden ikisi ayrı.

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

Telemetri json'u (FRAME gövdesinin başında):

| Alan | Anlam |
|---|---|
| `t` | Unity zamanı (s) |
| `yaw`, `pitch` | Taret açısı (derece) |
| `yaw_rate`, `pitch_rate` | Açısal hız (derece/s) |
| `w`, `h` | Kare boyutu |
| `vfov` | Dikey görüş açısı (derece) |
| `frame` | Gönderilen kare sayacı |
| `k1`, `k2` | Objektif distorsiyon katsayıları — yalnız `KameraGercekcilik` açıkken |
| `exp` | Kameranın o an uyguladığı otomatik pozlama çarpanı |
| `cam_off` | Kameranın menzil referansından eksenel ilerisi (1.90 m) — `estimate_range` bunu ekler |

`k1`/`k2` gelmediğinde Python distorsiyon düzeltmesini kendiliğinden atlar.

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
| `Assets/SteelDome/Scripts/KameraGercekcilik.cs` | Namlu kamerasının sensör/optik kusur modeli |
| `Assets/SteelDome/Shaders/CameraRealism.shader` | Distorsiyon, gürültü, vinyet, rolling shutter |
| `Assets/SteelDome/Editor/SahaOlculeri.cs` | Saha ölçülerinin tek kaynağı (`MENZIL`, saha/poligon boyutları) |
| `Assets/SteelDome/Editor/SahneGorselKurulum.cs` | Salonu kuran editör betiği (menü: **SteelDome ▸ Görsel Kurulum**) |
| `Assets/SteelDome/Editor/ParkurGeometriKurulum.cs` | Kol/ray/poligon/menzil bandı ölçülerini menzile göre kurar |
| `araclar/doku_uret.py` | Duvar/zemin/tavan dokularını üretir (seamless PNG) |
| `kamera_modeli.py` | Kamera iç parametreleri, distorsiyon düzeltme, vinyet telafisi |
| `bridge.py` | Soket istemcisi, piksel→açı, menzil kestirimi |
| `tracker.py` | HSV balon/maket dedektörü, PID, kilitlenme durum makinesi |
| `yolo_detector.py` | YOLO dedektörü (`--yolo`); balon/maket eşleme, iz bazlı sınıf oylaması, SAHI |
| `run.py` | Ana kontrol döngüsü |
| `test_connection.py` | Köprü doğrulama testi (yalnızca stdlib) |

## Bilinen eksik

**Tipe göre menzil penceresi hâlâ elle veriliyor.** Şartname Aşama-3'te tipe göre
farklı imha penceresi istiyor (F16 10-15 m, helikopter/füze 5-15 m, mini İHA
0-15 m) ve Yetenek 6 arayüzde sınıflandırma gösterilmesini bekliyor.

Tespit tarafı çözüldü: `yolo_detector.YoloTargetDetector` (`run.py --yolo
--weights ...`) `BalloonTargetDetector` ile aynı `detect()` imzasını kullanıyor,
kontrol katmanı değişmedi. Model hedef tipini veriyorsa tip artık `Engagement.label`
içinde taşınıyor ve teşhis penceresinde gösteriliyor.

Kalan iş: `run.py` içindeki tek `--min-range` eşiğini `label` → pencere tablosuna
çevirmek. HSV modunda tip bilgisi olmadığı için eşik tek değer olarak kalır.
