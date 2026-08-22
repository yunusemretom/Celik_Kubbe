"""
Unity <-> Python koprusu, istemci tarafi.

Unity'deki PythonBridge.cs bir TCP sunucusu acar. Bu modul o sunucuya baglanir,
namlu kamerasinin karelerini alir ve tarete yon komutu gonderir.

Protokol - her mesaj: [1 bayt tip][4 bayt uzunluk, big-endian][govde]
    0x01 FRAME   Unity -> Python : [2 bayt json uzunlugu][telemetri json][jpeg]
    0x10 COMMAND Python -> Unity : utf8 json

Kullanim:

    from bridge import SteelDomeClient

    with SteelDomeClient() as sd:
        for frame, telemetry in sd.frames():
            # frame: BGR numpy dizisi (OpenCV formati)
            sd.send_rate(yaw=0.3, pitch=-0.1)
"""

from __future__ import annotations

import json
import socket
import struct
import threading
from dataclasses import dataclass, field
from typing import Iterator, Optional, Tuple

import cv2
import numpy as np

from kamera_modeli import KameraModeli

MSG_FRAME = 0x01
MSG_COMMAND = 0x10

_HEADER = struct.Struct(">BI")  # tip + uzunluk


@dataclass
class Telemetry:
    """Her kareyle birlikte gelen taret durumu."""

    t: float = 0.0
    yaw: float = 0.0
    pitch: float = 0.0
    yaw_rate: float = 0.0
    pitch_rate: float = 0.0
    w: int = 0
    h: int = 0
    vfov: float = 60.0
    frame: int = 0
    # Unity'deki KameraGercekcilik acikken gelen objektif modeli
    k1: float = 0.0          # fici distorsiyonu (1. derece)
    k2: float = 0.0          # fici distorsiyonu (2. derece)
    exp: float = 1.0         # kameranin o an uyguladigi otomatik pozlama
    cam_off: float = 0.0     # kameranin menzil referansindan eksenel ilerisi (m)
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict) -> "Telemetry":
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data and k != "raw"}
        return cls(**known, raw=data)

    @property
    def hfov(self) -> float:
        """Yatay gorus acisi (derece). Unity dikey FOV'u sabit tutar."""
        if self.h == 0:
            return self.vfov
        aspect = self.w / self.h
        half_v = np.radians(self.vfov) / 2.0
        return float(np.degrees(2.0 * np.arctan(np.tan(half_v) * aspect)))


class BridgeError(RuntimeError):
    pass


class SteelDomeClient:
    """Unity simulasyonuna baglanan istemci."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765, timeout: float = 10.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._send_lock = threading.Lock()
        self._buf = bytearray()

    # ------------------------------------------------------------ baglanti

    def connect(self) -> "SteelDomeClient":
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock
        return self

    def close(self) -> None:
        if self._sock is not None:
            try:
                self.stop()
            except Exception:
                pass
            try:
                self._sock.close()
            finally:
                self._sock = None

    def __enter__(self) -> "SteelDomeClient":
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------ komutlar

    def _send(self, payload: dict) -> None:
        if self._sock is None:
            raise BridgeError("Baglanti yok - once connect() cagirin.")
        body = json.dumps(payload).encode("utf-8")
        with self._send_lock:
            self._sock.sendall(_HEADER.pack(MSG_COMMAND, len(body)) + body)

    def send_rate(self, yaw: float, pitch: float, fire: bool = False) -> None:
        """Normalize hiz komutu. yaw/pitch -1..1 araliginda kirpilir."""
        self._send({
            "mode": "rate",
            "yaw": float(np.clip(yaw, -1.0, 1.0)),
            "pitch": float(np.clip(pitch, -1.0, 1.0)),
            "fire": fire,
        })

    def send_angle(self, yaw: float, pitch: float, fire: bool = False) -> None:
        """Mutlak aci komutu (derece)."""
        self._send({"mode": "angle", "yaw": float(yaw), "pitch": float(pitch), "fire": fire})

    def stop(self) -> None:
        self._send({"mode": "stop"})

    def set_stage(self, stage: int) -> None:
        """Asamayi degistirir (1, 2 veya 3). Puan ve tur sayaci sifirlanir."""
        self._send({"mode": "stage", "stage": int(stage)})

    # ------------------------------------------------------------ kare alma

    def _recv_exactly(self, n: int) -> bytes:
        assert self._sock is not None
        while len(self._buf) < n:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise BridgeError("Baglanti Unity tarafindan kapatildi.")
            self._buf.extend(chunk)
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def read_frame(self) -> Tuple[np.ndarray, Telemetry]:
        """Tek bir kare ve telemetriyi okur. BGR numpy dizisi dondurur."""
        type_, length = _HEADER.unpack(self._recv_exactly(_HEADER.size))
        body = self._recv_exactly(length)

        if type_ != MSG_FRAME:
            raise BridgeError(f"Beklenmeyen mesaj tipi: 0x{type_:02x}")

        json_len = int.from_bytes(body[:2], "big")
        telemetry = Telemetry.from_json(json.loads(body[2 : 2 + json_len].decode("utf-8")))

        jpeg = np.frombuffer(body[2 + json_len :], dtype=np.uint8)
        image = cv2.imdecode(jpeg, cv2.IMREAD_COLOR)
        if image is None:
            raise BridgeError("JPEG cozulemedi.")

        return image, telemetry

    def frames(self) -> Iterator[Tuple[np.ndarray, Telemetry]]:
        """Baglanti kopana kadar kare uretir."""
        while True:
            try:
                yield self.read_frame()
            except BridgeError:
                return


# ---------------------------------------------------------------- yardimcilar


#: Sartname 5.4'e gore her maketin altina asilan balonun capi (metre).
#: Simulasyondaki balon prefabi de bu olcude.
BALLOON_DIAMETER_M = 0.28


def estimate_range(pixel_height: float, tel: Telemetry,
                   real_size_m: float = BALLOON_DIAMETER_M) -> float:
    """
    Balonun goruntudeki buyuklugunden menzil kestirir (metre).

    Balonun gercek capi bilindigi icin tek kameradan menzil cikarilabilir; bu
    Asama-3'te sart, cunku hedef tipine gore gecerli imha araligi degisiyor
    (F16 icin 10-15 m, helikopter/fuze icin 5-15 m) ve araligin disinda yapilan
    imha puan getirmiyor.

    **Referans noktasi:** goruntuden cikan mesafe *kameraya* olan mesafedir.
    Puanlama ise taretin donme merkezinden olcer (zemindeki menzil yaylari da
    oradan cizili). Kamera namlu boyunca ~1.9 m ileridedir; bu duzeltilmezse
    15 m'lik imha penceresinde %13 hata olur ve menzil disinda kalan bir hedef
    "gecerli" gorunur. Unity bu farki telemetride `cam_off` ile bildiriyor.

    Kestirim kucuk hedeflerde kabalasir: 15 m'de balon ~17 piksel, tek piksellik
    olcum hatasi ~1 m menzil hatasi demektir.
    """
    if pixel_height <= 0 or tel.h == 0:
        return float("inf")

    rad_per_px = np.radians(tel.vfov) / tel.h
    angular = pixel_height * rad_per_px
    if angular <= 1e-6:
        return float("inf")

    kameradan = real_size_m / (2.0 * np.tan(angular / 2.0))
    return float(kameradan + tel.cam_off)


_kamera_onbellek: Optional[KameraModeli] = None


def kamera_modeli(tel: Telemetry) -> KameraModeli:
    """Telemetriye uyan kamera modelini dondurur (degismedikce yeniden kurmaz)."""
    global _kamera_onbellek
    veri = tel.raw or {"w": tel.w, "h": tel.h, "vfov": tel.vfov, "k1": tel.k1, "k2": tel.k2}
    if _kamera_onbellek is None or not _kamera_onbellek.ayni_mi(veri):
        _kamera_onbellek = KameraModeli.telemetriden(veri)
    return _kamera_onbellek


def pixel_to_angles(cx: float, cy: float, tel: Telemetry,
                    duzelt: bool = True) -> Tuple[float, float]:
    """
    Goruntudeki bir pikseli, namlunun o noktaya donmesi icin gereken aci
    farkina cevirir.

    Kamera namluyla es eksenli oldugu icin goruntu merkezi tam olarak namlu
    dogrultusudur; dolayisiyla bu fark dogrudan duzeltme acisidir.

    `duzelt=True` iken once objektif distorsiyonu geri alinir. Unity kamerayi
    gercek bir objektif gibi bozuyor (k1 ~ 0.085); bu duzeltme olmadan kadraj
    kenarindaki bir hedefte nisan hatasi 0.6 dereceye cikar - 15 m'deki bir
    balonun yaricapindan buyuk. Telemetride k1/k2 gelmiyorsa (filtre kapali)
    duzeltme kendiliginden devre disi kalir.

    Donen deger: (yaw_hatasi, pitch_hatasi) derece cinsinden.
    Pozitif yaw = saga don, pozitif pitch = yukari bak.
    """
    if tel.w == 0 or tel.h == 0:
        return 0.0, 0.0

    return kamera_modeli(tel).acisal_hata(cx, cy, duzelt=duzelt)
