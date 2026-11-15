#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evaluasi template solver dengan split waktu (bank dari masa lalu, uji masa depan)."""
import json
import cv2
import numpy as np

import cosmos_templates as ct


def build_banks(rows):
    header, content = {}, {}
    for r in rows:
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
        if any(x in (None, "?") for x in labels) or len(set(labels)) != 3:
            continue
        base = ct.provided_header_templates()
        crops = ct.crop_header(img)
        clean = []
        for i, c in enumerate(crops):
            sc = {k: ct._tmatch(c["crop"], t) for k, t in base.items()}
            bn = max(sc, key=sc.get)
            name = bn if sc[bn] >= 0.90 else labels[i]
            clean.append(name)
            header.setdefault(name, []).append(c["crop"])
        if len(set(clean)) != 3:
            continue
        cands, _ = ct.content_candidates(img)
        pts = [tuple(map(int, p.split(","))) for p in r["pts"].split(";")]
        idx, ok = [], True
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
            content.setdefault(name, []).append(cands[bi]["crop"])
    return header, content


def evalset(cases, header, content):
    hok = bok = full = tot = 0
    details = []
    for r in cases:
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
        res, info = ct.solve(r["img"], header_bank=header, content_bank=content)
        if not res:
            details.append((r["ts"], "GAGAL", info))
            continue
        pred = [tuple(map(int, p.split(","))) for p in res["pts"].split(";")]
        true = [tuple(map(int, p.split(","))) for p in r["pts"].split(";")]
        # header acc
        hpred = [t["name"] for t in res["targets"]]
        hok += sum(hpred[i] == labels[i] for i in range(3))
        # blob acc: predicted tap harus dekat titik true yang sesuai
        for i in range(3):
            d = ((pred[i][0] - true[i][0]) ** 2 + (pred[i][1] - true[i][1]) ** 2) ** 0.5
            bok += (d <= 22)
        good = all(((pred[i][0] - true[i][0]) ** 2 + (pred[i][1] - true[i][1]) ** 2) ** 0.5 <= 22
                   for i in range(3))
        # unique
        good = good and len(set(pred)) == 3
        full += good
        tot += 3
        if not good:
            details.append((r["ts"], "SALAH", hpred, labels, pred, true,
                            [round(a["score"], 2) for a in res["assign"]]))
    return hok, bok, full, len(cases), details


def main():
    rows = [json.loads(l) for l in open("archive_index_fixed.jsonl")
            if json.loads(l)["result"] == "pass" and json.loads(l).get("assign")]
    cut = "2026-11-12T00:00:00"
    train = [r for r in rows if r["ts"] < cut]
    test = [r for r in rows if r["ts"] >= cut]
    header, content = build_banks(train)
    print("train", len(train), "test", len(test))
    print("bank header", {k: len(v) for k, v in header.items()})
    hok, bok, full, n, det = evalset(test, header, content)
    print(f"header {hok}/{n*3} ({hok/(n*3)*100:.1f}%)  blob {bok}/{n*3} ({bok/(n*3)*100:.1f}%)  full {full}/{n} ({full/n*100:.1f}%)")
    for d in det[:15]:
        print(d)


if __name__ == "__main__":
    main()
