#!/usr/bin/env python3
"""BUILD TEMPLATES — template koordinat dari gambar PASS + assign.
Output:
  template/<nama>.png     : preview anotasi (box + nomor blob + semantik + tap)
  templates.json          : indeks {img, targets, blobs:[bbox,semantic,tap], pts}
"""
import json
import os
import cv2
import numpy as np
import cosmos_solver as cs

HEAD = cs.HEAD


def main():
    os.makedirs("template", exist_ok=True)
    entries = []
    if not os.path.exists("archive_index.jsonl"):
        print("belum ada archive_index.jsonl")
        return
    for line in open("archive_index.jsonl"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("result") != "pass" or not d.get("assign"):
            continue
        img = d["img"]
        if not os.path.exists(img):
            continue
        im = cv2.imread(img)
        if im is None:
            continue
        blobs = cs.grid_blobs(im)
        vis = im.copy()
        blobinfo = []
        for a in d["assign"]:
            bi = a["blob"] - 1
            if bi < 0 or bi >= len(blobs):
                continue
            b = blobs[bi]
            x, y, w, h = [int(v) for v in b["bbox"]]
            cv2.rectangle(vis, (x, y + HEAD), (x + w, y + h + HEAD), (0, 255, 0), 1)
            cv2.putText(vis, f"t{a['t']}:{a['tsem']}", (x, y + HEAD - 3),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
            cx, cy = int(a.get("scorex", 0)), 0  # placeholder tidak dipakai
            blobinfo.append({
                "target": a["t"], "blob_idx": a["blob"],
                "bbox_grid": [x, y, w, h],
                "bbox_full": [x, y + HEAD, w, h],
                "semantic": a["tsem"], "tsscore": a.get("tsscore"),
                "score": a.get("score"),
            })
        # tap points
        pts = {}
        for i, p in enumerate(d["pts"].split(";"), 1):
            px, py = p.split(",")
            pts[str(i)] = [int(px), int(py)]
            cv2.circle(vis, (int(px), int(py)), 12, (0, 0, 255), 2)
        name = os.path.basename(img).replace(".png", ".tpl.png")
        cv2.imwrite(f"template/{name}", vis)
        entries.append({"img": img, "template": f"template/{name}",
                        "targets": [a["tsem"] for a in d["assign"]],
                        "blobs": blobinfo, "pts": pts, "ts": d.get("ts")})
    with open("templates.json", "w") as f:
        json.dump(entries, f, indent=1, ensure_ascii=False)
    print(f"templates.json: {len(entries)} entri | template/ berisi {len(entries)} preview")


if __name__ == "__main__":
    main()
