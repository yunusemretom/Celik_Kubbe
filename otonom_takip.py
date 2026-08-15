#!/usr/bin/env python3
"""
Celik Kubbe - kamera ile kirmizi hedef takibi + kumanda.

Aciklama:
    joyistik_control.py'nin kol okuma ve karta gonderme katmanini oldugu gibi
    kullanir; ustune bir kamera dongusu koyar. Kumandadaki Y tusu MANUEL ve
    OTONOM modlar arasinda gecis yapar:

      MANUEL : eksenler kumandadan surulur (joyistik_control ile ayni)
      OTONOM : kirmizi nesne bulunur ve GORUNTUNUN ORTASINA getirilir

    Goruntunun ortasina MAVI nisangah cizilir; otonom modun hedefi, bulunan
    nesneyi bu nisangaha oturtmaktir. Takip edilecek renk --renk ile
    degistirilebilir (or. --renk blue).

    Tespit ve kapali cevrim kontrol icin projede zaten bulunan siniflar
    kullanilir (Similasyon_Kullanim/tracker.py): ColorTargetDetector ve
    PID'li TurretTracker. Boylece simulasyondaki davranisla ayni kontrolcu
    gercek kamerada da calisir.

Kullanim:
    python3 otonom_takip.py                              # kamera 0, gonderim yok
    python3 otonom_takip.py --send --port /dev/ttyACM0   # USB kablo ile
    python3 otonom_takip.py --send --host 192.168.4.1    # WiFi/UDP ile
    python3 otonom_takip.py --kamera 2                   # baska kamera
    python3 otonom_takip.py --kamera test                # kamera yokken sahte hedef
    python3 otonom_takip.py --renk blue                  # mavi nesne takip et
    python3 otonom_takip.py --tara                       # hedef yokken yatayda supur

Tuslar:
    Y      : MANUEL <-> OTONOM
    RT     : atis motoru (her iki modda da calisir)
    B      : E-Stop  (otonom mod kapanir, eksenler durur)
    q / ESC: cikis
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from joyistik_control import (
    DEFAULT_RESET_DELAY_S,
    DEFAULT_SEND_HZ,
    DEFAULT_UDP_PORT,
    SERVO_RT_ESIK,
    SOURCE_AXES,
    ArduinoLink,
    HapticFeedback,
    UdpLink,
    XboxController,
    motor_orani,
)

#: tracker.py ve bridge.py'nin bulundugu dizin (telemetry_sim.py ile ayni yol).
SIM_DIR = Path(__file__).resolve().parent / "Similasyon_Kullanım"
if str(SIM_DIR) not in sys.path:
    sys.path.insert(0, str(SIM_DIR))

from tracker import (  # noqa: E402  (yol eklendikten sonra yuklenebilir)
    DRAW_COLORS,
    ColorTargetDetector,
    TrackState,
    TurretTracker,
)

#: Nisangah rengi (BGR). tracker.py'deki mavi ile ayni.
NISANGAH_RENGI = DRAW_COLORS["blue"]

#: Webcam'in dikey gorus acisi (derece). Piksel hatasini aci hatasina cevirmek
#: icin gerekir; kendi kameranizin degeriyle degistirin, yanlis olmasi takibi
#: bozmaz ama kazanci (dolayisiyla tepki hizini) degistirir.
VARSAYILAN_VFOV = 48.0

#: Otonom modda uretilen hiz komutunun carpani. Mekanik yavassa dusurun.
OTONOM_HIZ_CARPANI = 1.0


def piksel_aci_hatasi(
    cx: float, cy: float, genislik: int, yukseklik: int, vfov: float
) -> tuple:
    """Goruntudeki bir pikseli, ona donmek icin gereken aci hatasina cevirir.

    bridge.pixel_to_angles ile ayni matematik; orada Unity'nin Telemetry
    nesnesi kullanildigi icin burada webcam olculeriyle yeniden yazildi.
    Kamera namluyla es eksenli varsayilir: goruntu merkezi = namlu dogrultusu.

    Donen: (yaw_hatasi, pitch_hatasi) derece. Pozitif yaw = saga don.
    """
    if genislik == 0 or yukseklik == 0:
        return 0.0, 0.0

    nx = (cx - genislik / 2.0) / (genislik / 2.0)
    ny = (cy - yukseklik / 2.0) / (yukseklik / 2.0)

    yarim_v = np.radians(vfov) / 2.0
    en_boy = genislik / yukseklik

    yaw = np.degrees(np.arctan(nx * np.tan(yarim_v) * en_boy))
    pitch = np.degrees(np.arctan(-ny * np.tan(yarim_v)))  # goruntu y'si asagi artar
    return float(yaw), float(pitch)


class SahteKamera:
    """Kamera yokken test icin: kirmizi bir top ekranda gezinir.

    Gercek VideoCapture ile ayni read() imzasini kullanir, boylece dongude
    hicbir sey degismez.
    """

    def __init__(self, genislik: int = 640, yukseklik: int = 480, fps: float = 30.0):
        self.genislik, self.yukseklik = genislik, yukseklik
        self._periyot = 1.0 / fps
        self._t0 = time.monotonic()
        self._sonKare = 0.0

    def isOpened(self) -> bool:
        return True

    def read(self):
        # Gercek kamera gibi kare hizini sinirla; yoksa dongu bosa doner.
        bekle = self._periyot - (time.monotonic() - self._sonKare)
        if bekle > 0:
            time.sleep(bekle)
        self._sonKare = time.monotonic()

        t = time.monotonic() - self._t0
        kare = np.full((self.yukseklik, self.genislik, 3), 40, np.uint8)
        # Lissajous benzeri bir yol: hem yatay hem dikey hata uretsin.
        x = int(self.genislik / 2 + np.sin(t * 0.7) * self.genislik * 0.35)
        y = int(self.yukseklik / 2 + np.sin(t * 1.1) * self.yukseklik * 0.30)
        cv2.circle(kare, (x, y), 26, (40, 40, 220), -1)   # BGR: kirmizi
        return True, kare

    def release(self) -> None:
        pass


def kamera_ac(kaynak: str, genislik: int, yukseklik: int):
    """Kamerayi acar. kaynak 'test' ise sahte kamera dondurur."""
    if kaynak == "test":
        return SahteKamera(genislik, yukseklik)

    kam = cv2.VideoCapture(int(kaynak) if kaynak.isdigit() else kaynak)
    if kam.isOpened():
        kam.set(cv2.CAP_PROP_FRAME_WIDTH, genislik)
        kam.set(cv2.CAP_PROP_FRAME_HEIGHT, yukseklik)
        # Tampon kucuk tutulur: takipte eski kare islemek gecikme demektir.
        kam.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return kam


def en_buyuk_hedef(tespitler):
    """En buyuk alanli tespiti dondurur (en yakin/en belirgin nesne)."""
    return max(tespitler, key=lambda d: d.area) if tespitler else None


def cerceve_ciz(
    kare,
    hedef,
    otonom: bool,
    durum: TrackState,
    yaw_hata: float,
    pitch_hata: float,
    link_durumu: str,
    rt: float,
) -> None:
    """Nisangahi, hedefi ve durum bilgilerini kare uzerine cizer."""
    h, w = kare.shape[:2]
    ox, oy = w // 2, h // 2

    # --- MAVI NISANGAH: goruntunun tam ortasi, otonom modun hedefledigi nokta
    cv2.line(kare, (ox - 22, oy), (ox - 6, oy), NISANGAH_RENGI, 2)
    cv2.line(kare, (ox + 6, oy), (ox + 22, oy), NISANGAH_RENGI, 2)
    cv2.line(kare, (ox, oy - 22), (ox, oy - 6), NISANGAH_RENGI, 2)
    cv2.line(kare, (ox, oy + 6), (ox, oy + 22), NISANGAH_RENGI, 2)
    cv2.circle(kare, (ox, oy), 30, NISANGAH_RENGI, 1)

    if hedef is not None:
        x, y, bw, bh = hedef.bbox
        renk = DRAW_COLORS.get(hedef.color, (255, 255, 255))
        cv2.rectangle(kare, (x, y), (x + bw, y + bh), renk, 2)
        cv2.circle(kare, (int(hedef.cx), int(hedef.cy)), 4, renk, -1)
        # Hedeften nisangaha cizgi: kapatilmasi gereken hata gorunur olsun.
        cv2.line(kare, (int(hedef.cx), int(hedef.cy)), (ox, oy), renk, 1)

    mod_yazi = "OTONOM" if otonom else "MANUEL"
    mod_renk = (60, 220, 90) if otonom else (200, 200, 200)
    cv2.putText(kare, f"MOD: {mod_yazi}", (10, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, mod_renk, 2)

    if otonom:
        durum_renk = (60, 220, 90) if durum is TrackState.LOCKED else (60, 220, 235)
        cv2.putText(kare, f"{durum.value}", (10, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, durum_renk, 2)
        cv2.putText(kare, f"hata: yaw {yaw_hata:+.1f}  pitch {pitch_hata:+.1f}",
                    (10, 76), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

    if rt >= SERVO_RT_ESIK:
        cv2.putText(kare, f"ATIS %{rt * 100:.0f}", (w - 150, 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (60, 60, 235), 2)

    cv2.putText(kare, link_durumu, (10, h - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (170, 170, 170), 1)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Kirmizi hedef takibi + kumanda")
    p.add_argument("--kamera", default="0", help="Kamera indeksi/yolu, veya 'test'")
    p.add_argument("--genislik", type=int, default=640)
    p.add_argument("--yukseklik", type=int, default=480)
    p.add_argument("--renk", default="red", help="Takip edilecek renk (red/blue/green/yellow)")
    p.add_argument("--min-alan", type=int, default=300, help="Bu alandan kucuk lekeler yok sayilir")
    p.add_argument("--vfov", type=float, default=VARSAYILAN_VFOV, help="Kameranin dikey gorus acisi")
    p.add_argument("--tara", action="store_true", help="Hedef yokken yatayda supurerek ara")
    p.add_argument("--pencere-yok", action="store_true", help="OpenCV penceresi acma")

    g = p.add_argument_group("karta gonderim")
    g.add_argument("--send", action="store_true", help="Komutlari karta gonder")
    g.add_argument("--port", default=None, help="Seri port")
    g.add_argument("--host", default=None, help="WiFi/UDP ile gonder (kartin adresi)")
    g.add_argument("--udp-port", type=int, default=DEFAULT_UDP_PORT)
    g.add_argument("--send-hz", type=float, default=DEFAULT_SEND_HZ)
    g.add_argument("--scale", type=float, default=1.0)
    g.add_argument("--source", default="right", choices=tuple(SOURCE_AXES),
                   help="MANUEL modda eksenleri hangi kaynak surecek")
    g.add_argument("--fire-safety", action="store_true", help="Atis icin LB basili tutulsun")
    g.add_argument("--reset-delay", type=float, default=DEFAULT_RESET_DELAY_S,
                   help="Seri port acildiktan sonra kartin acilmasi icin beklenecek sure")
    g.add_argument("--no-rumble", action="store_true")
    args = p.parse_args(argv)

    kam = kamera_ac(args.kamera, args.genislik, args.yukseklik)
    if not kam.isOpened():
        print(f"Kamera acilamadi: {args.kamera}  (kamera yoksa --kamera test deneyin)")
        return 1

    pad = XboxController()
    if not pad.open():
        print("Kol bulunamadi; otonom mod calisir ama Y ile mod degistiremezsiniz.")
    haptic = HapticFeedback(pad, enabled=not args.no_rumble)

    dedektor = ColorTargetDetector(colors=[args.renk], min_area=args.min_alan)
    # search_pitch_deg=0: tarama sirasinda dikey eksen seviyede kalsin.
    # tracker.py'deki varsayilan (3 derece) simulasyondaki hedef yuksekligine
    # gore ayarlanmis; webcam kurulumunda dikeyi bosuna yukari surerdi.
    takipci = TurretTracker(search_pitch_deg=0.0)

    link = None
    if args.send:
        ortak = dict(send_hz=args.send_hz, scale=args.scale, source=args.source,
                     require_fire_safety=args.fire_safety)
        link = UdpLink(host=args.host, udp_port=args.udp_port, **ortak) if args.host \
            else ArduinoLink(port=args.port, reset_delay_s=args.reset_delay, **ortak)
        link.open()

    otonom = False
    onceki_kilit = False
    # Tarama, taretin nerede oldugunu bilmeyi gerektirir; encoder geri beslemesi
    # olmadigi icin komut edilen hizdan olu hesapla tahmin ediyoruz.
    yaw_tahmin = pitch_tahmin = 0.0
    son_zaman = time.monotonic()

    print("Y: mod degistir | RT: atis | q veya ESC: cikis")
    try:
        while True:
            ok, kare = kam.read()
            if not ok:
                print("Kamera karesi alinamadi.")
                break

            simdi = time.monotonic()
            dt = min(simdi - son_zaman, 0.2)
            son_zaman = simdi

            durum = pad.poll()

            # --- mod gecisi ---
            if durum.just_pressed("y"):
                otonom = not otonom
                takipci.reset()
                haptic.pulse("mod")
            if durum.just_pressed("b"):        # E-Stop: otonomdan cik
                otonom = False
                takipci.reset()
                haptic.pulse("estop")

            # --- tespit ---
            hedef = en_buyuk_hedef(dedektor.detect(kare))
            h, w = kare.shape[:2]
            yaw_hata = pitch_hata = 0.0

            # --- eksen komutlari ---
            if otonom:
                if hedef is not None:
                    yaw_hata, pitch_hata = piksel_aci_hatasi(
                        hedef.cx, hedef.cy, w, h, args.vfov
                    )
                    yaw_cmd, pitch_cmd = takipci.update(yaw_hata, pitch_hata, dt)
                elif args.tara:
                    yaw_cmd, pitch_cmd = takipci.search(yaw_tahmin, pitch_tahmin)
                else:
                    # Hedef yok: hicbir sey uydurmadan dur.
                    if takipci.state is not TrackState.SEARCH:
                        takipci.reset()
                    yaw_cmd = pitch_cmd = 0.0

                yaw_cmd *= OTONOM_HIZ_CARPANI
                pitch_cmd *= OTONOM_HIZ_CARPANI
                # Olu hesap: taretin tahmini konumu (yalnizca tarama icin).
                yaw_tahmin += yaw_cmd * takipci.max_yaw_speed * dt
                pitch_tahmin += pitch_cmd * takipci.max_pitch_speed * dt
            else:
                dikey, yatay = SOURCE_AXES[args.source](durum)
                pitch_cmd, yaw_cmd = dikey, yatay

            # --- karta gonder ---
            rt = link.fire_value(durum) if link else 0.0
            if link is not None:
                if otonom:
                    link.send_values(pitch_cmd * args.scale, yaw_cmd * args.scale, rt)
                else:
                    link.send_state(durum)   # manuel: olcek/emniyet mantigi orada

            # --- titresim: hareket agir motora, atis hafif motora ---
            hareket = max(motor_orani(pitch_cmd * args.scale),
                          motor_orani(yaw_cmd * args.scale))
            haptic.update(hareket, rt)

            kilitli = otonom and takipci.locked
            if kilitli and not onceki_kilit:
                haptic.pulse("kilit")
            elif onceki_kilit and not kilitli and hedef is None:
                haptic.pulse("hedef_kayip")
            onceki_kilit = kilitli

            # --- goruntu ---
            if not args.pencere_yok:
                cerceve_ciz(kare, hedef, otonom, takipci.state, yaw_hata, pitch_hata,
                            link.status() if link else "gonderim kapali (--send ile acin)", rt)
                cv2.imshow("Celik Kubbe - hedef takibi", kare)
                tus = cv2.waitKey(1) & 0xFF
                if tus in (ord("q"), 27):
                    break
                if tus == ord("m"):          # klavyeden de mod degistirilebilsin
                    otonom = not otonom
                    takipci.reset()
    except KeyboardInterrupt:
        print("\nCikiliyor.")
    finally:
        haptic.stop()
        if link is not None:
            link.close()
        pad.close()
        kam.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
