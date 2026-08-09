#!/usr/bin/env python3
"""
Celik Kubbe - ana kontrol dongusu.

Unity simulasyonuna baglanir, namlu kamerasindan kirmizi balonlari bulur,
balonun ustundeki maketin renginden dost/dusman ayrimini yapar ve dusman
balonuna kilitlenip ates eder.

Kullanim:
    python3 run.py                    # otonom takip + ates
    python3 run.py --no-fire          # sadece takip, ates etme
    python3 run.py --engage-unknown   # maketi secilemeyen balonlari da hedefle
    python3 run.py --no-window        # gorsel pencere olmadan
    python3 run.py --legacy-color     # eski renk-tabanli dedektor
"""

from __future__ import annotations

import argparse
import sys
import time

import cv2

from bridge import BridgeError, SteelDomeClient, estimate_range, pixel_to_angles
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
    return p.parse_args()


def main() -> int:
    args = parse_args()

    legacy = args.legacy_color
    if legacy:
        detector = ColorTargetDetector(
            colors=[args.color] if args.color else None,
            min_area=max(args.min_area, 120),
        )
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

            fire = False

            if legacy:
                detections = detector.detect(frame)
                target = pick_target(detections, frame.shape, prefer_color=args.color)
                key = target.color if target else None
            else:
                detections = detector.detect(frame)
                target = pick_engagement(detections, frame.shape,
                                         engage_unknown=args.engage_unknown)
                # Hedef kimligi olarak konumu kabaca kullanmak yeterli; amaci
                # hedef degistiginde PID birikimini sifirlatmak.
                key = f"{int(target.cx) // 24},{int(target.cy) // 24}" if target else None

            target_range = float("inf")
            if target is not None:
                yaw_error, pitch_error = pixel_to_angles(target.cx, target.cy, telemetry)
                yaw_cmd, pitch_cmd = tracker.update(yaw_error, pitch_error, dt, target_key=key)

                if not legacy:
                    target_range = estimate_range(target.bbox[3], telemetry)

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
                cv2.imshow("Celik Kubbe - Namlu Kamerasi", view)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break

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
            cv2.destroyAllWindows()
        print("Baglanti kapatildi, taret durduruldu.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
