"""
Visual menu-open detection: pixel diff + OCR.

Used as an additional signal alongside ARIA-tree diff and DOM-overlay scoring.
Especially valuable when a site renders its menu without ARIA labels (the
Khaite failure mode: ARIA diff was only 27 chars / "Close mobile menu").

Approach
--------
1. Compute pixel diff between before/after screenshots in PARALLEL on
   two representations:
     - raw RGB
     - contrast-enhanced (CLAHE via OpenCV, falls back to PIL autocontrast)
   Union the two change masks. Anti-alias noise and subtle fades hit one
   but not both, while a real menu overlay lights up both.
2. Bounding box of the union mask = the visual change region.
3. OCR (Tesseract via pytesseract) on that cropped region only — fast,
   bounded, and avoids OCRing the entire viewport.

The module degrades gracefully:
  - If OpenCV/CLAHE is unavailable, falls back to PIL autocontrast.
  - If pytesseract / tesseract binary is missing, returns empty OCR text
    rather than raising.

No LLM calls live in here. Downstream callers decide what to do with the
result (e.g. picking the overlay whose bbox best overlaps `bbox`).
"""

from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from PIL import Image, ImageOps


BBox = Tuple[int, int, int, int]  # (x, y, w, h)


@dataclass
class VisualDiff:
    changed_fraction: float           # raw RGB pixel-diff fraction [0,1]
    changed_fraction_contrast: float  # contrast-enhanced fraction [0,1]
    union_fraction: float             # union of both masks
    bbox: Optional[BBox]              # bounding box of union change region
    line_change: int                  # non-empty OCR lines (rough proxy)
    ocr_text: str                     # raw OCR text from the bbox crop
    menu_opened: bool                 # final verdict


def _diff_mask(a: np.ndarray, b: np.ndarray, threshold: int) -> np.ndarray:
    """L1 per-pixel diff -> boolean mask. Inputs uint8 HxWx3."""
    delta = np.abs(a.astype(np.int16) - b.astype(np.int16)).sum(axis=2)
    return delta > threshold


def _bbox_of_mask(mask: np.ndarray) -> Optional[BBox]:
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    if not rows.any() or not cols.any():
        return None
    y_idx = np.where(rows)[0]
    x_idx = np.where(cols)[0]
    y0, y1 = int(y_idx[0]), int(y_idx[-1])
    x0, x1 = int(x_idx[0]), int(x_idx[-1])
    return (x0, y0, x1 - x0 + 1, y1 - y0 + 1)


def _contrast_boost(img_rgb: np.ndarray) -> np.ndarray:
    """CLAHE on the L channel via cv2 if available; PIL autocontrast otherwise."""
    try:
        import cv2  # opencv-python is already in requirements.txt
        lab = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        l2 = clahe.apply(l)
        merged = cv2.merge((l2, a, b))
        return cv2.cvtColor(merged, cv2.COLOR_LAB2RGB)
    except Exception:
        pil = Image.fromarray(img_rgb)
        return np.array(ImageOps.autocontrast(pil, cutoff=2))


def _decode(png_bytes: bytes) -> np.ndarray:
    return np.array(Image.open(io.BytesIO(png_bytes)).convert("RGB"))


def _ocr_region(after_rgb: np.ndarray, bbox: BBox, pad: int = 8) -> str:
    try:
        import pytesseract
    except ImportError:
        return ""
    h, w = after_rgb.shape[:2]
    x, y, bw, bh = bbox
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(w, x + bw + pad)
    y1 = min(h, y + bh + pad)
    crop = after_rgb[y0:y1, x0:x1]
    try:
        return pytesseract.image_to_string(Image.fromarray(crop)).strip()
    except Exception as e:
        # Tesseract binary missing, or any runtime issue — degrade gracefully.
        return f""  # silent: caller treats empty OCR as "no signal"


def compute_visual_diff(
    before_png: bytes,
    after_png: bytes,
    pixel_threshold: int = 25,
    min_changed_fraction: float = 0.15,
    min_lines: int = 3,
    ocr_enabled: bool = True,
) -> VisualDiff:
    """Compare two screenshots and return change stats + OCR text.

    A menu is considered "opened" when union_fraction >= min_changed_fraction
    AND OCR finds at least min_lines text lines in the change region.
    """
    before = _decode(before_png)
    after = _decode(after_png)
    if before.shape != after.shape:
        # Resize after to before — viewport changes between shots are rare but possible.
        after_img = Image.fromarray(after).resize(
            (before.shape[1], before.shape[0])
        )
        after = np.array(after_img)

    def run_raw():
        m = _diff_mask(before, after, pixel_threshold)
        return m, float(m.sum()) / m.size

    def run_contrast():
        a_c = _contrast_boost(before)
        b_c = _contrast_boost(after)
        m = _diff_mask(a_c, b_c, pixel_threshold)
        return m, float(m.sum()) / m.size

    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_raw = ex.submit(run_raw)
        fut_con = ex.submit(run_contrast)
        mask_raw, frac_raw = fut_raw.result()
        mask_con, frac_con = fut_con.result()

    union_mask = mask_raw | mask_con
    union_frac = float(union_mask.sum()) / union_mask.size
    bbox = _bbox_of_mask(union_mask)

    ocr_text = ""
    if ocr_enabled and bbox is not None and union_frac >= min_changed_fraction:
        ocr_text = _ocr_region(after, bbox)

    line_change = sum(1 for ln in ocr_text.splitlines() if ln.strip())
    menu_opened = union_frac >= min_changed_fraction and line_change >= min_lines

    return VisualDiff(
        changed_fraction=frac_raw,
        changed_fraction_contrast=frac_con,
        union_fraction=union_frac,
        bbox=bbox,
        line_change=line_change,
        ocr_text=ocr_text,
        menu_opened=menu_opened,
    )


def bbox_overlap_ratio(overlay_bbox: BBox, change_bbox: BBox) -> float:
    """IoU between an overlay's bounding box and the change region.

    Used to pick which DOM overlay corresponds to the visual change — the
    overlay whose bbox best overlaps the changed pixels is the menu.
    """
    if not overlay_bbox or not change_bbox:
        return 0.0
    ax, ay, aw, ah = overlay_bbox
    bx, by, bw, bh = change_bbox
    ix0 = max(ax, bx)
    iy0 = max(ay, by)
    ix1 = min(ax + aw, bx + bw)
    iy1 = min(ay + ah, by + bh)
    iw = max(0, ix1 - ix0)
    ih = max(0, iy1 - iy0)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def ocr_text_to_aria_lines(ocr_text: str) -> str:
    """Convert raw OCR text into ARIA-format `- text: ...` lines.

    Used as a synthetic ARIA diff when the real ARIA diff is too thin to be
    useful but OCR has captured visible menu items.
    """
    lines = [ln.strip() for ln in ocr_text.splitlines() if ln.strip()]
    return "\n".join(f"  - text: {ln}" for ln in lines)
