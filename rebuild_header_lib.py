#!/usr/bin/env python3
"""Rebuild prototype H (ikon header) dari archive pass, label = semantic blob
yang sudah dikonfirmasi server (pairing dari pts, bukan tebakan library).

G prototype (grid) dipertahankan apa adanya.
"""
import json
import shutil

import cv2
import numpy as np

import cosmos_lib as cl
import cosmos_solver as cs


def main():
    shutil.copy("cosmos-lib.npz", "cosmos-lib.backup.npz")
    masks, labels, doms = cl.load_lib()
    keep = [(m, l) for m, l, d in zip(masks, labels, doms) if d != "H"]
    masks = [m for m, _ in keep]
    labels = [l for _, l in keep]
    doms = ["G"] * len(masks)
    print(f"G dipertahankan: {len(masks)}  (H lama dibuang)")

    proto = [cl.prep(m) for m in masks]
    added = skipped = 0

    def blob_sem(mask):
        q = cl.prep(cs.norm_mask(mask))
        best, bs = "?", -1.0
        for pf, l in zip(proto, labels):
            sc = cl.score_prep(q, pf)
            if sc > bs:
                best, bs = l, sc
        return best, bs

    seen = 0
    for line in open("archive_index.jsonl"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("result") != "pass":
            continue
        img_path = d.get("img") or ""
        img = cv2.imread(img_path)
        if img is None:
            skipped += 1
            continue
        icons = cs.header_icons(img)
        blobs = cs.grid_blobs(img)
        if len(icons) != 3 or len(blobs) < 3:
            skipped += 1
            continue
        pts = (d.get("pts") or "").split(";")
        if len(pts) != 3:
            skipped += 1
            continue
        seen += 1
        for i, p in enumerate(pts):
            try:
                x, y = map(int, p.split(","))
            except Exception:
                continue
            # cocokkan titik tap ke blob terdekat (koordinat tap = grid + HEAD)
            best, bd = None, 1e18
            for b in blobs:
                cx, cy = cl._tap_point(b, img)
                dd = (cx - x) ** 2 + (cy + cs.HEAD - y) ** 2
                if dd < bd:
                    best, bd = b, dd
            if best is None or bd > 40 ** 2:
                continue
            sem, sc = blob_sem(best["mask"])
            m = np.zeros((cs.HEAD, img.shape[1]), np.uint8)
            cv2.drawContours(m, [icons[i]], -1, 1, -1)
            nm = cs.norm_mask(m)
            if nm is not None:
                masks.append(nm)
                labels.append(sem)
                doms.append("H")
                added += 1
    cl._save(masks, labels, doms)
    print(f"gambar dipakai: {seen} | H baru: {added} | dilewati: {skipped}")
    print(f"total prototype: {len(masks)} "
          f"(G={sum(1 for d in doms if d=='G')}, H={sum(1 for d in doms if d=='H')})")


if __name__ == "__main__":
    main()
