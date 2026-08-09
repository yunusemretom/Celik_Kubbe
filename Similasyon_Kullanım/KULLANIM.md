# Çelik Kubbe — Kullanım Kılavuzu

Bu dosya "nasıl çalıştırırım" sorusunun cevabı. Sistemin nasıl kurulduğu ve
neden öyle kurulduğu için `README.md`'ye bakın.

---

## 1. Tek seferlik hazırlık

```bash
pip install opencv-python numpy
```

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

Görev panelindeki **zarf sırası** satırı, hangi hedefi sırada vurmanız
gerektiğini sarı renkle gösterir. Sıra dışı bir hedefi vurursanız −5 ceza
alırsınız (şartname 6.1).

Puanlama menzile göre: 5 m → 5 puan, 10 m → 10 puan, 15 m → 20 puan.

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
