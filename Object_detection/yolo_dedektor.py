"""
YOLO tabanli hedef tespiti + guvenli model yukleme.

NEDEN BU DOSYA VAR
------------------
1) .engine dosyalari TASINABILIR DEGILDIR. TensorRT motoru, derlendigi GPU
   mimarisine ve TensorRT surumune kilitlenir. Baska bir kartta (or. Colab'in
   T4'unde derlenip buradaki RTX 4050'de acilinca) TensorRT once

       "Using an engine plan file across different models of devices is not
        supported and is likely to affect performance or even cause errors"

   uyarisini basar, sonra SEGMENTATION FAULT ile tum python surecini oldurur.
   Bu bir python istisnasi degildir; try/except ile yakalanamaz. Tek guvenli
   yol motoru AYRI BIR SURECTE denemektir - cocuk surec cokerse ana program
   yasar ve .pt dosyasina duser.

2) otonom_takip.py ve realtime_detect.py ayni modeli kullanabilsin diye
   tespit katmani burada tek yerde toplanmistir.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

import numpy as np

# tracker.py'deki Detection ile ayni alanlar: otonom_takip.py'nin cizim ve
# takip kodu iki dedektoru de ayirt etmeden kullanabilsin.
_SIM_DIR = Path(__file__).resolve().parent.parent / "Similasyon_Kullanım"
if str(_SIM_DIR) not in sys.path:
    sys.path.insert(0, str(_SIM_DIR))

from tracker import Detection  # noqa: E402

try:
    from sahi import AutoDetectionModel
    from sahi.predict import get_sliced_prediction
    SAHI_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    AutoDetectionModel = None  # type: ignore[assignment]
    get_sliced_prediction = None  # type: ignore[assignment]
    SAHI_AVAILABLE = False

#: Sinif adlarini cizim rengine esler (tracker.DRAW_COLORS anahtarlari).
SINIF_RENKLERI = ["red", "yellow", "green", "blue"]

#: Motor deneme sonuclarinin saklandigi yer: her calistirmada 5 saniyelik
#: deneme surecini tekrar odememek icin.
ONBELLEK = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) \
    / "celik_kubbe" / "engine_denemeleri.json"


# --------------------------------------------------------------------------
# GUVENLI MODEL YUKLEME
# --------------------------------------------------------------------------

def _dosya_kimligi(yol: Path) -> str:
    """Dosyayi ve calisma ortamini tanimlayan anahtar."""
    st = yol.stat()
    try:
        import tensorrt
        trt = tensorrt.__version__
    except Exception:
        trt = "yok"
    return f"{yol}|{st.st_size}|{int(st.st_mtime)}|trt{trt}|py{sys.version_info[:2]}"


def _onbellek_oku() -> dict:
    try:
        return json.loads(ONBELLEK.read_text())
    except Exception:
        return {}


def _onbellek_yaz(veri: dict) -> None:
    try:
        ONBELLEK.parent.mkdir(parents=True, exist_ok=True)
        ONBELLEK.write_text(json.dumps(veri, indent=1))
    except Exception:
        pass


def motoru_dene(yol: Path, zaman_asimi: float = 180.0) -> tuple:
    """Bir .engine dosyasini AYRI SURECTE acmayi dener.

    Donen: (calisiyor_mu, aciklama)

    Cocuk surec segfault ile olurse returncode negatif (sinyal) gelir; boylece
    uyumsuz motoru ana surec cokmeden anlayabiliyoruz.
    """
    anahtar = _dosya_kimligi(yol)
    onbellek = _onbellek_oku()
    if anahtar in onbellek:
        kayit = onbellek[anahtar]
        return kayit["ok"], kayit["mesaj"] + " (onbellekten)"

    kod = (
        "import sys, warnings; warnings.filterwarnings('ignore');\n"
        "from ultralytics import YOLO\n"
        "m = YOLO(sys.argv[1]); m.predict(__import__('numpy').zeros((640,640,3),'uint8'),"
        " verbose=False)\n"
        "print('CALISIYOR')\n"
    )
    try:
        p = subprocess.run([sys.executable, "-c", kod, str(yol)],
                           capture_output=True, text=True, timeout=zaman_asimi)
    except subprocess.TimeoutExpired:
        sonuc = (False, f"motor {zaman_asimi:.0f} sn icinde acilmadi (takildi)")
    else:
        if p.returncode == 0 and "CALISIYOR" in p.stdout:
            sonuc = (True, "motor bu makinede calisiyor")
        elif p.returncode < 0:
            sonuc = (False,
                     f"motor surec coktu (sinyal {-p.returncode}) - bu motor "
                     f"BASKA BIR GPU/TensorRT surumunde derlenmis")
        else:
            son = (p.stderr.strip().splitlines() or ["bilinmeyen hata"])[-1]
            sonuc = (False, f"motor acilmadi: {son[:160]}")

    onbellek[anahtar] = {"ok": sonuc[0], "mesaj": sonuc[1], "zaman": time.time()}
    _onbellek_yaz(onbellek)
    return sonuc


def yedek_agirlik(yol: Path) -> Optional[Path]:
    """Bir .engine'in yanindaki ayni isimli .pt dosyasini bulur."""
    aday = yol.with_suffix(".pt")
    if aday.exists():
        return aday
    # "best (05.08).engine" -> "best (05.08).pt" zaten yukarida denendi;
    # ".yerel.engine" gibi ek uzantilar icin govdeyi kirp.
    govde = yol.name.split(".")[0]
    for p in sorted(yol.parent.glob(f"{govde}*.pt")):
        return p
    return None


def model_yolu_sec(yol: str, sessiz: bool = False) -> str:
    """Verilen agirligi dogrular; .engine acilmiyorsa .pt'ye duser.

    Donen: gercekten yuklenebilecek dosya yolu.
    """
    p = Path(yol)
    if not p.exists():
        raise FileNotFoundError(f"Model bulunamadi: {yol}")
    if p.suffix != ".engine":
        return str(p)

    calisiyor, mesaj = motoru_dene(p)
    if calisiyor:
        if not sessiz:
            print(f"[model] TensorRT motoru kullaniliyor ({mesaj})")
        return str(p)

    yedek = yedek_agirlik(p)
    if not sessiz:
        print(f"[model] UYARI: {p.name} kullanilamiyor - {mesaj}")
    if yedek is None:
        raise RuntimeError(
            f"{p.name} bu makinede acilamiyor ve yaninda .pt yedegi yok.\n"
            f"Cozum: motoru BU bilgisayarda yeniden uret:\n"
            f"  yolo export model=<model>.pt format=engine half=True device=0"
        )
    if not sessiz:
        print(f"[model] Bunun yerine {yedek.name} (PyTorch) yukleniyor.")
        print("[model] TensorRT hizini geri kazanmak icin motoru BU makinede uret:")
        print(f"        yolo export model='{yedek}' format=engine half=True device=0")
    return str(yedek)


# --------------------------------------------------------------------------
# DEDEKTOR
# --------------------------------------------------------------------------

@dataclass
class YoloDetection(Detection):
    """tracker.Detection + sinif adi ve guven skoru."""

    label: str = ""
    score: float = 0.0


class YoloTargetDetector:
    """YOLO ile hedef bulur; ColorTargetDetector ile ayni arayuzu sunar.

    detect(kare) -> List[Detection benzeri]
    Boylece otonom_takip.py'nin takip dongusu degismeden calisir.
    """

    def __init__(
        self,
        model_yolu: str,
        conf: float = 0.35,
        siniflar: Optional[Sequence[str]] = None,
        device: str = "",
        imgsz: int = 640,
        sessiz: bool = False,
        use_sahi: bool = False,
        slice_size: int = 640,
        overlap_ratio: float = 0.2,
    ):
        from ultralytics import YOLO   # agir import: yalnizca gerekince

        self.yol = model_yolu_sec(model_yolu, sessiz=sessiz)
        self.model = YOLO(self.yol)
        self.conf = conf
        self.imgsz = imgsz
        self.device = device if device != "" else None
        self.use_sahi = bool(use_sahi and SAHI_AVAILABLE)
        self.slice_size = max(128, int(slice_size))
        self.overlap_ratio = float(overlap_ratio)
        self._sahi_model = None

        if self.use_sahi:
            self._sahi_model = self._build_sahi()
            if not sessiz:
                print(f"[model] SAHI aktif - dilim {self.slice_size}px, ortusme {self.overlap_ratio:.0%}")
        elif use_sahi and not SAHI_AVAILABLE:
            print("[model] UYARI: SAHI kurulumu yok; normal YOLO tespiti kullaniliyor.")

        # {0: 'drone', 1: 'helicopter', ...}
        self.names = dict(self.model.names)
        self._renk = {i: SINIF_RENKLERI[i % len(SINIF_RENKLERI)] for i in self.names}

        # Sinif suzgeci: adlari indekse cevir (--sinif drone,plane)
        self.sinif_indeksleri = None
        if siniflar:
            istenen = {s.strip().lower() for s in siniflar if s.strip()}
            self.sinif_indeksleri = [i for i, ad in self.names.items()
                                     if ad.lower() in istenen]
            if not self.sinif_indeksleri:
                raise ValueError(
                    f"Bu modelde su siniflar yok: {sorted(istenen)}. "
                    f"Mevcut: {sorted(self.names.values())}")

        if not sessiz:
            print(f"[model] {Path(self.yol).name} | siniflar: "
                  f"{', '.join(self.names[i] for i in sorted(self.names))}")

    def _build_sahi(self):
        if not SAHI_AVAILABLE:
            return None

        device = self.device
        if device is None:
            try:
                import torch
                device = "cuda:0" if torch.cuda.is_available() else "cpu"
            except Exception:
                device = "cpu"

        for model_type in ("ultralytics", "yolov8"):
            try:
                return AutoDetectionModel.from_pretrained(
                    model_type=model_type,
                    model_path=self.yol,
                    confidence_threshold=self.conf,
                    device=device,
                )
            except (ValueError, KeyError, ImportError):
                continue
        return None

    def detect(self, kare: np.ndarray) -> List[Detection]:
        if self._sahi_model is not None:
            result = get_sliced_prediction(
                image=kare,
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

            bulunan: List[Detection] = []
            for pred in result.object_prediction_list:
                bbox = pred.bbox
                x1, y1, x2, y2 = float(bbox.minx), float(bbox.miny), float(bbox.maxx), float(bbox.maxy)
                g, y = x2 - x1, y2 - y1
                cid = getattr(pred.category, "id", 0)
                label = str(getattr(pred.category, "name", self.names.get(int(cid), str(cid))))
                bulunan.append(YoloDetection(
                    color=self._renk.get(int(cid), "red"),
                    cx=(x1 + x2) / 2.0,
                    cy=(y1 + y2) / 2.0,
                    area=max(0.0, g) * max(0.0, y),
                    bbox=(int(x1), int(y1), int(g), int(y)),
                    label=label,
                    score=float(pred.score.value),
                ))
            return bulunan

        sonuc = self.model.predict(
            kare,
            conf=self.conf,
            imgsz=self.imgsz,
            device=self.device,
            classes=self.sinif_indeksleri,
            verbose=False,
        )[0]

        bulunan: List[Detection] = []
        kutular = sonuc.boxes
        if kutular is None or len(kutular) == 0:
            return bulunan

        xyxy = kutular.xyxy.cpu().numpy()
        skorlar = kutular.conf.cpu().numpy()
        idler = kutular.cls.int().cpu().numpy()

        for (x1, y1, x2, y2), skor, cid in zip(xyxy, skorlar, idler):
            g, y = float(x2 - x1), float(y2 - y1)
            bulunan.append(YoloDetection(
                color=self._renk.get(int(cid), "red"),
                cx=float(x1) + g / 2.0,
                cy=float(y1) + y / 2.0,
                area=g * y,
                bbox=(int(x1), int(y1), int(g), int(y)),
                label=self.names.get(int(cid), str(cid)),
                score=float(skor),
            ))
        return bulunan
