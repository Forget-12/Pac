#!/usr/bin/env python3
"""Validasi matcher + kalibrasi tap-point vs ground truth visual."""
import cv2
import numpy as np
import cosmos_solver as cs
import cosmos_lib as cl

TRUTH = {
    "frozen": {"sun": (78, 305), "star": (118, 148), "saturn": (185, 228)},
    "f1": {"ufo": (45, 175), "sun": (240, 325), "star": (250, 125)},
    "f2": {"moon": (265, 315), "ufo": (165, 235), "saturn": (120, 140)},
    "f3": {"satellite": (255, 140), "rocket": (265, 290), "ufo": (150, 85)},
}


def tap_rules(hsv, bbox):
    x, y, w, h = bbox
    bx0, by0 = max(0, x), max(0, y)
    sub = hsv[by0:y + h, bx0:x + w]
    res = {}
    n, lab, st, cc = cv2.connectedComponentsWithStats(
        cv2.inRange(sub, (0, 95, 145), (180, 255, 255)))
    if n > 1:
        i = 1 + int(np.argmax(st[1:, 4]))
        res["loose_cent"] = (cc[i][0] + bx0, cc[i][1] + by0)
    for tag, (S, V) in {"core135": (135, 180), "core150": (150, 200)}.items():
        m = cv2.inRange(sub, (0, S, V), (180, 255, 255))
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        n2, lab2, st2, cc2 = cv2.connectedComponentsWithStats(m)
        if n2 > 1:
            j = 1 + int(np.argmax(st2[1:, 4]))
            if st2[j, 4] > 100:
                res[tag] = (cc2[j][0] + bx0, cc2[j][1] + by0)
                xx, yy, ww, hh = [int(v) for v in st2[j][:4]]
                res[tag + "bb"] = (bx0 + xx + ww / 2.0, by0 + yy + hh / 2.0)
    return res


def main():
    import collections
    errs = collections.defaultdict(list)
    ok = collections.defaultdict(list)
    for img, truths in TRUTH.items():
        im = cv2.imread(f"{img}.png")
        hsv = cv2.cvtColor(im[cs.HEAD:cs.H], cv2.COLOR_BGR2HSV)
        blobs = cs.grid_blobs(im)
        masks, labels, doms = cl.load_lib()
        icons = cs.header_icons(im)
        h = im[0:cs.HEAD]
        t_masks = []
        for ic in icons:
            m = np.zeros(h.shape[:2], np.uint8)
            cv2.drawContours(m, [ic], -1, 1, -1)
            t_masks.append(cs.norm_mask(m))
        tprof = [cl.semantic_profile(t, masks, labels, doms, "H") for t in t_masks]
        bprof = [cl.semantic_profile(cs.norm_mask(b["mask"]), masks, labels, doms, "G")
                 for b in blobs]

        def nrm(p):
            base = np.median(list(p.values()))
            adj = {s: max(0.0, v - base) for s, v in p.items()}
            z = sum(adj.values()) + 1e-9
            return {s: v / z for s, v in adj.items()}
        pairs = []
        tprof_n = [nrm(p) for p in tprof]
        bprof_n = [nrm(p) for p in bprof]
        for ti, tp in enumerate(tprof_n):
            for bi, bp in enumerate(bprof_n):
                sc = sum(np.sqrt(tp[s] * bp.get(s, 0.0)) for s in tp)
                pairs.append((-sc, ti, bi))
        pairs.sort()
        used_t, used_b = set(), set()
        for neg, ti, bi in pairs:
            if ti in used_t or bi in used_b:
                continue
            used_t.add(ti); used_b.add(bi)
            sem = max(tprof[ti], key=lambda s: tprof[ti][s])
            if sem not in truths:
                continue
            tx, ty = truths[sem]
            r = tap_rules(hsv, blobs[bi]["bbox"])
            for k, (cx, cy) in r.items():
                e = float(np.hypot(cx - tx, (cy + cs.HEAD) - ty))
                errs[k].append(round(e, 1))
                ok[k].append(e <= 25)
            if len(used_t) == 3:
                break
    for k in sorted(errs):
        print(f"{k}: n={len(errs[k])} mean={np.mean(errs[k]):.1f} max={max(errs[k])} ok<=25px={sum(ok[k])}/{len(ok[k])}")
        print("   ", errs[k])


if __name__ == "__main__":
    main()
