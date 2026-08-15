#!/usr/bin/env python3
"""
Celik Kubbe - Xbox kolu (gamepad) okuma katmani.

Aciklama:
    Xbox 360 / Xbox One / uyumlu bir kolu pygame uzerinden okur, eksen ve
    tuslari isimlendirilmis bir duruma (XboxState) cevirir. Uzerine, MANUAL
    modda tareti surmek icin kol verisini azimuth/elevasyon hedef acilarina
    ceviren ince bir katman (JoystickTurretControl) konur.

    Ayrica secilen kaynagin (varsayilan: D-PAD) degerleri karta gonderilir
    (bkz. --send). Iki tasima da ayni arayuzu kullanir:
      ArduinoLink : USB/seri kablo, 115200 baud
      UdpLink     : WiFi uzerinden UDP (--host ile secilir)
    Kaynak --source ile degistirilir: dpad | right | left.

Varsayilan tus atamalari (MANUAL mod):
    Sol cubuk        -> azimuth / elevasyon hizi
    Sag cubuk        -> ince ayar (hassas hiz)
    LB (tut)         -> emniyet; basili degilken ates istegi gitmez
    RT               -> ates istegi (esik: --fire-threshold)
    X                -> hedefleme lazeri ac/kapa
    Y                -> otonom / manuel mod degistir
    B                -> yazilimsal E-Stop (kilitlenir, START ile temizlenir)
    START            -> E-Stop temizle
    D-Pad            -> motorlari surer (--send ile) ve hedef aciyi kaydirir

Kullanim:
    python3 joyistik_control.py                 # canli durum tablosu (gonderim yok)
    python3 joyistik_control.py --raw           # ham eksen/tus (tus haritasi cikarmak icin)
    python3 joyistik_control.py --list          # bagli kollari ve seri portlari listele
    python3 joyistik_control.py --hz 100        # kol okuma frekansi

    # Motorlari surmek icin karta gonder:
    python3 joyistik_control.py --send --port /dev/ttyACM0       # USB kablosu ile
    python3 joyistik_control.py --send --host 192.168.4.1        # WiFi/UDP ile (kart AP modunda)
    python3 joyistik_control.py --send --host celikkubbe.local   # WiFi/UDP ile (kart bir aga bagli)
    python3 joyistik_control.py --send --scale 0.5               # D-Pad ile yarim hiz
    python3 joyistik_control.py --send --source right            # sag cubuga geri don
    python3 joyistik_control.py --send --format packet           # ESP32 binary protokolu

Seri format (--format text, varsayilan):
    "<dikey>,<yatay>\\n"  ornek: "1.000,0.000\\n"  ilk deger dikey (yukari +),
    ikincisi yatay (sag +). Arduino tarafi eksen1 -> 1. motor, eksen2 -> 2. motor.
    D-Pad dijitaldir: yalnizca -1 / 0 / +1 gider, ara hiz uretmez (--scale ile ayarlanir).

    NOT: Arduino sketch'inde de OLU_BOLGE varsa olu bolgeyi iki kez uygulamayin.
    Ikisi de 0.12 ise efektif olu bolge ~0.23'e cikar ve dusuk hizlar kaybolur.
    Cozum: bu tarafi --deadzone 0 ile calistirip isi Arduino'ya birakin.

Seri format (--format packet):
    PARS UART protokolu v1.3 (esp32_firmware/uart_protocol.h) CMD_AIM cercevesi:
      0xAA 0x55 | 0x01 | 10 | seq + azimuth(f32) + elevasyon(f32) + ctrl | crc16
    CRC-16/CCITT-FALSE. Bu bicim esp32_firmware icindir; joystick_motor.ino
    metin bicimini bekler.

Kutuphane olarak:
    from joyistik_control import XboxController, ArduinoLink

    pad = XboxController()
    pad.open()
    link = ArduinoLink(port=None, source="dpad")   # port=None -> otomatik bul
    link.open()
    while True:
        state = pad.poll()
        link.send_state(state)           # secili kaynak (D-Pad) gider
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, List, Optional

# Kol okumak icin video penceresine ihtiyac yok; basliksiz (headless) calis.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402  (SDL ortam degiskeninden sonra yuklenmeli)

try:
    import serial  # pyserial
    from serial.tools import list_ports
except ImportError:  # pyserial yoksa kol okuma yine calisir, sadece gonderim kapali
    serial = None
    list_ports = None

# ==================== TUS / EKSEN HARITASI ====================
# SDL2 (pygame 2.x) Xbox kollarini hem Linux'ta hem Windows'ta ayni sirayla
# raporlar. Farkli bir kol icin --raw ciktisina bakip bu tablolari duzenleyin.
AXIS_MAP: Dict[str, int] = {
    "left_x": 0,
    "left_y": 1,
    "trigger_left": 2,
    "right_x": 3,
    "right_y": 4,
    "trigger_right": 5,
}

BUTTON_MAP: Dict[str, int] = {
    "a": 0,
    "b": 1,
    "x": 2,
    "y": 3,
    "lb": 4,
    "rb": 5,
    "back": 6,
    "start": 7,
    "guide": 8,
    "ls": 9,   # sol cubuk basmasi
    "rs": 10,  # sag cubuk basmasi
}

#: Cubuklarin merkezdeki surunmesini yok saymak icin olu bolge.
DEFAULT_DEADZONE = 0.12

#: Tetigin "cekildi" sayilmasi icin gereken en dusuk deger (0..1).
DEFAULT_FIRE_THRESHOLD = 0.6

# ==================== HAREKET SINIRLARI ====================
# esp32_firmware/config.h ile ayni tutulmalidir.
AZIMUTH_MIN_DEG = -180.0
AZIMUTH_MAX_DEG = 180.0
ELEVATION_MIN_DEG = -10.0
ELEVATION_MAX_DEG = 45.0

#: Cubuk sonuna kadar itildiginde saniyedeki acisal hiz (derece/s).
AZIMUTH_RATE_DPS = 60.0
ELEVATION_RATE_DPS = 30.0

#: Sag cubugun (ince ayar) hiz carpani.
FINE_RATE_SCALE = 0.20

#: D-Pad'in her basisinda uygulanan adim (derece).
DPAD_STEP_DEG = 1.0

# ==================== CTRL_BITS (uart_protocol.h ile ayni) ====================
CTRL_ARM = 0x01       # bit0 - emniyet mandali; 0 iken firmware ates etmez
CTRL_LASER = 0x02     # bit1 - hedefleme lazeri
CTRL_MOTOR_EN = 0x04  # bit2 - motor suruculer etkin
CTRL_NO_FIRE = 0x08   # bit3 - hedef atisa yasak bolgede

# ==================== SERI ILETISIM (Arduino / ESP32) ====================
#: Sartname geregi haberlesme hizi (config.h -> RPI_UART_BAUD ile ayni).
SERIAL_BAUDRATE = 115200

#: Sag cubuk verisinin varsayilan gonderim frekansi (Hz).
#: Arduino tarafindaki VERI_TIMEOUT (500 ms) icin fazlasiyla yeterli.
DEFAULT_SEND_HZ = 50.0

#: Port acilinca kart DTR ile resetlenir; Uno/Nano bootloader'i ~2 sn surer.
#: Reset atmayan kartlarda (harici USB-TTL, ESP32 dogrudan UART) 0 verilebilir.
DEFAULT_RESET_DELAY_S = 2.0

#: WiFi (UDP) kontrolu icin varsayilanlar. Kart AP modundayken adresi sabittir.
DEFAULT_UDP_PORT = 5005
DEFAULT_AP_HOST = "192.168.4.1"
#: Kart STA modunda ise router'in verdigi IP degisebilir; mDNS adi sabit kalir.
DEFAULT_MDNS_HOST = "celikkubbe.local"

#: Otomatik port aramasinda oncelikli aranan isimler.
SERIAL_PORT_HINTS = ("USB", "ACM", "CH340", "CP210", "FTDI", "Arduino", "ESP32")

#: Karttan gelen satirlarda bunlar goruluyorsa kart yeniden basladi demektir.
#: ESP32 acilista bu satirlari USB-JTAG portundan basar.
CRASH_HINTS = (
    "brownout",        # besleme voltaji dustu - motor akimi cekince tipik
    "rst:",            # ESP32 reset sebebi satiri (or. "rst:0xc (SW_CPU_RESET)")
    "panic",           # cekirdek panigi
    "guru meditation", # bellek erisim hatasi
    "wdt",             # watchdog
    "hazir",           # sketch'in setup()'ta bastigi mesaj - yeniden baslamis
)

#: Karta gonderilecek eksenlerin kaynagi -> (dikey, yatay) ciftini veren fonksiyon.
#: Gonderim sirasi her zaman "dikey,yatay" olur: sketch'te eksen1 -> 1. motor,
#: eksen2 -> 2. motor. D-Pad dijitaldir, yalnizca -1 / 0 / +1 uretir; hizi
#: ayarlamak icin --scale kullanin (or. --scale 0.5 yarim hiz).
SOURCE_AXES = {
    "dpad":  lambda s: (float(s.dpad_y), float(s.dpad_x)),
    "right": lambda s: (s.right_y, s.right_x),
    "left":  lambda s: (s.left_y, s.left_x),
}
DEFAULT_SOURCE = "dpad"

#: Kart tarafindaki OLU_BOLGE ile ayni tutulmalidir (joystick_motor.ino).
#: Analog cubuk merkezdeyken bile birkac yuzdelik surunme uretir; kart bu
#: esigin altini yok sayar, dolayisiyla motor durur. Titresim de ayni esigi
#: kullanmali, yoksa motor dururken kol bosuna titrer.
MOTOR_OLU_BOLGE = 0.12

#: Atis motorunun calismaya baslamasi icin gereken en dusuk RT degeri.
#: joystick_motor.ino'daki RT_ESIK ile ayni tutulmalidir. Tetik tam
#: birakildiginda kucuk bir artik deger kalabilir; bu esik onu yok sayar.
SERVO_RT_ESIK = 0.05

#: Atis mekanizmasi BTS7960 surucu uzerinden surulen bir DC motordur ve kisa
#: DARBELERLE calisir: her darbe bir atistir. Darbenin suresi ve gucu sabittir;
#: RT yalnizca iki darbe arasindaki BEKLEMEYI kisaltir, yani saniyede kac atis
#: yapildigini belirler. Bu ucu joystick_motor.ino'daki ayni isimli sabitlerle
#: ayni tutun; titresim her darbede bir tik verebilsin diye PC de atis
#: frekansini ayni formulle hesaplar.
ATIS_CALISMA_MS = 200.0
ATIS_ARA_YAVAS_MS = 1500.0
ATIS_ARA_HIZLI_MS = 150.0


def atis_ara_suresi_ms(rt: float) -> float:
    """RT'den, iki darbe arasindaki bekleme suresini (ms) verir."""
    oran = min(max((rt - SERVO_RT_ESIK) / (1.0 - SERVO_RT_ESIK), 0.0), 1.0)
    return ATIS_ARA_YAVAS_MS - oran * (ATIS_ARA_YAVAS_MS - ATIS_ARA_HIZLI_MS)


def atis_hizi_hz(rt: float) -> float:
    """RT degerinden saniyedeki atis sayisini hesaplar (sketch ile ayni formul).

    Bir atis dongusu = motorun dondugu sure + bir sonraki darbeye kadar bekleme.
    """
    if rt < SERVO_RT_ESIK:
        return 0.0
    return 1000.0 / (ATIS_CALISMA_MS + atis_ara_suresi_ms(rt))


def motor_orani(deger: float) -> float:
    """Karta giden degeri motorun gercek hiz oranina (0..1) cevirir.

    Sketch'teki hedefAyarla ile ayni matematik: olu bolgenin altinda 0 doner
    (motor durur), ustunde kalan aralik yeniden 0..1'e yayilir. Boylece
    titresim siddeti motorun gercek hizini takip eder.
    """
    buyukluk = min(abs(deger), 1.0)
    if buyukluk < MOTOR_OLU_BOLGE:
        return 0.0
    return (buyukluk - MOTOR_OLU_BOLGE) / (1.0 - MOTOR_OLU_BOLGE)

# ==================== PARS UART PROTOKOLU v1.3 ====================
# esp32_firmware/uart_protocol.h ile birebir ayni olmalidir. Cerceve:
#
#   0xAA 0x55 | msgId(1) | len(1) | payload(len) | crc_lo | crc_hi
#
# CRC-16/CCITT-FALSE, msgId'den payload sonuna kadar hesaplanir (preamble ve
# CRC alaninin kendisi haric) ve little-endian yazilir.
UART_PREAMBLE_1 = 0xAA
UART_PREAMBLE_2 = 0x55
UART_CRC_POLY = 0x1021   # CRC-16/CCITT-FALSE
UART_CRC_INIT = 0xFFFF
UART_MAX_PAYLOAD = 32

#: RPi -> ESP32 mesaj kimlikleri (protokolde tanimli olanlarin kullandiklarimiz).
CMD_AIM = 0x01     # LEN 10: seq(1) + azimuth(f32) + elevasyon(f32) + ctrl(1)
CMD_FIRE = 0x02    # LEN 2 : shotCount(1) + targetId(1)


class JoystickError(RuntimeError):
    """Kol bulunamadi veya acilamadi."""


def _apply_deadzone(value: float, deadzone: float) -> float:
    """Olu bolgeyi kirpar ve kalan araligi yeniden 0..1'e yayar."""
    if abs(value) <= deadzone:
        return 0.0
    scaled = (abs(value) - deadzone) / (1.0 - deadzone)
    return scaled if value > 0 else -scaled


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


@dataclass
class XboxState:
    """Kolun tek bir okuma anindaki durumu."""

    #: Sol cubuk: -1 sol / +1 sag, -1 asagi / +1 yukari (invert_y ile duzeltilir).
    left_x: float = 0.0
    left_y: float = 0.0
    right_x: float = 0.0
    right_y: float = 0.0

    #: Tetikler 0.0 (birakildi) .. 1.0 (sonuna kadar cekildi).
    trigger_left: float = 0.0
    trigger_right: float = 0.0

    #: D-Pad: -1 / 0 / +1.
    dpad_x: int = 0
    dpad_y: int = 0

    #: Tus adi -> basili mi.
    buttons: Dict[str, bool] = field(default_factory=dict)
    #: Bu okumada basilan (kenar tetikli) tuslar.
    pressed: Dict[str, bool] = field(default_factory=dict)
    #: Bu okumada birakilan tuslar.
    released: Dict[str, bool] = field(default_factory=dict)

    connected: bool = False
    #: time.monotonic() zaman damgasi.
    timestamp: float = 0.0

    def button(self, name: str) -> bool:
        """Tus su an basili mi."""
        return bool(self.buttons.get(name, False))

    def just_pressed(self, name: str) -> bool:
        """Tusa bu okumada yeni basildi mi (kenar)."""
        return bool(self.pressed.get(name, False))

    def just_released(self, name: str) -> bool:
        """Tus bu okumada birakildi mi (kenar)."""
        return bool(self.released.get(name, False))


class XboxController:
    """Xbox kolunu acar, olu bolge/tetik normalizasyonu ile okur.

    Kol cikarilip takilirsa pygame olaylarindan yakalanir ve otomatik olarak
    yeniden acilir; bu sirada poll() connected=False olan bos bir durum dondurur.
    """

    def __init__(
        self,
        index: int = 0,
        deadzone: float = DEFAULT_DEADZONE,
        invert_y: bool = True,
        axis_map: Optional[Dict[str, int]] = None,
        button_map: Optional[Dict[str, int]] = None,
    ) -> None:
        self.index = index
        self.deadzone = deadzone
        #: Kollarda cubugu ileri itmek negatif deger uretir; True ise duzeltilir.
        self.invert_y = invert_y
        self.axis_map = dict(axis_map or AXIS_MAP)
        self.button_map = dict(button_map or BUTTON_MAP)

        self._joystick: Optional[pygame.joystick.Joystick] = None
        self._prev_buttons: Dict[str, bool] = {}
        #: Bazi suruculer tetigi ilk hareketine kadar 0.0 raporlar; -1 (birakildi)
        #: ile 0 (yari cekili) ayrimini yapabilmek icin ilk hareketi bekleriz.
        self._trigger_seen: Dict[str, bool] = {}

    # ---------------- yasam dongusu ----------------

    def open(self) -> bool:
        """Kolu acar. Kol yoksa False doner (istisna firlatmaz)."""
        if not pygame.get_init():
            pygame.init()
        if not pygame.joystick.get_init():
            pygame.joystick.init()

        if pygame.joystick.get_count() <= self.index:
            return False

        self._joystick = pygame.joystick.Joystick(self.index)
        self._joystick.init()
        self._prev_buttons = {}
        self._trigger_seen = {}
        return True

    def close(self) -> None:
        if self._joystick is not None:
            self._joystick.quit()
            self._joystick = None
        if pygame.joystick.get_init():
            pygame.joystick.quit()

    def __enter__(self) -> "XboxController":
        self.open()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    @property
    def connected(self) -> bool:
        return self._joystick is not None

    @property
    def name(self) -> str:
        return self._joystick.get_name() if self._joystick else "-"

    # ---------------- okuma ----------------

    def poll(self) -> XboxState:
        """Kolu okur ve XboxState dondurur. Kol yoksa connected=False doner."""
        # SDL olay kuyrugu bosaltilmadan eksen degerleri guncellenmez.
        for event in pygame.event.get():
            if event.type == pygame.JOYDEVICEREMOVED:
                self._on_removed()
            elif event.type == pygame.JOYDEVICEADDED and not self.connected:
                self.open()

        if not self.connected:
            # Kol yeniden takilmis olabilir; olay gelmediyse sayimdan yakala.
            if pygame.joystick.get_init() and pygame.joystick.get_count() > self.index:
                self.open()
            if not self.connected:
                return XboxState(timestamp=time.monotonic())

        state = XboxState(connected=True, timestamp=time.monotonic())

        state.left_x = self._axis("left_x")
        state.left_y = self._axis("left_y", invert=self.invert_y)
        state.right_x = self._axis("right_x")
        state.right_y = self._axis("right_y", invert=self.invert_y)
        state.trigger_left = self._trigger("trigger_left")
        state.trigger_right = self._trigger("trigger_right")

        if self._joystick.get_numhats() > 0:
            hat_x, hat_y = self._joystick.get_hat(0)
            state.dpad_x, state.dpad_y = int(hat_x), int(hat_y)

        n_buttons = self._joystick.get_numbuttons()
        for name, idx in self.button_map.items():
            down = bool(self._joystick.get_button(idx)) if idx < n_buttons else False
            was_down = self._prev_buttons.get(name, False)
            state.buttons[name] = down
            state.pressed[name] = down and not was_down
            state.released[name] = was_down and not down
        self._prev_buttons = dict(state.buttons)

        return state

    def raw(self) -> Dict[str, object]:
        """Tus haritasi cikarmak icin ham eksen/tus/hat degerleri."""
        if not self.connected:
            return {"axes": [], "buttons": [], "hats": []}
        pygame.event.pump()
        js = self._joystick
        return {
            "axes": [round(js.get_axis(i), 3) for i in range(js.get_numaxes())],
            "buttons": [js.get_button(i) for i in range(js.get_numbuttons())],
            "hats": [js.get_hat(i) for i in range(js.get_numhats())],
        }

    def run(self, callback: Callable[[XboxState], None], hz: float = 50.0) -> None:
        """Kolu verilen frekansta okuyup her durumu callback'e verir."""
        period = 1.0 / hz
        while True:
            callback(self.poll())
            time.sleep(period)

    # ---------------- titresim (rumble) ----------------

    def rumble(self, low: float, high: float, duration_ms: int) -> bool:
        """Kolu titretir. Basarili olduysa True doner.

        low  : agir (dusuk frekansli) motor - derin, gucla hissedilen titresim
        high : hafif (yuksek frekansli) motor - ince, tikirti gibi
        duration_ms: sure. Sure dolunca titresim kendiliginden durur, bu yuzden
        surekli titresim icin bu cagri periyodik olarak tazelenmelidir.
        """
        if not self.connected:
            return False
        try:
            return bool(
                self._joystick.rumble(
                    _clamp(low, 0.0, 1.0), _clamp(high, 0.0, 1.0), max(int(duration_ms), 0)
                )
            )
        except (AttributeError, pygame.error):
            # pygame < 2.0.2 veya titresimi desteklemeyen kol/surucu.
            return False

    def stop_rumble(self) -> None:
        """Devam eden titresimi hemen keser."""
        if not self.connected:
            return
        try:
            self._joystick.stop_rumble()
        except (AttributeError, pygame.error):
            pass

    # ---------------- ic yardimcilar ----------------

    def _on_removed(self) -> None:
        self._joystick = None
        self._prev_buttons = {}
        self._trigger_seen = {}

    def _axis(self, name: str, invert: bool = False) -> float:
        idx = self.axis_map.get(name, -1)
        if idx < 0 or idx >= self._joystick.get_numaxes():
            return 0.0
        value = _apply_deadzone(self._joystick.get_axis(idx), self.deadzone)
        return -value if invert else value

    def _trigger(self, name: str) -> float:
        """Tetigi -1..+1 araligindan 0..1'e cevirir."""
        idx = self.axis_map.get(name, -1)
        if idx < 0 or idx >= self._joystick.get_numaxes():
            return 0.0
        raw = self._joystick.get_axis(idx)
        if not self._trigger_seen.get(name, False):
            if raw <= -0.99 or raw > 0.01:
                # Ya tam birakilmis (-1) ya da gercekten cekilmis; artik guveniriz.
                self._trigger_seen[name] = True
            else:
                return 0.0
        return _clamp((raw + 1.0) * 0.5, 0.0, 1.0)


@dataclass
class TurretCommand:
    """Kol durumundan uretilen taret komutu (UART paketiyle ayni alanlar)."""

    azimuth_deg: float = 0.0
    elevation_deg: float = 0.0
    fire: bool = False
    laser: bool = False
    autonomous: bool = False
    estop: bool = False
    #: Kol bagli degil / veri gecersiz -> gondermeden once kontrol edin.
    valid: bool = False

    @property
    def ctrl_bits(self) -> int:
        """CMD_AIM payload'undaki ctrl baytini uretir (uart_protocol.h v1.3).

        Protokolde ates istegi ctrl icinde tasinmaz; ayri bir CMD_FIRE mesaji
        vardir. Buradaki CTRL_ARM yalnizca "emniyet acik" demektir, firmware
        ates icin bu biti ve FLAG_LOCKED'i birlikte arar.
        """
        bits = 0
        if self.fire:
            bits |= CTRL_ARM          # tetik cekilmis -> emniyet acik
        if self.laser:
            bits |= CTRL_LASER
        if not self.estop:
            bits |= CTRL_MOTOR_EN     # E-Stop'ta suruculer devre disi kalir
        return bits


class JoystickTurretControl:
    """Kol verisini hedef azimuth/elevasyon acilarina cevirir.

    Cubuklar hiz komutu uretir; acilar bu hizin zamana gore integrali olarak
    tutulur ve config.h'deki mekanik sinirlarda kirpilir.
    """

    def __init__(
        self,
        azimuth_rate_dps: float = AZIMUTH_RATE_DPS,
        elevation_rate_dps: float = ELEVATION_RATE_DPS,
        fire_threshold: float = DEFAULT_FIRE_THRESHOLD,
        require_safety: bool = True,
    ) -> None:
        self.azimuth_rate_dps = azimuth_rate_dps
        self.elevation_rate_dps = elevation_rate_dps
        self.fire_threshold = fire_threshold
        #: True ise ates istegi icin LB (emniyet) basili tutulmalidir.
        self.require_safety = require_safety

        self.azimuth_deg = 0.0
        self.elevation_deg = 0.0
        self.laser = False
        self.autonomous = False
        self.estop = False
        self._last_ts: Optional[float] = None
        self._prev_dpad = (0, 0)

    def reset(self, azimuth_deg: float = 0.0, elevation_deg: float = 0.0) -> None:
        """Hedef acilari (ornegin taretin gercek konumuna) esitler."""
        self.azimuth_deg = _clamp(azimuth_deg, AZIMUTH_MIN_DEG, AZIMUTH_MAX_DEG)
        self.elevation_deg = _clamp(elevation_deg, ELEVATION_MIN_DEG, ELEVATION_MAX_DEG)
        self._last_ts = None

    def update(self, state: XboxState) -> TurretCommand:
        """Bir kol durumunu isleyip guncel taret komutunu dondurur."""
        now = state.timestamp or time.monotonic()
        dt = 0.0 if self._last_ts is None else _clamp(now - self._last_ts, 0.0, 0.2)
        self._last_ts = now

        if not state.connected:
            # Kol dustu: hareket uretme, mevcut acilarda kal ve gecersiz isaretle.
            return TurretCommand(
                azimuth_deg=self.azimuth_deg,
                elevation_deg=self.elevation_deg,
                laser=self.laser,
                autonomous=self.autonomous,
                estop=self.estop,
                valid=False,
            )

        # --- kenar tetikli tuslar ---
        if state.just_pressed("x"):
            self.laser = not self.laser
        if state.just_pressed("y"):
            self.autonomous = not self.autonomous
        if state.just_pressed("b"):
            self.estop = True
        if state.just_pressed("start"):
            self.estop = False

        # --- eksenler -> aci ---
        az_rate = state.left_x + state.right_x * FINE_RATE_SCALE
        el_rate = state.left_y + state.right_y * FINE_RATE_SCALE
        self.azimuth_deg += az_rate * self.azimuth_rate_dps * dt
        self.elevation_deg += el_rate * self.elevation_rate_dps * dt

        # --- D-Pad: her basista tek adim (basili tutmak surekli kaydirmaz) ---
        if state.dpad_x != self._prev_dpad[0] and state.dpad_x != 0:
            self.azimuth_deg += state.dpad_x * DPAD_STEP_DEG
        if state.dpad_y != self._prev_dpad[1] and state.dpad_y != 0:
            self.elevation_deg += state.dpad_y * DPAD_STEP_DEG
        self._prev_dpad = (state.dpad_x, state.dpad_y)

        self.azimuth_deg = _clamp(self.azimuth_deg, AZIMUTH_MIN_DEG, AZIMUTH_MAX_DEG)
        self.elevation_deg = _clamp(self.elevation_deg, ELEVATION_MIN_DEG, ELEVATION_MAX_DEG)

        # --- ates istegi ---
        safety_ok = state.button("lb") or not self.require_safety
        fire = (
            safety_ok
            and not self.estop
            and state.trigger_right >= self.fire_threshold
        )

        return TurretCommand(
            azimuth_deg=self.azimuth_deg,
            elevation_deg=self.elevation_deg,
            fire=fire,
            laser=self.laser,
            autonomous=self.autonomous,
            estop=self.estop,
            valid=True,
        )


class HapticFeedback:
    """Olaylari kolun titresim motorlarina cevirir.

    Iki tur geri bildirim uretir:

      * Darbe (pulse): tek seferlik olaylar - ates, E-Stop, baglanti kopmasi,
        mod degisimi. Kisa ve belirgindir, suresi bitince kendiliginden susar.
      * Surekli: secili kaynak (D-Pad/cubuk) hareket komutu verdigi surece
        hafif bir titresim. SDL titresimi sure dolunca kestigi icin
        REFRESH_S araliklariyla tazelenir.

    Darbe caldigi surece surekli titresim bastirilir, darbe bitince geri doner.
    """

    #: olay adi -> (agir motor, hafif motor, sure ms)
    PATTERNS: Dict[str, tuple] = {
        "ates":        (1.00, 1.00, 180),
        "estop":       (1.00, 0.80, 450),
        "kopma":       (0.75, 0.00, 260),   # seri baglanti dustu
        "baglandi":    (0.00, 0.45, 90),    # kol veya kart geri geldi
        "mod":         (0.00, 0.40, 70),    # lazer / otonom degisimi
        "kilit":       (0.00, 0.85, 120),   # otonom takipte hedefe kilitlenildi
        "hedef_kayip": (0.45, 0.00, 200),   # kilitli hedef goruntuden cikti
        "sinir":       (0.00, 0.55, 60),    # hareket sinirina dayandi
        "test":        (0.80, 0.80, 500),
    }

    #: Surekli titresimin tazelenme araligi ve verilen sure (s / ms).
    REFRESH_S = 0.15
    REFRESH_MS = 300

    #: Hareket titresiminin alt ve ust siddeti. Siddet, motorun hiz oraniyla
    #: (0..1) bu ikisi arasinda dogru orantili degisir: cubugu az itince hafif,
    #: sonuna kadar itince guclu titrer.
    #:
    #: Alt sinir 0 degil: sifirdan baslayan bir olcekte kucuk cubuk
    #: hareketlerinin titresimi hissedilmeyecek kadar zayif kalir.
    MOVE_MIN = 0.12
    MOVE_MAX = 1.0

    #: Titresim ancak bu kadar degisince yeniden gonderilir. Cok kucuk olursa
    #: her dongude SDL cagrisi yapilir, cok buyuk olursa cubugu ittikce
    #: titresimin arttigi hissedilmez.
    SIDDET_ADIMI = 0.04

    #: Atis titresimi: motorun her darbesinde bir tik. Hafif (yuksek frekansli)
    #: motoru kullanir; hareketin agir motorundan tamamen farkli hissedilir ve
    #: ikisi ayni anda calisabilir.
    ATIS_SIDDET = 0.9
    #: Tikin cevrim icindeki payi. Kucuk tutulur ki "tik tik" diye ayri ayri
    #: hissedilsin, surekli vizilti olmasin.
    ATIS_DOLULUK = 0.35
    #: Tik frekansinin ust siniri (Hz). Bunun ustunde tikler birbirine karisip
    #: tek bir vizildamaya donusur, atis hizi anlasilmaz olur.
    ATIS_EN_YUKSEK_HZ = 8.0

    @classmethod
    def hareket_siddeti(cls, oran: float, strength: float = 1.0) -> float:
        """Motor hiz orani (0..1) -> titresim siddeti. Oran 0 ise titresim yok."""
        oran = _clamp(oran, 0.0, 1.0)
        if oran <= 0.0:
            return 0.0
        return (cls.MOVE_MIN + oran * (cls.MOVE_MAX - cls.MOVE_MIN)) * strength

    def __init__(self, pad: XboxController, enabled: bool = True, strength: float = 1.0) -> None:
        self.pad = pad
        self.enabled = enabled
        #: Tum siddetleri olcekler; 0 = sessiz, 1 = tam.
        self.strength = _clamp(strength, 0.0, 1.0)
        self.supported: Optional[bool] = None   # ilk denemede belirlenir

        self._pulse_until = 0.0
        self._next_refresh = 0.0
        self._moving = False
        #: En son uygulanan siddetler (agir / hafif motor); degisimi izlemek icin.
        self._last_siddet = 0.0
        self._last_hafif = 0.0
        #: Atis tikinin kare dalga fazi (0..1) ve son guncelleme zamani.
        self._atis_faz = 0.0
        self._son_zaman = 0.0

    def pulse(self, name: str) -> None:
        """Adlandirilmis bir olay darbesi calar."""
        if not self.enabled:
            return
        low, high, ms = self.PATTERNS.get(name, self.PATTERNS["mod"])
        ok = self.pad.rumble(low * self.strength, high * self.strength, ms)
        if self.supported is None:
            self.supported = ok
        if ok:
            self._pulse_until = time.monotonic() + ms / 1000.0
            self._moving = False   # darbe bitince surekli titresim yeniden kurulur

    def update(self, hareket: float, atis: float = 0.0) -> None:
        """Her dongude cagrilir. Iki geri bildirimi ayri motorlara dagitir.

        hareket : motorun hiz orani (0..1) -> AGIR motor, surekli derin titresim.
                  0 ise kesilir; cubuk merkezdeyken surunme yuzunden kolun
                  bosuna titremesini boyle engelleriz.
        atis    : RT degeri (0..1) -> HAFIF motor, her atis tikinda bir darbe.

        Ikisi ayni anda calisabilir: taret hareket ederken ates edildiginde
        derin titresimin uzerine tikler biner, hangisinin ne oldugu karisMAZ.
        """
        if not self.enabled:
            return

        now = time.monotonic()
        gecen = now - self._son_zaman if self._son_zaman else 0.0
        self._son_zaman = now

        if now < self._pulse_until:
            return  # darbe caliyor, ustune yazma

        agir = self.hareket_siddeti(hareket, self.strength)
        hafif = self._atis_tiki(atis, gecen)

        # Titresim yalnizca ortada is yokken tamamen kesilir. Tikin "kapali"
        # yarisinda kesilmez: o sirada hafif motor zaten 0 gonderiliyor, ustune
        # bir de stop_rumble cagirmak bosuna gidip gelme yaratirdi.
        if hareket <= 0.0 and atis < SERVO_RT_ESIK:
            if self._moving:
                self.pad.stop_rumble()
                self._moving = False
                self._last_siddet = 0.0
                self._last_hafif = 0.0
            return

        # Tazeleme sartlari:
        #   1) yeni basliyor,
        #   2) SDL suresi dolmak uzere (surekli titresim kesilmesin),
        #   3) siddetlerden biri gozle gorulur degisti - cubugu/tetigi
        #      ittikce titresimin degistigi hissedilsin, tik aninda gecsin.
        degisti = (
            abs(agir - self._last_siddet) >= self.SIDDET_ADIMI
            or abs(hafif - self._last_hafif) >= self.SIDDET_ADIMI
        )
        if not self._moving or now >= self._next_refresh or degisti:
            ok = self.pad.rumble(agir, hafif, self.REFRESH_MS)
            if self.supported is None:
                self.supported = ok
            self._moving = True
            self._last_siddet = agir
            self._last_hafif = hafif
            self._next_refresh = now + self.REFRESH_S

    def _atis_tiki(self, atis: float, gecen: float) -> float:
        """Atis hizinda kare dalga uretir: motorun her darbesinde bir tik.

        Faz, gercek zamanla ilerletilir; boylece titresim frekansi atis
        frekansiyla ayni olur - tetigi actikca tikler siklasir ve kac atis
        yaptigini elinden sayabilirsin.
        """
        hz = min(atis_hizi_hz(atis), self.ATIS_EN_YUKSEK_HZ)
        if hz <= 0.0:
            self._atis_faz = 0.0
            return 0.0
        self._atis_faz = (self._atis_faz + gecen * hz) % 1.0
        return self.ATIS_SIDDET * self.strength if self._atis_faz < self.ATIS_DOLULUK else 0.0

    def stop(self) -> None:
        """Cikista titresimi kesin olarak kapatir."""
        self._moving = False
        self._pulse_until = 0.0
        self.pad.stop_rumble()


def crc16_ccitt_false(data: bytes) -> int:
    """CRC-16/CCITT-FALSE - uart_protocol.cpp'deki ayni isimli fonksiyonla ayni.

    Protokol dokumanindaki dogrulama testi: crc16_ccitt_false(b"\\x00\\x00")
    sonucu 0x1D0F olmalidir.
    """
    crc = UART_CRC_INIT
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ UART_CRC_POLY) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def build_frame(msg_id: int, payload: bytes = b"") -> bytes:
    """PARS UART v1.3 cercevesi uretir (sendFrame'in Python karsiligi)."""
    if len(payload) > UART_MAX_PAYLOAD:
        raise ValueError(f"payload en fazla {UART_MAX_PAYLOAD} byte olabilir")
    body = bytes([msg_id, len(payload)]) + payload
    return bytes([UART_PREAMBLE_1, UART_PREAMBLE_2]) + body + struct.pack("<H", crc16_ccitt_false(body))


def build_cmd_aim(
    azimuth: float, elevation: float, ctrl: int = 0, seq: int = 0
) -> bytes:
    """CMD_AIM cercevesi (LEN 10): seq + azimuth + elevasyon + ctrl.

    seq 0..255 arasinda dolasir; firmware kayip paket saymak icin kullanir.
    """
    payload = struct.pack("<BffB", seq & 0xFF, azimuth, elevation, ctrl)
    return build_frame(CMD_AIM, payload)


def find_serial_port() -> Optional[str]:
    """Muhtemel Arduino/ESP32 portunu bulur; emin olamazsa None doner.

    Anakart uzerindeki /dev/ttyS* portlari elenir: bunlar cogu makinede bos
    durur ve yanlislikla acilirsa veri hicbir yere gitmez.
    """
    if list_ports is None:
        return None
    candidates = [p for p in list_ports.comports() if not p.device.startswith("/dev/ttyS")]
    for port in candidates:
        haystack = f"{port.device} {port.description} {port.manufacturer or ''}"
        if any(hint.lower() in haystack.lower() for hint in SERIAL_PORT_HINTS):
            return port.device
    # Ipucu eslesmedi: tek aday varsa odur, birden fazlaysa --port ile secilmeli.
    return candidates[0].device if len(candidates) == 1 else None


def list_serial_ports() -> List[str]:
    if list_ports is None:
        return []
    return [f"{p.device} | {p.description}" for p in list_ports.comports()]


class ArduinoLink:
    """Sag cubugun degerlerini seri port uzerinden Arduino'ya gonderir.

    Yalnizca secili kaynagin iki ekseni gonderilir (varsayilan D-Pad); diger
    eksenler ve tuslar hatta cikmaz. Iki format desteklenir:

      "text"    -> "<x>,<y>\\n"  (Arduino'da virgulden ayrilip atof ile okunur)
      "packet"  -> uart_protocol.h'deki 14 byte'lik binary UartPacket

    TUM seri islemler arka plan thread'inde yapilir. Ana dongu yalnizca son
    degeri birakir (send_right_stick) ve asla bloke olmaz: port acilirken
    beklenen kart reset suresi, yazma zaman asimi ve yeniden baglanma
    denemelerinin hicbiri kol okumasini yavaslatmaz.
    """

    def __init__(
        self,
        port: Optional[str] = None,
        baudrate: int = SERIAL_BAUDRATE,
        fmt: str = "text",
        send_hz: float = DEFAULT_SEND_HZ,
        scale: float = 1.0,
        decimals: int = 3,
        reconnect_s: float = 2.0,
        reset_delay_s: float = DEFAULT_RESET_DELAY_S,
        read_back: bool = True,
        dtr: bool = False,
        source: str = DEFAULT_SOURCE,
        require_fire_safety: bool = False,
    ) -> None:
        if fmt not in ("text", "packet"):
            raise ValueError("format 'text' veya 'packet' olmali")
        if source not in SOURCE_AXES:
            raise ValueError(f"source su degerlerden biri olmali: {', '.join(SOURCE_AXES)}")
        #: None ise otomatik aranir (her denemede degil, yalnizca baglanirken).
        self.port = port
        self.baudrate = baudrate
        self.fmt = fmt
        #: Gonderim frekansi; kol okuma frekansindan bagimsizdir.
        self.min_period = 1.0 / max(send_hz, 1.0)
        #: -1..1 araligini olceklemek icin (ornegin 90 -> derece).
        self.scale = scale
        self.decimals = decimals
        self.reconnect_s = reconnect_s
        #: Port acilinca kart DTR ile resetlenir; bootloader cikana kadar beklenir.
        self.reset_delay_s = reset_delay_s
        #: True ise Arduino'nun bastigi satirlar okunur (last_rx ile gorulur).
        self.read_back = read_back
        #: DTR/RTS acilista yukari cekilsin mi. Arduino/Nano'da bu karti
        #: resetler, ESP32'de bootloader'a dusurebilir; varsayilan kapali.
        self.dtr = dtr
        #: Motorlari suren eksenlerin kaynagi: "dpad", "right" veya "left".
        self.source = source
        #: True ise RT'nin is gormesi icin LB (emniyet) basili tutulmalidir.
        self.require_fire_safety = require_fire_safety

        #: Kullanicinin verdigi port; kart yeniden numaralandiginda tekrar aranir.
        self._preferred_port = port
        self._serial = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        #: Gonderilecek son deger; ana dongu yazar, thread okur.
        #: (dikey eksen, yatay eksen, atis tetigi 0..1)
        self._value = (0.0, 0.0, 0.0)

        self.last_error: Optional[str] = None
        #: Arduino'dan gelen son satir (sketch'te DEBUG aciksa dolar).
        self.last_rx: str = ""
        #: Basariyla gonderilen paket sayisi (teshis icin).
        self.tx_count = 0
        #: Baglantinin kac kez koptugu. Motorlar hareket ederken artiyorsa
        #: kart resetleniyor demektir (ESP32'de tipik olarak brownout).
        self.drops = 0
        #: Son olaylar: "saat mesaj" seklinde, teshis icin ekranda gosterilir.
        self.events: Deque[str] = deque(maxlen=8)

    # ---------------- yasam dongusu ----------------

    def open(self) -> bool:
        """Gonderim thread'ini baslatir. Baglanti arka planda kurulur.

        Donus degeri yalnizca thread'in baslayip baslamadigini soyler; portun
        acilip acilmadigi icin connected / status() bakin.
        """
        if serial is None:
            self.last_error = "pyserial kurulu degil (pip install pyserial)"
            return False
        if self._thread is not None and self._thread.is_alive():
            return True

        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ArduinoLink", daemon=True)
        self._thread.start()
        return True

    def close(self, send_zero: bool = True) -> None:
        """Motorlarin takili kalmamasi icin son bir (0,0) yollar ve kapatir."""
        if send_zero and self.connected:
            with self._lock:
                self._value = (0.0, 0.0, 0.0)
            # Thread'in sifiri yazmasina firsat ver.
            time.sleep(min(self.min_period * 2, 0.1))

        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._close_port()

    def __enter__(self) -> "ArduinoLink":
        self.open()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    @property
    def connected(self) -> bool:
        ser = self._serial
        return ser is not None and ser.is_open

    # ---------------- ana dongunun cagirdigi (bloke etmeyen) ----------------

    def send_state(self, state: XboxState) -> None:
        """Gonderilecek degeri gunceller. Seri yazma thread'de olur, beklemez.

        Uc deger gonderilir: dikey eksen (1. motor), yatay eksen (2. motor) ve
        RT tetigi (atis hizi). Hangi eksenlerin okunacagi self.source
        ile secilir. Kol bagli degilse hepsi 0 birakilir: motorlar durur, atis
        bekleme konumuna doner.
        """
        if state.connected:
            dikey, yatay = SOURCE_AXES[self.source](state)
            x = _clamp(dikey, -1.0, 1.0) * self.scale
            y = _clamp(yatay, -1.0, 1.0) * self.scale
            rt = self.fire_value(state)
        else:
            x = y = rt = 0.0
        with self._lock:
            self._value = (x, y, rt)

    #: Eski isim; sag cubuk disinda bir kaynak secilmisse de calisir.
    send_right_stick = send_state

    def fire_value(self, state: XboxState) -> float:
        """RT'den atis hizini (0..1) uretir.

        require_fire_safety acikken LB basili degilse 0 doner; boylece tetige
        yanlislikla dokunmak atis mekanizmasini calistirmaz.
        """
        if self.require_fire_safety and not state.button("lb"):
            return 0.0
        return _clamp(state.trigger_right, 0.0, 1.0)

    def send_values(self, x: float, y: float, rt: float = 0.0) -> None:
        """Gonderilecek degeri dogrudan verir (kol disindan surmek icin)."""
        with self._lock:
            self._value = (x, y, rt)

    def status(self) -> str:
        """Canli tabloda gosterilecek tek satirlik durum."""
        kopma = f" kopma={self.drops}" if self.drops else ""
        if self.connected:
            return f"{self.port} @ {self.baudrate} [{self.fmt}] tx={self.tx_count}{kopma}"
        return f"BAGLI DEGIL{kopma} ({self.last_error or 'baglaniyor...'})"

    def _log(self, mesaj: str) -> None:
        """Olay gunlugune zaman damgali satir ekler."""
        self.events.append(f"{time.strftime('%H:%M:%S')} {mesaj}")

    # ---------------- arka plan thread'i ----------------

    def _run(self) -> None:
        """Portu acar, send_hz frekansinda son degeri yazar, kopunca toparlar."""
        next_send = time.monotonic()
        while not self._stop.is_set():
            if not self.connected:
                if not self._connect():
                    # Basarisiz: bir sure bekle, ana dongu bundan etkilenmez.
                    self._stop.wait(self.reconnect_s)
                    continue
                next_send = time.monotonic()

            with self._lock:
                x, y, rt = self._value

            if not self._write(x, y, rt):
                continue  # _write portu kapatti, dongu basinda yeniden baglanilir

            if self.read_back:
                self._read_lines()

            next_send += self.min_period
            delay = next_send - time.monotonic()
            if delay < 0:
                next_send = time.monotonic()  # geride kaldik, birikimi sifirla
                delay = 0
            self._stop.wait(delay)

        self._close_port()

    def _resolve_port(self) -> Optional[str]:
        """Kullanilacak port yolunu bulur.

        ESP32'nin yerlesik USB-JTAG/serial birimi kullaniliyorsa portu cipin
        kendisi uretir: cip resetlenir veya coker ise /dev/ttyACM0 dugumu yok
        olur, geri gelirken baska bir numarayla (ttyACM1) gelebilir. Bu yuzden
        kullanicinin verdigi yol kaybolduysa otomatik aramaya duseriz.
        """
        wanted = self._preferred_port
        if wanted is None:
            return find_serial_port()
        if os.path.exists(wanted):
            return wanted
        # Kart yeniden numaralandiysa baska bir yolda olabilir.
        alternatif = find_serial_port()
        if alternatif:
            self._log(f"{wanted} kayboldu, {alternatif} deneniyor")
        return alternatif

    def _connect(self) -> bool:
        port = self._resolve_port()
        if port is None:
            self.last_error = "seri port yok (kart resetlenmis olabilir)"
            return False

        try:
            # Port ve ayarlar once kuruluyor, acilis en sonda: boylece DTR/RTS
            # baslangic durumu port acilmadan once belirlenebiliyor.
            ser = serial.Serial()
            ser.port = port
            ser.baudrate = self.baudrate
            ser.timeout = 0
            # Yazma sonsuza kadar asili kalmasin; zaman asimi thread'de yakalanir.
            ser.write_timeout = 0.5
            # DTR/RTS: Arduino'da bunlar karti resetler, ESP32'de bootloader'a
            # dusurebilir. Varsayilan olarak indirilir (kart resetlenmez).
            ser.dtr = self.dtr
            ser.rts = self.dtr
            try:
                # Baska bir surec (or. ModemManager) portu kapmissa net hata ver.
                ser.exclusive = True
            except AttributeError:
                pass  # Windows'ta bu ozellik yok
            ser.open()
            self._serial = ser
        except Exception as exc:  # SerialException, izin hatasi, OSError...
            self._serial = None
            self.last_error = f"{port}: {exc}"
            return False

        self.port = port
        self.last_error = None
        # Kartin acilmasini bekle. Uno/Nano DTR ile resetlenir; ESP32-S3'un
        # yerlesik USB-JTAG portunda ise DTR indirilse bile port acilisi cipi
        # resetler (rst:0x15 USB_UART_CHIP_RESET), o yuzden her durumda beklenir.
        if self._stop.wait(self.reset_delay_s):
            return False
        try:
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
        except Exception:
            pass
        self._log(f"baglandi: {port}")
        return True

    def _write(self, x: float, y: float, rt: float = 0.0) -> bool:
        ser = self._serial
        if ser is None:
            return False

        payload = self._payload(x, y, rt)

        try:
            ser.write(payload)
        except Exception as exc:
            self.last_error = str(exc)
            self.drops += 1
            # Kart calisirken kopuyorsa sebep genellikle karttadir: reset,
            # brownout veya USB'nin yeniden numaralanmasi.
            self._log(f"KOPTU (tx={self.tx_count}): {exc}")
            self._close_port()
            return False

        self.tx_count += 1
        return True

    def _payload(self, x: float, y: float, rt: float) -> bytes:
        """Gonderilecek baytlari uretir (iki tasima da bunu kullanir).

        text   : "<dikey>,<yatay>,<rt>\\n"  - joystick_motor.ino'nun bekledigi
                 bicim; rt atis darbelerinin sikligidir.
        packet : PARS UART v1.3 CMD_AIM cercevesi - esp32_firmware icindir.
                 Protokolde atis hizi alani yoktur; RT esigi gecince yalnizca
                 CTRL_ARM biti kalkar, asil ates emri ayri bir CMD_FIRE
                 mesajidir (bu katman onu gondermez).
        """
        if self.fmt == "text":
            # "-0.000" yerine "0.000" gitsin (eksi sifir cirkin gorunuyor).
            x, y = x + 0.0 if x else 0.0, y + 0.0 if y else 0.0
            n = self.decimals
            return f"{x:.{n}f},{y:.{n}f},{rt:.{n}f}\n".encode("ascii")

        ctrl = CTRL_MOTOR_EN
        if rt >= DEFAULT_FIRE_THRESHOLD:
            ctrl |= CTRL_ARM
        self._seq = (getattr(self, "_seq", -1) + 1) & 0xFF
        return build_cmd_aim(x, y, ctrl=ctrl, seq=self._seq)

    def _read_lines(self) -> None:
        """Arduino'nun bastigi satirlari okur (teshis icin, bloke etmez)."""
        ser = self._serial
        if ser is None:
            return
        try:
            waiting = ser.in_waiting
            if waiting:
                data = ser.read(waiting).decode("ascii", "replace")
                for line in data.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    self.last_rx = line[:60]
                    # Kart yeniden basladiysa/coktuyse iz birak; "bagli degil"
                    # hatasinin sebebini bulmak icin en degerli bilgi budur.
                    dusuk = line.lower()
                    if any(iz in dusuk for iz in CRASH_HINTS):
                        self._log(f"KART MESAJI: {line[:50]}")
        except Exception:
            pass  # teshis amacli; okuma hatasi gonderimi bozmasin

    def _close_port(self) -> None:
        ser, self._serial = self._serial, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass


class UdpLink(ArduinoLink):
    """Ayni komutlari kablo yerine WiFi/UDP uzerinden gonderir.

    ArduinoLink ile bire bir ayni arayuze sahiptir; yalnizca tasima katmani
    degisir. Gonderim yine arka plan thread'inde, ayni frekansta ve ayni
    guvenlik davranisiyla yapilir: kol dusunce (0, 0) gider, kart tarafindaki
    VERI_TIMEOUT ise paketler kesilirse motorlari durdurur.

    UDP secilmesinin sebebi: kaybolan paketi yeniden gondermeye calismak
    kontrolu geciktirir. Zaten saniyede 50 kez guncel deger gonderildigi icin
    kaybolan paketin yerini 20 ms sonraki alir.
    """

    def __init__(
        self,
        host: str,
        udp_port: int = DEFAULT_UDP_PORT,
        **kwargs,
    ) -> None:
        kwargs.pop("port", None)
        super().__init__(port=None, **kwargs)
        #: Kartin IP adresi veya mDNS adi (or. "192.168.4.1", "celikkubbe.local").
        self.host = host
        self.udp_port = udp_port
        self._sock = None
        #: Ad cozumlemesi bir kez yapilip saklanir.
        self._addr: Optional[tuple] = None

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def status(self) -> str:
        kopma = f" kopma={self.drops}" if self.drops else ""
        if self.connected:
            return f"udp {self.host}:{self.udp_port} [{self.fmt}] tx={self.tx_count}{kopma}"
        return f"BAGLI DEGIL{kopma} ({self.last_error or 'baglaniyor...'})"

    def _connect(self) -> bool:
        import socket

        try:
            # Ad cozumlemesi (mDNS dahil) burada, thread icinde yapilir; ana
            # dongu DNS beklemesinden etkilenmez.
            bilgi = socket.getaddrinfo(self.host, self.udp_port, 0, socket.SOCK_DGRAM)[0]
            sock = socket.socket(bilgi[0], socket.SOCK_DGRAM)
            sock.setblocking(False)
            # Kartin geri yolladigi durum satirlarini alabilmek icin dinle.
            sock.bind(("", 0))
            self._addr = bilgi[4]
            self._sock = sock
        except Exception as exc:
            self._sock = None
            self.last_error = f"{self.host}:{self.udp_port}: {exc}"
            return False

        self.last_error = None
        self._log(f"udp hedefi: {self._addr[0]}:{self.udp_port}")
        return True

    def _write(self, x: float, y: float, rt: float = 0.0) -> bool:
        sock = self._sock
        if sock is None:
            return False

        try:
            sock.sendto(self._payload(x, y, rt), self._addr)
        except Exception as exc:
            self.last_error = str(exc)
            self.drops += 1
            # UDP'de gonderim hatasi genelde ag arayuzu dustu demektir
            # (WiFi koptu, arayuz kapandi). Kart sessizce gitse hata cikmaz;
            # o durumu kartin geri gonderdigi satirlarin kesilmesinden anlarsiniz.
            self._log(f"AG HATASI (tx={self.tx_count}): {exc}")
            self._close_port()
            return False

        self.tx_count += 1
        return True

    def _read_lines(self) -> None:
        """Kartin geri yolladigi durum satirlarini okur (bloke etmez)."""
        sock = self._sock
        if sock is None:
            return
        try:
            while True:
                veri, _ = sock.recvfrom(512)
                for line in veri.decode("ascii", "replace").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    self.last_rx = line[:60]
                    if any(iz in line.lower() for iz in CRASH_HINTS):
                        self._log(f"KART MESAJI: {line[:50]}")
        except BlockingIOError:
            pass       # okunacak paket kalmadi - normal
        except Exception:
            pass       # teshis amacli; okuma hatasi gonderimi bozmasin

    def _close_port(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


# ==================== CLI ====================

def _bar(value: float, width: int = 21) -> str:
    """-1..+1 araligini ortasi sifir olan bir cubukla gosterir."""
    mid = width // 2
    cells = ["-"] * width
    cells[mid] = "|"
    pos = int(round(mid + _clamp(value, -1.0, 1.0) * mid))
    cells[_clamp(pos, 0, width - 1)] = "#"
    return "".join(cells)


def _list_devices() -> int:
    pygame.init()
    pygame.joystick.init()
    count = pygame.joystick.get_count()
    print("--- Kollar ---")
    if count == 0:
        print("Bagli kol yok. Kolu takip tekrar deneyin (Linux: xpad/xone surucusu).")
    for i in range(count):
        js = pygame.joystick.Joystick(i)
        js.init()
        print(
            f"[{i}] {js.get_name()} | eksen: {js.get_numaxes()} "
            f"tus: {js.get_numbuttons()} hat: {js.get_numhats()} guid: {js.get_guid()}"
        )

    print("--- Seri portlar ---")
    ports = list_serial_ports()
    if not ports:
        print("Seri port bulunamadi." if serial else "pyserial kurulu degil (pip install pyserial).")
    for line in ports:
        print(line)
    auto = find_serial_port()
    print(f"--send icin otomatik secilecek port: {auto or 'yok (--port ile belirtin)'}")
    return 0 if count else 1


def _haptic_durum(haptic: HapticFeedback, hareket: float, atis: float) -> str:
    """Titresim satiri: hangi motor, ne siddette, neden calisiyor."""
    if not haptic.enabled:
        return "kapali (--no-rumble)"
    if haptic.supported is False:
        return "kol/surucu desteklemiyor"
    if time.monotonic() < haptic._pulse_until:
        return "DARBE (olay)"

    parcalar = []
    if hareket > 0:
        siddet = HapticFeedback.hareket_siddeti(hareket, haptic.strength)
        parcalar.append(f"agir motor {siddet:.2f} (hareket %{hareket * 100:.0f})")
    hz = min(atis_hizi_hz(atis), HapticFeedback.ATIS_EN_YUKSEK_HZ)
    if hz > 0:
        parcalar.append(f"hafif motor {hz:.1f} tik/sn (her atista bir darbe)")
    return "  +  ".join(parcalar) if parcalar else "hazir - hicbir sey calismiyor"


def _rumble_test(pad: XboxController, haptic: HapticFeedback) -> int:
    """Titresim desenlerini sirayla calar; donanimin destekledigini gosterir."""
    if not pad.connected:
        print("Kol bagli degil, titresim test edilemez.")
        return 1

    print(f"Kol: {pad.name}")
    for ad, (low, high, ms) in HapticFeedback.PATTERNS.items():
        ok = pad.rumble(low * haptic.strength, high * haptic.strength, ms)
        print(f"  {ad:<10} agir={low:.2f} hafif={high:.2f} {ms:>3} ms -> {'OK' if ok else 'DESTEKLENMIYOR'}")
        time.sleep(ms / 1000.0 + 0.25)

    print("  surekli hareket titresimi (2 sn)...")
    t0 = time.monotonic()
    while time.monotonic() - t0 < 2.0:
        pad.poll()                 # SDL olay kuyrugu islenmeli
        haptic.update(hareket=1.0)
        time.sleep(0.02)
    haptic.stop()
    pad.close()
    print("Bitti.")
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Xbox kolu okuma / taret komut testi")
    parser.add_argument("--index", type=int, default=0, help="Kol indeksi (varsayilan 0)")
    parser.add_argument("--hz", type=float, default=50.0, help="Okuma frekansi (Hz)")
    parser.add_argument("--deadzone", type=float, default=DEFAULT_DEADZONE, help="Cubuk olu bolgesi")
    parser.add_argument(
        "--fire-threshold",
        type=float,
        default=DEFAULT_FIRE_THRESHOLD,
        help="RT icin ates esigi (0..1)",
    )
    parser.add_argument("--no-safety", action="store_true", help="Ates icin LB sarti aranmasin")
    parser.add_argument("--no-rumble", action="store_true", help="Kol titresimini kapat")
    parser.add_argument(
        "--rumble-strength",
        type=float,
        default=1.0,
        help="Titresim siddeti carpani (0..1, varsayilan 1.0)",
    )
    parser.add_argument(
        "--rumble-test",
        action="store_true",
        help="Titresim desenlerini sirayla calip cikar (donanim testi)",
    )
    parser.add_argument("--raw", action="store_true", help="Ham eksen/tus degerlerini bas")
    parser.add_argument("--list", action="store_true", help="Kollari ve seri portlari listele, cik")

    ser = parser.add_argument_group("seri iletisim (motorlari suren eksenler)")
    ser.add_argument("--send", action="store_true", help="Secili kaynagi seri porttan karta gonder")
    ser.add_argument(
        "--source",
        choices=tuple(SOURCE_AXES),
        default=DEFAULT_SOURCE,
        help="Motorlari ne surecek: dpad (varsayilan), right (sag cubuk), left (sol cubuk)",
    )
    ser.add_argument("--port", default=None, help="Seri port (bos birakilirsa otomatik bulunur)")
    ser.add_argument(
        "--host",
        default=None,
        help="Kabloyu birakip WiFi/UDP ile gonder. Kartin IP'si veya mDNS adi. "
        f"AP modunda {DEFAULT_AP_HOST}, STA modunda {DEFAULT_MDNS_HOST}",
    )
    ser.add_argument(
        "--udp-port", type=int, default=DEFAULT_UDP_PORT, help="UDP portu (kartla ayni olmali)"
    )
    ser.add_argument(
        "--fire-safety",
        action="store_true",
        help="Atis motorunun calismasi icin LB (emniyet) basili tutulsun; "
        "boylece RT'ye yanlislikla dokunmak atis yapmaz",
    )
    ser.add_argument("--baud", type=int, default=SERIAL_BAUDRATE, help="Baud hizi (varsayilan 115200)")
    ser.add_argument(
        "--format",
        dest="fmt",
        choices=("text", "packet"),
        default="text",
        help="text: 'x,y\\n' | packet: uart_protocol.h binary paketi",
    )
    ser.add_argument("--send-hz", type=float, default=DEFAULT_SEND_HZ, help="Seri gonderim frekansi")
    ser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="Gonderilen degerin carpani. D-Pad dijitaldir (+-1), hizi bununla "
        "ayarlayin: 0.5 -> yarim hiz",
    )
    ser.add_argument(
        "--reset-delay",
        type=float,
        default=DEFAULT_RESET_DELAY_S,
        help="Port acildiktan sonra bootloader icin beklenecek sure (sn, --dtr ile)",
    )
    ser.add_argument(
        "--dtr",
        action="store_true",
        help="Acilista DTR/RTS'i yukari cek. Arduino Uno/Nano'yu resetler; "
        "ESP32'nin yerlesik USB portunda kart bootloader'a dusebilir, kapali birakin",
    )
    args = parser.parse_args(argv)

    if args.list:
        return _list_devices()

    pad = XboxController(index=args.index, deadzone=args.deadzone)
    if not pad.open():
        print("Kol bulunamadi. --list ile kontrol edin; takildiginda otomatik baglanilacak.")

    haptic = HapticFeedback(pad, enabled=not args.no_rumble, strength=args.rumble_strength)

    if args.rumble_test:
        return _rumble_test(pad, haptic)

    ctrl = JoystickTurretControl(
        fire_threshold=args.fire_threshold,
        require_safety=not args.no_safety,
    )

    link: Optional[ArduinoLink] = None
    if args.send:
        ortak = dict(
            fmt=args.fmt,
            send_hz=args.send_hz,
            scale=args.scale,
            source=args.source,
            require_fire_safety=args.fire_safety,
        )
        if args.host:
            link = UdpLink(host=args.host, udp_port=args.udp_port, **ortak)
        else:
            link = ArduinoLink(
                port=args.port,
                baudrate=args.baud,
                reset_delay_s=args.reset_delay,
                dtr=args.dtr,
                **ortak,
            )
        if not link.open():
            print(f"Gonderim baslatilamadi: {link.last_error}")
        elif args.host:
            print(f"WiFi/UDP ile gonderiliyor: {args.host}:{args.udp_port}")
        else:
            print("Seri port arka planda aciliyor...")

    period = 1.0 / max(args.hz, 1.0)
    printed_lines = 0
    print(f"Kol: {pad.name}   (cikmak icin Ctrl-C)")
    # Titresim olaylarini kenar tetiklemek icin bir onceki durum.
    onceki = {"ates": False, "estop": False, "kopma": 0, "kol": pad.connected}
    try:
        while True:
            state = pad.poll()
            cmd = ctrl.update(state)
            if link is not None:
                link.send_state(state)

            # --- titresim: once tek seferlik olaylar ---
            # "ates" darbesi burada YOK: atis artik surekli bir eylem ve kendi
            # tik titresimi var. Ustune bir de darbe binseydi ikisi karisirdi.
            if cmd.estop and not onceki["estop"]:
                haptic.pulse("estop")
            if state.just_pressed("x") or state.just_pressed("y"):
                haptic.pulse("mod")
            if state.connected and not onceki["kol"]:
                haptic.pulse("baglandi")
            if link is not None and link.drops > onceki["kopma"]:
                haptic.pulse("kopma")
                onceki["kopma"] = link.drops
            onceki["ates"], onceki["estop"] = cmd.fire, cmd.estop
            onceki["kol"] = state.connected

            # --- titresim: motorun gercek hizini takip eder ---
            # Ham cubuk degeri degil, karta giden (olcekli) deger kartin olu
            # bolgesinden gecirilerek kullanilir. Boylece cubuk merkezdeyken
            # surunme titresim uretmez ve cubugu ittikce titresim artar.
            if link is not None:
                dikey, yatay = SOURCE_AXES[link.source](state)
                atis = link.fire_value(state)
                hareket = max(
                    motor_orani(dikey * link.scale), motor_orani(yatay * link.scale)
                )
            else:
                hareket = atis = 0.0
            # Hareket agir motora, atis hafif motora gider: ikisi ayri hissedilir.
            haptic.update(hareket, atis)

            if args.raw:
                print(pad.raw())
                time.sleep(period)
                continue

            held = " ".join(n.upper() for n, down in state.buttons.items() if down) or "-"
            kaynak = link.source if link is not None else None
            lines = [
                f"durum      : {'BAGLI' if state.connected else 'KOL YOK'}",
                f"sol  cubuk : X {_bar(state.left_x)} {state.left_x:+.2f}   "
                f"Y {_bar(state.left_y)} {state.left_y:+.2f}",
                f"sag  cubuk : X {_bar(state.right_x)} {state.right_x:+.2f}   "
                f"Y {_bar(state.right_y)} {state.right_y:+.2f}",
                f"tetikler   : LT {state.trigger_left:.2f}   RT {state.trigger_right:.2f}",
                f"d-pad      : ({state.dpad_x:+d}, {state.dpad_y:+d})"
                + ("   <- motorlar bundan suruluyor" if kaynak == "dpad" else ""),
                f"tuslar     : {held}",
                f"titresim   : {_haptic_durum(haptic, hareket, atis)}",
                f"hedef aci  : AZ {cmd.azimuth_deg:+7.2f}   EL {cmd.elevation_deg:+6.2f}",
                f"komut      : ATES {int(cmd.fire)}  LAZER {int(cmd.laser)}  "
                f"OTONOM {int(cmd.autonomous)}  ESTOP {int(cmd.estop)}  "
                f"ctrl_bits 0x{cmd.ctrl_bits:02X}",
            ]
            if link is not None:
                dikey, yatay = SOURCE_AXES[link.source](state)
                rt = link.fire_value(state)
                emniyet = ""
                if link.require_fire_safety and not state.button("lb"):
                    emniyet = "  (EMNIYETTE - LB basili tutun)"
                lines.append(
                    f"gonderilen : kaynak={link.source} -> "
                    f"{dikey * link.scale:+.3f},{yatay * link.scale:+.3f},{rt:.3f}"
                )
                lines.append(
                    f"atis motor : RT {rt:.2f} -> "
                    f"{'atis yok (motor durdu)' if rt < SERVO_RT_ESIK else f'saniyede {atis_hizi_hz(rt):.1f} darbe'}"
                    f"{emniyet}"
                )
                lines.append(f"seri       : {link.status()}")
                lines.append(f"kart       : {link.last_rx or '-'}")
                # Son iki olay: kopmanin ne zaman ve neden oldugunu gosterir.
                for olay in list(link.events)[-2:]:
                    lines.append(f"olay       : {olay}")
                for _ in range(2 - len(list(link.events)[-2:])):
                    lines.append("olay       : -")
            if printed_lines:
                sys.stdout.write(f"\x1b[{printed_lines}A")
            sys.stdout.write("\n".join(line.ljust(78) for line in lines) + "\n")
            sys.stdout.flush()
            printed_lines = len(lines)

            time.sleep(period)
    except KeyboardInterrupt:
        print("\nCikiliyor.")
    finally:
        haptic.stop()
        if link is not None:
            # Kol birakilmis gibi son bir sifir gonderip hatti kapatir.
            link.close()
        pad.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
