"""
Hedef tespiti ve taret kontrol dongusu.

Tespit su an renk esiklemeye dayali - simulasyondaki hedefler emissive malzemeli
oldugu icin ton (hue) isiklandirmadan bagimsiz ve kararli. Daha sonra bu sinifin
yerine bir YOLO dedektoru koymak icin sadece `detect()` metodunu ayni imzayla
uygulamak yeterli.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np


# ------------------------------------------------------------------ tespit


@dataclass
class Detection:
    """Goruntude bulunan tek bir hedef."""

    color: str
    cx: float
    cy: float
    area: float
    bbox: Tuple[int, int, int, int]  # x, y, w, h

    @property
    def center(self) -> Tuple[float, float]:
        return self.cx, self.cy


# HSV araliklari (OpenCV: H 0-179, S 0-255, V 0-255).
# Kirmizi ton cemberinin iki ucuna yayildigi icin iki araliga bolunur.
COLOR_RANGES = {
    "red": [((0, 120, 70), (8, 255, 255)), ((170, 120, 70), (179, 255, 255))],
    "green": [((40, 90, 70), (85, 255, 255))],
    "blue": [((95, 110, 70), (130, 255, 255))],
    "yellow": [((20, 110, 90), (34, 255, 255))],
}

DRAW_COLORS = {
    "red": (60, 60, 235),
    "green": (80, 220, 90),
    "blue": (235, 140, 60),
    "yellow": (60, 220, 235),
}


class ColorTargetDetector:
    """Renk esikleme ile hedef bulur."""

    def __init__(self, colors: Optional[Sequence[str]] = None, min_area: int = 120):
        self.colors = list(colors) if colors else list(COLOR_RANGES.keys())
        self.min_area = min_area
        self._kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    def detect(self, frame: np.ndarray) -> List[Detection]:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        found: List[Detection] = []

        for color in self.colors:
            mask = self._mask_for(hsv, color)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            for contour in contours:
                area = cv2.contourArea(contour)
                if area < self.min_area:
                    continue
                moments = cv2.moments(contour)
                if moments["m00"] == 0:
                    continue
                cx = moments["m10"] / moments["m00"]
                cy = moments["m01"] / moments["m00"]
                found.append(Detection(color, cx, cy, area, cv2.boundingRect(contour)))

        return found

    def _mask_for(self, hsv: np.ndarray, color: str) -> np.ndarray:
        mask = None
        for lo, hi in COLOR_RANGES[color]:
            part = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
            mask = part if mask is None else cv2.bitwise_or(mask, part)
        # Gurultu temizligi: once kucuk lekeleri sil, sonra delikleri kapat
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._kernel)
        return mask


# ------------------------------------------- balon + maket (yarisma duzeni)


@dataclass
class Engagement:
    """
    Vurulacak balon ve onu tasiyan maket. Nisan noktasi balondur; dost/dusman
    ayrimi ise balonun uzerindeki maketin renginden yapilir.
    """

    cx: float
    cy: float
    area: float
    bbox: Tuple[int, int, int, int]
    faction: str                       # "dusman" | "dost" | "bilinmiyor"
    maket_bbox: Optional[Tuple[int, int, int, int]] = None

    @property
    def is_enemy(self) -> bool:
        return self.faction == "dusman"


class BalloonTargetDetector:
    """
    Sartnamenin kurdugu tuzagi cozen dedektor.

    Sartname 5.4: butun maketlerin altina - dostun da dusmanin da - KIRMIZI
    balon asilir, ve imha yalnizca balondan sayilir. Dolayisiyla "kirmizi leke
    = dusman" varsayimi dogrudan dost atesine goturur.

    Dogru sira sudur: once kirmizi balonlar bulunur (nisan noktalari), sonra
    her balonun hemen ustundeki pencerede maket rengi olculur ve taraf ona gore
    belirlenir.
    """

    def __init__(
        self,
        min_area: int = 25,
        min_circularity: float = 0.60,
        aspect_range: Tuple[float, float] = (0.55, 1.8),
        # cv2.contourArea konturun orta cizgisini olctugu icin rasterlenmis
        # kucuk dairelerde gercek doluluk (pi/4 = 0.785) yerine 0.45-0.65 cikar;
        # esik buna gore dusuk tutulmali yoksa uzak balonlar elenir.
        min_fill: float = 0.40,
        maket_gap: Tuple[float, float] = (0.7, 3.4),
        maket_span: float = 2.4,
    ):
        self.min_area = min_area
        self.min_circularity = min_circularity
        self.aspect_range = aspect_range
        self.min_fill = min_fill
        self.maket_gap = maket_gap      # balon yuksekliginin kati cinsinden arama penceresi
        self.maket_span = maket_span    # balon genisliginin kati cinsinden yanal genislik
        self._kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    def detect(self, frame: np.ndarray) -> List[Engagement]:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        h, w = frame.shape[:2]

        red = self._mask(hsv, "red")
        blue = self._mask(hsv, "blue")

        contours, _ = cv2.findContours(red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        results: List[Engagement] = []

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < self.min_area:
                continue

            # Balon yuvarlaktir; kirmizi maketin govdesi degildir. Tek basina
            # dairesellik yetmiyor - kisa bir dikdortgen govde de esigi gecebilir,
            # bu yuzden en/boy orani ve kutuyu doldurma orani da kontrol edilir.
            perimeter = cv2.arcLength(contour, True)
            if perimeter <= 0:
                continue
            circularity = 4.0 * np.pi * area / (perimeter * perimeter)
            if circularity < self.min_circularity:
                continue

            x, y, bw, bh = cv2.boundingRect(contour)
            if bw <= 0 or bh <= 0:
                continue
            aspect = bw / float(bh)
            if not (self.aspect_range[0] <= aspect <= self.aspect_range[1]):
                continue
            if area / float(bw * bh) < self.min_fill:
                continue

            moments = cv2.moments(contour)
            if moments["m00"] == 0:
                continue
            cx = moments["m10"] / moments["m00"]
            cy = moments["m01"] / moments["m00"]

            faction, maket_box = self._classify(red, blue, (x, y, bw, bh), w, h)
            results.append(Engagement(cx, cy, area, (x, y, bw, bh), faction, maket_box))

        return results

    def _classify(self, red, blue, bbox, w, h):
        """Balonun ustundeki pencerede kirmizi/mavi piksel sayarak tarafi belirler."""
        x, y, bw, bh = bbox
        lo, hi = self.maket_gap
        y0 = int(max(0, y - hi * bh))
        y1 = int(max(0, y - lo * bh))
        pad = int(self.maket_span * bw * 0.5)
        x0 = int(max(0, x + bw / 2 - pad))
        x1 = int(min(w, x + bw / 2 + pad))

        if y1 <= y0 or x1 <= x0:
            return "bilinmiyor", None

        red_px = int(np.count_nonzero(red[y0:y1, x0:x1]))
        blue_px = int(np.count_nonzero(blue[y0:y1, x0:x1]))

        # 15 m'de maket yalnizca birkac piksel; esigi dusuk tutmak sart.
        if max(red_px, blue_px) < 3:
            return "bilinmiyor", (x0, y0, x1 - x0, y1 - y0)
        faction = "dusman" if red_px >= blue_px else "dost"
        return faction, (x0, y0, x1 - x0, y1 - y0)

    def _mask(self, hsv: np.ndarray, color: str) -> np.ndarray:
        mask = None
        for lo, hi in COLOR_RANGES[color]:
            part = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
            mask = part if mask is None else cv2.bitwise_or(mask, part)
        return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._kernel)


def pick_engagement(
    targets: Sequence[Engagement],
    frame_shape: Tuple[int, int],
    engage_unknown: bool = False,
) -> Optional[Engagement]:
    """
    Dusman olarak siniflanan balonlar arasindan merkeze en yakin ve buyuk olani
    secer. Dost hedefler asla dondurulmez - Asama-3'te dost vurmak -10 puandir.
    """
    allowed = {"dusman"} | ({"bilinmiyor"} if engage_unknown else set())
    candidates = [t for t in targets if t.faction in allowed]
    if not candidates:
        return None

    h, w = frame_shape[:2]
    cx0, cy0 = w / 2.0, h / 2.0
    diag = float(np.hypot(w, h))
    max_area = max(t.area for t in candidates)

    def score(t: Engagement) -> float:
        distance = np.hypot(t.cx - cx0, t.cy - cy0) / diag
        size = t.area / max_area
        return distance - 0.35 * size

    return min(candidates, key=score)


def pick_target(
    detections: Sequence[Detection],
    frame_shape: Tuple[int, int],
    prefer_color: Optional[str] = None,
) -> Optional[Detection]:
    """
    Hedef secimi: istenen renk varsa onunla sinirlar, ardindan merkeze en yakin
    ve buyuk olani secer. Merkeze yakinlik oncelikli - taret zaten oraya bakiyor.
    """
    candidates = list(detections)
    if prefer_color:
        filtered = [d for d in candidates if d.color == prefer_color]
        if filtered:
            candidates = filtered
    if not candidates:
        return None

    h, w = frame_shape[:2]
    cx0, cy0 = w / 2.0, h / 2.0
    diag = float(np.hypot(w, h))
    max_area = max(d.area for d in candidates)

    def score(d: Detection) -> float:
        distance = np.hypot(d.cx - cx0, d.cy - cy0) / diag   # 0 = merkez
        size = d.area / max_area                              # 1 = en buyuk
        return distance - 0.35 * size                         # kucuk = iyi

    return min(candidates, key=score)


# ------------------------------------------------------------------ kontrol


class PID:
    """
    Aci hatasindan (derece) istenen donme hizina (derece/sn) ceviren kontrolcu.

    Iki windup korumasi var, ikisi de gercek bir sorunu cozuyor:

    `i_band` - integral ayrimi. Hedef uzaktayken (ornegin 40 derece otede)
    integral hizla buyur ve hedefe varildiginda P terimini iptal edecek kadar
    birikmis olur; taret son bir derecelik hatayi dakikalarca kapatamaz.
    Bu yuzden integral yalnizca hedefe yakinken calisir - zaten gorevi de
    kucuk ve inatci kalici hatayi silmektir.

    `out_limit` - doyum karsiti koruma. Cikis zaten sinirdayken integrali
    buyutmek bir ise yaramaz, sadece geri donuste asma yaratir.
    """

    def __init__(
        self,
        kp: float,
        ki: float = 0.0,
        kd: float = 0.0,
        i_limit: float = 6.0,
        i_band: Optional[float] = 3.0,
        out_limit: Optional[float] = None,
        d_filter: float = 0.6,
    ):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.i_limit = i_limit
        self.i_band = i_band
        self.out_limit = out_limit
        self.d_filter = d_filter
        self._integral = 0.0
        self._prev_error: Optional[float] = None
        self._derivative = 0.0

    def reset(self) -> None:
        self._integral = 0.0
        self._prev_error = None
        self._derivative = 0.0

    def __call__(self, error: float, dt: float) -> float:
        if dt <= 0.0:
            return 0.0

        proportional = self.kp * error

        # Turev: merkez tespiti gurultulu oldugu icin alcak geciren suzgecten gecir
        if self._prev_error is not None:
            raw = (error - self._prev_error) / dt
            self._derivative += (raw - self._derivative) * (1.0 - self.d_filter)
        self._prev_error = error
        derivative = self.kd * self._derivative

        # Integral ayrimi: hedef uzaktayken biriktirme, biriktirdigini de bosalt
        if self.i_band is not None and abs(error) > self.i_band:
            self._integral = 0.0
        else:
            candidate = float(np.clip(self._integral + error * dt, -self.i_limit, self.i_limit))
            # Doyum karsiti: cikis sinirdaysa integrali ayni yonde buyutme
            trial = proportional + self.ki * candidate + derivative
            saturated = self.out_limit is not None and abs(trial) >= self.out_limit
            if not (saturated and np.sign(candidate) == np.sign(trial)):
                self._integral = candidate

        output = proportional + self.ki * self._integral + derivative
        if self.out_limit is not None:
            output = float(np.clip(output, -self.out_limit, self.out_limit))
        return output


class TrackState(Enum):
    SEARCH = "ARAMA"
    TRACK = "TAKIP"
    LOCKED = "KILITLI"


class TurretTracker:
    """
    Kapali cevrim: goruntudeki hedef konumundan taret hiz komutu uretir.

    Kamera namluyla es eksenli oldugu icin goruntu merkezine olan piksel farki
    dogrudan nisan hatasidir - ayri bir kalibrasyon adimi gerekmez.
    """

    def __init__(
        self,
        max_yaw_speed: float = 90.0,
        max_pitch_speed: float = 60.0,
        lock_tolerance_deg: float = 0.6,
        lock_frames: int = 5,
        search_rate: float = 0.25,
        # Taret ±95° donebilir ama atisa izinli sektor ±80° (sartname 4.2:
        # harekete yasak bolge ile atisa yasak bolge ayri seylerdir). Tarama
        # atis yapamayacagi bolgede vakit harcamasin diye dar olani kullaniyoruz.
        yaw_limits: Tuple[float, float] = (-80.0, 80.0),
        search_pitch_deg: float = 3.0,
    ):
        self.max_yaw_speed = max_yaw_speed
        self.max_pitch_speed = max_pitch_speed
        self.lock_tolerance_deg = lock_tolerance_deg
        self.lock_frames = lock_frames
        self.search_rate = search_rate
        self.yaw_limits = yaw_limits
        self.search_pitch_deg = search_pitch_deg

        self.yaw_pid = PID(kp=4.0, ki=0.8, kd=0.15, i_band=3.0, out_limit=max_yaw_speed)
        self.pitch_pid = PID(kp=4.0, ki=0.8, kd=0.15, i_band=3.0, out_limit=max_pitch_speed)

        self.state = TrackState.SEARCH
        self.yaw_error = 0.0
        self.pitch_error = 0.0
        self._on_target_count = 0
        self._search_direction = 1.0
        self._target_key: Optional[str] = None

    def reset(self) -> None:
        self.yaw_pid.reset()
        self.pitch_pid.reset()
        self.state = TrackState.SEARCH
        self._on_target_count = 0
        self._target_key = None

    def update(
        self,
        yaw_error: float,
        pitch_error: float,
        dt: float,
        target_key: Optional[str] = None,
    ) -> Tuple[float, float]:
        """
        Hedef gorunurken cagrilir. Aci hatalarini (derece) alir, normalize
        hiz komutu (-1..1) dondurur.

        `target_key` verilirse hedef degistiginde kontrolcu sifirlanir - eski
        hedefin birikimi yenisine tasinmasin diye.
        """
        # Hedef degisimi: ya kimlik degisti ya da hata aniden sicradi
        jumped = (
            abs(yaw_error - self.yaw_error) > 5.0 or abs(pitch_error - self.pitch_error) > 5.0
        )
        if (target_key is not None and target_key != self._target_key) or jumped:
            self._target_key = target_key
            self.yaw_pid.reset()
            self.pitch_pid.reset()
            self._on_target_count = 0

        self.yaw_error, self.pitch_error = yaw_error, pitch_error

        yaw_speed = self.yaw_pid(yaw_error, dt)
        pitch_speed = self.pitch_pid(pitch_error, dt)

        error_magnitude = float(np.hypot(yaw_error, pitch_error))
        if error_magnitude <= self.lock_tolerance_deg:
            self._on_target_count += 1
        else:
            self._on_target_count = 0

        self.state = (
            TrackState.LOCKED if self._on_target_count >= self.lock_frames else TrackState.TRACK
        )

        return (
            float(np.clip(yaw_speed / self.max_yaw_speed, -1.0, 1.0)),
            float(np.clip(pitch_speed / self.max_pitch_speed, -1.0, 1.0)),
        )

    def search(self, current_yaw: float, current_pitch: float) -> Tuple[float, float]:
        """
        Hedef gorunmuyorken yan eksende suparek tarar.

        Yon degistirme sart: taret yan eksende sinirli (sartname 4.2 hareket
        yasak bolgesi) ve tek yonlu bir tarama sinira dayanip orada takilip
        kalir - hedef parkurdan cikana kadar taret hic donmez.
        """
        if self.state is not TrackState.SEARCH:
            self.state = TrackState.SEARCH
            self._on_target_count = 0
            self.yaw_pid.reset()
            self.pitch_pid.reset()

        lo, hi = self.yaw_limits
        margin = 3.0
        if current_yaw >= hi - margin:
            self._search_direction = -1.0
        elif current_yaw <= lo + margin:
            self._search_direction = 1.0

        # Hedefler ~1.15 m'de, namlu 1.28 m'de: tarama irtifasi hafif asagida.
        pitch_cmd = float(np.clip((self.search_pitch_deg - current_pitch) * 0.1, -0.3, 0.3))
        return self.search_rate * self._search_direction, pitch_cmd

    @property
    def locked(self) -> bool:
        return self.state is TrackState.LOCKED


# ------------------------------------------------------------------ gorsellestirme


FACTION_COLORS = {
    "dusman": (60, 60, 235),      # kirmizi
    "dost": (235, 140, 60),       # mavi
    "bilinmiyor": (140, 140, 140),
}


def draw_engagements(
    frame: np.ndarray,
    targets: Sequence[Engagement],
    selected: Optional[Engagement],
    tracker: "TurretTracker",
    telemetry,
    fps: float = 0.0,
    fire_ready: bool = False,
    target_range: float = float("inf"),
) -> np.ndarray:
    """Balon/maket duzenine gore teshis penceresi."""
    canvas = frame.copy()
    h, w = canvas.shape[:2]
    cx, cy = w // 2, h // 2

    for t in targets:
        colour = FACTION_COLORS.get(t.faction, (140, 140, 140))
        x, y, bw, bh = t.bbox
        chosen = selected is not None and t is selected
        cv2.rectangle(canvas, (x, y), (x + bw, y + bh), colour, 2 if chosen else 1)
        if t.maket_bbox is not None:
            mx, my, mw, mh = t.maket_bbox
            cv2.rectangle(canvas, (mx, my), (mx + mw, my + mh), colour, 1)
        cv2.putText(canvas, t.faction, (x, y + bh + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, colour, 1, cv2.LINE_AA)

    lock = tracker.locked
    reticle = (60, 230, 60) if lock else (200, 200, 200)
    cv2.line(canvas, (cx - 22, cy), (cx - 7, cy), reticle, 1)
    cv2.line(canvas, (cx + 7, cy), (cx + 22, cy), reticle, 1)
    cv2.line(canvas, (cx, cy - 22), (cx, cy - 7), reticle, 1)
    cv2.line(canvas, (cx, cy + 7), (cx, cy + 22), reticle, 1)

    if selected is not None:
        tx, ty = int(selected.cx), int(selected.cy)
        cv2.line(canvas, (cx, cy), (tx, ty), (0, 200, 255), 1)
        cv2.circle(canvas, (tx, ty), 6, (0, 200, 255), 2)
        if lock:
            cv2.circle(canvas, (cx, cy), 26, (60, 230, 60), 2)

    enemies = sum(1 for t in targets if t.faction == "dusman")
    friends = sum(1 for t in targets if t.faction == "dost")
    menzil = "  --  " if target_range == float("inf") else f"{target_range:5.1f} m"
    lines = [
        f"DURUM: {tracker.state.value}" + ("   [ATES]" if fire_ready else ""),
        f"HATA : yaw {tracker.yaw_error:+6.2f}  pitch {tracker.pitch_error:+6.2f} derece",
        f"TARET: yaw {telemetry.yaw:+7.2f}  pitch {telemetry.pitch:+6.2f}   menzil {menzil}",
        f"BALON: dusman {enemies}  dost {friends}   {fps:5.1f} fps",
    ]
    overlay = canvas.copy()
    cv2.rectangle(overlay, (0, 0), (330, 22 + 18 * len(lines)), (0, 0, 0), -1)
    canvas = cv2.addWeighted(overlay, 0.55, canvas, 0.45, 0)
    for i, line in enumerate(lines):
        cv2.putText(canvas, line, (8, 20 + 18 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (230, 230, 230), 1, cv2.LINE_AA)
    return canvas


def draw_overlay(
    frame: np.ndarray,
    detections: Sequence[Detection],
    target: Optional[Detection],
    tracker: TurretTracker,
    telemetry,
    fps: float = 0.0,
) -> np.ndarray:
    """Teshis penceresi icin tespitleri ve durumu goruntunun uzerine cizer."""
    canvas = frame.copy()
    h, w = canvas.shape[:2]
    cx, cy = w // 2, h // 2

    for d in detections:
        x, y, bw, bh = d.bbox
        colour = DRAW_COLORS.get(d.color, (200, 200, 200))
        is_target = target is not None and d is target
        cv2.rectangle(canvas, (x, y), (x + bw, y + bh), colour, 2 if is_target else 1)
        if not is_target:
            cv2.putText(canvas, d.color, (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, colour, 1)

    # Nisangah
    lock = tracker.locked
    reticle = (60, 230, 60) if lock else (200, 200, 200)
    cv2.line(canvas, (cx - 22, cy), (cx - 7, cy), reticle, 1)
    cv2.line(canvas, (cx + 7, cy), (cx + 22, cy), reticle, 1)
    cv2.line(canvas, (cx, cy - 22), (cx, cy - 7), reticle, 1)
    cv2.line(canvas, (cx, cy + 7), (cx, cy + 22), reticle, 1)

    if target is not None:
        tx, ty = int(target.cx), int(target.cy)
        cv2.line(canvas, (cx, cy), (tx, ty), (0, 200, 255), 1)
        cv2.circle(canvas, (tx, ty), 6, (0, 200, 255), 2)
        if lock:
            cv2.circle(canvas, (cx, cy), 26, (60, 230, 60), 2)

    # Durum satirlari
    lines = [
        f"DURUM: {tracker.state.value}",
        f"HATA : yaw {tracker.yaw_error:+6.2f}  pitch {tracker.pitch_error:+6.2f} derece",
        f"TARET: yaw {telemetry.yaw:+7.2f}  pitch {telemetry.pitch:+6.2f} derece",
        f"AKIS : {fps:5.1f} fps   hedef: {len(detections)}",
    ]
    overlay = canvas.copy()
    cv2.rectangle(overlay, (0, 0), (330, 22 + 18 * len(lines)), (0, 0, 0), -1)
    canvas = cv2.addWeighted(overlay, 0.55, canvas, 0.45, 0)

    for i, line in enumerate(lines):
        cv2.putText(canvas, line, (8, 20 + 18 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (230, 230, 230), 1, cv2.LINE_AA)

    return canvas
