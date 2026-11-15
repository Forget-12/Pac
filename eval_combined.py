#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evaluasi kolaborasi: k-NN header + k-NN blob + assignment, LOO pada data PASS."""
import json, itertools, collections
import cv2
import numpy as np

import cosmos_solver as cs
import cosmos_lib as cl
import cosmos_templates as ct


def header_mask(img, box):
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


def gray_crop(img, box):
    xs, xe = box
    return cv2.cvtColor(img[ct.HEADER_Y[0]:ct.HEADER_Y[1], xs:xe], cv2.COLOR_BGR2GRAY)


def tmatch(a, b):
    if a.shape[0] < b.shape[0] or a.shape[1] < b.shape[1]:
        b = cv2.resize(b, (a.shape[1], a.shape[0]))
    res = cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)
    _, mv, _, _ = cv2.minMaxLoc(res)
    return float(mv)


def load_cases():
    rows = [json.loads(l) for l in open("archive_index_fixed.jsonl") if json.loads(l)["result"] == "pass"]
    cases = []
    for r in rows:
        if not r.get("assign"):
            continue
        img = cv2.imread(r["img"])
        if img is None:
            continue
        icons = cs.header_icons(img)
        blobs = cs.grid_blobs(img)
        if len(icons) != 3 or len(blobs) < 3:
            continue
        cents = []
        for b in blobs:
            cx, cy = cl._tap_point(b, img)
            cents.append((cx, cy + cs.HEAD))
        pts = [tuple(map(int, p.split(","))) for p in r["pts"].split(";")]
        true = []
        ok = True
        for x, y in pts:
            bi = min(range(len(cents)), key=lambda i: (cents[i][0] - x) ** 2 + (cents[i][1] - y) ** 2)
            if ((cents[bi][0] - x) ** 2 + (cents[bi][1] - y) ** 2) ** 0.5 > 22:
                ok = False
                break
            true.append(bi)
        if not ok or len(set(true)) != 3:
            continue
        # label header: template dulu, fallback bsem
        temps = ct.load_header_templates()
        hlab, hconf = [], []
        for box in ct.HEADER_BOXES:
            g = gray_crop(img, box)
            best, bn = -1, "?"
            for name, t in temps.items():
                s = tmatch(g, t)
                if s > best:
                    best, bn = s, name
            hlab.append(bn)
            hconf.append(best)
        if min(hconf) < 0.90 or len(set(hlab)) != 3:
            lab = [None] * 3
            for a in r["assign"]:
                t = a.get("t", 0) - 1
                if 0 <= t < 3:
                    lab[t] = a.get("bsem")
            if any(x in (None, "?") for x in lab):
                continue
            hlab = lab
        # header features
        hm = [header_mask(img, box) for box in ct.HEADER_BOXES]
        hg = [gray_crop(img, box) for box in ct.HEADER_BOXES]
        if any(m is None for m in hm):
            continue
        # blob features (mask + color)
        bm, bcol = [], []
        for b in blobs:
            nm = cs.norm_mask(b["mask"])
            if nm is None:
                ok = False
                break
            bm.append(nm)
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            x, y, w, h = b["bbox"]
            sub = hsv[cs.HEAD + y:cs.HEAD + y + h, x:x + w]
            core = b["mask"][:sub.shape[0], :sub.shape[1]] > 0
            px = sub[core]
            if len(px) == 0:
                bcol.append(np.zeros(14))
            else:
                hh = px[:, 0].astype(float) * 2 * np.pi / 180
                ss = px[:, 1].astype(float) / 255
                vv = px[:, 2].astype(float) / 255
                hist, _ = np.histogram(hh, bins=12, range=(0, 2 * np.pi), weights=ss * vv)
                hist = hist / (hist.sum() + 1e-9)
                bcol.append(np.concatenate([hist, [ss.mean(), vv.mean()]]))
        if not ok:
            continue
        cases.append({"img": img, "true": true, "hlab": hlab,
                      "hm": hm, "hg": hg, "bm": bm, "bcol": bcol,
                      "hfeat": [cl.prep(m) for m in hm],
                      "bfeat": [cl.prep(m) for m in bm]})
    return cases


def assign(scores):
    best, bp = -1e9, None
    for perm in itertools.permutations(range(len(scores[0])), 3):
        s = sum(scores[t][perm[t]] for t in range(3))
        if s > best:
            best, bp = s, perm
    return list(bp)


def main():
    cases = load_cases()
    print("cases", len(cases))
    print("header labels", collections.Counter(l for c in cases for l in c["hlab"]))
    # LOO
    hok = bok = full = tot = 0
    for i, c in enumerate(cases):
        tr = [x for j, x in enumerate(cases) if j != i]
        # header class scores per target
        H = []
        for t in range(3):
            sc = collections.defaultdict(float)
            for x in tr:
                for j in range(3):
                    s = cl.score_prep(c["hfeat"][t], x["hfeat"][j])
                    s2 = tmatch(c["hg"][t], x["hg"][j])
                    s = 0.5 * s + 0.5 * max(0.0, s2)
                    sc[x["hlab"][j]] = max(sc[x["hlab"][j]], s)
            H.append(dict(sc))
        # blob class scores per blob
        B = []
        for b in range(len(c["bm"])):
            sc = collections.defaultdict(float)
            for x in tr:
                for j, tb in enumerate(x["true"]):
                    s = cl.score_prep(c["bfeat"][b], x["bfeat"][tb])
                    # cosine color
                    a, bb = c["bcol"][b], x["bcol"][tb]
                    cs_ = float(np.dot(a, bb) / (np.linalg.norm(a) * np.linalg.norm(bb) + 1e-9))
                    s = 0.8 * s + 0.2 * cs_
                    sc[x["hlab"][j]] = max(sc[x["hlab"][j]], s)
            B.append(dict(sc))
        # normalize per target/blob
        def norm(p):
            base = np.median(list(p.values())) if p else 0
            adj = {k: max(0.0, v - base) for k, v in p.items()}
            z = sum(adj.values()) + 1e-9
            return {k: v / z for k, v in adj.items()}
        Hn = [norm(p) for p in H]
        Bn = [norm(p) for p in B]
        S = [[sum(np.sqrt(Hn[t].get(k, 0) * Bn[b].get(k, 0)) for k in Hn[t])
              for b in range(len(Bn))] for t in range(3)]
        perm = assign(S)
        # header accuracy
        hpred = [max(Hn[t].items(), key=lambda kv: kv[1])[0] for t in range(3)]
        bpred = [max(Bn[b].items(), key=lambda kv: kv[1])[0] for b in range(len(Bn))]
        hok += sum(hpred[t] == c["hlab"][t] for t in range(3))
        bok += sum(bpred[c["true"][t]] == c["hlab"][t] for t in range(3))
        full += (perm == c["true"])
        tot += 3
    print(f"header {hok}/{tot} ({hok/tot*100:.1f}%)  blob {bok}/{tot} ({bok/tot*100:.1f}%)  full {full}/{len(cases)} ({full/len(cases)*100:.1f}%)")


if __name__ == "__main__":
    main()
