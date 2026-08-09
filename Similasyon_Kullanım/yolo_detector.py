"""
YOLO tabanli hedef tespiti - `BalloonTargetDetector` ile ayni imza.

`detect(frame) -> List[Engagement]` dondurdugu icin kontrol katmani (pick_engagement,
TurretTracker, draw_engagements) hic degismeden calisir.

Isleyis, sartname 5.4'un kurdugu tuzagi HSV dedektoruyle ayni sirayla cozer -
sadece renk esikleme yerine model kullanir:

  1. Nisan noktasi balondur (imha yalnizca balondan sayilir, menzil de balonun
     bilinen capindan kestirilir).
  2. Dost/dusman ayrimi balonun ustundeki maketten gelir; "kirmizi leke = dusman"
     varsayimi dogrudan dost atesine goturur.

Model her iki sinifi da (balon + maket) veriyorsa esleme tamamen YOLO ile yapilir.
Model yalnizca maket siniflari iceriyorsa balonu HSV dedektoru bulur, tarafi YOLO
soyler - modelin guclu oldugu is siniflandirma, balonun daire geometrisi zaten
renkle kararli cikiyor.

Sinif adlari modelden modele degistigi icin eslestirme disaridan verilebilir
(`--balloon-classes`, `--enemy-classes`, `--friend-classes`).
"""

from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from tracker import BalloonTargetDetector, Engagement

try:
    from ultralytics import YOLO
except ImportError:  # kurulu degilse anlasilir hata icin main'de kontrol edilir
    YOLO = None

try:
    from sahi import AutoDetectionModel
    from sahi.predict import get_sliced_prediction
    SAHI_AVAILABLE = True
except ImportError:
    SAHI_AVAILABLE = False


# Varsayilan sinif adi sozlukleri. Normalize edilmis (kucuk harf, Turkce
# karakterler sadelestirilmis) hallerine bakilir.
BALLOON_NAMES = ("balon", "balloon", "balon_kirmizi", "red_balloon")
ENEMY_NAMES = ("dusman", "dusman_maket", "enemy", "hostile", "red", "kirmizi")
FRIEND_NAMES = ("dost", "dost_maket", "friend", "friendly", "blue", "mavi")

# Yalnizca hedef TIPINI veren siniflar (Object_detection'daki model boyle:
# drone/helicopter/plane/rocket). Bu siniflar dost/dusman ayrimi yapmaz - taraf
# maketin renginden gelir, tip yalnizca etiket olarak tasinir.
TYPE_NAMES = (
    "drone", "dron", "iha", "mini_iha", "uav", "quadcopter",
    "helicopter", "helikopter", "heli",
    "plane", "ucak", "f16", "jet",
    "rocket", "fuze", "missile", "balistik_fuze",
    "maket", "hedef", "target",
    # Tipi secilemeyen hedef de bir hedeftir; taraf zaten renkten geldigi icin
    # bunu elemek gereksiz yere menzil disi birakir.
    "undefined", "unknown", "bilinmeyen",
)


def _norm(name: str) -> str:
    """Sinif adini karsilastirilabilir hale getirir: 'Düşman Maket' -> 'dusman_maket'."""
    text = unicodedata.normalize("NFKD", str(name).strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    for src, dst in (("ı", "i"), ("ş", "s"), ("ğ", "g"), ("ç", "c"), ("ö", "o"), ("ü", "u")):
        text = text.replace(src, dst)
    return "_".join(text.replace("-", " ").replace("_", " ").split())


@dataclass
class _Box:
    """Modelden gelen ham kutu."""

    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    name: str
    track_id: Optional[int] = None

    @property
    def bbox(self) -> Tuple[int, int, int, int]:
        return int(self.x1), int(self.y1), int(self.x2 - self.x1), int(self.y2 - self.y1)

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2.0

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)


class _Voter:
    """
    Iz basina guven-agirlikli oylama (taraf ve hedef tipi icin ayri ayri).

    Dedektor kare kare karari titretebilir; dost atesi -10 puan oldugu icin tek
    karelik bir "dusman" tahmini yeterli sayilmamali. Yeterli oy toplanana kadar
    anlik tahmin kullanilir, sonrasinda kumulatif cogunluk.
    """

    def __init__(self, min_votes: int = 3, forget_frames: int = 120):
        self._hist: Dict[int, Counter] = defaultdict(Counter)
        self._seen: Dict[int, int] = {}
        self._votes: Dict[int, int] = defaultdict(int)
        self._min_votes = min_votes
        self._forget = forget_frames
        self._frame = 0

    def vote(self, track_id: int, choice: str, weight: float) -> str:
        self._hist[track_id][choice] += float(weight)
        self._votes[track_id] += 1
        self._seen[track_id] = self._frame
        if self._votes[track_id] < self._min_votes:
            return choice
        return self._hist[track_id].most_common(1)[0][0]

    def tick(self) -> None:
        self._frame += 1
        if self._frame % 60:
            return
        stale = [t for t, f in self._seen.items() if self._frame - f > self._forget]
        for t in stale:
            self._hist.pop(t, None)
            self._seen.pop(t, None)
            self._votes.pop(t, None)


class YoloTargetDetector:
    """YOLO tabanli balon/maket dedektoru."""

    def __init__(
        self,
        weights: str,
        conf: float = 0.25,
        iou: float = 0.7,
        imgsz: int = 640,
        device: str = "",
        balloon_classes: Sequence[str] = BALLOON_NAMES,
        enemy_classes: Sequence[str] = ENEMY_NAMES,
        friend_classes: Sequence[str] = FRIEND_NAMES,
        type_classes: Sequence[str] = TYPE_NAMES,
        use_sahi: bool = False,
        slice_size: int = 512,
        overlap_ratio: float = 0.2,
        use_track: bool = False,
        tracker_cfg: str = "bytetrack.yaml",
        vote_frames: int = 3,
        fallback: Optional[BalloonTargetDetector] = None,
        crop_classify: bool = True,
        crop_conf: float = 0.05,
        crop_refresh: int = 10,
        maket_only: bool = True,
        maket_size_m: float = 0.50,
        maket_gap: float = 2.0,
        maket_span: float = 1.5,
        verbose: bool = True,
    ):
        if YOLO is None:
            raise SystemExit(
                "[HATA] ultralytics kurulu degil. 'pip install ultralytics' calistirin."
            )

        self.conf = conf
        self.iou = iou
        self.imgsz = imgsz
        self.device = device or None
        self.use_track = use_track
        self.tracker_cfg = tracker_cfg
        self.fallback = fallback
        self.crop_classify = crop_classify
        self.crop_conf = crop_conf
        self.crop_refresh = max(1, crop_refresh)
        self._label_cache: Dict[Tuple[int, int], Tuple[str, float, Tuple[int, int, int, int], int]] = {}
        self._crop_frame = 0
        self.maket_only = maket_only
        self.maket_size_m = maket_size_m
        self.maket_gap = maket_gap      # balon/maket yuksekliginin kati - dikey arama payi
        self.maket_span = maket_span    # kutu genisliginin kati - yatay hizalama payi

        self._roles: Dict[str, str] = {}
        for group, role in ((balloon_classes, "balon"),
                            (enemy_classes, "dusman"),
                            (friend_classes, "dost"),
                            (type_classes, "maket")):
            for name in group:
                self._roles[_norm(name)] = role

        print(f"[BILGI] YOLO modeli yukleniyor: {weights}")
        self._model = YOLO(weights)
        self._names = {int(k): str(v) for k, v in self._model.names.items()}

        self._sahi_model = None
        if use_sahi:
            if not SAHI_AVAILABLE:
                print("[UYARI] sahi kurulu degil ('pip install sahi'), tek gecisli "
                      "cikarim kullanilacak.")
            elif use_track:
                # SAHI dilim dilim NMS yapar, iz kimligi uretmez.
                print("[UYARI] SAHI ile iz takibi birlikte calismaz; --yolo-track yok sayildi.")
            if SAHI_AVAILABLE:
                self._sahi_model = self._build_sahi(weights, conf)
                self.use_track = False
                self.slice_size = slice_size
                self.overlap_ratio = overlap_ratio
                print(f"[BILGI] SAHI aktif - dilim {slice_size}px, ortusme {overlap_ratio:.0%}")

        self._voter = _Voter(min_votes=vote_frames) if self.use_track else None
        self._label_voter = _Voter(min_votes=vote_frames) if self.use_track else None
        if verbose:
            self._report_classes()

    # ------------------------------------------------------------ kurulum

    def _build_sahi(self, weights: str, conf: float):
        # SAHI, ultralytics'ten farkli olarak cihazi kendisi secmez; bos birakilirsa
        # CPU'ya duser ve dilimli cikarim saniyelere cikar.
        device = self.device
        if not device:
            try:
                import torch
                device = "cuda:0" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        # sahi 0.12+ 'ultralytics', eski surumler 'yolov8' bekliyor.
        for model_type in ("ultralytics", "yolov8"):
            try:
                return AutoDetectionModel.from_pretrained(
                    model_type=model_type,
                    model_path=weights,
                    confidence_threshold=conf,
                    device=device,
                )
            except (ValueError, KeyError, ImportError):
                continue
        print("[UYARI] SAHI modeli kurulamadi, tek gecisli cikarim kullanilacak.")
        return None

    def _report_classes(self) -> None:
        mapping = {name: self._roles.get(_norm(name)) for name in self._names.values()}
        matched = {n: r for n, r in mapping.items() if r}
        ignored = [n for n, r in mapping.items() if not r]

        if not matched:
            raise SystemExit(
                "[HATA] Modelin siniflari ('" + "', '".join(self._names.values()) + "') "
                "bilinen rollerle eslesmedi.\n"
                "       --balloon-classes / --enemy-classes / --friend-classes / "
                "--type-classes ile eslestirmeyi verin."
            )

        print("[BILGI] Sinif eslesmesi: "
              + ", ".join(f"{n} -> {r}" for n, r in matched.items()))
        if ignored:
            print(f"[BILGI] Yok sayilan siniflar: {', '.join(ignored)}")

        if not any(r == "balon" for r in matched.values()):
            source = "HSV yedek dedektoru" if self.fallback is not None else "maket kutusu"
            print(f"[BILGI] Modelde balon sinifi yok; nisan noktasi {source} ile bulunacak.")

        if not any(r in ("dusman", "dost") for r in matched.values()):
            # Tip modeli (drone/helicopter/plane/rocket) dost/dusman ayrimi yapmaz.
            # Ayrimi maket renginden HSV dedektoru yapar; yedek kapaliysa hicbir
            # hedef "dusman" olarak isaretlenemez.
            if self.fallback is not None:
                print("[BILGI] Modelde dost/dusman sinifi yok; taraf ayrimi maket "
                      "renginden (HSV) yapilacak, model yalnizca hedef tipini verir.")
            else:
                print("[UYARI] Modelde dost/dusman sinifi yok ve HSV yedegi kapali - "
                      "tum hedefler 'bilinmiyor' kalir. --engage-unknown olmadan "
                      "ates edilmez.")

    # ------------------------------------------------------------ cikarim

    def _infer(self, frame: np.ndarray) -> List[_Box]:
        if self._sahi_model is not None:
            result = get_sliced_prediction(
                image=frame,
                detection_model=self._sahi_model,
                slice_height=self.slice_size,
                slice_width=self.slice_size,
                overlap_height_ratio=self.overlap_ratio,
                overlap_width_ratio=self.overlap_ratio,
                postprocess_type="NMS",
                postprocess_match_metric="IOU",
                postprocess_match_threshold=0.5,
                verbose=0,
            )
            return [
                _Box(p.bbox.minx, p.bbox.miny, p.bbox.maxx, p.bbox.maxy,
                     float(p.score.value), str(p.category.name))
                for p in result.object_prediction_list
            ]

        if self.use_track:
            # persist=True ardisik karelerde iz durumunu korur - kare akisi
            # kesintisiz oldugu icin burada dogru secim.
            result = self._model.track(
                frame, persist=True, tracker=self.tracker_cfg, imgsz=self.imgsz,
                conf=self.conf, iou=self.iou, device=self.device, verbose=False,
            )[0]
        else:
            result = self._model.predict(
                frame, imgsz=self.imgsz, conf=self.conf, iou=self.iou,
                device=self.device, verbose=False,
            )[0]

        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return []

        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().tolist()
        clss = boxes.cls.int().cpu().tolist()
        ids = boxes.id.int().cpu().tolist() if boxes.id is not None else [None] * len(clss)

        return [
            _Box(float(b[0]), float(b[1]), float(b[2]), float(b[3]),
                 float(cf), self._names.get(int(cid), str(cid)), tid)
            for b, cf, cid, tid in zip(xyxy, confs, clss, ids)
        ]

    # ------------------------------------------------------------- tespit

    def detect(self, frame: np.ndarray) -> List[Engagement]:
        boxes = self._infer(frame)
        if self._voter is not None:
            self._voter.tick()
            self._label_voter.tick()

        balloons: List[_Box] = []
        makets: List[Tuple[_Box, str]] = []
        for box in boxes:
            role = self._roles.get(_norm(box.name))
            if role == "balon":
                balloons.append(box)
            elif role in ("dusman", "dost", "maket"):
                # "maket" rolu yalnizca tip verir; taraf renk katmanindan gelir.
                faction = role if role != "maket" else "bilinmiyor"
                if self._voter is not None and box.track_id is not None:
                    if faction != "bilinmiyor":
                        faction = self._voter.vote(box.track_id, faction, box.score)
                    # Etiket de titremesin: hedef tipi iz boyunca oylanir.
                    box.name = self._label_voter.vote(box.track_id, box.name, box.score)
                makets.append((box, faction))

        results: List[Engagement] = []

        if balloons:
            for balloon in balloons:
                faction, maket = self._pair(balloon.bbox, makets)
                results.append(Engagement(
                    cx=balloon.cx, cy=balloon.cy, area=balloon.area, bbox=balloon.bbox,
                    faction=faction, maket_bbox=maket[0].bbox if maket else None,
                    label=maket[0].name if maket else balloon.name,
                    score=min(balloon.score, maket[0].score) if maket else balloon.score,
                    track_id=balloon.track_id,
                ))
        elif self.fallback is not None:
            # Model balonu goremedi (ya sinifi yok ya da bu karede kacirdi):
            # nisan noktasini renk dedektoru bulsun, tarafi YOLO soylesin.
            for eng in self.fallback.detect(frame):
                faction, maket = self._pair(eng.bbox, makets)
                if faction == "bilinmiyor":
                    faction = eng.faction  # YOLO maketi eslemedi -> renk yedegi
                results.append(Engagement(
                    cx=eng.cx, cy=eng.cy, area=eng.area, bbox=eng.bbox,
                    faction=faction,
                    maket_bbox=maket[0].bbox if maket else eng.maket_bbox,
                    label=maket[0].name if maket else "",
                    score=maket[0].score if maket else 0.0,
                    track_id=maket[0].track_id if maket else None,
                ))

        # Hicbir balon bulunamadiysa maketin kendisine nisan al. Menzil bu durumda
        # maketin kaba boyundan kestirildigi icin balona gore daha az guvenilir.
        if not results and self.maket_only:
            for maket, faction in makets:
                results.append(Engagement(
                    cx=maket.cx, cy=maket.cy, area=maket.area, bbox=maket.bbox,
                    faction=faction, maket_bbox=maket.bbox,
                    label=f"{maket.name} (maket)", score=maket.score,
                    size_m=self.maket_size_m, track_id=maket.track_id,
                ))

        # Tipi hala bos olan hedefler icin ikinci gecis.
        if self.crop_classify:
            self._classify_crops(frame, results)

        return results

    # ------------------------------------------------- kirpma ile siniflandirma

    def _classify_crops(self, frame: np.ndarray, results: List[Engagement]) -> None:
        """
        Tipi belirlenemeyen her balonun ustundeki bolgeyi kirpip modele yeniden
        sorar ve etiketi yerine yazar.

        Neden gerekli: 15 m'deki maket tam karede birkac on piksel; model o
        olcekte ya hic kutu uretmiyor ya da guveni esigin altinda kaliyor. Kirpilan
        bolge cikarim boyutuna (imgsz) buyutuldugu icin maket buyuk gorunur ve
        siniflandirma isabeti belirgin artar. SAHI'nin dilimleme fikri ile ayni,
        ama tum kareyi dilimlemek yerine yalnizca balonun ustune bakar - maliyeti
        hedef basina tek kucuk cikarim.

        Sartname Yetenek 6 arayuzde hedef tipinin gosterilmesini istiyor; taraf
        ayrimi yine maket renginden gelir, buradan yalnizca tip yazilir.
        """
        pending = [e for e in results if not e.label]
        if not pending:
            return

        self._crop_frame += 1
        if self._crop_frame % 120 == 0:
            self._prune_cache()

        h, w = frame.shape[:2]
        crops, origins, owners = [], [], []

        for eng in pending:
            bx, by, bw, bh = eng.bbox

            # Tip her karede yeniden sorulmaz: hedefin tipi kare kare degismiyor,
            # ama ikinci cikarim kare hizini dusuruyor. Onbellek hedefin kaba
            # konumuna gore tutulur ve birkac karede bir tazelenir.
            cached = self._label_cache.get(self._cache_key(eng))
            if cached is not None and self._crop_frame - cached[3] < self.crop_refresh:
                eng.label, eng.score = cached[0], cached[1]
                dx, dy, mw, mh = cached[2]
                eng.maket_bbox = (int(bx + dx), int(by + dy), mw, mh)
                continue

            bcx = bx + bw / 2.0
            half = max(self.maket_span * bw, 12.0)
            x0 = int(max(0, bcx - half))
            x1 = int(min(w, bcx + half))
            # Balonun biraz ustunden basla, tepesini de al: maket kutusu cogu
            # zaman balonla ust uste biniyor.
            y0 = int(max(0, by - self.maket_gap * max(bh, 8) - bh))
            y1 = int(min(h, by + 0.4 * bh))
            if x1 - x0 < 8 or y1 - y0 < 8:
                continue
            crops.append(frame[y0:y1, x0:x1])
            origins.append((x0, y0))
            owners.append(eng)

        if not crops:
            return

        # Tek cagride topluca: her hedef icin ayri predict cagirmak kare basina
        # birkac milisaniyeyi bosa harcar.
        preds = self._model.predict(crops, imgsz=self.imgsz, conf=self.crop_conf,
                                    iou=self.iou, device=self.device, verbose=False)

        for eng, (x0, y0), pred in zip(owners, origins, preds):
            best, best_score, best_role = None, 0.0, None
            boxes = pred.boxes
            if boxes is None or len(boxes) == 0:
                continue
            for box, cf, cid in zip(boxes.xyxy.cpu().numpy(), boxes.conf.cpu().tolist(),
                                    boxes.cls.int().cpu().tolist()):
                name = self._names.get(int(cid), str(cid))
                role = self._roles.get(_norm(name))
                if role in ("dusman", "dost", "maket") and cf > best_score:
                    best, best_score, best_role = (box, name), cf, role

            if best is None:
                continue

            box, name = best
            mx, my = int(x0 + box[0]), int(y0 + box[1])
            mw, mh = int(box[2] - box[0]), int(box[3] - box[1])

            eng.label = name
            eng.score = float(best_score)
            eng.maket_bbox = (mx, my, mw, mh)
            # Model taraf da soyluyorsa ve renk katmani karar verememisse kullan.
            if best_role in ("dusman", "dost") and eng.faction == "bilinmiyor":
                eng.faction = best_role

            # Maket kutusu balona gore saklanir; hedef hareket ederken onbellekten
            # cizilen kutu da onunla birlikte kayar.
            bx, by = eng.bbox[0], eng.bbox[1]
            self._label_cache[self._cache_key(eng)] = (
                name, float(best_score), (mx - bx, my - by, mw, mh), self._crop_frame,
            )

    def _cache_key(self, eng: Engagement) -> Tuple[int, int]:
        if eng.track_id is not None:
            return (-1, int(eng.track_id))
        return (int(eng.cx) // 32, int(eng.cy) // 32)

    def _prune_cache(self) -> None:
        stale = [k for k, v in self._label_cache.items()
                 if self._crop_frame - v[3] > 10 * self.crop_refresh]
        for k in stale:
            self._label_cache.pop(k, None)

    def _pair(
        self,
        balloon_bbox: Tuple[int, int, int, int],
        makets: Sequence[Tuple[_Box, str]],
    ) -> Tuple[str, Optional[Tuple[_Box, str]]]:
        """Balonun hemen ustundeki maketi bulur; yoksa taraf 'bilinmiyor' kalir."""
        bx, by, bw, bh = balloon_bbox
        bcx = bx + bw / 2.0

        best: Optional[Tuple[_Box, str]] = None
        best_gap = float("inf")

        for maket, faction in makets:
            mx, my, mw, mh = maket.bbox
            if abs((mx + mw / 2.0) - bcx) > self.maket_span * max(bw, mw):
                continue

            # Maket balonun ustunde olmali - asagidaki bir kutu baska bir hedefe aittir.
            if my + mh / 2.0 >= by + bh / 2.0:
                continue

            # Maketin alt kenari ile balonun ust kenari arasindaki bosluk. Negatif
            # deger ust uste binmedir ve normaldir: cogu model maketi balonu (hatta
            # direği) de kapsayacak sekilde kutular. Ust uste binmeye maketin kendi
            # boyu kadar izin veriyoruz; ustteki merkez sarti zaten yon garantisi.
            gap = by - (my + mh)
            if gap < -mh or gap > self.maket_gap * max(bh, mh, 1):
                continue
            if abs(gap) < abs(best_gap):
                best, best_gap = (maket, faction), gap

        return (best[1], best) if best is not None else ("bilinmiyor", None)
