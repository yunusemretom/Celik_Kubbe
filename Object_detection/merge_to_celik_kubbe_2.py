#!/usr/bin/env python3
"""
Forklanan iki Universe setini celik_kubbe_2 projesine birlestirir.

  - bird iceren goruntuler tamamen atilir
  - sinif isimleri celik_kubbe_2 semasina esitlenir
  - ayni videodan gelen ardisik kareler ayni split'e sabitlenir (leakage onlemi)
  - her sey tek bir batch altina yuklenir, boylece geri alinabilir

Kurulum:
    pip install roboflow pillow

Calistirma:
    export ROBOFLOW_API_KEY="..."      # app.roboflow.com > Settings > API Keys
    python merge_to_celik_kubbe_2.py --dry-run    # once bunu calistirin
    python merge_to_celik_kubbe_2.py              # sonra gercegini
"""

import argparse
import hashlib
import os
import random
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image
from roboflow import Roboflow

WORKSPACE = "egitim-i2v3l"
TARGET_PROJECT = "celik_kubbe_2"
BATCH_NAME = "universe-merge-2026-08"

SOURCES = [
    ("multiclass-missile-9gioj", 1),
    ("aerial-images-vugjs-culgv", 1),
]

# ---------------------------------------------------------------------------
# SINIF ESLEME
#
# "DROP_IMAGE" -> bu sinifi iceren goruntu tamamen atilir
# "DROP_LABEL" -> etiket silinir ama goruntu kalir (nesne arka plan olarak ogrenilir)
# ---------------------------------------------------------------------------
CLASS_MAP = {
    "airplane":  "plane",
    "plane":     "plane",
    "drone":     "drone",
    "helicopter": "helicopter",
    "Missile":   "rocket",
    "missile":   "rocket",

    "bird":      "DROP_IMAGE",   # istediginiz gibi: kus goruntuleri tamamen cikiyor

    # Aerial images setinde fazladan gelen siniflar.
    # DROP_IMAGE = goruntuyu at. DROP_LABEL yaparsaniz goruntu kalir ve
    # parasut/balon modele "arka plan" olarak ogretilir (plane ile yarismaz).
    "parachute": "DROP_IMAGE",
    "baloon":    "DROP_IMAGE",
    "undefined": "DROP_IMAGE",
}

VALID_RATIO = 0.15
TEST_RATIO = 0.05
SEED = 1337

# "U-S-Air-Force-AGM-130_mp4-0084.jpg" -> "U-S-Air-Force-AGM-130_mp4"
FRAME_SUFFIX = re.compile(r"[-_]?\d{2,6}$")


def group_key(stem: str) -> str:
    """Ayni videodan gelen kareleri tek bir gruba toplar."""
    base = stem.split(".rf.")[0]
    return FRAME_SUFFIX.sub("", base) or base


def read_yolo(label_path: Path, names: list[str], w: int, h: int):
    """YOLO txt -> [(sinif_adi, xmin, ymin, xmax, ymax), ...]"""
    boxes = []
    if not label_path.exists():
        return boxes
    for line in label_path.read_text().strip().splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        idx, cx, cy, bw, bh = int(parts[0]), *map(float, parts[1:5])
        if idx >= len(names):
            continue
        xmin = max(0, int((cx - bw / 2) * w))
        ymin = max(0, int((cy - bh / 2) * h))
        xmax = min(w, int((cx + bw / 2) * w))
        ymax = min(h, int((cy + bh / 2) * h))
        if xmax > xmin and ymax > ymin:
            boxes.append((names[idx], xmin, ymin, xmax, ymax))
    return boxes


def write_voc(path: Path, filename: str, w: int, h: int, boxes) -> None:
    """Pascal VOC XML yazar. Sinif isimleri dosyanin icinde durdugu icin
    labelmap uyusmazligi riski olmaz."""
    root = ET.Element("annotation")
    ET.SubElement(root, "filename").text = filename
    size = ET.SubElement(root, "size")
    ET.SubElement(size, "width").text = str(w)
    ET.SubElement(size, "height").text = str(h)
    ET.SubElement(size, "depth").text = "3"
    for name, xmin, ymin, xmax, ymax in boxes:
        obj = ET.SubElement(root, "object")
        ET.SubElement(obj, "name").text = name
        ET.SubElement(obj, "difficult").text = "0"
        bnd = ET.SubElement(obj, "bndbox")
        for tag, val in (("xmin", xmin), ("ymin", ymin), ("xmax", xmax), ("ymax", ymax)):
            ET.SubElement(bnd, tag).text = str(val)
    ET.ElementTree(root).write(path, encoding="utf-8")


def parse_names(dataset_dir: Path) -> list[str]:
    """data.yaml icindeki names listesini okur (yaml bagimliligi olmadan)."""
    text = (dataset_dir / "data.yaml").read_text()
    m = re.search(r"names:\s*\[(.*?)\]", text, re.S)
    if m:
        return [n.strip().strip("'\"") for n in m.group(1).split(",") if n.strip()]
    names, collecting = [], False
    for line in text.splitlines():
        if line.startswith("names:"):
            collecting = True
            continue
        if collecting:
            if line.startswith("-"):
                names.append(line.lstrip("- ").strip().strip("'\""))
            elif line.strip() and not line.startswith(" "):
                break
    return names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Hicbir sey yuklemez, sadece ne olacagini raporlar.")
    ap.add_argument("--workdir", default="./rf_merge")
    args = ap.parse_args()

    api_key = os.environ.get("ROBOFLOW_API_KEY")
    if not api_key:
        print("HATA: ROBOFLOW_API_KEY ortam degiskeni tanimli degil.", file=sys.stderr)
        return 1

    workdir = Path(args.workdir)
    staging = workdir / "staging"
    staging.mkdir(parents=True, exist_ok=True)

    rf = Roboflow(api_key=api_key)
    ws = rf.workspace(WORKSPACE)

    stats = Counter()
    dropped_by_class = Counter()
    seen_hashes: set[str] = set()
    groups: dict[str, list[tuple[Path, Path]]] = defaultdict(list)

    # ---------------- indirme + filtreleme ----------------
    for slug, version in SOURCES:
        print(f"\n=== {slug} v{version} indiriliyor ===")
        dest = workdir / "download" / slug
        if not dest.exists():
            ws.project(slug).version(version).download("yolov8", location=str(dest))
        names = parse_names(dest)
        print(f"  kaynak siniflar: {names}")

        for split_dir in ("train", "valid", "test"):
            img_dir = dest / split_dir / "images"
            lbl_dir = dest / split_dir / "labels"
            if not img_dir.exists():
                continue

            for img_path in sorted(img_dir.iterdir()):
                if img_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                    continue
                stats["okunan"] += 1

                digest = hashlib.md5(img_path.read_bytes()).hexdigest()
                if digest in seen_hashes:
                    stats["kopya_atlandi"] += 1
                    continue

                try:
                    with Image.open(img_path) as im:
                        w, h = im.size
                except Exception:
                    stats["bozuk_goruntu"] += 1
                    continue

                raw = read_yolo(lbl_dir / f"{img_path.stem}.txt", names, w, h)
                if not raw:
                    stats["etiketsiz_atlandi"] += 1
                    continue

                mapped, drop_image = [], False
                for name, *box in raw:
                    target = CLASS_MAP.get(name)
                    if target is None:
                        dropped_by_class[f"{name} (esleme yok)"] += 1
                        drop_image = True
                        break
                    if target == "DROP_IMAGE":
                        dropped_by_class[name] += 1
                        drop_image = True
                        break
                    if target == "DROP_LABEL":
                        dropped_by_class[f"{name} (etiket silindi)"] += 1
                        continue
                    mapped.append((target, *box))

                if drop_image:
                    stats["sinif_nedeniyle_atildi"] += 1
                    continue
                if not mapped:
                    stats["etiketi_kalmadi_atildi"] += 1
                    continue

                seen_hashes.add(digest)
                out_img = staging / f"{slug}__{img_path.name}"
                out_xml = staging / f"{slug}__{img_path.stem}.xml"
                if not args.dry_run:
                    out_img.write_bytes(img_path.read_bytes())
                    write_voc(out_xml, out_img.name, w, h, mapped)

                groups[f"{slug}::{group_key(img_path.stem)}"].append((out_img, out_xml))
                stats["kabul_edildi"] += 1
                for name, *_ in mapped:
                    stats[f"kutu:{name}"] += 1

    # ---------------- split atamasi (grup butunlugu korunur) ----------------
    keys = sorted(groups)
    random.Random(SEED).shuffle(keys)
    total = sum(len(groups[k]) for k in keys)
    assignment: dict[str, str] = {}
    running = 0
    for k in keys:
        frac = running / total if total else 0
        assignment[k] = ("valid" if frac < VALID_RATIO
                         else "test" if frac < VALID_RATIO + TEST_RATIO
                         else "train")
        running += len(groups[k])

    # ---------------- rapor ----------------
    print("\n" + "=" * 55)
    for key in ("okunan", "kabul_edildi", "sinif_nedeniyle_atildi",
                "kopya_atlandi", "etiketsiz_atlandi",
                "etiketi_kalmadi_atildi", "bozuk_goruntu"):
        if stats[key]:
            print(f"  {key:<28} {stats[key]:>6}")
    print("\n  Eklenecek kutular:")
    for k, v in sorted(stats.items()):
        if k.startswith("kutu:"):
            print(f"    {k[5:]:<26} {v:>6}")
    print("\n  Atilan siniflar:")
    for k, v in dropped_by_class.most_common():
        print(f"    {k:<26} {v:>6}")
    split_counts = Counter(assignment[k] for k in keys for _ in groups[k])
    print(f"\n  Split dagilimi: {dict(split_counts)}")
    print(f"  Video/kaynak grubu sayisi: {len(keys)}")
    print("=" * 55)

    if args.dry_run:
        print("\n--dry-run: hicbir sey yuklenmedi.")
        return 0

    # ---------------- yukleme ----------------
    target = ws.project(TARGET_PROJECT)
    uploaded, failed = 0, 0
    for k in keys:
        split = assignment[k]
        for img, xml in groups[k]:
            try:
                target.upload(
                    image_path=str(img),
                    annotation_path=str(xml),
                    batch_name=BATCH_NAME,
                    split=split,
                    num_retry_uploads=3,
                )
                uploaded += 1
                if uploaded % 250 == 0:
                    print(f"  ... {uploaded}/{stats['kabul_edildi']} yuklendi")
            except Exception as exc:
                failed += 1
                print(f"  HATA {img.name}: {exc}", file=sys.stderr)

    print(f"\nBitti. Yuklenen: {uploaded}, basarisiz: {failed}")
    print(f"Batch adi: {BATCH_NAME}  (sonuc kotu cikarsa bu batch'i silin)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
