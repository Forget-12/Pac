#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COSMOS LIB — prototype library utk captcha sf_cosmos
Library: mask 48x48 ternormalisasi + label semantik (satellite/star/moon/
rocket/ufo/saturn/sun/comet) dari blob grid yang sudah dikonfirmasi manual.
Matcher dua tahap (soft):
  sim(T,s) = maks skor antara target header dan prototype semantik s
  sim(B,s) = maks skor antara blob grid dan prototype semantik s
  skor akhir(T,B) = gabungan distribusi semantik -> greedy assignment
"""
import os
import numpy as np
import cv2

import cosmos_solver as cs

LIB = "cosmos-lib.npz"


def harvest_header(img_path, labels):
    """labels: dict {1..3: semantik} dari ikon header (domain 'H')."""
    masks, labs, doms = load_lib()
    img = cv2.imread(img_path)
    icons = cs.header_icons(img)
    added = []
    for idx, sem in labels.items():
        if idx < 1 or idx > len(icons):
            continue
        m = np.zeros((cs.HEAD, img.shape[1]), np.uint8)
        cv2.drawContours(m, [icons[idx - 1]], -1, 1, -1)
        nm = cs.norm_mask(m)
        if nm is None:
            continue
        masks.append(nm); labs.append(sem); doms.append("H")
        added.append((idx, sem))
    _save(masks, labs, doms)
    print(f"library header: +{len(added)}, total {len(masks)}")
    return added


def load_lib():
    if os.path.exists(LIB):
        d = np.load(LIB, allow_pickle=True)
        masks = list(d["masks"]); labels = list(d["labels"])
        doms = list(d["doms"]) if "doms" in d else ["G"] * len(masks)
        return masks, labels, doms
    return [], [], []


def save_lib(masks, labels):
    doms = ["G"] * len(masks)
    _save(masks, labels, doms)


def _save(masks, labels, doms):
    np.savez(LIB, masks=np.array(masks), labels=np.array(labels),
             doms=np.array(doms))


def harvest(img_path, labels):
    """labels: dict {no_blob: semantik} -> tambah ke library."""
    masks, labs, doms = load_lib()
    img = cv2.imread(img_path)
    blobs = cs.grid_blobs(img)
    added = []
    for idx, sem in labels.items():
        if idx < 1 or idx > len(blobs):
            print(f"  !! blob {idx} tidak ada ({len(blobs)} blob)")
            continue
        nm = cs.norm_mask(blobs[idx - 1]["mask"])
        if nm is None:
            continue
        masks.append(nm)
        labs.append(sem)
        doms.append("G")
        added.append((idx, sem))
    _save(masks, labs, doms)
    print(f"library: +{len(added)} prototype, total {len(masks)}")
    for i, s in added:
        print(f"   blob{i} -> {s}")
    return added


def _score(a, b):
    """skor kemiripan 0..1 antara dua mask ternormalisasi."""
    iou = cs.iou_rot(a, b)
    ra, rb = cs_radial(a), cs_radial(b)
    rr = 0.0
    if ra is not None and rb is not None:
        rr = max(0.0, 1.0 - float(np.linalg.norm(ra - rb)) / 0.30)
    return 0.65 * iou + 0.35 * rr


HEAD_DOMAIN = "H"   # domain prototype untuk klasifikasi ikon header ("H" atau "G")
_ROT_STEP = 10
_ROT_CACHE = {}


def prep(mask):
    """Pra-hitung fitur mask: radial signature + semua rotasi (vektor)."""
    key = (id(mask), mask.shape, int(mask.sum()))
    hit = _ROT_CACHE.get(key)
    if hit is not None:
        return hit
    rad = cs.radial_sig(mask)
    c, s = mask.shape[0] // 2, mask.shape[1] // 2
    rots = []
    for ang in range(0, 360, _ROT_STEP):
        if ang == 0:
            r = mask
        else:
            M = cv2.getRotationMatrix2D((s, c), ang, 1.0)
            r = (cv2.warpAffine(mask * 255, M, (mask.shape[1], mask.shape[0])) > 110)
        rots.append(r.astype(bool))
    out = (rad, np.stack(rots))
    _ROT_CACHE[key] = out
    return out


def score_prep(a, b):
    """Skor cepat: IoU(a vs semua rotasi b) + kemiripan radial."""
    ra, a_rots = a
    rb, b_rots = b
    a0 = a_rots[0]
    inter = np.logical_and(b_rots, a0).sum(axis=(1, 2))
    union = np.logical_or(b_rots, a0).sum(axis=(1, 2))
    iou = float((inter / np.maximum(union, 1)).max())
    rr = 0.0
    if ra is not None and rb is not None:
        rr = max(0.0, 1.0 - float(np.linalg.norm(ra - rb)) / 0.30)
    return 0.65 * iou + 0.35 * rr


def cs_radial(mask):
    import cosmos_solver as _cs
    # radial pada mask 48x48 — pakai fungsi solver
    f = _cs.radial_sig(mask)
    return f


def semantic_profile(mask, masks, labels, doms=None, domain=None):
    """distribusi semantik: skor tertinggi per label (filter domain)."""
    if doms is None:
        doms = ["G"] * len(masks)
    sems = sorted(set(labels))
    prof = {}
    for s in sems:
        best = 0.0
        for m, l, d in zip(masks, labels, doms):
            if l != s:
                continue
            if domain and d != domain:
                continue
            best = max(best, _score(mask, m))
        prof[s] = best
    return prof


def match(img_path, debug=True, out_debug="c-solve-debug.png"):
    masks, labels, doms = load_lib()
    if sum(1 for d in doms if d == "G") < 4:
        return None, "library grid terlalu kecil"
    if sum(1 for d in doms if d == "H") < 3:
        return None, "library header terlalu kecil"
    img = cv2.imread(img_path)
    icons = cs.header_icons(img)
    if len(icons) != 3:
        return None, f"ikon header {len(icons)}"
    blobs = cs.grid_blobs(img)
    if len(blobs) < 3:
        return None, f"blob {len(blobs)}"

    t_masks = []
    h = img[0:cs.HEAD]
    for ic in icons:
        m = np.zeros(h.shape[:2], np.uint8)
        cv2.drawContours(m, [ic], -1, 1, -1)
        t_masks.append(cs.norm_mask(m))

    # pra-hitung fitur (sekali per mask) -> skor cepat
    proto_feats = [prep(m) for m in masks]
    t_feats = [prep(t) for t in t_masks]
    b_feats = [prep(cs.norm_mask(b["mask"])) for b in blobs]
    sems = sorted(set(labels))

    def profile(qfeat, domain):
        prof = {}
        for s in sems:
            best = 0.0
            for pf, l, d in zip(proto_feats, labels, doms):
                if l != s or (domain and d != domain):
                    continue
                sc = score_prep(qfeat, pf)
                if sc > best:
                    best = sc
            prof[s] = best
        return prof

    tprof = [profile(f, HEAD_DOMAIN) for f in t_feats]
    bprof = [profile(f, "G") for f in b_feats]

    # skor gabungan: Bhattacharyya antara profil (setelah baseline)
    def norm(p):
        base = np.median(list(p.values()))
        adj = {s: max(0.0, v - base) for s, v in p.items()}
        z = sum(adj.values()) + 1e-9
        return {s: v / z for s, v in adj.items()}
    tprof_n = [norm(p) for p in tprof]
    bprof_n = [norm(p) for p in bprof]

    pairs = []
    for ti, tp in enumerate(tprof_n):
        for bi, bp in enumerate(bprof_n):
            sc = sum(np.sqrt(tp[s] * bp.get(s, 0.0)) for s in tp)
            pairs.append((-sc, ti, bi))
    pairs.sort()
    taps, used_t, used_b, detail, assign = {}, set(), set(), [], []
    for neg, ti, bi in pairs:
        if ti in used_t or bi in used_b:
            continue
        used_t.add(ti); used_b.add(bi)
        bx0, by0 = blobs[bi]["bbox"][0], blobs[bi]["bbox"][1]
        cx, cy = _tap_point(blobs[bi], img)
        taps[ti] = (cx, cy)
        ts = max(tprof[ti].items(), key=lambda kv: kv[1])
        bs = max(bprof[bi].items(), key=lambda kv: kv[1])
        detail.append((ti + 1, (cx, cy), round(-neg, 3),
                       f"T~{ts[0]}:{ts[1]:.2f} B~{bs[0]}:{bs[1]:.2f}"))
        assign.append({"t": ti + 1, "blob": bi + 1, "tsem": ts[0], "tsscore": ts[1],
                       "bsem": bs[0], "score": round(-neg, 3)})
        if len(taps) == 3:
            break
    if len(taps) < 3:
        return None, f"pasangan cukup {len(taps)}/3"
    pts = ";".join(f"{taps[i][0]},{taps[i][1] + cs.HEAD}" for i in range(3))
    minscore = min(a["score"] for a in assign)
    blob_sem = []
    for p in bprof:
        s, v = max(p.items(), key=lambda kv: kv[1])
        blob_sem.append((s, float(v)))
    if debug:
        vis = img.copy()
        for num, (cx, cy), sc, info in detail:
            cv2.circle(vis, (cx, cy + cs.HEAD), 13, (0, 0, 255), 2)
            cv2.putText(vis, str(num), (cx - 5, cy + cs.HEAD - 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        cv2.imwrite(out_debug, vis)
    return {"pts": pts, "assign": assign, "min_score": minscore,
            "blob_sem": blob_sem}, detail


def _tap_point(blob, img):
    """pusat lingkaran maksimal (distance transform) di union core — pusat sprite sejati."""
    hsv = cv2.cvtColor(img[cs.HEAD:cs.H], cv2.COLOR_BGR2HSV)
    x, y, w, h = blob["bbox"]
    bx0, by0 = max(0, x), max(0, y)
    sub = hsv[by0:y + h, bx0:x + w]
    m = cv2.inRange(sub, (0, 135, 180), (180, 255, 255))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n2, lab2, st2, cc2 = cv2.connectedComponentsWithStats(m)
    keep = np.zeros_like(m)
    for j in range(1, n2):
        if st2[j, 4] > 100:
            keep[lab2 == j] = 1
    if keep.sum() > 100:
        dist = cv2.distanceTransform(keep, cv2.DIST_L2, 5)
        _, _, _, loc = cv2.minMaxLoc(dist)
        return int(loc[0] + bx0), int(loc[1] + by0)
    return blob["cent"]


def harvest_pass(img_path, assign, harvest_header=True):
    """Setelah server konfirmasi PASS: tambah blob & ikon header ke library.

    harvest_header=False untuk jalur manual/guess: pairing target->blob dari
    library belum tentu sama dengan jawaban yang dikirim, jadi ikon header
    jangan dimasukkan (menghindari label salah).
    """
    masks, labels, doms = load_lib()
    img = cv2.imread(img_path)
    if img is None:
        return 0
    blobs = cs.grid_blobs(img)
    icons = cs.header_icons(img)
    added = 0
    for a in assign:
        bi = a["blob"] - 1
        if 0 <= bi < len(blobs):
            nm = cs.norm_mask(blobs[bi]["mask"])
            if nm is not None:
                masks.append(nm); labels.append(a["bsem"]); doms.append("G")
                added += 1
        if not harvest_header:
            continue
        ti = a["t"] - 1
        if 0 <= ti < len(icons):
            m = np.zeros((cs.HEAD, img.shape[1]), np.uint8)
            cv2.drawContours(m, [icons[ti]], -1, 1, -1)
            nm = cs.norm_mask(m)
            if nm is not None:
                masks.append(nm); labels.append(a["tsem"]); doms.append("H")
                added += 1
    _save(masks, labels, doms)
    return added


if __name__ == "__main__":
    import sys
    if sys.argv[1] == "harvest":
        img = sys.argv[2]
        labels = {}
        for kv in sys.argv[3:]:
            k, v = kv.split("=")
            labels[int(k)] = v
        harvest(img, labels)
    elif sys.argv[1] == "harvest-header":
        img = sys.argv[2]
        labels = {}
        for kv in sys.argv[3:]:
            k, v = kv.split("=")
            labels[int(k)] = v
        harvest_header(img, labels)
    else:
        p = sys.argv[1] if len(sys.argv) > 1 else "frozen.png"
        r, info = match(p)
        if r is None:
            print("GAGAL:", info)
        else:
            print("PTS:", r["pts"], "| min_score:", round(r["min_score"], 3))
            for a in r["assign"]:
                print("  ", a)
