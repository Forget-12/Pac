#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COSMOS SOLVER — pembaca captcha sf_cosmos otomatis (OpenCV)
Meniru cara manual: baca 3 ikon target (siluet putih di header),
cari objek berbentuk sama di grid, urutkan sesuai nomor 1->2->3.
Cara kerja:
  1. Header (y 0-60): threshold putih (V tinggi, S rendah) -> 3 siluet ikon
  2. Grid (y 60-380): threshold warna (S&V tinggi) -> komponen terhubung
     -> gabungkan komponen berdekatan (objek multi-warna: roket, satelit, UFO)
  3. Pencocokan: cv2.matchShapes (Hu moments — invarian skala/rotasi/posisi)
     antara kontur siluet target dan kontur tiap blob grid
  4. Greedy: tiap target ambil blob dgn skor terbaik; tap di centroid blob
Output: "x1,y1;x2,y2;x3,y3" + gambar debug (c-solve-debug.png)
"""
import cv2
import numpy as np

W, H, HEAD = 320, 380, 60
DEBUG = "c-solve-debug.png"


def _largest_contour(mask):
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None
    return max(cnts, key=cv2.contourArea)


def header_icons(img):
    """Return list kontur 3 ikon target (koordinat header asli)."""
    head = img[0:HEAD]
    hsv = cv2.cvtColor(head, cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, (0, 0, 190), (180, 75, 255))
    # 3 kotak ikon berposisi tetap (header teratur) — hindari cluster salah
    slots = [(30, 122), (122, 202), (202, 300)]
    icons = []
    for a, b in slots:
        sub = np.zeros_like(white)
        sub[:, a:b + 1] = white[:, a:b + 1]
        c = _largest_contour(sub)
        if c is not None and cv2.contourArea(c) > 150:
            icons.append(c)
    icons.sort(key=lambda c: cv2.boundingRect(c)[0])
    return icons


def grid_blobs(img):
    """Segmentasi objek grid: list dict(contour, centroid, area, bbox)."""
    grid = img[HEAD:H]
    hsv = cv2.cvtColor(grid, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (0, 95, 145), (180, 255, 255))
    k = np.ones((5, 5), np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(m)
    blobs = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 400:
            continue
        if area > 1100:
            # blob gabungan (glow menjembatani 2 objek) -> re-threshold ketat
            sub = hsv[max(0, y - 4):y + h + 4, max(0, x - 4):x + w + 4]
            t = cv2.inRange(sub, (0, 135, 180), (180, 255, 255))
            t = cv2.morphologyEx(t, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
            n2, lab2, st2, c2 = cv2.connectedComponentsWithStats(t)
            parts = []
            for j in range(1, n2):
                a2 = st2[j, 4]
                if a2 < 350:
                    continue
                mm = (lab2 == j).astype(np.uint8)
                cnt = _largest_contour(mm)
                if cnt is None:
                    continue
                parts.append({
                    "contour": cnt, "area": int(a2),
                    "bbox": (int(st2[j, 0] + max(0, x - 4)), int(st2[j, 1] + max(0, y - 4)),
                             int(st2[j, 2]), int(st2[j, 3])),
                    "cent": (int(c2[j][0] + max(0, x - 4)), int(c2[j][1] + max(0, y - 4))),
                    "mask": mm})
            if len(parts) >= 2:
                blobs.extend(parts)
                continue
            # gagal dipecah -> pakai mask ketat sebagai wakili (kurangi glow)
            if parts:
                blobs.extend(parts)
                continue
        cnt = _largest_contour((lab == i).astype(np.uint8))
        if cnt is None:
            continue
        cx, cy = cent[i]
        # titik tap = centroid CORE (threshold ketat) agar glow tak menggeser
        bx0, by0 = max(0, x), max(0, y)
        sub = hsv[by0:y + h, bx0:x + w]
        core = cv2.inRange(sub, (0, 135, 180), (180, 255, 255))
        core = cv2.morphologyEx(core, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        nc2, labc2, stc2, ccc2 = cv2.connectedComponentsWithStats(core)
        if nc2 > 1:
            ci = 1 + int(np.argmax(stc2[1:, 4]))
            if stc2[ci, 4] > 150:
                cx, cy = ccc2[ci][0] + bx0, ccc2[ci][1] + by0
        blobs.append({"contour": cnt, "cent": (int(cx), int(cy)),
                      "area": int(area), "bbox": (x, y, w, h),
                      "mask": (lab == i).astype(np.uint8)})
    return blobs


def norm_mask(mask, size=48):
    """Mask -> crop bbox -> resize ASPEK ASLI -> pad tengah (bentuk asli)."""
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return None
    sub = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8)
    h, w = sub.shape
    sc = size / max(h, w)
    nh, nw = max(1, int(h * sc)), max(1, int(w * sc))
    r = cv2.resize(sub * 255, (nw, nh), interpolation=cv2.INTER_AREA)
    cv = np.zeros((size, size), np.uint8)
    y0, x0 = (size - nh) // 2, (size - nw) // 2
    cv[y0:y0 + nh, x0:x0 + nw] = r
    return (cv > 110).astype(np.uint8)


def iou_rot(a, b, step=10):
    """IoU maksimum antara mask a dan b dalam berbagai rotasi b."""
    best = 0.0
    c, s = a.shape[0] // 2, a.shape[1] // 2
    for ang in range(0, 360, step):
        if ang == 0:
            r = b
        else:
            M = cv2.getRotationMatrix2D((s, c), ang, 1.0)
            r = (cv2.warpAffine(b * 255, M, (a.shape[1], a.shape[0])) > 110).astype(np.uint8)
        inter = np.logical_and(a.astype(bool), r.astype(bool)).sum()
        union = np.logical_or(a.astype(bool), r.astype(bool)).sum()
        if union:
            best = max(best, inter / union)
    return best


def radial_sig(mask, bins=180):
    """Profil radius kontur -> magnitudo Fourier[:9] (invarian rotasi)."""
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return None
    cy, cx = ys.mean(), xs.mean()
    cnts, _ = cv2.findContours((mask > 0).astype(np.uint8),
                               cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None
    cnt = max(cnts, key=cv2.contourArea).reshape(-1, 2).astype(float)
    ang = np.arctan2(cnt[:, 1] - cy, cnt[:, 0] - cx) % (2 * np.pi)
    rad = np.hypot(cnt[:, 1] - cy, cnt[:, 0] - cx)
    idx = np.clip((ang / (2 * np.pi) * bins).astype(int), 0, bins - 1)
    prof = np.zeros(bins)
    for i, r in zip(idx, rad):
        prof[i] = max(prof[i], r)
    nz = np.nonzero(prof)[0]
    if len(nz) == 0:
        return None
    prof = np.interp(np.arange(bins), nz, prof[nz], period=bins)
    prof /= (prof.max() + 1e-9)
    f = np.abs(np.fft.rfft(prof))[:9]
    return f / (f.sum() + 1e-9)


def solve(path, debug=True):
    """Return (pts_str, list skor) atau (None, alasan)."""
    img = cv2.imread(path)
    if img is None:
        return None, "gambar tidak terbaca"
    icons = header_icons(img)
    if len(icons) != 3:
        return None, f"ikon header terdeteksi {len(icons)} (butuh 3)"
    blobs = grid_blobs(img)
    if len(blobs) < 3:
        return None, f"blob grid hanya {len(blobs)}"

    # skor = IoU (dengan rotasi) antara mask target dan mask blob
    t_masks = []
    for ic in icons:
        m = np.zeros(img[0:HEAD].shape[:2], np.uint8)
        cv2.drawContours(m, [ic], -1, 1, -1)
        t_masks.append(norm_mask(m))
    scores = []
    rads = [radial_sig(tm) for tm in t_masks]
    for ti, tm in enumerate(t_masks):
        for bi, b in enumerate(blobs):
            bm = norm_mask(b["mask"])
            if bm is None or tm is None:
                continue
            iou = iou_rot(tm, bm)
            rb = radial_sig(bm)
            if rads[ti] is not None and rb is not None:
                rl = float(np.linalg.norm(rads[ti] - rb))
                rr = max(0.0, 1.0 - rl / 0.30)
            else:
                rr = 0.0
            d = 1.0 - (0.65 * iou + 0.35 * rr)   # skor gabungan, kecil=baik
            scores.append((d, ti, bi))
    scores.sort()

    taps = {}
    used_t, used_b = set(), set()
    detail = []
    for d, ti, bi in scores:
        if ti in used_t or bi in used_b:
            continue
        used_t.add(ti); used_b.add(bi)
        taps[ti] = blobs[bi]["cent"]
        detail.append((ti + 1, blobs[bi]["cent"], round(d, 3)))
        if len(taps) == 3:
            break
    if len(taps) < 3:
        return None, f"cocok hanya {len(taps)}/3"

    pts = ";".join(f"{taps[i][0]},{taps[i][1] + HEAD}" for i in range(3))
    if debug:
        vis = img.copy()
        for num, (cx, cy), d in detail:
            cv2.circle(vis, (cx, cy + HEAD), 14, (0, 0, 255), 2)
            cv2.putText(vis, str(num), (cx - 5, cy + HEAD - 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        cv2.imwrite(DEBUG, vis)
    return pts, detail


if __name__ == "__main__":
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else "c-cosmos.png"
    pts, info = solve(p)
    print("PTS:", pts)
    print("detail:", info)
