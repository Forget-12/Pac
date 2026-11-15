#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evaluasi klasifikasi ikon header (leave-one-out) dari data PASS."""
import json, collections
import cv2
import numpy as np
import cosmos_templates as ct

ROWS = [json.loads(l) for l in open("archive_index_fixed.jsonl") if json.loads(l)["result"] == "pass"]


def header_mask(img, box):
    """Mask putih ikon header dari crop box (x0,x1) -> 48x48 ternormalisasi."""
    xs, xe = box
    g = cv2.cvtColor(img[ct.HEADER_Y[0]:ct.HEADER_Y[1], xs:xe], cv2.COLOR_BGR2GRAY)
    _, m = cv2.threshold(g, 180, 255, cv2.THRESH_BINARY)
    ys, xs2 = np.nonzero(m)
    if len(ys) == 0:
        return None
    m = m[ys.min():ys.max() + 1, xs2.min():xs2.max() + 1]
    h, w = m.shape
    sc = 40.0 / max(h, w)
    r = cv2.resize(m, (max(1, int(w * sc)), max(1, int(h * sc))), interpolation=cv2.INTER_AREA)
    out = np.zeros((48, 48), np.uint8)
    y0, x0 = (48 - r.shape[0]) // 2, (48 - r.shape[1]) // 2
    out[y0:y0 + r.shape[0], x0:x0 + r.shape[1]] = r
    return (out > 110).astype(np.uint8)


def crop_gray(img, box):
    xs, xe = box
    return cv2.cvtColor(img[ct.HEADER_Y[0]:ct.HEADER_Y[1], xs:xe], cv2.COLOR_BGR2GRAY)


def iou_rot(a, b, step=15):
    best = 0.0
    c, s = a.shape[0] // 2, a.shape[1] // 2
    for ang in range(0, 360, step):
        if ang:
            M = cv2.getRotationMatrix2D((s, c), ang, 1.0)
            r = (cv2.warpAffine(b * 255, M, (a.shape[1], a.shape[0])) > 110).astype(np.uint8)
        else:
            r = b
        inter = np.logical_and(a, r).sum()
        union = np.logical_or(a, r).sum()
        if union:
            best = max(best, inter / union)
    return best


def tmatch(a, b):
    if a.shape[0] < b.shape[0] or a.shape[1] < b.shape[1]:
        b = cv2.resize(b, (a.shape[1], a.shape[0]))
    res = cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)
    _, mv, _, _ = cv2.minMaxLoc(res)
    return float(mv)


def main():
    data = []
    for r in ROWS:
        if not r.get("assign"):
            continue
        img = cv2.imread(r["img"])
        if img is None:
            continue
        labels = [None] * 3
        for a in r["assign"]:
            t = a.get("t", 0) - 1
            if 0 <= t < 3:
                labels[t] = a.get("bsem")
        if any(x in (None, "?") for x in labels):
            continue
        items = []
        for i, box in enumerate(ct.HEADER_BOXES):
            g = crop_gray(img, box)
            m = header_mask(img, box)
            items.append({"gray": g, "mask": m, "label": labels[i]})
        data.append(items)
    print("images", len(data), "samples", len(data) * 3)
    print("labels", collections.Counter(x["label"] for im in data for x in im))

    # leave-one-out: prediksi tiap header dari semua header lain (bukan gambar yang sama)
    ok_m = ok_g = 0
    tot = 0
    conf = collections.Counter()
    for di, items in enumerate(data):
        train = [x for j, im in enumerate(data) if j != di for x in im]
        for x in items:
            # mask IoU
            best_m, bm_lab = -1, None
            best_g, bg_lab = -1, None
            for y in train:
                if x["mask"] is not None and y["mask"] is not None:
                    s = iou_rot(x["mask"], y["mask"], step=20)
                    if s > best_m:
                        best_m, bm_lab = s, y["label"]
                s2 = tmatch(x["gray"], y["gray"])
                if s2 > best_g:
                    best_g, bg_lab = s2, y["label"]
            ok_m += (bm_lab == x["label"])
            ok_g += (bg_lab == x["label"])
            tot += 1
            conf[(x["label"], bm_lab, bg_lab)] += 1
    print(f"mask-knn {ok_m}/{tot} ({ok_m/tot*100:.1f}%)  gray-knn {ok_g}/{tot} ({ok_g/tot*100:.1f}%)")
    print("salah mask:", [(k, v) for k, v in conf.items() if k[0] != k[1]][:20])
    print("salah gray:", [(k, v) for k, v in conf.items() if k[0] != k[2]][:20])


if __name__ == "__main__":
    main()
