#!/usr/bin/env python3
"""
Celik Kubbe - ana kontrol dongusu.

Unity simulasyonuna baglanir, namlu kamerasindan kirmizi balonlari bulur,
balonun ustundeki maketin renginden dost/dusman ayrimini yapar ve dusman
balonuna kilitlenip ates eder.

Kullanim:
    python3 run.py                    # otonom takip + ates (HSV dedektoru)
    python3 run.py --no-fire          # sadece takip, ates etme
    python3 run.py --engage-unknown   # maketi secilemeyen balonlari da hedefle
    python3 run.py --no-window        # gorsel pencere olmadan
    python3 run.py --legacy-color     # eski renk-tabanli dedektor

    # YOLO dedektoru:
    python3 run.py --yolo --weights best.pt
    python3 run.py --yolo --weights best.engine --yolo-track     # iz + sinif oylamasi
    python3 run.py --yolo --weights best.pt --yolo-sahi          # kucuk hedef icin dilimli
"""

from __future__ import annotations

import argparse
import sys
import time

import cv2

from bridge import (
    BALLOON_DIAMETER_M,
    BridgeError,
    SteelDomeClient,
    estimate_range,
    kamera_modeli,
    pixel_to_angles,
)
from tracker import (
    BalloonTargetDetector,
    ColorTargetDetector,
    TurretTracker,
    draw_engagements,
    draw_overlay,
    pick_engagement,
    pick_target,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Celik Kubbe otonom takip dongusu")
    p.add_argument("--host", default="127.0.0.1", help="Unity sunucu adresi")
    p.add_argument("--port", type=int, default=8765, help="Unity sunucu portu")
    p.add_argument("--no-window", action="store_true", help="Teshis penceresini acma")
    p.add_argument("--no-fire", action="store_true", help="Kilitlense de ates etme")
    p.add_argument("--engage-unknown", action="store_true",
                   help="Maket rengi okunamayan balonlari da dusman say")
    p.add_argument("--min-area", type=int, default=25,
                   help="En kucuk gecerli balon alani (piksel)")
    p.add_argument("--fire-interval", type=float, default=0.6,
                   help="Ayni hedefe iki atis arasi minimum sure (sn)")
    p.add_argument("--min-range", type=float, default=5.0,
                   help="Bu menzilden yakin hedefe ates etme (m). Sartname: helikopter "
                        "ve balistik fuze icin 5 m alti imha puan getirmez.")
    p.add_argument("--max-range", type=float, default=15.0,
                   help="Bu menzilden uzak hedefe ates etme (m)")
    p.add_argument("--legacy-color", action="store_true",
                   help="Balon/maket yerine eski duz renk dedektorunu kullan")
    p.add_argument("--color", default=None, choices=["red", "green", "blue", "yellow"],
                   help="--legacy-color ile: sadece bu rengi takip et")

    y = p.add_argument_group("YOLO dedektoru")
    y.add_argument("--yolo", action="store_true",
                   help="HSV yerine YOLO dedektorunu kullan (--weights sart)")
    y.add_argument("--weights", default=None, help="YOLO model yolu (.pt / .engine)")
    y.add_argument("--yolo-conf", type=float, default=0.25,
                   help="Guven esigi. Iz takibi acikken dusuk tutulabilir")
    y.add_argument("--yolo-iou", type=float, default=0.7, help="NMS IoU esigi")
    y.add_argument("--yolo-imgsz", type=int, default=640,
                   help="Cikarim cozunurlugu (egitimle ayni olmali)")
    y.add_argument("--yolo-device", default="", help="Cihaz: '', 'cpu', '0'")
    y.add_argument("--yolo-track", action="store_true",
                   help="ByteTrack izleri + iz bazli taraf oylamasi (dost atesine karsi)")
    y.add_argument("--yolo-tracker", default="bytetrack.yaml",
                   help="Takipci yapilandirmasi (ornegin ../Object_detection/cfg/"
                        "tracker_gimbal.yaml)")
    y.add_argument("--yolo-vote-frames", type=int, default=3,
                   help="--yolo-track ile: taraf kararina guvenmek icin gereken kare")
    y.add_argument("--yolo-sahi", action="store_true",
                   help="SAHI dilimli cikarim - uzak/kucuk hedefte tespiti artirir, "
                        "kare hizini dusurur")
    y.add_argument("--slice-size", type=int, default=512, help="SAHI dilim boyutu (piksel)")
    y.add_argument("--overlap-ratio", type=float, default=0.2, help="SAHI ortusme orani")
    y.add_argument("--no-hsv-fallback", action="store_true",
                   help="Model balonu bulamadiginda HSV balon dedektorune dusme")
    y.add_argument("--no-crop-classify", action="store_true",
                   help="Tipi belirlenemeyen hedefin ustundeki bolgeyi kirpip modele "
                        "yeniden sorma (varsayilan: sorar)")
    y.add_argument("--crop-conf", type=float, default=0.05,
                   help="Kirpma ile siniflandirmada guven esigi. Tam karedekinden "
                        "dusuk tutulur: bolge buyutuldugu icin tespit zaten kolaylasir")
    y.add_argument("--balloon-classes", default=None,
                   help="Balon sinif adlari (virgulle ayrilmis)")
    y.add_argument("--enemy-classes", default=None,
                   help="Dusman maket sinif adlari (virgulle ayrilmis)")
    y.add_argument("--friend-classes", default=None,
                   help="Dost maket sinif adlari (virgulle ayrilmis)")
    y.add_argument("--type-classes", default=None,
                   help="Yalnizca hedef tipi veren sinif adlari (drone, helicopter, "
                        "plane, rocket ...). Bunlarda taraf ayrimini maket rengi yapar")
    y.add_argument("--maket-size", type=float, default=0.50,
                   help="Balon bulunamayip maketin kendisine nisan alindiginda menzil "
                        "kestiriminde kullanilacak maket boyu (m)")

    k = p.add_argument_group("kamera")
    k.add_argument("--vinyet-telafi", type=float, default=0.0, metavar="GUC",
                   help="Kameranin kenar kararmasini geri al. Unity'deki "
                        "KameraGercekcilik.vinyet degeriyle ayni verilmeli (varsayilan "
                        "profil 0.26). 0 = kapali. Renk esikleri kadrajin kenarindaki "
                        "hedefte kayiyorsa acin.")

    args = p.parse_args()
    if args.yolo and args.legacy_color:
        p.error("--yolo ile --legacy-color birlikte kullanilamaz.")
    if args.yolo and not args.weights:
        p.error("--yolo icin --weights vermelisiniz.")
    return args


def _class_list(value, default):
    """Virgulle ayrilmis sinif adi listesini ayristirir; bos ise varsayilan kalir."""
    if not value:
        return default
    return tuple(part.strip() for part in value.split(",") if part.strip())


def build_yolo_detector(args: argparse.Namespace):
    """
    YOLO dedektorunu kurar.

    Import burada yapiliyor: ultralytics yuklemesi birkac saniye suruyor, HSV
    moduyla calisanlar bunu odemesin.
    """
    from yolo_detector import (
        BALLOON_NAMES,
        ENEMY_NAMES,
        FRIEND_NAMES,
        TYPE_NAMES,
        YoloTargetDetector,
    )

    # Model balonu kacirdiginda nisan noktasi ve menzil kaybolmasin diye HSV
    # dedektoru yedekte durur - balon dairesel ve emissive oldugu icin renk
    # esikleme burada hala guvenilir.
    fallback = None if args.no_hsv_fallback else BalloonTargetDetector(min_area=args.min_area)

    return YoloTargetDetector(
        weights=args.weights,
        conf=args.yolo_conf,
        iou=args.yolo_iou,
        imgsz=args.yolo_imgsz,
        device=args.yolo_device,
        balloon_classes=_class_list(args.balloon_classes, BALLOON_NAMES),
        enemy_classes=_class_list(args.enemy_classes, ENEMY_NAMES),
        friend_classes=_class_list(args.friend_classes, FRIEND_NAMES),
        type_classes=_class_list(args.type_classes, TYPE_NAMES),
        use_sahi=args.yolo_sahi,
        slice_size=args.slice_size,
        overlap_ratio=args.overlap_ratio,
        use_track=args.yolo_track,
        tracker_cfg=args.yolo_tracker,
        vote_frames=args.yolo_vote_frames,
        fallback=fallback,
        crop_classify=not args.no_crop_classify,
        crop_conf=args.crop_conf,
        maket_size_m=args.maket_size,
    )


def main() -> int:
    args = parse_args()

    legacy = args.legacy_color
    if legacy:
        detector = ColorTargetDetector(
            colors=[args.color] if args.color else None,
            min_area=max(args.min_area, 120),
        )
    elif args.yolo:
        detector = build_yolo_detector(args)
    else:
        detector = BalloonTargetDetector(min_area=args.min_area)
    tracker = TurretTracker()

    print(f"Unity'ye baglaniliyor: {args.host}:{args.port} ...")
    try:
        client = SteelDomeClient(args.host, args.port).connect()
    except OSError as e:
        print(f"Baglanti kurulamadi: {e}", file=sys.stderr)
        print("Unity'de SteelDomeSim sahnesi Play modunda mi?", file=sys.stderr)
        return 1

    print("Baglanti kuruldu. Cikmak icin Ctrl+C (pencere aciksa Q).")

    last_time = time.monotonic()
    last_fire = 0.0
    fps = 0.0
    frame_count = 0
    fps_start = last_time

    try:
        for frame, telemetry in client.frames():
            now = time.monotonic()
            dt = now - last_time
            last_time = now

            # Vinyet telafisi dedektorden once yapilmali: HSV esikleri kadrajin
            # kenarinda kararan kirmizi balonu kacirabiliyor. Distorsiyon ise
            # burada duzeltilmez - tum kareyi remap etmek pahali, yalniz hedef
            # merkezini tasimak yeterli (pixel_to_angles bunu kendisi yapar).
            if args.vinyet_telafi > 0.0:
                frame = kamera_modeli(telemetry).vinyet_telafisi(frame, args.vinyet_telafi)

            fire = False

            if legacy:
                detections = detector.detect(frame)
                target = pick_target(detections, frame.shape, prefer_color=args.color)
                key = target.color if target else None
            else:
                detections = detector.detect(frame)
                target = pick_engagement(detections, frame.shape,
                                         engage_unknown=args.engage_unknown)
                # Iz kimligi varsa (YOLO + --yolo-track) onu kullan; yoksa konumu
                # kabaca kullanmak yeterli. Amac hedef degistiginde PID birikimini
                # sifirlatmak.
                if target is None:
                    key = None
                elif target.track_id is not None:
                    key = f"id{target.track_id}"
                else:
                    key = f"{int(target.cx) // 24},{int(target.cy) // 24}"

            target_range = float("inf")
            if target is not None:
                yaw_error, pitch_error = pixel_to_angles(target.cx, target.cy, telemetry)
                yaw_cmd, pitch_cmd = tracker.update(yaw_error, pitch_error, dt, target_key=key)

                if not legacy:
                    # Nisan noktasi balonsa capi bilinir; maketin kendisine nisan
                    # alindiysa dedektor tahmini boyu size_m ile bildirir.
                    target_range = estimate_range(
                        target.bbox[3], telemetry,
                        target.size_m if target.size_m is not None else BALLOON_DIAMETER_M,
                    )

                # Ates yalnizca kilitliyken ve gecerli menzil penceresindeyken;
                # nisan hatasi buyukken atesleme yandaki dost hedefi vurabilir,
                # menzil disi imha ise sartnameye gore puan getirmez.
                in_window = args.min_range <= target_range <= args.max_range
                if (not args.no_fire and tracker.locked and (legacy or in_window)
                        and now - last_fire >= args.fire_interval):
                    fire = True
                    last_fire = now
            else:
                yaw_cmd, pitch_cmd = tracker.search(telemetry.yaw, telemetry.pitch)

            client.send_rate(yaw_cmd, pitch_cmd, fire=fire)

            frame_count += 1
            if now - fps_start >= 1.0:
                fps = frame_count / (now - fps_start)
                frame_count, fps_start = 0, now

            if not args.no_window:
                if legacy:
                    view = draw_overlay(frame, detections, target, tracker, telemetry, fps)
                else:
                    view = draw_engagements(frame, detections, target, tracker,
                                            telemetry, fps, fire_ready=fire,
                                            target_range=target_range)
                try:
                    cv2.imshow("Celik Kubbe - Namlu Kamerasi", view)
                    if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                        break
                except cv2.error as e:
                    # Basssiz makine ya da GUI'siz opencv kurulumu: takip ve ates
                    # calismaya devam etsin, yalnizca pencere kapansin.
                    print(f"[UYARI] Pencere acilamadi, gorsel cikis kapatiliyor: {e}",
                          file=sys.stderr)
                    args.no_window = True

    except KeyboardInterrupt:
        print("\nKullanici tarafindan durduruldu.")
    except BridgeError as e:
        print(f"Koprü hatasi: {e}", file=sys.stderr)
        return 1
    finally:
        try:
            client.stop()
        except Exception:
            pass
        client.close()
        if not args.no_window:
            # Kapanis, asil hatayi maskelemesin.
            try:
                cv2.destroyAllWindows()
            except cv2.error:
                pass
        print("Baglanti kapatildi, taret durduruldu.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
