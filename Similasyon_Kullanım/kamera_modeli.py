"""Simulasyondaki namlu kamerasinin optik modeli ve duzeltme araclari.

Unity tarafindaki `KameraGercekcilik` bileseni goruntuye bilerek gercek bir
kameranin kusurlarini ekliyor: fici distorsiyonu, kromatik aberasyon, vinyet,
gurultu, otomatik pozlama. Buradaki kod o bozulmalarin *bilinen* kismini geri
almak ve kamera ic parametrelerini (intrinsics) hesaplamak icin.

Neden onemli: taretin acisal hatasini pikselden hesaplarken distorsiyon dogrudan
nisan hatasina donusur. 640x480 / 30 derece FOV / k1=0.085 ile kadrajin
kenarindaki bir hedef ~20 piksel kayar; bu 0.6 derecelik bir nisan hatasi, yani
15 m'deki bir balonun yaricapindan buyuk.

Unity her karede telemetriye `k1`, `k2` ve `vfov` koyuyor; boylece Unity'de
katsayiyi degistirdiginizde Python otomatik uyum saglar.

Kullanim:
    from kamera_modeli import KameraModeli

    model = KameraModeli.telemetriden(tel)     # her karede/degisince
    duz = model.duzelt(kare)                   # distorsiyonu geri al
    yaw, pitch = model.acisal_hata(cx, cy)     # piksel -> derece
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

try:
    import cv2
except ImportError:  # cv2 yoksa yalniz acisal hesap calisir
    cv2 = None


@dataclass
class KameraModeli:
    """Pinhole + radyal distorsiyon modeli.

    Unity'nin uyguladigi distorsiyon normalize edilmis kadraj koordinatinda
    (kisa kenar yerine *uzun* kenara gore olceklenmis, merkezden yariyaricap)
    tanimli. OpenCV ise odak uzakligina normalize edilmis koordinat kullanir.
    `_opencv_katsayilari` bu ikisi arasindaki olcek farkini kapatir.
    """

    genislik: int = 640
    yukseklik: int = 480
    vfov_derece: float = 30.0
    k1: float = 0.0
    k2: float = 0.0

    _harita_x: Optional[np.ndarray] = field(default=None, repr=False, compare=False)
    _harita_y: Optional[np.ndarray] = field(default=None, repr=False, compare=False)

    # ------------------------------------------------------------------ kurulum

    @classmethod
    def telemetriden(cls, tel: dict) -> "KameraModeli":
        """PythonBridge'in gonderdigi telemetri sozlugunden model kurar."""
        return cls(
            genislik=int(tel.get("w", 640)),
            yukseklik=int(tel.get("h", 480)),
            vfov_derece=float(tel.get("vfov", 30.0)),
            k1=float(tel.get("k1", 0.0)),
            k2=float(tel.get("k2", 0.0)),
        )

    def ayni_mi(self, tel: dict) -> bool:
        """Telemetri ayni kamera ayarlarini mi tarif ediyor (harita cache'i icin)."""
        return (
            int(tel.get("w", 640)) == self.genislik
            and int(tel.get("h", 480)) == self.yukseklik
            and abs(float(tel.get("vfov", 30.0)) - self.vfov_derece) < 1e-3
            and abs(float(tel.get("k1", 0.0)) - self.k1) < 1e-6
            and abs(float(tel.get("k2", 0.0)) - self.k2) < 1e-6
        )

    # -------------------------------------------------------------- parametreler

    @property
    def fy(self) -> float:
        """Dikey odak uzakligi (piksel)."""
        return (self.yukseklik / 2.0) / np.tan(np.radians(self.vfov_derece) / 2.0)

    @property
    def fx(self) -> float:
        """Kare piksel varsayimi -> fx = fy."""
        return self.fy

    @property
    def hfov_derece(self) -> float:
        return float(np.degrees(2 * np.arctan((self.genislik / 2.0) / self.fx)))

    @property
    def K(self) -> np.ndarray:
        return np.array(
            [[self.fx, 0.0, self.genislik / 2.0],
             [0.0, self.fy, self.yukseklik / 2.0],
             [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )

    def opencv_katsayilari(self) -> np.ndarray:
        """OpenCV'nin (cv2.solvePnP, calibrateCamera) bekledigi distCoeffs.

        DIKKAT - isaret tersine doner. Unity shader'i cikti pikselini kaynakta
        ARAYARAK ornekliyor: goruntudeki r yaricapindaki piksel, sahnede
        r*(1+k1 r^2) yaricapinda olan noktayi gosterir. OpenCV ise ters yonu
        tanimlar (ideal -> gozlenen). Iki iliski birbirinin tersi oldugundan
        birinci mertebede kc1 = -k1 olur.

        Olcek: bizim r'miz (piksel ofseti)/yukseklik, OpenCV'ninki
        (piksel ofseti)/fy. Yani r_bizim = r_opencv * (fy/yukseklik).
        """
        s = self.fy / self.yukseklik
        return np.array([-self.k1 * s**2, -self.k2 * s**4, 0.0, 0.0, 0.0], dtype=np.float64)

    # ---------------------------------------------------------------- duzeltme

    def _kadraj(self, x, y):
        """Piksel -> shader'in kullandigi kadraj koordinati (yukseklige normalize)."""
        return (x - self.genislik / 2.0) / self.yukseklik, (y - self.yukseklik / 2.0) / self.yukseklik

    def _piksel(self, mx, my):
        return mx * self.yukseklik + self.genislik / 2.0, my * self.yukseklik + self.yukseklik / 2.0

    def _olcek(self, r2):
        return 1.0 + self.k1 * r2 + self.k2 * r2 * r2

    @property
    def distorsiyonsuz(self) -> bool:
        return abs(self.k1) < 1e-9 and abs(self.k2) < 1e-9

    def nokta_duzelt(self, x: float, y: float) -> tuple[float, float]:
        """Gozlenen pikseli, distorsiyon olmasaydi bulunacagi piksele tasir.

        Shader'in bagintisi dogrudan bu yonde tanimli oldugu icin yineleme
        gerekmez; tek polinom degerlendirmesi tam sonuc verir.
        """
        if self.distorsiyonsuz:
            return float(x), float(y)
        mx, my = self._kadraj(x, y)
        f = self._olcek(mx * mx + my * my)
        return self._piksel(mx * f, my * f)

    def nokta_boz(self, x: float, y: float, yineleme: int = 12) -> tuple[float, float]:
        """nokta_duzelt'in tersi: ideal piksel -> goruntude gorunecegi piksel.

        Polinom ters cevrilemedigi icin sabit nokta yinelemesi kullanilir;
        k1 ~ 0.1 mertebesinde birkac adimda 1e-6 pikselin altina iner.
        """
        if self.distorsiyonsuz:
            return float(x), float(y)
        tx, ty = self._kadraj(x, y)
        mx, my = tx, ty
        for _ in range(yineleme):
            f = self._olcek(mx * mx + my * my)
            mx, my = tx / f, ty / f
        return self._piksel(mx, my)

    def _haritalari_hazirla(self) -> None:
        """remap tablolari: hedef (duzeltilmis) pikselden kaynak pikseline."""
        if self._harita_x is not None:
            return

        yy, xx = np.mgrid[0:self.yukseklik, 0:self.genislik].astype(np.float64)
        tx = (xx - self.genislik / 2.0) / self.yukseklik
        ty = (yy - self.yukseklik / 2.0) / self.yukseklik

        mx, my = tx.copy(), ty.copy()
        for _ in range(12):
            r2 = mx * mx + my * my
            f = 1.0 + self.k1 * r2 + self.k2 * r2 * r2
            mx, my = tx / f, ty / f

        self._harita_x = (mx * self.yukseklik + self.genislik / 2.0).astype(np.float32)
        self._harita_y = (my * self.yukseklik + self.yukseklik / 2.0).astype(np.float32)

    def duzelt(self, kare: np.ndarray) -> np.ndarray:
        """Tum kareyi duzeltir. Harita bir kez hesaplanip saklanir.

        Takip dongusunde tum kareyi duzeltmek gereksiz pahalidir; yalniz
        hedefin merkezini `nokta_duzelt` ile tasimak ayni sonucu verir.
        Bu metot gorsel dogrulama ve kayit icin.
        """
        if self.distorsiyonsuz:
            return kare
        if cv2 is None:
            raise RuntimeError("Tum kareyi duzeltmek icin opencv gerekli.")
        self._haritalari_hazirla()
        return cv2.remap(kare, self._harita_x, self._harita_y,
                         cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)

    # ------------------------------------------------------------------ geometri

    def acisal_hata(self, cx: float, cy: float, duzelt: bool = True) -> tuple[float, float]:
        """Piksel merkezinden taretin donmesi gereken (yaw, pitch) acisi (derece).

        Ekran merkezine gore saga pozitif yaw, yukari pozitif pitch.
        """
        if duzelt:
            cx, cy = self.nokta_duzelt(cx, cy)

        dx = cx - self.genislik / 2.0
        dy = cy - self.yukseklik / 2.0

        yaw = float(np.degrees(np.arctan2(dx, self.fx)))
        pitch = float(np.degrees(np.arctan2(-dy, self.fy)))
        return yaw, pitch

    def piksel_boyu_metre(self, mesafe_m: float) -> float:
        """Verilen mesafede bir pikselin karsiligi (metre). Balon capi kontrolu icin."""
        return mesafe_m / self.fx

    def vinyet_telafisi(self, kare: np.ndarray, guc: float = 0.32) -> np.ndarray:
        """Kenar kararmasini kabaca geri alir (renk esiklemesi kenarlarda sasmasin).

        `guc` Unity'deki `vinyet` degeriyle ayni olmali.
        """
        h, w = kare.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w]
        mx = (xx / w - 0.5) * (w / h)
        my = yy / h - 0.5
        r2 = (mx * mx + my * my) * 2.0            # shader'daki 1.4142 carpaninin karesi
        kazanc = 1.0 / np.clip(1.0 - guc * r2, 0.25, 1.0)

        duz = kare.astype(np.float32)
        if duz.ndim == 3:
            kazanc = kazanc[..., None]
        return np.clip(duz * kazanc, 0, 255).astype(kare.dtype)


__all__ = ["KameraModeli"]
