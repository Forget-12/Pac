#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bangun bank template header + konten dari archive PASS yang sudah terkonfirmasi."""
import json
import os
import cv2
import numpy as np

import cosmos_templates as ct

ROWS = [json.loads(l) for l in open("archive_index_fixed.jsonl")
        if json.loads(l)["result"] == "pass"]
OUT = "cosmos-templates.json"


def main():
    header = {}
    content = {}
    used = 0
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
        if len(set(labels)) != 3:
            continue
        crops = ct.crop_header(img)
        base = ct.provided_header_templates()
        # label header: template awal dulu (akurat utk 8 kelas dasar),
        # fallback bsem hanya utk varian sun/comet/saturn (skor < 0.9)
        clean = []
        for i, c in enumerate(crops):
            sc = {k: ct._tmatch(c["crop"], t) for k, t in base.items()}
            bn = max(sc, key=sc.get)
            name = bn if sc[bn] >= 0.90 else labels[i]
            clean.append(name)
            header.setdefault(name, []).append(ct._gray_to_b64(c["crop"]))
        if len(set(clean)) != 3:
            continue
        cands, _ = ct.content_candidates(img)
        if not cands:
            continue
        pts = [tuple(map(int, p.split(","))) for p in r["pts"].split(";")]
        idx = []
        ok = True
        for x, y in pts:
            bi = min(range(len(cands)),
                     key=lambda i: (cands[i]["x"] - x) ** 2 + (cands[i]["y"] - y) ** 2)
            d = ((cands[bi]["x"] - x) ** 2 + (cands[bi]["y"] - y) ** 2) ** 0.5
            if d > 24:
                ok = False
                break
            idx.append(bi)
        if not ok or len(set(idx)) != 3:
            continue
        for bi, name in zip(idx, clean):
            content.setdefault(name, []).append(ct._mask_to_b64(cands[bi]["crop"]))
        used += 1
    # dedupe + batasi
    for d in (header, content):
        for k in list(d):
            seen, out = set(), []
            for b in d[k]:
                if b in seen:
                    continue
                seen.add(b)
                out.append(b)
            d[k] = out[:120]
    data = {"header": header, "content": content}
    json.dump(data, open(OUT + ".tmp", "w"))
    os.replace(OUT + ".tmp", OUT)
    print("cases", used)
    print("header", {k: len(v) for k, v in header.items()})
    print("content", {k: len(v) for k, v in content.items()})


if __name__ == "__main__":
    main()
