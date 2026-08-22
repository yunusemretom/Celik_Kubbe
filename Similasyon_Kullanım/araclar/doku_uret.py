#!/usr/bin/env python3
"""Celik Kubbe simulasyonu icin fuar salonu dokularini uretir.

Neden elle uretiyoruz: Unity projesinde harici doku paketi yok ve makine
cevrimdisi calisabilmeli. Buradaki dokular *seamless* (kenarlari birbirine
gecen) uretiliyor, boylece 14 x 18 m'lik salon yuzeylerinde tekrarlarken
dikis izi cikmiyor.

Her yuzey icin uc harita yazilir:
  *_Albedo.png        temel renk (sRGB)
  *_Normal.png        yukseklikten turetilmis normal harita (lineer)
  *_MetalSmooth.png   R = metalik, A = puruzsuzluk (URP Lit'in bekledigi duzen)

Fiziksel olcek: her doku 2 x 2 m'lik bir alani temsil eder. Unity tarafinda
tiling bu varsayima gore hesaplanir (bkz. SahneGorselKurulum.cs).

Kullanim:
    python araclar/doku_uret.py [--cikti <klasor>] [--boyut 1024]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

# Unity projesinin dokularin dusecegi klasoru
VARSAYILAN_CIKTI = Path(
    "/home/tom/Setup Guide In-Editor Tutorial/Assets/SteelDome/Textures"
)

# Dokunun temsil ettigi fiziksel kenar uzunlugu (metre).
DOKU_METRE = 2.0


# --------------------------------------------------------------------------- gurultu

def _periyodik_deger_gurultusu(n: int, hucre: int, rng: np.random.Generator) -> np.ndarray:
    """hucre x hucre'lik rastgele izgarayi kubik interpolasyonla n x n'e buyutur.

    Indeksler modulo alindigi icin sonuc her iki eksende de periyodik --
    dokunun sag kenari sol kenariyla, alti ustuyle kusursuz eslesir.
    """
    izgara = rng.random((hucre, hucre), dtype=np.float64)

    koord = np.arange(n) * (hucre / n)
    i0 = np.floor(koord).astype(int)
    t = koord - i0

    # Kubik (Catmull-Rom benzeri) yumusatma: 6t^5 - 15t^4 + 10t^3
    w = t * t * t * (t * (t * 6 - 15) + 10)

    def eksen_karistir(dizi: np.ndarray) -> np.ndarray:
        a = dizi[i0 % hucre]
        b = dizi[(i0 + 1) % hucre]
        return a + (b - a) * w[:, None]

    ara = eksen_karistir(izgara)                 # satirlar
    return eksen_karistir(ara.T).T               # sutunlar


def fraktal_gurultu(n: int, oktavlar: int, taban_hucre: int,
                    rng: np.random.Generator, kalicilik: float = 0.5) -> np.ndarray:
    """Periyodik value noise'lardan fraktal (fBm) gurultu. Cikti 0..1."""
    toplam = np.zeros((n, n))
    genlik = 1.0
    agirlik = 0.0
    hucre = taban_hucre
    for _ in range(oktavlar):
        toplam += genlik * _periyodik_deger_gurultusu(n, min(hucre, n), rng)
        agirlik += genlik
        genlik *= kalicilik
        hucre *= 2
    return toplam / agirlik


def _normalize(a: np.ndarray) -> np.ndarray:
    lo, hi = float(a.min()), float(a.max())
    return (a - lo) / (hi - lo) if hi > lo else np.zeros_like(a)


# --------------------------------------------------------------------------- yardimcilar

def cizgi_maskesi(n: int, adet: int, kalinlik_px: float, eksen: int,
                  ofset: float = 0.0) -> np.ndarray:
    """Dokuyu `adet` esit parcaya bolen periyodik derz cizgileri (0..1)."""
    koord = (np.arange(n) + 0.5) / n * adet + ofset
    uzaklik = np.abs(((koord + 0.5) % 1.0) - 0.5) * (n / adet)   # px cinsinden derze uzaklik
    profil = np.clip(1.0 - uzaklik / max(kalinlik_px, 1e-6), 0.0, 1.0)
    profil = profil ** 1.5
    return np.tile(profil, (n, 1)) if eksen == 1 else np.tile(profil[:, None], (1, n))


def normal_haritasi(yukseklik: np.ndarray, guc: float = 1.0) -> np.ndarray:
    """Yukseklik alanindan tanjant uzayi normal haritasi (periyodik turev)."""
    dx = (np.roll(yukseklik, -1, axis=1) - np.roll(yukseklik, 1, axis=1)) * 0.5
    dy = (np.roll(yukseklik, -1, axis=0) - np.roll(yukseklik, 1, axis=0)) * 0.5

    nx = -dx * guc * yukseklik.shape[0] / 256.0
    ny = -dy * guc * yukseklik.shape[0] / 256.0
    nz = np.ones_like(nx)

    boy = np.sqrt(nx * nx + ny * ny + nz * nz)
    nx, ny, nz = nx / boy, ny / boy, nz / boy

    return np.stack([(nx + 1) * 0.5, (ny + 1) * 0.5, (nz + 1) * 0.5], axis=-1)


def _u8(a: np.ndarray) -> np.ndarray:
    return np.clip(a * 255.0 + 0.5, 0, 255).astype(np.uint8)


def yaz(klasor: Path, ad: str, albedo: np.ndarray, yukseklik: np.ndarray,
        metalik: np.ndarray, puruzsuzluk: np.ndarray, normal_guc: float) -> None:
    klasor.mkdir(parents=True, exist_ok=True)

    Image.fromarray(_u8(albedo), "RGB").save(klasor / f"{ad}_Albedo.png")
    Image.fromarray(_u8(normal_haritasi(yukseklik, normal_guc)), "RGB").save(
        klasor / f"{ad}_Normal.png")

    n = albedo.shape[0]
    ms = np.zeros((n, n, 4))
    ms[..., 0] = metalik            # R = metalik
    ms[..., 3] = puruzsuzluk        # A = puruzsuzluk (URP Lit bunu okur)
    Image.fromarray(_u8(ms), "RGBA").save(klasor / f"{ad}_MetalSmooth.png")

    print(f"  {ad}: albedo + normal + metal/smooth yazildi")


# --------------------------------------------------------------------------- yuzeyler

def duvar(n: int, rng: np.random.Generator) -> dict:
    """Fuar salonu duvari: acik gri boyali alcipan panel, 1 m'lik derzler."""
    # Rulo dokusu ("portakal kabugu") + genis lekelenme
    ince = fraktal_gurultu(n, 5, 128, rng)
    genis = fraktal_gurultu(n, 3, 4, rng)

    # 2 m'lik dokuda 1 m arayla dusey, 1 m arayla yatay panel derzi
    derz = np.maximum(cizgi_maskesi(n, 2, 2.0, eksen=1),
                      cizgi_maskesi(n, 2, 2.0, eksen=0))

    yukseklik = 0.72 * ince + 0.28 * genis
    yukseklik = yukseklik - derz * 0.85          # derzler iceri cukur

    # Fuar salonu duvari: neredeyse beyaz, cok hafif soguk gri
    taban = np.array([0.855, 0.862, 0.868])
    parlaklik = 0.94 + 0.06 * _normalize(genis) - 0.05 * _normalize(ince)
    albedo = taban[None, None, :] * parlaklik[..., None]
    albedo *= (1.0 - derz * 0.22)[..., None]     # derz cizgisi golgeli

    # Mat boya: puruzsuzluk dusuk, derzde daha da dusuk
    puruzsuzluk = 0.28 + 0.05 * _normalize(ince) - derz * 0.12
    return dict(albedo=np.clip(albedo, 0, 1), yukseklik=yukseklik,
                metalik=np.zeros((n, n)), puruzsuzluk=np.clip(puruzsuzluk, 0, 1),
                normal_guc=0.55)


def zemin(n: int, rng: np.random.Generator) -> dict:
    """Cilali beton/epoksi zemin: acik gri, agrega benegi, 2 m'lik kesim derzi."""
    benek = fraktal_gurultu(n, 6, 256, rng)
    leke = fraktal_gurultu(n, 3, 3, rng)

    # Agrega taneleri: ince gurultunun tepe noktalari
    agrega = np.clip((benek - 0.62) / 0.38, 0, 1) ** 2

    # Dokunun kenarindan gecen tek kesim derzi (2 m izgara)
    derz = np.maximum(cizgi_maskesi(n, 1, 2.5, eksen=1),
                      cizgi_maskesi(n, 1, 2.5, eksen=0))

    yukseklik = 0.25 * benek + 0.75 * leke - derz * 1.0 - agrega * 0.15

    taban = np.array([0.585, 0.592, 0.600])
    parlaklik = 0.92 + 0.10 * _normalize(leke)
    albedo = taban[None, None, :] * parlaklik[..., None]
    albedo += agrega[..., None] * np.array([0.10, 0.10, 0.095])[None, None, :]
    albedo *= (1.0 - derz * 0.45)[..., None]

    # Cilali zemin: yuksek puruzsuzluk, cilanin yer yer matlasmasi
    puruzsuzluk = 0.70 + 0.12 * _normalize(leke) - agrega * 0.25 - derz * 0.35
    return dict(albedo=np.clip(albedo, 0, 1), yukseklik=yukseklik,
                metalik=np.zeros((n, n)), puruzsuzluk=np.clip(puruzsuzluk, 0, 1),
                normal_guc=0.35)


def tavan(n: int, rng: np.random.Generator) -> dict:
    """Beyaz metal kaset tavan paneli: 2 m'lik dokuda 4 x 4 kaset (50 cm)."""
    kaset = 4
    ince = fraktal_gurultu(n, 4, 64, rng)

    ek_yeri = np.maximum(cizgi_maskesi(n, kaset, 3.0, eksen=1),
                         cizgi_maskesi(n, kaset, 3.0, eksen=0))

    # Kaset ici hafif ic bukey (panel sarkmasi)
    u = ((np.arange(n) + 0.5) / n * kaset) % 1.0
    kubbe = np.outer(np.sin(np.pi * u), np.sin(np.pi * u))

    yukseklik = kubbe * 0.25 + ince * 0.08 - ek_yeri * 1.0

    taban = np.array([0.905, 0.910, 0.905])
    albedo = taban[None, None, :] * (0.97 + 0.04 * _normalize(ince))[..., None]
    albedo *= (1.0 - ek_yeri * 0.42)[..., None]

    puruzsuzluk = 0.42 + 0.08 * kubbe - ek_yeri * 0.30
    metalik = np.full((n, n), 0.35) * (1.0 - ek_yeri)
    return dict(albedo=np.clip(albedo, 0, 1), yukseklik=yukseklik,
                metalik=np.clip(metalik, 0, 1), puruzsuzluk=np.clip(puruzsuzluk, 0, 1),
                normal_guc=0.9)


YUZEYLER = {"T_Wall": duvar, "T_Floor": zemin, "T_Ceiling": tavan}


def main() -> None:
    ap = argparse.ArgumentParser(description="Fuar salonu dokularini uret")
    ap.add_argument("--cikti", type=Path, default=VARSAYILAN_CIKTI,
                    help="PNG'lerin yazilacagi klasor (varsayilan: Unity Textures)")
    ap.add_argument("--boyut", type=int, default=1024, help="Doku kenar uzunlugu (px)")
    ap.add_argument("--seed", type=int, default=20260822, help="Tekrarlanabilirlik icin")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    print(f"Dokular uretiliyor -> {args.cikti} ({args.boyut}px, {DOKU_METRE} m kenar)")
    for ad, uretici in YUZEYLER.items():
        yaz(args.cikti, ad, **uretici(args.boyut, rng))
    print("Bitti.")


if __name__ == "__main__":
    main()
