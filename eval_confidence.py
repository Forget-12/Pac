#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5-fold CV: akurasi + distribusi confidence template solver."""
import json
import cv2
import numpy as np

import cosmos_templates as ct
from eval_template_split import build_banks


def dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def main():
    rows = [json.loads(l) for l in open("archive_index_fixed.jsonl")
            if json.loads(l)["result"] == "pass" and json.loads(l).get("assign")
            and "c-cosmos" not in json.loads(l)["img"]]
    print("cases", len(rows))
    K = 5
    folds = [rows[i::K] for i in range(K)]
    recs = []
    for fi in range(K):
        test = folds[fi]
        train = [r for j, f in enumerate(folds) if j != fi for r in f]
        header, content = build_banks(train)
        for r in test:
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
                recs.append((r["ts"], 0, 0, 0, 0, 0, labels, None, info))
                continue
            pred = [tuple(map(int, p.split(","))) for p in res["pts"].split(";")]
            true = [tuple(map(int, p.split(","))) for p in r["pts"].split(";")]
            ds = [dist(pred[i], true[i]) for i in range(3)]
            good = all(d <= 30 for d in ds) and len(set(pred)) == 3
            recs.append((r["ts"], good, res["confidence"], res["header_min"],
                         res["content_min"], res["assign_margin"],
                         labels, [round(d, 1) for d in ds], res["pts"]))
    ok = sum(1 for x in recs if x[1])
    print(f"full {ok}/{len(recs)} ({ok/len(recs)*100:.1f}%)")
    print("\n== CORRECT ==")
    for x in sorted([x for x in recs if x[1]], key=lambda z: z[2])[:8]:
        print(x[2:6], x[6], x[7])
    print("... high:")
    for x in sorted([x for x in recs if x[1]], key=lambda z: z[2])[-5:]:
        print(x[2:6], x[6], x[7])
    print("\n== WRONG ==")
    for x in sorted([x for x in recs if not x[1]], key=lambda z: -z[2]):
        print(x[0], "conf/hmin/cmin/am=", x[2:6], "labels", x[6], "d", x[7],
              "pts", x[8])
    # threshold grid
    print("\n== threshold grid (hmin>=.9) ==")
    for cmin in (0.70, 0.75, 0.80, 0.85, 0.90):
        for conf in (0.90, 1.00, 1.05, 1.10):
            sel = [x for x in recs if x[1] is not None and x[3] >= 0.90
                   and x[4] >= cmin and x[2] >= conf]
            if not sel:
                continue
            acc = sum(1 for x in sel if x[1]) / len(sel)
            print(f"cmin>={cmin} conf>={conf}: n={len(sel)} acc={acc*100:.0f}%")


if __name__ == "__main__":
    main()
