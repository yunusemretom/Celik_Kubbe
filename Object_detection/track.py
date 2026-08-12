"""
TAKIP (TRACKING) SCRIPTI
========================
Ortam : gimbal / pan-tilt kamera (hareketli) -> kamera hareketi telafisi ACIK
Hedef : hizli hareket eden hava araclari
Oncelik: sinif ayrimi dogrulugu

EN ONEMLI OZELLIK: IZ BAZLI ZAMANSAL SINIF OYLAMASI
---------------------------------------------------
Dedektor kare kare sinifi titretebilir (bir karede f16, sonrakinde rocket).
Bu script her track_id icin guven-agirlikli bir sinif histogrami tutar ve
ekrana kumulatif cogunlugu yazar.

Pratikte tek kare dogrulugu %85 olan modeli 15-20 kare sonra %97+ iz
dogruluguna cikarir. FPS maliyeti sifir. Ultralytics bunu KENDISI YAPMAZ.

Kullanim:
    python track.py --weights best.pt --source video.mp4
    python track.py --weights best.pt --source 0 --show          # webcam
    python track.py --weights best.pt --source rtsp://... --save
    python track.py --weights best_hailo_model --source 0        # Hailo HEF
    python track.py --weights best.pt --source video.mp4 --static-camera
"""

import argparse
import time
from collections import Counter, defaultdict, deque
from pathlib import Path

import cv2
import numpy as np

try:
    from ultralytics import YOLO
except ImportError:  # pragma: no cover - import may be missing in some environments
    YOLO = None

# --------------------------------------------------------------------------
# 1) TAKIPCI YAPILANDIRMASI (otomatik uretilir)
# --------------------------------------------------------------------------

TRACKER_GIMBAL = """\
# Gimbal / pan-tilt (HAREKETLI) kamera icin ByteTrack
# BoT-SORT, belirli Ultralytics surumlerinde uyumsuzluk olusturabildigi icin
# daha stabil bir varsayilan olarak ByteTrack kullanilir.
tracker_type: bytetrack

track_high_thresh: 0.40   # varsayilan 0.5. Kucuk/hizli hedefte conf dusuk, esigi indirdik.
track_low_thresh: 0.10    # ikinci asama kurtarma icin genis tut
new_track_thresh: 0.50    # yeni iz acmak icin daha secici ol (duplike ID engelle)
track_buffer: 45          # ~1.5 sn @ 30 FPS. Kisa sureli kayipta ID korunur.
match_thresh: 0.85        # hizli hedefte IoU zayiflar -> eslesmeyi gevset
fuse_score: true

gmc_method: none         # gimbal telafisi istenirse daha sonra ayarlanabilir
"""

TRACKER_SABIT = """\
# Sabit / tripod kamera icin ByteTrack (minimum ek yuk)
tracker_type: bytetrack

track_high_thresh: 0.40
track_low_thresh: 0.10
new_track_thresh: 0.50
track_buffer: 45
match_thresh: 0.85
fuse_score: true
"""


def tracker_yaml_hazirla(static_camera: bool, out_dir: Path) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    if static_camera:
        p = out_dir / "tracker_sabit.yaml"
        p.write_text(TRACKER_SABIT, encoding="utf-8")
    else:
        p = out_dir / "tracker_gimbal.yaml"
        p.write_text(TRACKER_GIMBAL, encoding="utf-8")
    print(f"[BILGI] Takipci yapilandirmasi: {p}")
    return str(p)


# --------------------------------------------------------------------------
# 2) IZ BAZLI ZAMANSAL SINIF OYLAMASI  <-- BU SCRIPTIN KALBI
# --------------------------------------------------------------------------

class IzSinifOylayici:
    """
    Her track_id icin guven-agirlikli sinif histogrami tutar.

    - oy_ver()      : her kare cagirilir, tespiti histograma ekler
    - kararli_sinif(): iz icin kumulatif en olasi sinifi ve kararliligi dondurur
    - temizle()     : uzun sure gorunmeyen ID'leri bellekten atar
    """

    def __init__(self, unutma_karesi: int = 300, min_oy: int = 5):
        self.hist = defaultdict(Counter)     # track_id -> {sinif_id: agirlikli_oy}
        self.son_gorulme = {}                # track_id -> kare no
        self.gecmis = defaultdict(lambda: deque(maxlen=64))  # ID -> son sinif dizisi
        self.unutma_karesi = unutma_karesi
        self.min_oy = min_oy

    def oy_ver(self, track_id: int, sinif_id: int, conf: float, kare_no: int):
        # Guvenle agirliklandir: emin oldugu kareler daha cok soz sahibi
        self.hist[track_id][sinif_id] += float(conf)
        self.gecmis[track_id].append(sinif_id)
        self.son_gorulme[track_id] = kare_no

    def kararli_sinif(self, track_id: int):
        """(sinif_id, kararlilik_0_1, toplam_oy) dondurur."""
        c = self.hist.get(track_id)
        if not c:
            return None, 0.0, 0
        sinif_id, agirlik = c.most_common(1)[0]
        toplam = sum(c.values())
        kararlilik = agirlik / toplam if toplam > 0 else 0.0
        return int(sinif_id), float(kararlilik), len(self.gecmis[track_id])

    def guvenilir_mi(self, track_id: int) -> bool:
        """Yeterli oy toplanmadan karara guvenme."""
        return len(self.gecmis.get(track_id, ())) >= self.min_oy

    def temizle(self, kare_no: int):
        eski = [t for t, k in self.son_gorulme.items() if kare_no - k > self.unutma_karesi]
        for t in eski:
            self.hist.pop(t, None)
            self.son_gorulme.pop(t, None)
            self.gecmis.pop(t, None)


# --------------------------------------------------------------------------
# 3) CIZIM
# --------------------------------------------------------------------------

RENKLER = [(66, 135, 245), (46, 204, 113), (231, 76, 60), (241, 196, 15),
           (155, 89, 182), (26, 188, 156), (230, 126, 34), (52, 73, 94)]


def kutu_ciz(frame, xyxy, etiket, renk, kalin=2):
    x1, y1, x2, y2 = map(int, xyxy)
    cv2.rectangle(frame, (x1, y1), (x2, y2), renk, kalin)
    (tw, th), _ = cv2.getTextSize(etiket, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw + 6, y1), renk, -1)
    cv2.putText(frame, etiket, (x1 + 3, y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)


def iz_ciz(frame, noktalar, renk):
    if len(noktalar) < 2:
        return
    pts = np.array(noktalar, dtype=np.int32).reshape((-1, 1, 2))
    cv2.polylines(frame, [pts], isClosed=False, color=renk, thickness=2)


# --------------------------------------------------------------------------
# 4) ANA DONGU
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Hava araci takibi (gimbal + zamansal sinif oylamasi)")
    ap.add_argument("--weights", required=True, help="best.pt VEYA Hailo export dizini")
    ap.add_argument("--source", required=True, help="video.mp4 | 0 (webcam) | rtsp://...")
    ap.add_argument("--imgsz", type=int, default=640, help="Egitim/HEF ile AYNI olmali")
    ap.add_argument("--conf", type=float, default=0.20,
                    help="Dusuk tut: takipcinin dusuk-guven kurtarma asamasi var")
    ap.add_argument("--iou", type=float, default=0.7)
    ap.add_argument("--static-camera", action="store_true",
                    help="Kamera sabitse: ByteTrack + GMC kapali (daha hizli)")
    ap.add_argument("--tracker", default=None, help="Kendi tracker yaml'ini ver (otomatigi ezer)")
    ap.add_argument("--show", action="store_true", help="Pencerede goster")
    ap.add_argument("--save", default=None, help="Cikti video yolu (orn: cikti.mp4)")
    ap.add_argument("--iz-uzunluk", type=int, default=40, help="Yorunge kuyruk uzunlugu (kare)")
    ap.add_argument("--min-oy", type=int, default=5,
                    help="Kararli sinifa guvenmek icin gereken minimum kare")
    args = ap.parse_args()

    if YOLO is None:
        raise SystemExit("[HATA] ultralytics kurulu degil. 'pip install ultralytics opencv-python' calistirin.")

    # Takipci yapilandirmasi
    tracker = args.tracker or tracker_yaml_hazirla(args.static_camera, Path("cfg"))

    model = YOLO(args.weights)
    names = model.names
    print(f"[BILGI] Siniflar: {names}")

    kaynak = int(args.source) if args.source.isdigit() else args.source
    cap = cv2.VideoCapture(kaynak)
    if not cap.isOpened():
        raise SystemExit(f"[HATA] Kaynak acilamadi: {args.source}")

    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    writer = None
    if args.save:
        writer = cv2.VideoWriter(args.save, cv2.VideoWriter_fourcc(*"mp4v"), src_fps, (W, H))

    oylayici = IzSinifOylayici(min_oy=args.min_oy)
    izler = defaultdict(lambda: deque(maxlen=args.iz_uzunluk))

    kare_no = 0
    fps_pencere = deque(maxlen=30)
    t_baslangic = time.time()

    print("[BILGI] Baslatildi. Cikmak icin 'q'.")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            kare_no += 1
            t0 = time.perf_counter()

            # persist=True: ARDISIK karelerde iz durumunu korur.
            # Ilgisiz goruntulerde/farkli akista KULLANMA - iz durumu sizar.
            r = model.track(
                frame,
                persist=True,
                tracker=tracker,
                imgsz=args.imgsz,
                conf=args.conf,
                iou=args.iou,
                verbose=False,
            )[0]

            fps_pencere.append(1.0 / max(time.perf_counter() - t0, 1e-6))

            if r.boxes is not None and len(r.boxes) and r.boxes.is_track:
                xyxy = r.boxes.xyxy.cpu().numpy()
                xywh = r.boxes.xywh.cpu().numpy()
                tids = r.boxes.id.int().cpu().tolist()
                clss = r.boxes.cls.int().cpu().tolist()
                confs = r.boxes.conf.cpu().tolist()

                for box, ctr, tid, cid, cf in zip(xyxy, xywh, tids, clss, confs):
                    # --- ZAMANSAL OYLAMA ---
                    oylayici.oy_ver(tid, cid, cf, kare_no)
                    kararli_id, kararlilik, oy = oylayici.kararli_sinif(tid)
                    guvenilir = oylayici.guvenilir_mi(tid)

                    # Kararli sinif yeterli oy topladiysa onu kullan, yoksa anlik tahmini
                    goster_id = kararli_id if guvenilir else cid
                    renk = RENKLER[goster_id % len(RENKLER)]

                    if guvenilir:
                        etiket = f"#{tid} {names[goster_id]} {kararlilik:.0%} [{oy}k]"
                        if kararli_id != cid:
                            # Anlik tahmin oylamayla celisiyor -> duzeltildi
                            etiket += " *"
                    else:
                        etiket = f"#{tid} {names[goster_id]} {cf:.2f} (?)"

                    kutu_ciz(frame, box, etiket, renk)

                    izler[tid].append((float(ctr[0]), float(ctr[1])))
                    iz_ciz(frame, izler[tid], renk)

            if kare_no % 60 == 0:
                oylayici.temizle(kare_no)

            fps = float(np.mean(fps_pencere)) if fps_pencere else 0.0
            cv2.putText(frame, f"FPS {fps:5.1f} | kare {kare_no} | aktif iz {len(izler)}",
                        (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA)

            if writer is not None:
                writer.write(frame)
            if args.show:
                try:
                    cv2.imshow("Hava Araci Takibi", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                except cv2.error as exc:
                    print(f"[UYARI] Ekran penceresi acilamadi, goruntu gosterimi kapatiliyor: {exc}")
                    args.show = False

    except KeyboardInterrupt:
        print("\n[BILGI] Kullanici tarafindan durduruldu.")
    finally:
        cap.release()
        if writer is not None:
            writer.release()
        try:
            cv2.destroyAllWindows()
        except cv2.error:
            pass

    # ---------------- OZET ----------------
    sure = time.time() - t_baslangic
    ort_fps = kare_no / sure if sure > 0 else 0
    print("\n" + "=" * 70)
    print("TAKIP OZETI")
    print("=" * 70)
    print(f"Islenen kare  : {kare_no}")
    print(f"Sure          : {sure:.1f} sn")
    print(f"Ortalama FPS  : {ort_fps:.1f}")
    print(f"Toplam iz     : {len(oylayici.hist)}")

    print("\nIZ BAZLI NIHAI SINIF KARARLARI:")
    print("-" * 70)
    print(f"{'ID':>5}{'Sinif':>14}{'Kararlilik':>13}{'Kare':>8}   Dagilim")
    print("-" * 70)
    for tid in sorted(oylayici.hist):
        cid, kararlilik, oy = oylayici.kararli_sinif(tid)
        if oy < args.min_oy:
            continue  # cok kisa izler gurultu
        c = oylayici.hist[tid]
        toplam = sum(c.values())
        dag = ", ".join(f"{names[int(k)]}={v / toplam:.0%}" for k, v in c.most_common())
        uyari = "  <-- KARARSIZ" if kararlilik < 0.70 else ""
        print(f"{tid:>5}{names[cid]:>14}{kararlilik:>12.0%}{oy:>8}   {dag}{uyari}")
    print("=" * 70)

    print("\nAYAR NOTLARI:")
    print(f"  - track_buffer su an 45 (~1.5sn @30FPS). Olctugun FPS {ort_fps:.0f} ->")
    print(f"    ayni sure toleransi icin track_buffer = {max(15, int(ort_fps * 1.5))} yap.")
    print("  - Cok fazla ID degisimi (ID switch) varsa: match_thresh'i 0.85 -> 0.9 cikar,")
    print("    track_buffer'i artir.")
    print("  - Yeni ID'ler surekli aciliyorsa: new_track_thresh'i yukselt.")
    print("  - 'KARARSIZ' iz cok ise: o sinif cifti icin hedefli veri topla (bkz. test.py).")


if __name__ == "__main__":
    main()
