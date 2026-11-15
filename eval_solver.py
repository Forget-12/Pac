#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline evaluation of sf_cosmos solvers on archived, server-confirmed passes."""
import json, os, sys, itertools
import numpy as np
import cv2

import cosmos_solver as cs
import cosmos_lib as cl

ROWS = [json.loads(l) for l in open("archive_index_fixed.jsonl")]


def load_case(row):
    img = cv2.imread(row["img"])
    if img is None:
        return None
    icons = cs.header_icons(img)
    blobs = cs.grid_blobs(img)
    if len(icons) != 3 or len(blobs) < 3:
        return None
    # tap points in full-image coords
    cents = []
    for b in blobs:
        cx, cy = cl._tap_point(b, img)
        cents.append((cx, cy + cs.HEAD))
    pts = []
    for p in row["pts"].split(";"):
        x, y = map(int, p.split(","))
        pts.append((x, y))
    # map pts -> blob indices
    true = []
    for x, y in pts:
        bi = min(range(len(cents)), key=lambda i: (cents[i][0] - x) ** 2 + (cents[i][1] - y) ** 2)
        d = ((cents[bi][0] - x) ** 2 + (cents[bi][1] - y) ** 2) ** 0.5
        if d > 22:
            return None
        true.append(bi)
    if len(set(true)) != 3:
        return None
    t_masks = []
    h = img[0:cs.HEAD]
    for ic in icons:
        m = np.zeros(h.shape[:2], np.uint8)
        cv2.drawContours(m, [ic], -1, 1, -1)
        t_masks.append(cs.norm_mask(m))
    b_masks = [cs.norm_mask(b["mask"]) for b in blobs]
    if any(m is None for m in t_masks + b_masks):
        return None
    return {"row": row, "img": img, "true": true, "t": t_masks,
            "b": b_masks, "cents": cents, "blobs": blobs}


def assignment(scores):
    """scores[ti][bi] -> best assignment list via brute force (3 targets)."""
    best, bestp = -1e9, None
    for perm in itertools.permutations(range(len(scores[0])), 3):
        s = sum(scores[ti][perm[ti]] for ti in range(3))
        if s > best:
            best, bestp = s, perm
    return list(bestp), best


def eval_cases(cases, score_fn, name):
    ok = 0
    per_t = [0, 0, 0]
    tot = 0
    for c in cases:
        S = [[score_fn(c["t"][ti], c["b"][bi]) for bi in range(len(c["b"]))] for ti in range(3)]
        perm, _ = assignment(S)
        tot += 1
        good = [perm[i] == c["true"][i] for i in range(3)]
        per_t = [per_t[i] + good[i] for i in range(3)]
        if all(good):
            ok += 1
    print(f"{name}: full {ok}/{tot} ({ok/max(tot,1)*100:.1f}%)  per-target {per_t}/{tot}")
    return ok, tot


if __name__ == "__main__":
    cases = []
    for r in ROWS:
        if r["result"] != "pass":
            continue
        c = load_case(r)
        if c:
            cases.append(c)
    print("cases:", len(cases))
    # baseline features
    def f_iou(a, b):
        return cs.iou_rot(a, b)

    def f_iou0(a, b):
        inter = np.logical_and(a, b).sum()
        union = np.logical_or(a, b).sum()
        return inter / max(union, 1)

    def f_rad(a, b):
        ra, rb = cs.radial_sig(a), cs.radial_sig(b)
        if ra is None or rb is None:
            return 0.0
        return max(0.0, 1.0 - float(np.linalg.norm(ra - rb)) / 0.30)

    eval_cases(cases, f_iou, "iou_rot")
    eval_cases(cases, f_iou0, "iou0")
    eval_cases(cases, f_rad, "radial")
    eval_cases(cases, lambda a, b: 0.65 * f_iou(a, b) + 0.35 * f_rad(a, b), "mix65")
