#!/usr/bin/env python3
"""
YKI — Telemetri koprusu / simulatoru.

Iki kaynaktan telemetri uretip YKI backend'ine UDP/JSON olarak yollar:

  sim   Unity simulasyonuna baglanir (Similasyon_Kullanim/bridge.py), run.py'deki
        takip dongusunun aynisini calistirir ve gercek taret + hedef verisini
        yayinlar. Istege bagli olarak namlu kamerasini MJPEG ile de servis eder,
        boylece YKI'nin kamera penceresinde simulasyon goruntusu acilir.
  fake  Simulasyon yokken sinus dalgalariyla sahte veri uretir (eski davranis).

Kullanim:
    python3 telemetry_sim.py                          # auto: once Unity, olmazsa sahte
    python3 telemetry_sim.py 127.0.0.1 5001           # hedef ip/port (eski kullanim)
    python3 telemetry_sim.py --mode sim               # yalnizca Unity
    python3 telemetry_sim.py --mode fake              # yalnizca sahte veri
    python3 telemetry_sim.py --mode sim --no-fire     # takip et, ates etme
    python3 telemetry_sim.py --mode sim --passive     # tarete komut gonderme, sadece izle
    python3 telemetry_sim.py --mode sim --mjpeg-port 8090   # kamerayi da YKI'ya ver
    python3 telemetry_sim.py --mode sim --yolo --weights best.pt

YKI tarafi:
    Ayarlar > RPi5 > Telemetri UDP portu  ->  buradaki --port ile ayni olmali (5001)
    Ayarlar > Kamera > MJPEG HTTP Stream  ->  http://127.0.0.1:8090/stream
"""

from __future__ import annotations

import argparse
import json
import math
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

#: run.py, bridge.py ve tracker.py'nin bulundugu dizin.
SIM_DIR = Path(__file__).resolve().parent.parent / "Similasyon_Kullanım"

#: Taret namlusunun yerden yuksekligi (m) - hedef irtifasi bundan kestirilir.
TURRET_HEIGHT_M = 1.28

#: Sartname geregi sistem sabit bir mevzide duruyor; GPS mevzi konumudur.
DEFAULT_LAT = 39.925533
DEFAULT_LON = 32.866287

#: run.build_yolo_detector'in bekledigi ama burada CLI'ya acilmayan alanlar.
#: Degerler run.py'deki argparse varsayilanlariyla ayni.
YOLO_PASSTHROUGH_DEFAULTS = {
    "yolo_iou": 0.7,
    "yolo_vote_frames": 3,
    "balloon_classes": None,
    "enemy_classes": None,
    "friend_classes": None,
    "type_classes": None,
    "no_hsv_fallback": False,
    "no_crop_classify": False,
    "crop_conf": 0.05,
    "maket_size": 0.50,
}


# ---------------------------------------------------------------- yayinci


def _clean(obj):
    """
    JSON'a girmeden once inf/nan ve numpy skalerlerini temizler.

    Menzil hesabi hedef yokken inf donuyor; json.dumps bunu `Infinity` diye
    yaziyor ve tarayicidaki JSON.parse patliyor - bu yuzden None'a ceviriyoruz.
    """
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, bool) or obj is None or isinstance(obj, (str, int)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if hasattr(obj, "item"):  # numpy skaleri
        return _clean(obj.item())
    return obj


class YkiPublisher:
    """Telemetriyi YKI backend'ine UDP/JSON olarak yollar, hizi sinirlar."""

    def __init__(self, host: str, port: int, rate_hz: float = 10.0):
        self.addr = (host, port)
        self.min_interval = 1.0 / rate_hz if rate_hz > 0 else 0.0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.seq = 0
        self._last_sent = 0.0

    def send(self, payload: dict, force: bool = False) -> bool:
        """Paketi yollar. Hiz sinirina takilirsa False doner."""
        now = time.monotonic()
        if not force and now - self._last_sent < self.min_interval:
            return False
        self._last_sent = now

        data = dict(payload)
        data["seq"] = self.seq
        data["timestamp"] = int(time.time() * 1000)
        self.sock.sendto(json.dumps(_clean(data)).encode(), self.addr)
        self.seq += 1
        return True

    def close(self) -> None:
        self.sock.close()


class Battery:
    """
    Batarya modeli.

    Simulasyonda batarya yok; YKI'nin batarya gostergesi bos kalmasin diye
    calisma suresine ve atis sayisina bagli dogrusal bir tuketim uretiyoruz.
    """

    def __init__(self, start: float = 100.0, drain_per_s: float = 0.05,
                 drain_per_shot: float = 0.15):
        self.start = start
        self.drain_per_s = drain_per_s
        self.drain_per_shot = drain_per_shot
        self.shots = 0

    def level(self, elapsed_s: float) -> float:
        used = elapsed_s * self.drain_per_s + self.shots * self.drain_per_shot
        return max(0.0, self.start - used)


def rssi_from_fps(fps: float, target_fps: float = 30.0) -> float:
    """
    Kare hizini baglanti kalitesi gostergesine cevirir.

    Simulasyonda telsiz yok; kopru yavasladiginda (dusuk fps) YKI'de de sinyalin
    zayifladigi gorulsun diye fps'i dBm olcegine tasiyoruz.
    """
    if fps <= 0:
        return -95.0
    q = max(0.0, min(1.0, fps / target_fps))
    return round(-95.0 + 55.0 * q, 1)


def target_altitude(range_m: float, pitch_deg: float):
    """Menzil ve namlu acisindan hedefin irtifasini kestirir (m)."""
    if range_m is None or not math.isfinite(range_m):
        return None
    return TURRET_HEIGHT_M + range_m * math.sin(math.radians(pitch_deg))


# ---------------------------------------------------------------- MJPEG


class FrameHub:
    """Son kareyi tutar, MJPEG istemcilerini yeni kare geldiginde uyandirir."""

    def __init__(self):
        self._cv = threading.Condition()
        self._jpeg = None
        self._seq = 0

    def publish(self, jpeg: bytes) -> None:
        with self._cv:
            self._jpeg = jpeg
            self._seq += 1
            self._cv.notify_all()

    def wait(self, last_seq: int, timeout: float = 2.0):
        """Yeni kare gelene kadar bekler; (jpeg, seq) doner."""
        with self._cv:
            if self._seq == last_seq:
                self._cv.wait(timeout)
            return self._jpeg, self._seq


class _MjpegHandler(BaseHTTPRequestHandler):
    hub: FrameHub = None  # alt sinifta baglanir
    protocol_version = "HTTP/1.0"

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler arayuzu
        if self.path.split("?")[0] not in ("/", "/stream", "/video", "/video.mjpg"):
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        # YKI kareyi <img> ile alip canvas'a ciziyor: crossOrigin="anonymous"
        # istegi CORS basligi olmadan canvas'i kirletir ve cizim engellenir.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
        self.end_headers()

        seq = -1
        try:
            while True:
                jpeg, seq = self.hub.wait(seq)
                if jpeg is None:
                    continue
                self.wfile.write(
                    b"--FRAME\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(jpeg)).encode()
                    + b"\r\n\r\n"
                )
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            return  # istemci sekmeyi kapatti

    def log_message(self, *args):  # sunucu logu konsol ciktisini bozmasin
        pass


def start_mjpeg_server(hub: FrameHub, port: int) -> ThreadingHTTPServer:
    handler = type("BoundMjpegHandler", (_MjpegHandler,), {"hub": hub})
    srv = ThreadingHTTPServer(("0.0.0.0", port), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ---------------------------------------------------------------- sahte kaynak


def run_fake(args, pub: YkiPublisher) -> int:
    """Simulasyon yokken sinus dalgalariyla telemetri uretir."""
    battery = Battery()
    t0 = time.time()
    period = 1.0 / args.rate if args.rate > 0 else 0.1

    print(f"Kaynak: SAHTE VERI  →  {args.host}:{args.port} ({args.rate:g} Hz)")
    print("Ctrl+C ile durdurun...\n")

    try:
        while True:
            t = time.time() - t0
            payload = {
                "source": "fake",
                "battery": battery.level(t),
                "altitude": 100 + 40 * math.sin(t / 15),
                "speed": 12 + 5 * math.cos(t / 10),
                "rssi": -55 - 15 * abs(math.sin(t / 8)),
                "pitch": 10 * math.sin(t / 5),
                "roll": 20 * math.sin(t / 7),
                "yaw": (t * 15) % 360,
                "heading": (t * 15) % 360,
                "mode": "TAKIP" if int(t / 15) % 2 == 0 else "ARAMA",
                "tracking": int(t / 15) % 2 == 0,
                "gps": {
                    "lat": args.lat + 0.0005 * math.sin(t / 20),
                    "lon": args.lon + 0.0005 * math.cos(t / 20),
                    "fix": True,
                    "satellites": 12,
                },
            }
            pub.send(payload, force=True)

            print(f"\rSeq:{pub.seq:5d} | Bat:{payload['battery']:.1f}% | "
                  f"Alt:{payload['altitude']:.1f}m | P:{payload['pitch']:.1f}° "
                  f"R:{payload['roll']:.1f}° H:{payload['heading']:.0f}° | "
                  f"Mod:{payload['mode']}", end="", flush=True)

            time.sleep(period)
    except KeyboardInterrupt:
        print(f"\n\nDurduruldu. Toplam {pub.seq} paket gonderildi.")
    return 0


# ---------------------------------------------------------------- simulasyon


def build_detector(args):
    """HSV ya da YOLO dedektorunu kurar; YOLO icin run.py'nin kurucusunu kullanir."""
    sys.path.insert(0, str(SIM_DIR))
    from tracker import BalloonTargetDetector

    if not args.yolo:
        return BalloonTargetDetector(min_area=args.min_area)

    import run  # ultralytics yuklemesi pahali, yalnizca gerekince

    merged = argparse.Namespace(**{**YOLO_PASSTHROUGH_DEFAULTS, **vars(args)})
    return run.build_yolo_detector(merged)


def run_sim(args, pub: YkiPublisher) -> int:
    """Unity'ye baglanir, run.py'nin takip dongusunu calistirip telemetri yayinlar."""
    sys.path.insert(0, str(SIM_DIR))
    try:
        import cv2
        from bridge import (
            BALLOON_DIAMETER_M,
            BridgeError,
            SteelDomeClient,
            estimate_range,
            pixel_to_angles,
        )
        from tracker import TurretTracker, draw_engagements, pick_engagement
    except ImportError as e:
        print(f"Simulasyon modulleri yuklenemedi ({e}).", file=sys.stderr)
        print(f"Beklenen dizin: {SIM_DIR}", file=sys.stderr)
        return 2

    detector = build_detector(args)
    tracker = TurretTracker()

    print(f"Unity'ye baglaniliyor: {args.sim_host}:{args.sim_port} ...")
    try:
        client = SteelDomeClient(args.sim_host, args.sim_port).connect()
    except OSError as e:
        print(f"Baglanti kurulamadi: {e}", file=sys.stderr)
        return 1

    hub = FrameHub()
    mjpeg_srv = None
    if args.mjpeg_port:
        mjpeg_srv = start_mjpeg_server(hub, args.mjpeg_port)

    # Kare uzerine bindirme yalnizca birine bakan varsa cizilir.
    draw_needed = bool(args.mjpeg_port) or args.window

    print(f"Kaynak: SIMULASYON  →  telemetri {args.host}:{args.port} "
          f"({args.rate:g} Hz)")
    if mjpeg_srv:
        print(f"Kamera : MJPEG      →  http://127.0.0.1:{args.mjpeg_port}/stream")
    if args.passive:
        print("Pasif mod: tarete komut gonderilmiyor.")
    print("Ctrl+C ile durdurun...\n")

    battery = Battery()
    t_wall = time.time()
    last_time = time.monotonic()
    last_fire = 0.0
    fps = 0.0
    frame_count = 0
    fps_start = last_time
    fired_this_frame = False

    try:
        for frame, telemetry in client.frames():
            now = time.monotonic()
            dt = now - last_time
            last_time = now
            fired_this_frame = False

            detections = detector.detect(frame)
            target = pick_engagement(detections, frame.shape,
                                     engage_unknown=args.engage_unknown)

            if target is None:
                key = None
            elif target.track_id is not None:
                key = f"id{target.track_id}"
            else:
                key = f"{int(target.cx) // 24},{int(target.cy) // 24}"

            target_range = float("inf")
            yaw_err = pitch_err = 0.0
            in_window = False

            if target is not None:
                yaw_err, pitch_err = pixel_to_angles(target.cx, target.cy, telemetry)
                yaw_cmd, pitch_cmd = tracker.update(yaw_err, pitch_err, dt, target_key=key)
                target_range = estimate_range(
                    target.bbox[3], telemetry,
                    target.size_m if target.size_m is not None else BALLOON_DIAMETER_M,
                )
                in_window = args.min_range <= target_range <= args.max_range

                if (not args.no_fire and not args.passive and tracker.locked
                        and in_window and now - last_fire >= args.fire_interval):
                    fired_this_frame = True
                    last_fire = now
                    battery.shots += 1
            else:
                yaw_cmd, pitch_cmd = tracker.search(telemetry.yaw, telemetry.pitch)

            if not args.passive:
                client.send_rate(yaw_cmd, pitch_cmd, fire=fired_this_frame)

            frame_count += 1
            if now - fps_start >= 1.0:
                fps = frame_count / (now - fps_start)
                frame_count, fps_start = 0, now

            # ── Telemetri paketi ────────────────────────────────────────
            slew = float(math.hypot(telemetry.yaw_rate, telemetry.pitch_rate))
            alt = target_altitude(target_range, telemetry.pitch)

            payload = {
                "source": "sim",
                # YKI grafiklerinin bekledigi alanlar
                "battery": battery.level(time.time() - t_wall),
                "altitude": alt,                 # hedefin kestirilen irtifasi (m)
                "speed": slew,                   # taret donus hizi (°/s)
                "rssi": rssi_from_fps(fps),      # fps'ten turetilen baglanti kalitesi
                # Ucus enstrumanlari: taret sabit govdede, yatis yok
                "pitch": float(telemetry.pitch),
                "roll": 0.0,
                "yaw": float(telemetry.yaw),
                "heading": float(telemetry.yaw) % 360.0,
                "mode": tracker.state.value,     # ARAMA | TAKIP | KILITLI
                "tracking": target is not None,
                "gps": {
                    "lat": args.lat, "lon": args.lon,
                    "fix": True, "satellites": 12,
                },
                # Simulasyona ozel ayrintilar
                "fps": round(fps, 1),
                "frame": telemetry.frame,
                "locked": tracker.locked,
                "fire": fired_this_frame,
                "shots": battery.shots,
                "detections": len(detections),
                "turret": {
                    "yaw": float(telemetry.yaw),
                    "pitch": float(telemetry.pitch),
                    "yaw_rate": float(telemetry.yaw_rate),
                    "pitch_rate": float(telemetry.pitch_rate),
                    "yaw_cmd": float(yaw_cmd),
                    "pitch_cmd": float(pitch_cmd),
                    "state": tracker.state.value,
                },
                "target": None if target is None else {
                    "label": target.label or None,
                    "faction": target.faction,
                    "track_id": target.track_id,
                    "range_m": float(target_range),
                    "in_range_window": in_window,
                    "yaw_error": float(yaw_err),
                    "pitch_error": float(pitch_err),
                    "cx": float(target.cx),
                    "cy": float(target.cy),
                    "score": float(target.score),
                },
            }
            # Atis anlik bir olay: hiz sinirina takilip kaybolmasin.
            pub.send(payload, force=fired_this_frame)

            # ── Gorsel cikis ────────────────────────────────────────────
            if draw_needed:
                view = draw_engagements(frame, detections, target, tracker,
                                        telemetry, fps, fire_ready=fired_this_frame,
                                        target_range=target_range)
                if args.mjpeg_port:
                    ok, buf = cv2.imencode(
                        ".jpg", view, [int(cv2.IMWRITE_JPEG_QUALITY), args.jpeg_quality]
                    )
                    if ok:
                        hub.publish(buf.tobytes())
                if args.window:
                    try:
                        cv2.imshow("YKI Kopru - Namlu Kamerasi", view)
                        if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                            break
                    except cv2.error as e:
                        print(f"\n[UYARI] Pencere acilamadi, kapatiliyor: {e}",
                              file=sys.stderr)
                        args.window = False
                        draw_needed = bool(args.mjpeg_port)

            rng = f"{target_range:5.1f}m" if math.isfinite(target_range) else "  --  "
            print(f"\rPkt:{pub.seq:5d} | {tracker.state.value:8s} | "
                  f"Y:{telemetry.yaw:6.1f}° P:{telemetry.pitch:5.1f}° | "
                  f"Hedef:{len(detections):2d} Menzil:{rng} | "
                  f"Atis:{battery.shots:3d} | {fps:4.1f} fps", end="", flush=True)

    except KeyboardInterrupt:
        print("\n\nKullanici tarafindan durduruldu.")
    except BridgeError as e:
        print(f"\nKopru hatasi: {e}", file=sys.stderr)
        return 1
    finally:
        try:
            if not args.passive:
                client.stop()
        except Exception:
            pass
        client.close()
        if mjpeg_srv:
            mjpeg_srv.shutdown()
        if args.window:
            try:
                import cv2 as _cv2
                _cv2.destroyAllWindows()
            except Exception:
                pass
        print(f"\nBaglanti kapatildi. {pub.seq} paket gonderildi, "
              f"{battery.shots} atis yapildi.")

    return 0


# ---------------------------------------------------------------- CLI


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Simulasyon telemetrisini YKI'ya tasiyan kopru",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("host", nargs="?", default="127.0.0.1",
                   help="YKI backend adresi (varsayilan 127.0.0.1)")
    p.add_argument("port", nargs="?", type=int, default=5001,
                   help="YKI telemetri UDP portu (varsayilan 5001)")
    p.add_argument("--mode", choices=["auto", "sim", "fake"], default="auto",
                   help="auto: once Unity denenir, baglanamazsa sahte veriye duser")
    p.add_argument("--rate", type=float, default=10.0,
                   help="Saniyedeki telemetri paketi (Hz)")
    p.add_argument("--lat", type=float, default=DEFAULT_LAT, help="Mevzi enlemi")
    p.add_argument("--lon", type=float, default=DEFAULT_LON, help="Mevzi boylami")

    s = p.add_argument_group("Simulasyon baglantisi")
    s.add_argument("--sim-host", default="127.0.0.1", help="Unity sunucu adresi")
    s.add_argument("--sim-port", type=int, default=8765, help="Unity sunucu portu")
    s.add_argument("--passive", action="store_true",
                   help="Tarete komut gonderme; yalnizca kareleri okuyup telemetri "
                        "yayinla (run.py ayri calisiyorken)")
    s.add_argument("--no-fire", action="store_true", help="Kilitlense de ates etme")
    s.add_argument("--engage-unknown", action="store_true",
                   help="Maket rengi okunamayan balonlari da dusman say")
    s.add_argument("--min-area", type=int, default=25, help="En kucuk balon alani (px)")
    s.add_argument("--fire-interval", type=float, default=0.6,
                   help="Ayni hedefe iki atis arasi minimum sure (sn)")
    s.add_argument("--min-range", type=float, default=5.0, help="Alt atis menzili (m)")
    s.add_argument("--max-range", type=float, default=15.0, help="Ust atis menzili (m)")

    v = p.add_argument_group("Goruntu")
    v.add_argument("--mjpeg-port", type=int, default=0,
                   help="Namlu kamerasini bu portta MJPEG olarak yayinla (0 = kapali)")
    v.add_argument("--jpeg-quality", type=int, default=70, help="MJPEG JPEG kalitesi")
    v.add_argument("--window", action="store_true", help="Yerel teshis penceresini ac")

    y = p.add_argument_group("YOLO dedektoru")
    y.add_argument("--yolo", action="store_true", help="HSV yerine YOLO kullan")
    y.add_argument("--weights", default=None, help="YOLO model yolu (.pt / .engine)")
    y.add_argument("--yolo-conf", type=float, default=0.25, help="Guven esigi")
    y.add_argument("--yolo-imgsz", type=int, default=640, help="Cikarim cozunurlugu")
    y.add_argument("--yolo-device", default="", help="Cihaz: '', 'cpu', '0'")
    y.add_argument("--yolo-track", action="store_true", help="ByteTrack izleri")
    y.add_argument("--yolo-tracker", default="bytetrack.yaml", help="Takipci yapilandirmasi")
    y.add_argument("--yolo-sahi", action="store_true", help="SAHI dilimli cikarim")
    y.add_argument("--slice-size", type=int, default=512, help="SAHI dilim boyutu")
    y.add_argument("--overlap-ratio", type=float, default=0.2, help="SAHI ortusme orani")

    args = p.parse_args()
    if args.yolo and not args.weights:
        p.error("--yolo icin --weights vermelisiniz.")
    if args.mode == "fake" and args.mjpeg_port:
        print("[UYARI] Sahte veri modunda kamera yok, --mjpeg-port yok sayiliyor.",
              file=sys.stderr)
        args.mjpeg_port = 0
    return args


def main() -> int:
    args = parse_args()
    pub = YkiPublisher(args.host, args.port, args.rate)

    print("YKI Telemetri Koprusu")
    try:
        if args.mode == "fake":
            return run_fake(args, pub)

        rc = run_sim(args, pub)
        if rc == 1 and args.mode == "auto":
            # Unity kapali: YKI'nin bos ekranla kalmamasi icin sahte veriye dus.
            print("Unity'ye baglanilamadi, sahte veriye duseliyor "
                  "(--mode sim ile bunu kapatabilirsiniz).\n")
            return run_fake(args, pub)
        return rc
    finally:
        pub.close()


if __name__ == "__main__":
    raise SystemExit(main())
