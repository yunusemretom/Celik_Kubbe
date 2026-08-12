# Çelik Kubbe — Kullanım Kılavuzu

Bu dosya "nasıl çalıştırırım" sorusunun cevabı. Sistemin nasıl kurulduğu ve
neden öyle kurulduğu için `README.md`'ye bakın.

---

## 1. Tek seferlik hazırlık

HSV dedektörü için:

```bash
pip install "opencv-python<5" numpy
```

YOLO dedektörü de kullanacaksanız, depo kökündeki venv'e (`uv venv` ile açıldı):

```bash
cd /home/tom/Documents/Projeler/Celik_Kubbe
uv pip install --index-url https://download.pytorch.org/whl/cu124 torch torchvision
uv pip install ultralytics sahi "opencv-python<5"
```

Sonra betikleri **venv'in** Python'uyla çalıştırın:

```bash
cd Similasyon_Kullanım
../.venv/bin/python run.py --yolo --weights /yol/best.pt
```

> **cu124 neden:** sürücü 550 CUDA 12.x'e kadar destekliyor, cu130 (CUDA 13)
> tekerlekleri sürücü 580+ ister. Sistem genelindeki kurulumda torch 2.13+cu130
> ile torchvision 0.21 eşleşmediği için `operator torchvision::nms does not exist`
> hatası çıkıyor — YOLO'yu venv'den çalıştırın.
>
> **`opencv-python<5` neden:** opencv-python 5.0 tekerleği GUI backend'i olmadan
> geliyor, `cv2.imshow` "The function is not implemented" hatası veriyor.
> (`run.py` bu durumda çökmüyor, yalnızca pencereyi kapatıp takibe devam ediyor.)

Unity tarafında hiçbir paket kurulumu gerekmiyor. Unity 6000.5.7f1 ile
`/home/tom/Setup Guide In-Editor Tutorial/` projesini açın.

---

## 2. Simülasyonu başlatma

1. Unity'de `Assets/SteelDome/Scenes/SteelDomeSim.unity` sahnesini açın
2. **Play**'e basın

Play'e basar basmaz:
- `PythonBridge` `127.0.0.1:8765` portunu dinlemeye başlar
- `ParkurManager` seçili aşamayı kurar (varsayılan: **Aşama-1**)
- Ekranın sağ üstünde namlu kamerası, sol üstte telemetri ve görev paneli çıkar

### Çıkmak

Ekranın **sağ alt köşesindeki kırmızı `CIKIS` butonu** ya da **Shift+Q**.
İkisi de önce onay sorar (`EVET, CIK` / `VAZGEC`) — sürmekte olan bir tur yanlış
tıklamayla kaybolmasın diye. Onaylayınca taret durdurulur, sonra editörde Play
modu kapanır, derlenmiş oyunda uygulama sonlanır.

Kısayolun `Shift` istemesi bilinçli: yalın `Q` nişan alırken kolayca basılabilir.

---

## 3. Aşamalar arası geçiş

Üç yol var, üçü de aynı işi yapar (`ParkurManager.SelectAsama`).

### Klavye — en pratik yol

Unity **Game penceresine tıklayın** (klavye odağı orada olmalı), sonra:

| Tuş | Ne yapar |
|---|---|
| `1` | Aşama-1: farklı menzillerde duran hedef imhası |
| `2` | Aşama-2: sürü saldırısı (4 tur) |
| `3` | Aşama-3: farklı katmanlardaki hareketli hedefler (8 tur) |
| `R` | Bulunulan aşamayı baştan başlatır |

Aşama değiştirmek **puanı ve tur sayacını sıfırlar**, parkurdaki hedefleri
siler ve yenilerini kurar.

### Inspector — Play'e basmadan seçmek için

`SimManager` nesnesini seçin → `Parkur Manager` bileşeni → **Asama** alanı.
Buradaki seçim, Play'e basıldığında hangi aşamanın kurulacağını belirler.

### Python — testi baştan sona betikle sürmek için

```python
from bridge import SteelDomeClient

with SteelDomeClient() as c:
    c.set_stage(3)      # Aşama-3'ü başlat
```

---

## 4. Manuel mod (Aşama-1 için)

Şartname Aşama-1'in **tamamen manuel** yapılmasını istiyor. Python bağlı
değilken sistem zaten manuel moddadır.

| Tuş | İşlev |
|---|---|
| Ok tuşları / WASD | Namluyu çevir |
| Boşluk | Ateş |
| `M` | Manuel ↔ otomatik geçiş |
| `Esc` | Acil durdur (aç/kapa) — hem hareketi hem ateşi keser |
| `Shift+Q` | Simülasyondan çık (onay ister) |

Görev panelindeki **zarf sırası** satırı, hangi hedefi sırada vurmanız
gerektiğini sarı renkle gösterir. Sıra dışı bir hedefi vurursanız −5 ceza
alırsınız (şartname 6.1).

Puanlama menzile göre: 5 m → 5 puan, 10 m → 10 puan, 15 m → 20 puan.

Hedefler **rayın üzerinde durur, hareket etmez** — gerçekteki gibi maketler
arabalarla ray üstündedir, bu aşamada arabalar hareket etmez. Konumlar kolun
5/10/15 m çemberini kestiği noktalardan, ateş sektörünün içinde ve birbirine
açı olarak yayılacak şekilde seçilir. 5 m bandında 4 değil 3 hedef olması
normaldir: sektör içinde üç kol o çemberi üç noktada kesiyor (toplam 11 hedef).

---

## 5. Otonom mod (Aşama-2 ve 3)

Unity Play modundayken, ayrı bir terminalde:

```bash
cd /home/tom/steel_dome
python3 run.py
```

Python bağlanır bağlanmaz Unity manuel kontrolü **otomatik olarak** devre dışı
bırakır; bağlantı koparsa geri verir ve tareti durdurur.

Açılan OpenCV penceresinde ne göreceksiniz:
- kırmızı kutu = düşman olarak sınıflanan balon
- mavi kutu = dost (asla hedeflenmez)
- gri kutu = maket rengi okunamadı ("bilinmiyor")
- her balonun üstündeki ikinci kutu = maket rengi ölçülen pencere
- yeşil halka = kilitlendi

Çıkmak için pencerede `Q` veya terminalde `Ctrl+C`.

### Sık kullanılan seçenekler

```bash
python3 run.py --no-fire          # sadece takip et, ateş etme
python3 run.py --no-window        # OpenCV penceresi açma (uzaktan/başsız)
python3 run.py --min-range 10     # F16 penceresi: 10 m altına ateş etme
python3 run.py --max-range 15     # 15 m üstüne ateş etme
python3 run.py --engage-unknown   # maket rengi okunamayan balonları da vur
python3 run.py --fire-interval 1.0  # atışlar arası bekleme (sn)
python3 run.py --legacy-color     # eski düz renk dedektörü
python3 run.py --host 192.168.1.5  # Unity başka makinede
```

> **Menzil kapısı neden var:** şartname Aşama-3'te hedef tipine göre farklı
> imha penceresi istiyor (F16 10–15 m, helikopter/füze 5–15 m, mini İHA
> 0–15 m). Pencere dışında yapılan imha puan getirmiyor. Python henüz hedef
> **tipini** ayırt edemediği için `--min-range` tek bir sabit eşik olarak
> çalışıyor; varsayılan 5 m helikopter ve füze için doğru, F16 için 10
> vermeniz gerekir.

### YOLO dedektörü

Varsayılan dedektör HSV renk eşiklemedir. Eğitilmiş bir model varsa:

```bash
python3 run.py --yolo --weights best.pt
python3 run.py --yolo --weights best.engine --yolo-track   # iz + sınıf oylaması
python3 run.py --yolo --weights best.pt --yolo-sahi        # uzak/küçük hedef
```

Model açılırken sınıflarını rollere eşleştirir ve eşleşmeyi terminale yazar.
Sınıf adlarınız farklıysa elle verin:

```bash
python3 run.py --yolo --weights best.pt \
    --balloon-classes balon --enemy-classes dusman --friend-classes dost
```

Model **yalnızca tip** veriyorsa (`Object_detection/` altındaki modelde olduğu
gibi: `drone, helicopter, plane, rocket`) hiçbir şey vermenize gerek yok; bu
sınıflar otomatik "maket" rolüne düşer. Bu durumda **dost/düşman ayrımını yine
maket rengi yapar**, model yalnızca tipi etiketler — model dost/düşman etiketi
taşımadığı sürece sınıfını düşman saymak doğrudan dost ateşi demektir.

| Seçenek | İşlev |
|---|---|
| `--yolo-conf`, `--yolo-iou`, `--yolo-imgsz`, `--yolo-device` | Standart çıkarım ayarları |
| `--yolo-track` | ByteTrack izi + iz başına güven ağırlıklı taraf/tip oylaması. Tek karelik "düşman" titremesi ateşe dönüşmez |
| `--yolo-tracker` | Takipçi yaml'i (ör. `../Object_detection/cfg/tracker_gimbal.yaml`) |
| `--yolo-sahi`, `--slice-size`, `--overlap-ratio` | Dilimli çıkarım — 15 m'deki balon birkaç piksel, dilimleme tespiti artırır ama kare hızını düşürür |
| `--no-hsv-fallback` | Model balonu bulamadığında HSV balon dedektörüne düşme |
| `--no-crop-classify`, `--crop-conf` | Tipi belirlenemeyen hedefin üstündeki bölgeyi kırpıp modele yeniden sorma (varsayılan açık) |
| `--maket-size` | Balon hiç bulunamayıp maketin kendisine nişan alındığında menzil kestiriminde kullanılan boy (m) |

Nişan noktası ve menzil her zaman **balondan** gelir; model balon sınıfı
içermiyorsa ya da o karede kaçırırsa balonu HSV dedektörü bulur, tarafı YOLO
söyler. İkisi de bulunamazsa maketin kendisine nişan alınır — menzil o durumda
`--maket-size` üzerinden kabaca kestirilir.

### Hedef tipinin ekrana yazılması (Yetenek 6)

Teşhis penceresinde **maketin üstünde modelin sınıfı** (`plane 0.34`, `drone`…),
balonun altında ise taraf (`dusman` / `dost`) yazar. Tip `Engagement.label`
alanında taşınır, dolayısıyla arayüze veya menzil penceresi tablosuna doğrudan
bağlanabilir.

Tipi tam karede okunamayan hedefler için **kırpma ile sınıflandırma** devreye
girer: balonun üstündeki bölge kırpılıp modele ikinci kez sorulur. Bölge çıkarım
boyutuna büyütüldüğü için maket çok daha büyük görünür — ölçülen etki, aynı
sahnede güvenin **0.11 → 0.20–0.41**'e çıkması. Sonuç hedefin kaba konumuna göre
birkaç kare önbelleklenir, böylece ek çıkarımın kare hızına maliyeti kalmaz
(19.3 fps, akışın tam hızı). Kapatmak için `--no-crop-classify`.

> **`Object_detection/` modeliyle simülasyon:** `best (05.08.02).pt` gerçek uçak
> görüntüleriyle eğitildi; simülasyondaki alçak-poligonlu maketlerde tam karedeki
> güveni **0.10–0.12**'de kalıyor, yani varsayılan `--yolo-conf 0.25` ile tam
> karede tek kutu bile üretmiyor. Kırpma ile sınıflandırma bu açığı kapatıyor —
> varsayılan eşikle çalışır:
>
> ```bash
> ../.venv/bin/python run.py --yolo --weights '/home/tom/Downloads/best (05.08.02).pt'
> ```
>
> Ölçülen: 19.3 fps, maketler `plane 0.34` / `drone` olarak doğru etiketleniyor.
> Maketi kare dışında kalan (çok yakın) balon tipsiz kalır. Simülasyonda daha
> yüksek güven için model simülasyon kareleriyle eğitilmeli; gerçek parkurda
> varsayılan eşik zaten doğrudur. Taraf ayrımı her hâlükârda maket renginden
> geldiği için düşük güven dost ateşi riski yaratmaz — yalnızca tip etiketini
> etkiler.

---

## 6. Bağlantıyı doğrulama

Bir şey çalışmıyorsa önce köprüyü test edin (OpenCV gerektirmez):

```bash
python3 test_connection.py
```

Dört aşamayı sırayla dener: bağlanma, 20 kare akış, hız komutu, mutlak açı
komutu. Hepsi geçerse sorun Unity–Python arasında değildir.

---

## 7. Sorun giderme

| Belirti | Sebep / çözüm |
|---|---|
| `Baglanti kurulamadi` | Unity Play modunda değil. Önce Play'e basın. |
| Telemetri panelinde `BEKLENIYOR` | Python henüz bağlanmadı; normal. |
| Taret hiç dönmüyor | HUD'da `[MANUEL]` yazıyorsa `M` ile otomatiğe alın. |
| Taret dönüyor ama ateş etmiyor | Görev panelinde `ATISA YASAK BOLGE` mi yazıyor? Namlu izinli sektörün dışında. `Esc` ile acil durdur açık olabilir. |
| Hiç hedef bulunmuyor | Aşama-1'de hedefler duruyor ama otonom mod Aşama-2/3 için tasarlandı. `2` veya `3` tuşuna basın. |
| Tuşlar çalışmıyor | Unity **Game** penceresine tıklayın; klavye odağı Scene penceresindeyse tuşlar gitmez. |
| Puan hep 0 kalıyor | Düşman muhtemelen geçerli menzil penceresi dışında imha ediliyor. `--min-range` / `--max-range` ayarlayın. |
| Dost vuruluyor (−10) | `--engage-unknown` açıksa kapatın; maket rengi okunamayan balonları düşman sayıyor. |
| **Scene view baştan aşağı kırmızı** | Unity'nin OpenGL sürücü hatası, sahneyle ilgisi yok — aşağıya bakın. |

### Scene view'ın kırmızı olması

Linux'ta Unity bu makinede **OpenGLCore** ile açılıyordu ve Mesa/Intel sürücüsünde
Scene view kamerasının render'ında **kırmızı kanal her pikselde 1.0'a kilitleniyordu**.
Ölçüldü: kamera bomboş yeşil bir zemine temizlense bile çıktı `(1.000, 0.494, 0.000)`,
piksellerin %100'ünde R doygun. Yani sahne verisi, ışıklar ve post-process temiz;
sorun tamamen sürücü tarafında.

Oyun kameraları (OperatorCam, MuzzleCam) etkilenmiyordu — Python'a giden akış ve
puanlama hep doğruydu, yalnızca editördeki görüntü bozuktu.

Çözüm, projenin grafik API sırasının **Vulkan** önceliğine alınmasıdır; yapıldı:

```
Project Settings > Player > Other Settings > Graphics APIs
    Vulkan          ← önce bu denenir
    OpenGLCore      ← Vulkan başlatılamazsa yedek
```

**Bu ayarın etkili olması için Unity'nin yeniden başlatılması gerekir.** Yeniden
açtıktan sonra `Help > About Unity` başlığında `<Vulkan>` yazmalı (eskiden
`<OpenGL 4.5>` yazıyordu). Bu makinede Vulkan doğrulandı: ayrık
`NVIDIA GeForce RTX 4050 Laptop GPU` görünüyor, yani hem hata düzelir hem de
render entegre Intel yerine ayrık kartta çalışabilir.

Tek seferlik denemek isterseniz Unity'yi `-force-vulkan` argümanıyla da açabilirsiniz.

---

## 8. Hedef sayısını değiştirmek

`SimManager > ParkurManager > Hedef sayilari` başlığı altında:

| Alan | Varsayılan | Şartname |
|---|---|---|
| `Asama2 Target Count` | 9 | 3 (her kolda bir) |
| `Asama3 Target Count` | 10 | 3 |
| `Asama3 Enemy Count` | 3 | 1 |
| `Random Start Positions` | açık | — |

Hedefler kollara sırayla dağıtılır; aynı koldakiler halkaya eşit aralıklarla
yerleşir ve rastgele mod bu aralığın içinde oynatır — böylece konumlar her
turda değişir ama hedefler üst üste binmez (ölçülen en küçük aralık ~7 m).

Şartname değerlerine dönmek için 3 / 3 / 1 yazın; puanlama o değerlerde
şartname tablolarını birebir üretir.

Aşama-1'in yerleşimi `Asama-1 yerlesimi` başlığı altındadır:

| Alan | Varsayılan | Ne yapar |
|---|---|---|
| `Static On Lanes` | açık | Hedefleri ray güzergâhının üzerine oturtur |
| `Static Ranges` | 5 / 10 / 15 | Menzil bantları |
| `Static Min Separation` | 1.2 m | Aynı banttaki iki hedef arası en küçük mesafe |
| `Static Max Yaw` | 78° | Bu açının dışındaki ray noktaları kullanılmaz (ateş sektörü ±80°) |

### Maket boyutunu değiştirmek

`Assets/SteelDome/Prefabs/Hedef_*.prefab` → `Model` nesnesinin `Scale` alanı.
Şu an **1.5**; şartname ölçeğine dönmek için 1 yazın.

> Büyütürken dikkat: maketin **alt kenarı balonun üstünü (y = 1.29) geçmemeli**.
> Geçerse maket balonu gölgeler ve balonu vurmak imkânsız hale gelir — imha
> yalnızca balondan sayıldığı için aşama tıkanır. Balistik füze dik durduğu ve
> en uzun model olduğu için `Model` yüksekliği onda 1.58 yerine 1.715'e
> çıkarıldı; diğer üçü 1.58'de kaldı.
>
> **Balonu büyütmeyin.** Çapı 0.28 m ve Python menzili balonun piksel
> yüksekliğinden kestiriyor (`bridge.py` → `BALLOON_DIAMETER_M`); balon
> büyürse tüm menzil ölçümleri kayar.

> **Puanlama nasıl ölçekleniyor:** Aşama-2'nin tablosu (1 imha 5, 2 imha 15,
> 3 imha 30 puan) `30·k(k+1) / n(n+1)` formülünün özel hali. Hedef sayısı
> değişse de bir turun tam temizlenmesi yine 30 puan eder, yani aşama toplamı
> şartname aralığında kalır. Aşama-3 hedef başına puanladığı için düşman
> sayısını artırmak aşama puanını da artırır (şartname üst sınırı 160).
> Ceza tur başına 10 puanla sınırlı — birden çok dost vurmak cezayı katlamaz.

---

## 9. Parkuru değiştirmek

`Kollar` altındaki her `Kol-N` nesnesinin `LanePath` bileşeninde:

| Alan | Anlamı |
|---|---|
| `Near X` | Tarete bakan **dalgalı** koşunun yanal konumu |
| `Far X` | **Düz** dönüş koşusunun yanal konumu |
| `Near Z` / `Far Z` | Halkanın tarete yakın / uzak ucu |
| `Corner Radius` | Uç dönüşlerin yarıçapı |
| `Wave Amplitude` / `Wave Length` | Yılanlama genliği ve adımı |

Değeri değiştirince yol otomatik yeniden üretilir; Scene penceresinde turuncu
çizgi yaklaşma koşusunu, soluk gri çizgi dönüş koşusunu gösterir.

Hedef hızı ve kalkış gecikmesi `ParkurManager` üzerindedir
(`Target Speed`, `Stagger Seconds`). Senaryoyu tekrarlanabilir yapmak için
`Seed` alanına 0 dışında bir sayı verin.

> Görünür rayları da güncellemek isterseniz `Kol-N/Ray` altındaki küpler
> sahneye gömülüdür; `LanePath` değerlerini değiştirdikten sonra rayı elle
> yeniden üretmek gerekir (yol hesabı raydan bağımsız çalışır, sadece görsel
> uyumsuzluk olur).
