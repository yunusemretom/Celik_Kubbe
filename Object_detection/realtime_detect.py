"""
GERÇEK ZAMANLI NESNE TESPİTİ (SAHI DESTEKLİ)
=============================================
YOLOv8 + SAHI (Slicing Aided Hyper Inference) ile gerçek zamanlı tespit.

SAHI, büyük çözünürlüklü görüntüleri küçük dilimlere bölerek küçük nesnelerin
algılanma başarısını önemli ölçüde artırır.

Kullanım:
    python realtime_detect.py                           # Varsayılan (SAHI açık)
    python realtime_detect.py --no-sahi                 # SAHI'sız klasik tespit
    python realtime_detect.py --slice-size 512          # Dilim boyutunu ayarla
    python realtime_detect.py --source video.mp4        # Video dosyasından
    python realtime_detect.py --source rtsp://...       # RTSP akışından
"""

import argparse
import time
from collections import deque

import cv2
import numpy as np
from ultralytics import YOLO

try:
    from sahi import AutoDetectionModel
    from sahi.predict import get_sliced_prediction
    SAHI_AVAILABLE = True
except ImportError:
    SAHI_AVAILABLE = False
    print("[UYARI] sahi kurulu değil. 'pip install sahi' ile kurun. Klasik tespit kullanılacak.")


# --------------------------------------------------------------------------
# SAHI İLE TESPİT
# --------------------------------------------------------------------------

def sahi_detect(frame, detection_model, slice_height, slice_width,
                overlap_ratio, conf_thresh):
    """
    SAHI sliced prediction uygular.

    Görüntüyü belirtilen boyutta dilimlere böler, her dilimde ayrı çıkarım yapar
    ve sonuçları NMS ile birleştirir. Küçük nesneler için tespit oranını artırır.

    Args:
        frame: BGR numpy dizisi (OpenCV formatı)
        detection_model: SAHI AutoDetectionModel nesnesi
        slice_height: Dilim yüksekliği (piksel)
        slice_width: Dilim genişliği (piksel)
        overlap_ratio: Dilimler arası örtüşme oranı (0.0 - 1.0)
        conf_thresh: Güven eşiği

    Returns:
        list of dict: Her tespit için {bbox, score, class_id, class_name}
    """
    result = get_sliced_prediction(
        image=frame,
        detection_model=detection_model,
        slice_height=slice_height,
        slice_width=slice_width,
        overlap_height_ratio=overlap_ratio,
        overlap_width_ratio=overlap_ratio,
        postprocess_type="NMS",
        postprocess_match_metric="IOU",
        postprocess_match_threshold=0.5,
        postprocess_class_agnostic=False,
        verbose=0,
    )

    detections = []
    for pred in result.object_prediction_list:
        bbox = pred.bbox  # sahi BoundingBox nesnesi
        detections.append({
            "bbox": [bbox.minx, bbox.miny, bbox.maxx, bbox.maxy],
            "score": pred.score.value,
            "class_id": pred.category.id,
            "class_name": pred.category.name,
        })
    return detections


# --------------------------------------------------------------------------
# KLASİK TESPİT (SAHI'sız)
# --------------------------------------------------------------------------

def classic_detect(frame, model, conf_thresh):
    """
    Standart YOLO çıkarımı (tek geçiş, dilim yok).

    Args:
        frame: BGR numpy dizisi
        model: Ultralytics YOLO modeli
        conf_thresh: Güven eşiği

    Returns:
        list of dict: Her tespit için {bbox, score, class_id, class_name}
    """
    results = model(frame, conf=conf_thresh, verbose=False)
    detections = []
    r = results[0]
    if r.boxes is not None and len(r.boxes):
        xyxy = r.boxes.xyxy.cpu().numpy()
        confs = r.boxes.conf.cpu().tolist()
        clss = r.boxes.cls.int().cpu().tolist()
        names = r.names
        for box, cf, cid in zip(xyxy, confs, clss):
            detections.append({
                "bbox": [float(box[0]), float(box[1]), float(box[2]), float(box[3])],
                "score": cf,
                "class_id": cid,
                "class_name": names[cid],
            })
    return detections


# --------------------------------------------------------------------------
# ÇİZİM
# --------------------------------------------------------------------------

RENKLER = [
    (66, 135, 245), (46, 204, 113), (231, 76, 60), (241, 196, 15),
    (155, 89, 182), (26, 188, 156), (230, 126, 34), (52, 73, 94),
]


def kutu_ciz(frame, bbox, etiket, renk, kalinlik=2):
    """Bounding box ve etiketi frame üzerine çizer."""
    x1, y1, x2, y2 = map(int, bbox)
    cv2.rectangle(frame, (x1, y1), (x2, y2), renk, kalinlik)
    (tw, th), _ = cv2.getTextSize(etiket, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw + 6, y1), renk, -1)
    cv2.putText(frame, etiket, (x1 + 3, y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)


# --------------------------------------------------------------------------
# ANA FONKSİYON
# --------------------------------------------------------------------------

def run_realtime_detection(args):
    """
    SAHI destekli gerçek zamanlı nesne tespiti.

    SAHI aktifse görüntüyü dilimlere bölerek küçük nesneleri daha iyi tespit eder.
    SAHI kapalıysa standart tek geçişli YOLO çıkarımı kullanır.
    """
    use_sahi = args.sahi and SAHI_AVAILABLE

    print(f"[BİLGİ] Model yükleniyor: {args.weights}")
    model = YOLO(args.weights)

    # SAHI modeli hazırla
    detection_model = None
    if use_sahi:
        print(f"[BİLGİ] SAHI aktif — Dilim: {args.slice_size}x{args.slice_size}, "
              f"Örtüşme: {args.overlap_ratio:.0%}")
        detection_model = AutoDetectionModel.from_pretrained(
            model_type="yolov8",
            model_path=args.weights,
            confidence_threshold=args.conf,
            device=args.device,
        )
    else:
        if args.sahi and not SAHI_AVAILABLE:
            print("[UYARI] SAHI istendi ama kütüphane bulunamadı. Klasik tespit kullanılacak.")
        print("[BİLGİ] Klasik (SAHI'sız) tespit modu.")

    # Video kaynağını aç
    source = int(args.source) if args.source.isdigit() else args.source
    cap = cv2.VideoCapture(source)

    if not cap.isOpened():
        print(f"[HATA] Video kaynağı açılamadı: {args.source}")
        return

    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    # Kayıt
    writer = None
    if args.save:
        writer = cv2.VideoWriter(args.save, cv2.VideoWriter_fourcc(*"mp4v"), src_fps, (W, H))
        print(f"[BİLGİ] Çıktı kaydedilecek: {args.save}")

    kare_no = 0
    fps_pencere = deque(maxlen=30)
    t_baslangic = time.time()

    mode_str = f"SAHI ({args.slice_size}px)" if use_sahi else "Klasik"
    print(f"[BİLGİ] Gerçek zamanlı tespit başlatıldı [{mode_str}]. Çıkmak için 'q'.")

    try:
        while True:
            success, frame = cap.read()
            if not success:
                print("[BİLGİ] Video kaynağından kare okunamadı. Çıkılıyor...")
                break

            kare_no += 1
            t0 = time.perf_counter()

            # --- TESPİT ---
            if use_sahi:
                detections = sahi_detect(
                    frame=frame,
                    detection_model=detection_model,
                    slice_height=args.slice_size,
                    slice_width=args.slice_size,
                    overlap_ratio=args.overlap_ratio,
                    conf_thresh=args.conf,
                )
            else:
                detections = classic_detect(frame, model, args.conf)

            dt = time.perf_counter() - t0
            fps_pencere.append(1.0 / max(dt, 1e-6))

            # --- ÇİZİM ---
            for det in detections:
                cid = det["class_id"]
                renk = RENKLER[cid % len(RENKLER)]
                etiket = f"{det['class_name']} {det['score']:.2f}"
                kutu_ciz(frame, det["bbox"], etiket, renk)

            # OSD (On-Screen Display)
            fps = float(np.mean(fps_pencere)) if fps_pencere else 0.0
            osd = f"FPS {fps:5.1f} | kare {kare_no} | tespit {len(detections)} | {mode_str}"
            cv2.putText(frame, osd, (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)

            # Kaydet / göster
            if writer is not None:
                writer.write(frame)

            cv2.imshow("YOLO + SAHI Gerçek Zamanlı Tespit", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    except KeyboardInterrupt:
        print("\n[BİLGİ] Kullanıcı tarafından durduruldu.")
    finally:
        cap.release()
        if writer is not None:
            writer.release()
        cv2.destroyAllWindows()

    # --- ÖZET ---
    sure = time.time() - t_baslangic
    ort_fps = kare_no / sure if sure > 0 else 0
    print("\n" + "=" * 60)
    print("TESPİT ÖZETİ")
    print("=" * 60)
    print(f"  Mod           : {mode_str}")
    print(f"  İşlenen kare  : {kare_no}")
    print(f"  Süre          : {sure:.1f} sn")
    print(f"  Ortalama FPS  : {ort_fps:.1f}")
    if use_sahi:
        print(f"  Dilim boyutu  : {args.slice_size}x{args.slice_size} px")
        print(f"  Örtüşme oranı : {args.overlap_ratio:.0%}")
    print("=" * 60)


# --------------------------------------------------------------------------
# ARGPARSE
# --------------------------------------------------------------------------

def parse_args():
    ap = argparse.ArgumentParser(
        description="SAHI destekli gerçek zamanlı nesne tespiti (YOLOv8)"
    )
    ap.add_argument("--weights", default="/home/tom/Downloads/best (05.08).enginepytho",
                     help="YOLO model yolu (.pt veya .engine)")
    ap.add_argument("--source", default="0",
                     help="Video kaynağı: 0 (webcam), video.mp4, rtsp://...")
    ap.add_argument("--conf", type=float, default=0.5,
                     help="Güven eşiği")
    ap.add_argument("--device", default="",
                     help="Cihaz: '', 'cpu', '0' (GPU)")

    # SAHI parametreleri
    sahi_group = ap.add_argument_group("SAHI Parametreleri")
    sahi_group.add_argument("--no-sahi", dest="sahi", action="store_false",
                             help="SAHI'yi devre dışı bırak (klasik tespit)")
    sahi_group.add_argument("--slice-size", type=int, default=640,
                             help="Dilim boyutu (piksel). Küçük nesneler için 256-512 önerilir")
    sahi_group.add_argument("--overlap-ratio", type=float, default=0.2,
                             help="Dilimler arası örtüşme oranı (0.0-1.0)")

    # Kayıt
    ap.add_argument("--save", default=None,
                     help="Çıktı video yolu (ör: cikti.mp4)")

    return ap.parse_args()


if __name__ == "__main__":
    run_realtime_detection(parse_args())
