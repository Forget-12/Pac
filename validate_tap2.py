#!/usr/bin/env python3
"""Kalibrasi aturan tap-point: uji 3 aturan vs posisi visual semua blob."""
import cv2
import numpy as np
import cosmos_solver as cs
import collections

TRUTH = {
    "frozen": {1:(192,105),2:(262,145),3:(48,122),4:(118,148),5:(262,225),6:(57,232),7:(185,228),8:(78,305),9:(188,318)},
    "f1": {1:(65,110),2:(145,105),3:(250,125),4:(130,185),5:(45,175),6:(220,205),7:(125,285),8:(30,320),9:(240,325)},
    "f2": {1:(195,80),2:(55,90),3:(120,140),4:(240,140),5:(30,190),6:(165,235),7:(60,300),8:(265,315),9:(160,330)},
    "f3": {1:(150,85),2:(30,160),3:(255,140),4:(165,180),5:(50,235),6:(135,270),7:(265,290),8:(195,355),9:(35,340)},
    "archive/165450": {1:(110,75),2:(220,75),3:(225,130),4:(45,195),5:(120,215),6:(225,215),7:(55,285),8:(275,320),9:(195,320)},
    "archive/165455": {1:(55,90),2:(140,90),3:(225,125),4:(165,175),5:(265,185),6:(45,240),7:(230,270),8:(140,280),9:(75,325)},
    "archive/165501": {1:(150,95),2:(35,95),3:(230,120),4:(115,140),5:(160,185),6:(50,240),7:(260,255),8:(120,320),9:(230,330)},
}


def rules(hsv, bbox):
    x, y, w, h = bbox
    bx0, by0 = max(0, x), max(0, y)
    sub = hsv[by0:y + h, bx0:x + w]
    res = {}
    m0 = cv2.inRange(sub, (0, 95, 145), (180, 255, 255))
    n, lab, st, cc = cv2.connectedComponentsWithStats(m0)
    if n > 1:
        i = 1 + int(np.argmax(st[1:, 4]))
        res["A_core135"] = (cc[i][0] + bx0, cc[i][1] + by0)
        # B: union bbox semua core comp >100px
        m2 = cv2.inRange(sub, (0, 135, 180), (180, 255, 255))
        m2 = cv2.morphologyEx(m2, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        n2, lab2, st2, cc2 = cv2.connectedComponentsWithStats(m2)
        xs, ys, xe, ye = [], [], [], []
        cnt = 0
        for j in range(1, n2):
            if st2[j, 4] > 100:
                xx, yy, ww, hh = [int(v) for v in st2[j][:4]]
                xs.append(xx); ys.append(yy); xe.append(xx + ww); ye.append(yy + hh)
                cnt += 1
        if cnt:
            res["B_unionbb"] = (bx0 + (min(xs) + max(xe)) / 2.0,
                                by0 + (min(ys) + max(ye)) / 2.0)
    return res


def main():
    errs = collections.defaultdict(list)
    for img, truths in TRUTH.items():
        im = cv2.imread(f"{img}.png")
        hsv = cv2.cvtColor(im[cs.HEAD:cs.H], cv2.COLOR_BGR2HSV)
        blobs = cs.grid_blobs(im)
        for idx, (tx, ty) in truths.items():
            if idx > len(blobs):
                continue
            r = rules(hsv, blobs[idx - 1]["bbox"])
            for k, (cx, cy) in r.items():
                errs[k].append(round(float(np.hypot(cx - tx, cy - ty)), 1))
    for k in sorted(errs):
        v = errs[k]
        print(f"{k}: n={len(v)} mean={np.mean(v):.1f} p90={np.percentile(v,90):.1f} max={max(v)} ok25={sum(1 for e in v if e<=25)}/{len(v)} ok30={sum(1 for e in v if e<=30)}/{len(v)}")


if __name__ == "__main__":
    main()
