#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Template-based sf_cosmos solver (kolaborasi dengan cosmos_lib / cosmos_solver).

Ide: klasifikasi ikon target di header memakai template abu-abu 42x30,
lalu cocokkan blob grid memakai template biner 70x70 (multi-sampel, rotasi).
Semua template bisa ditambah otomatis (harvest) dan disimpan sebagai base64.
"""
import base64
import json
import os

import cv2
import numpy as np

TEMPLATE_FILE = "cosmos-templates.json"

HEADER_BOXES = [(58, 100), (144, 186), (230, 273)]
HEADER_Y = (15, 45)
CONTENT_SIZE = 70

# Template header awal (siluet putih di header, abu-abu 42x30).
HEADER_BASE64 = {
    "moon": "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",
    "planet": "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",
    "rocket": "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",
    "satellite": "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",
    "star": "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",
    "sun": "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",
    "ufo": "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",
}


def _b64_to_gray(b64):
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    raw = base64.b64decode(b64)
    arr = np.frombuffer(raw, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)


def _gray_to_b64(img):
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        return None
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _mask_to_b64(mask):
    return _gray_to_b64((mask > 0).astype(np.uint8) * 255)


def _canon(name):
    return {"planet": "saturn", "meteor": "comet"}.get(name, name)


def provided_header_templates():
    out = {}
    for name, b64 in HEADER_BASE64.items():
        g = _b64_to_gray(b64)
        if g is not None:
            out[_canon(name)] = g
    return out


def load_header_bank():
    """Semua varian header per kelas (list gambar), untuk skor maksimum."""
    bank = {}
    for name, b64 in HEADER_BASE64.items():
        g = _b64_to_gray(b64)
        if g is not None:
            bank.setdefault(_canon(name), []).append(g)
    if os.path.exists(TEMPLATE_FILE):
        try:
            d = json.load(open(TEMPLATE_FILE))
        except Exception:
            d = {}
        for name, arr in d.get("header", {}).items():
            name = _canon(name)
            for b64 in arr:
                g = _b64_to_gray(b64)
                if g is not None and g.shape[0] >= 20 and g.shape[1] >= 20:
                    bank.setdefault(name, []).append(g)
    for k in bank:
        seen, out = set(), []
        for g in bank[k]:
            key = (g.shape, g.tobytes())
            if key in seen:
                continue
            seen.add(key)
            out.append(g)
        bank[k] = out
    return bank


def load_header_templates():
    return {k: v[0] for k, v in load_header_bank().items() if v}


def load_content_templates():
    """Muat template konten dari file JSON (hasil harvest), jika ada."""
    if not os.path.exists(TEMPLATE_FILE):
        return {}
    try:
        d = json.load(open(TEMPLATE_FILE))
    except Exception:
        return {}
    out = {}
    for name, arr in d.get("content", {}).items():
        imgs = []
        for b64 in arr:
            g = _b64_to_gray(b64)
            if g is not None:
                imgs.append(g)
        if imgs:
            out[name] = imgs
    return out


def save_content_templates(templates):
    data = {"content": {}}
    if os.path.exists(TEMPLATE_FILE):
        try:
            data = json.load(open(TEMPLATE_FILE))
        except Exception:
            data = {"content": {}}
    data["content"] = {
        name: [_gray_to_b64(g) for g in imgs if g is not None]
        for name, imgs in templates.items()
    }
    tmp = TEMPLATE_FILE + ".tmp"
    json.dump(data, open(tmp, "w"))
    os.replace(tmp, TEMPLATE_FILE)


def add_header_template(name, gray):
    data = {"content": {}, "header": {}}
    if os.path.exists(TEMPLATE_FILE):
        try:
            data = json.load(open(TEMPLATE_FILE))
        except Exception:
            pass
    data.setdefault("header", {}).setdefault(name, []).append(_gray_to_b64(gray))
    data["header"][name] = data["header"][name][-120:]
    tmp = TEMPLATE_FILE + ".tmp"
    json.dump(data, open(tmp, "w"))
    os.replace(tmp, TEMPLATE_FILE)


def _tmatch(a, b):
    if a.shape[0] < b.shape[0] or a.shape[1] < b.shape[1]:
        b = cv2.resize(b, (a.shape[1], a.shape[0]))
    res = cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)
    _, mv, _, _ = cv2.minMaxLoc(res)
    return float(mv)


def header_scores(img, bank=None):
    """Skor tiap kelas untuk 3 ikon header (maks atas semua varian)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if bank is None:
        bank = load_header_bank()
    out = []
    for xs, xe in HEADER_BOXES:
        crop = gray[HEADER_Y[0]:HEADER_Y[1], xs:xe]
        sc = {}
        for name, tpls in bank.items():
            best = -1.0
            for t in tpls:
                s = _tmatch(crop, t)
                if s > best:
                    best = s
            sc[name] = best
        out.append(sc)
    return out


def crop_header(img):
    """Kembalikan list dict(name, score, crop, bbox) utk 3 ikon header."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    scores = header_scores(img)
    out = []
    for i, (xs, xe) in enumerate(HEADER_BOXES):
        sc = scores[i]
        best_name = max(sc, key=sc.get) if sc else "unknown"
        best_score = sc.get(best_name, -1.0)
        crop = gray[HEADER_Y[0]:HEADER_Y[1], xs:xe]
        out.append({"name": best_name, "score": best_score, "crop": crop,
                    "scores": sc,
                    "bbox": (xs, HEADER_Y[0], xe - xs, HEADER_Y[1] - HEADER_Y[0])})
    return out


def content_candidates(img):
    """Segmentasi kandidat konten (threshold grayscale 120) + crop 70x70."""
    height, width = img.shape[:2]
    y0 = int(height * 0.15)
    gray = cv2.cvtColor(img[y0:height, 0:width], cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    _, thresh = cv2.threshold(blurred, 120, 255, cv2.THRESH_BINARY)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    cands = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if not (10 <= w <= 150 and 10 <= h <= 150):
            continue
        cx, cy = x + w // 2, y + h // 2
        hx = CONTENT_SIZE // 2
        x1, y1 = max(0, cx - hx), max(0, cy - hx)
        x2, y2 = min(thresh.shape[1], cx + hx), min(thresh.shape[0], cy + hx)
        crop = thresh[y1:y2, x1:x2]
        if crop.shape != (CONTENT_SIZE, CONTENT_SIZE):
            crop = cv2.resize(crop, (CONTENT_SIZE, CONTENT_SIZE),
                              interpolation=cv2.INTER_NEAREST)
        cands.append({"x": cx, "y": cy + y0, "crop": crop,
                      "w": CONTENT_SIZE, "h": CONTENT_SIZE,
                      "area": int(cv2.contourArea(c))})
    return _dedupe_candidates(cands), y0


def _dedupe_candidates(cands, min_dist=26):
    """Buang kandidat duplikat/pecahan (pusat berdekatan), sisakan area terbesar."""
    cands = sorted(cands, key=lambda c: -c.get("area", 0))
    out = []
    for c in cands:
        if all(((c["x"] - o["x"]) ** 2 + (c["y"] - o["y"]) ** 2) ** 0.5 >= min_dist
               for o in out):
            out.append(c)
    return out


def _best_assignment(S, n_targets=3):
    """S[t][b] -> (perm, best, second_best, class_margin)."""
    import itertools
    n = len(S[0])
    perms = list(itertools.permutations(range(n), n_targets))
    scored = []
    for p in perms:
        scored.append((sum(S[t][p[t]] for t in range(n_targets)), p))
    scored.sort(reverse=True)
    best, bp = scored[0]
    second = scored[1][0] if len(scored) > 1 else -1e9
    # margin tiap target: skor terpilih vs kandidat terbaik lain
    cm = []
    for t in range(n_targets):
        vals = sorted((S[t][b] for b in range(n) if b != bp[t]), reverse=True)
        cm.append(S[t][bp[t]] - (vals[0] if vals else 0))
    return list(bp), best, second, min(cm)


def _rotate(img, angle):
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def _match_score(cand, templates, step=30):
    best = -1.0
    for t in templates:
        if t.shape != cand.shape:
            t = cv2.resize(t, (cand.shape[1], cand.shape[0]))
        for ang in range(0, 360, step):
            r = t if ang == 0 else _rotate(t, ang)
            res = cv2.matchTemplate(cand, r, cv2.TM_CCOEFF_NORMED)
            _, mv, _, _ = cv2.minMaxLoc(res)
            if mv > best:
                best = float(mv)
    return best


def _refine_tap(img, cand):
    """Pakai pusat sprite dari grid_blobs (distance transform) bila berdekatan."""
    try:
        import cosmos_solver as cs
        import cosmos_lib as cl
    except Exception:
        return cand["x"], cand["y"]
    try:
        blobs = cs.grid_blobs(img)
    except Exception:
        return cand["x"], cand["y"]
    best, bd = None, 1e9
    for b in blobs:
        cx, cy = cl._tap_point(b, img)
        d = ((cx - cand["x"]) ** 2 + (cy + cs.HEAD - cand["y"]) ** 2) ** 0.5
        if d < bd:
            best, bd = (int(cx), int(cy + cs.HEAD)), d
    if best is not None and bd <= 32:
        return best
    return cand["x"], cand["y"]


def solve(path, debug=False, header_bank=None, content_bank=None):
    """Return dict(pts, assign, min_score, margin, confidence, ...) atau None."""
    img = cv2.imread(path)
    if img is None:
        return None, "gambar tidak terbaca"
    scores = header_scores(img, bank=header_bank)
    targets = []
    for i, sc in enumerate(scores):
        bn = max(sc, key=sc.get) if sc else "unknown"
        targets.append({"name": bn, "score": sc.get(bn, -1.0), "scores": sc})
    if any(t["name"] == "unknown" for t in targets):
        return None, "header tidak dikenal"
    if len({t["name"] for t in targets}) != 3:
        return None, "target ganda: " + ",".join(t["name"] for t in targets)
    cands, _ = content_candidates(img)
    if len(cands) < 3:
        return None, f"kandidat {len(cands)}"
    templates = content_bank if content_bank is not None else load_content_templates()
    if not templates:
        return None, "template konten kosong"
    # matriks skor target x kandidat
    S, detail_scores = [], []
    for ti, t in enumerate(targets):
        tpls = templates.get(t["name"], [])
        if not tpls:
            return None, f"template '{t['name']}' kosong"
        row = [_match_score(c["crop"], tpls) for c in cands]
        S.append(row)
        detail_scores.append(row)
    perm, best, second, class_margin = _best_assignment(S)
    assign, detail = [], []
    for ti, bi in enumerate(perm):
        c = cands[bi]
        tx, ty = _refine_tap(img, c)
        assign.append({"t": ti + 1, "blob": bi + 1, "tsem": targets[ti]["name"],
                       "bsem": targets[ti]["name"],
                       "score": round(float(S[ti][bi]), 3)})
        detail.append((ti + 1, (tx, ty), round(float(S[ti][bi]), 3),
                       targets[ti]["name"]))
    pts = ";".join(f"{detail[i][1][0]},{detail[i][1][1]}" for i in range(3))
    content_min = min(a["score"] for a in assign)
    header_min = min(t["score"] for t in targets)
    assign_margin = best - second
    # confidence heuristik: skor minimum + margin assignment + margin kelas
    conf = (min(header_min, content_min)
            + 0.35 * min(max(assign_margin, 0.0), 0.6)
            + 0.25 * min(max(class_margin, 0.0), 0.4))
    if debug:
        vis = img.copy()
        for num, (cx, cy), sc, name in detail:
            cv2.circle(vis, (cx, cy), 14, (0, 0, 255), 2)
            cv2.putText(vis, f"{num}:{name}", (cx - 18, cy - 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
        cv2.imwrite("c-template-debug.png", vis)
    return {"pts": pts, "assign": assign, "min_score": content_min,
            "header_min": round(float(header_min), 3),
            "content_min": round(float(content_min), 3),
            "assign_margin": round(float(assign_margin), 3),
            "class_margin": round(float(class_margin), 3),
            "confidence": round(float(conf), 3),
            "candidates": [{"blob": i + 1, "x": c["x"], "y": c["y"]}
                           for i, c in enumerate(cands)],
            "targets": [{"t": i + 1, "name": t["name"],
                         "score": round(t["score"], 3)}
                        for i, t in enumerate(targets)]}, detail


def harvest_from_pass(img_path, pts, header_labels=None, content_labels=None):
    """Tambah template header + konten dari challenge yang sudah PASS.

    header_labels: list 3 nama (opsional, default hasil crop_header).
    content_labels: list 3 nama sesuai urutan pts (opsional).
    """
    img = cv2.imread(img_path)
    if img is None:
        return 0
    targets = crop_header(img)
    if header_labels is None:
        header_labels = [t["name"] for t in targets]
    cands, _ = content_candidates(img)
    if not cands:
        return 0
    used = []
    for p in pts.split(";"):
        try:
            x, y = map(int, p.split(","))
        except Exception:
            return 0
        bi = min(range(len(cands)),
                 key=lambda i: (cands[i]["x"] - x) ** 2 + (cands[i]["y"] - y) ** 2)
        used.append(bi)
    if len(set(used)) != 3:
        return 0
    if content_labels is None:
        content_labels = header_labels
    data = {"header": {}, "content": {}}
    if os.path.exists(TEMPLATE_FILE):
        try:
            data = json.load(open(TEMPLATE_FILE))
        except Exception:
            pass
    data.setdefault("header", {})
    data.setdefault("content", {})
    added = 0
    for bi, name in zip(used, content_labels):
        if name in (None, "unknown"):
            continue
        arr = data["content"].setdefault(name, [])
        arr.append(_mask_to_b64(cands[bi]["crop"]))
        data["content"][name] = arr[-120:]
        added += 1
    for i, name in enumerate(header_labels):
        if name in (None, "unknown") or i >= len(targets):
            continue
        arr = data["header"].setdefault(name, [])
        arr.append(_gray_to_b64(targets[i]["crop"]))
        data["header"][name] = arr[-120:]
        added += 1
    if added:
        tmp = TEMPLATE_FILE + ".tmp"
        json.dump(data, open(tmp, "w"))
        os.replace(tmp, TEMPLATE_FILE)
    return added


if __name__ == "__main__":
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else "c-cosmos.png"
    r, info = solve(p, debug=True)
    print("PTS:", r["pts"] if r else None)
    print("info:", info)
    if r:
        print("target:", r["targets"])
        print("assign:", r["assign"])
