import os
import base64
import time
import math
import io
import json
import asyncio
import numpy as np
from typing import List, Dict, Any, Optional

try:
    from .utils import CaptchaError
except ImportError:
    from utils import CaptchaError

class AlcaptchaSolver:
    def __init__(self):
        self.VA71 = [
            [0, -3], [1, -3], [2, -2], [3, -1], [3, 0],
            [3, 1], [2, 2], [1, 3], [0, 3], [-1, 3],
            [-2, 2], [-3, 1], [-3, 0], [-3, -1],
            [-2, -2], [-1, -3]
        ]
        self.VF1094 = self._make_vF1094()
        self._POPCNT = np.array([bin(i).count('1') for i in range(256)], dtype=np.uint8)
        self._TRANSFORM_CACHE = {}

    def _make_vF1094(self):
        t = np.zeros((256, 4), dtype=np.int8)
        seed = 2271560481
        for i in range(256):
            for j in range(4):
                seed = ((seed * 1103515245) + 12345) & 2147483647
                t[i, j] = (seed % 25) - 12
        return t

    def f65(self, buf):
        from PIL import Image, ImageSequence

        im = Image.open(io.BytesIO(buf))
        out_frames = []
        for frame in ImageSequence.Iterator(im):
            arr = np.asarray(frame.convert('RGBA'), dtype=np.uint8)
            out_frames.append({
                'data': arr.ravel(),
                'width': arr.shape[1],
                'height': arr.shape[0]
            })
        return out_frames

    def f70(self, s):
        b64 = s.split(',', 1)[1] if ',' in s else s
        return base64.b64decode(b64)

    def f71(self, x, y, w, h):
        cw = w / 3; ch = h / 2
        return [min(int(y / ch), 1), min(int(x / cw), 2)]

    def f72(self, data, w, h, threshold, min_run):
        d = np.asarray(data, dtype=np.int32).reshape(h, w)
        if h < 7 or w < 7:
            return []
        ys_all, xs_all = np.meshgrid(
            np.arange(3, h-3, dtype=np.int32),
            np.arange(3, w-3, dtype=np.int32),
            indexing='ij')
        ys_all = ys_all.ravel(); xs_all = xs_all.ravel()
        N = ys_all.size
        if N == 0: return []
        ring = np.empty((N, 16), dtype=np.int32)
        for i in range(16):
            dy, dx = self.VA71[i][1], self.VA71[i][0]
            ring[:, i] = d[ys_all + dy, xs_all + dx]
        center = d[ys_all, xs_all]
        above = np.zeros(N, dtype=np.int32); below = np.zeros(N, dtype=np.int32)
        for i in (0, 4, 8, 12):
            above += (ring[:, i] > center + threshold)
            below += (ring[:, i] < center - threshold)
        cand = (above >= 3) | (below >= 3)
        if not cand.any(): return []
        ys_c = ys_all[cand]; xs_c = xs_all[cand]
        ring = ring[cand]; center = center[cand]
        M = ys_c.size
        gt = (ring > (center + threshold)[:, None]).astype(np.int32)
        lt = (ring < (center - threshold)[:, None]).astype(np.int32)
        gt2 = np.concatenate([gt, gt, gt], axis=1)
        lt2 = np.concatenate([lt, lt, lt], axis=1)
        ra = np.zeros_like(gt2); rb = np.zeros_like(lt2)
        ra[:, 0] = gt2[:, 0]; rb[:, 0] = lt2[:, 0]
        for k in range(1, 48):
            ra[:, k] = (ra[:, k-1] + 1) * gt2[:, k]
            rb[:, k] = (rb[:, k-1] + 1) * lt2[:, k]
        found = ((ra[:, 16:32] >= min_run).any(axis=1)) | ((rb[:, 16:32] >= min_run).any(axis=1))
        if not found.any(): return []
        ys_f = ys_c[found]; xs_f = xs_c[found]
        if ys_f.size > 500:
            cen = d[ys_f, xs_f]
            score = np.zeros(ys_f.size, dtype=np.int64)
            for i in range(16):
                dy, dx = self.VA71[i][1], self.VA71[i][0]
                score += np.abs(cen - d[ys_f + dy, xs_f + dx])
            top = np.argsort(-score, kind='stable')[:500]
            ys_f = ys_f[top]; xs_f = xs_f[top]
        return [{'x': int(xs_f[i]), 'y': int(ys_f[i])} for i in range(ys_f.size)]

    def f73(self, img, w, h, pt):
        arr = np.asarray(img)
        xi = pt['x']; yi = pt['y']
        x1 = xi + self.VF1094[:, 0].astype(np.int64)
        y1 = yi + self.VF1094[:, 1].astype(np.int64)
        x2 = xi + self.VF1094[:, 2].astype(np.int64)
        y2 = yi + self.VF1094[:, 3].astype(np.int64)
        valid = (x1 >= 0) & (x1 < w) & (y1 >= 0) & (y1 < h) & (x2 >= 0) & (x2 < w) & (y2 >= 0) & (y2 < h)
        bits = np.zeros(32, dtype=np.uint8)
        idx = np.where(valid)[0]
        if idx.size == 0: return bits
        a = arr[y1[idx] * w + x1[idx]]
        b = arr[y2[idx] * w + x2[idx]]
        greater = a > b
        fi = idx[greater]
        if fi.size == 0: return bits
        np.bitwise_or.at(bits, fi >> 3, (1 << (fi & 7)).astype(np.uint8))
        return bits

    def f74(self, v):
        v = v & 0xFFFFFFFF
        v = v - ((v >> 1) & 0x55555555)
        v = (v & 0x33333333) + ((v >> 2) & 0x33333333)
        v = (v + (v >> 4)) & 0x0F0F0F0F
        return ((v * 0x01010101) & 0xFFFFFFFF) >> 24

    def f75(self, a, b):
        x = np.bitwise_xor(np.asarray(a, dtype=np.uint8), np.asarray(b, dtype=np.uint8))
        return int(self._POPCNT[x].sum())

    def f76(self, data, w, h):
        if len(data) == 0: return np.zeros(0, dtype=np.uint8)
        arr = np.asarray(data, dtype=np.int64).reshape(-1, 4)
        return ((arr[:, 0]*77 + arr[:, 1]*150 + arr[:, 2]*29) >> 8).astype(np.uint8)

    def f77(self, p2713, p2714, p2715=None, src_rgb=None):
        import cv2
        H = p2713['rows']; W = p2713['cols']
        th = p2714['rows']; tw = p2714['cols']

        if src_rgb is None:
            src_flat = np.asarray(p2713['data'], dtype=np.uint8)
            src_rgb = src_flat.reshape(H, W, 4)[..., :3].astype(np.float32)

        # Cache template per objek: dipakai untuk semua frame.
        tmpl_rgb = p2714.get('_rgb_f32')
        mask_rgb = p2714.get('_mask_rgb')
        if tmpl_rgb is None or mask_rgb is None:
            tmpl_flat = np.asarray(p2714['data'], dtype=np.uint8)
            tmpl = tmpl_flat.reshape(th, tw, 4)
            mask = ~((tmpl[..., 0] == 0) & (tmpl[..., 1] == 0)
                     & (tmpl[..., 2] == 0) & (tmpl[..., 3] == 0))
            if not mask.any():
                return {'score': 0, 'x': 0, 'y': 0}
            tmpl_rgb = tmpl[..., :3].astype(np.float32)
            mask_rgb = np.repeat(mask[..., None], 3, axis=2).astype(np.float32)
            p2714['_rgb_f32'] = tmpl_rgb
            p2714['_mask_rgb'] = mask_rgb

        result = cv2.matchTemplate(src_rgb, tmpl_rgb, cv2.TM_SQDIFF, mask=mask_rgb)

        if p2715:
            x0 = max(0, int(p2715['x'])); y0 = max(0, int(p2715['y']))
            x1 = min(result.shape[1], int(p2715['x'] + p2715['w']))
            y1 = min(result.shape[0], int(p2715['y'] + p2715['h']))
            if x0 < x1 and y0 < y1:
                result[y0:y1, x0:x1] = np.inf

        mi = np.unravel_index(int(result.argmin()), result.shape)
        return {'score': float(result[mi]), 'x': int(mi[1]), 'y': int(mi[0])}

    def f78(self, score_fn, t_cols, t_rows, s_cols, s_rows, roi):
        best = float('inf'); bx = by = 0
        for y in range(0, t_rows - s_rows + 1):
            for x in range(0, t_cols - s_cols + 1):
                if roi:
                    if (x < roi['x']+roi['w'] and x+s_cols > roi['x'] and
                        y < roi['y']+roi['h'] and y+s_rows > roi['y']):
                        continue
                s = score_fn(x, y)
                if s < best: best = s; bx = x; by = y
        return {'score': best, 'x': bx, 'y': by}

    def f79(self, img, tmpl, roi=None, p2871=240, p2872=255, src_bin=None):
        import cv2
        H = img['rows']; W = img['cols']
        th = tmpl['rows']; tw = tmpl['cols']

        if src_bin is None:
            src_flat = np.asarray(img['data'], dtype=np.uint8)
            src_gray = self.f76(src_flat, W, H).reshape(H, W)
            src_bin = np.where(src_gray > 235, 255, 0).astype(np.uint8)

        # Cache template biner per objek: dipakai untuk semua frame.
        tmpl_bin = tmpl.get('_bin')
        if tmpl_bin is None:
            tmpl_flat = np.asarray(tmpl['data'], dtype=np.uint8)
            tmpl_gray = self.f76(tmpl_flat, tw, th).reshape(th, tw)
            tmpl_bin = np.where(tmpl_gray > 80, 255, 0).astype(np.uint8)
            tmpl['_bin'] = tmpl_bin

        if src_bin.shape[0] < tmpl_bin.shape[0] or src_bin.shape[1] < tmpl_bin.shape[1]:
            return {'score': 0, 'x': 0, 'y': 0}
        if not tmpl_bin.any():
            return {'score': 0, 'x': 0, 'y': 0}

        result = cv2.matchTemplate(src_bin, tmpl_bin, cv2.TM_CCOEFF_NORMED)

        if roi:
            x0 = max(0, int(roi['x'])); y0 = max(0, int(roi['y']))
            x1 = min(result.shape[1], int(roi['x'] + roi['w']))
            y1 = min(result.shape[0], int(roi['y'] + roi['h']))
            if x0 < x1 and y0 < y1:
                result[y0:y1, x0:x1] = -np.inf

        mi = np.unravel_index(int(result.argmax()), result.shape)
        return {'score': float(result[mi]), 'x': int(mi[1]), 'y': int(mi[0])}

    def f80(self, a, b, c=None, d=240, e=255):
        return self.f79(a, b, c)

    def f84(self, img):
        arr = np.asarray(img['data'], dtype=np.float64).reshape(-1, 4)
        out = 0.299*arr[:,0] + 0.587*arr[:,1] + 0.114*arr[:,2]
        return {'data': out, 'width': img['width'], 'height': img['height']}

    def f85(self, img):
        import cv2
        m = img['width']; y = img['height']
        mat = img['data'].reshape((y, m)).astype(np.uint8)
        out = cv2.medianBlur(mat, 3)
        return {'data': out.flatten().astype(np.float64), 'width': m, 'height': y}

    def f86(self, img, sx, sy, ex, ey):
        g = img['width']; p = img['height']
        w = ex - sx; h = ey - sy
        out = np.full(w*h, 255.0, dtype=np.float64)
        src = np.asarray(img['data'], dtype=np.float64).reshape(p, g)
        y0 = max(0, sy); y1 = min(p, ey)
        x0 = max(0, sx); x1 = min(g, ex)
        if y0 < y1 and x0 < x1:
            out.reshape(h, w)[y0-sy:y1-sy, x0-sx:x1-sx] = src[y0:y1, x0:x1]
        return {'data': out, 'width': w, 'height': h}

    def f87(self, img, sx, sy, ex, ey):
        b = img['width']; v = img['height']
        w = max(1, ex - sx); h = max(1, ey - sy)
        src = np.asarray(img['data'], dtype=np.uint8).reshape(v, b, 4)
        out = np.full((h, w, 4), 255, dtype=np.uint8)
        y0 = max(0, sy); y1 = min(v, ey)
        x0 = max(0, sx); x1 = min(b, ex)
        if y0 < y1 and x0 < x1:
            out[y0-sy:y1-sy, x0-sx:x1-sx] = src[y0:y1, x0:x1]
        return {'data': out.flatten(), 'width': w, 'height': h}

    def f1316(self, arr):
        a = np.asarray(arr, dtype=np.float64)
        return float(a.mean()) if a.size else 0.0

    def f1317(self, arr, m):
        a = np.asarray(arr, dtype=np.float64)
        return float(np.sqrt(((a - m)**2).mean())) if a.size else 0.0

    def f88(self, img, rgba):
        import cv2
        G = img['width']; W = img['height']
        j = np.asarray(img['data'], dtype=np.float64)
        dark = self.f1316(j) < 110
        v733 = rgba['data'] if rgba else None
        if dark: mask = (j > 115).astype(np.uint8)
        else: mask = (j < 95).astype(np.uint8)
        if v733 is not None:
            rgb = np.asarray(v733, dtype=np.int64).reshape(-1, 4)
            R = rgb[:,0]; Gc = rgb[:,1]; B = rgb[:,2]
            green = (Gc > 90) & (Gc > R + 25) & (Gc > B + 15)
            mask = np.where((mask == 0) & green, 1, mask).astype(np.uint8)
        m2 = mask.reshape(W, G)
        k = np.ones((3,3), np.uint8)
        e = cv2.erode(m2, k)
        d1 = cv2.dilate(e, k)
        d2 = cv2.dilate(d1, k)
        final = cv2.erode(d2, k)
        return {
            'mask': final.flatten().astype(np.uint8),
            'width': G,
            'height': W,
            'darkBg': dark
        }

    def f89(self, mask, w, h):
        import cv2
        m2 = mask.reshape(h, w).astype(np.uint8) * 255
        k = np.ones((3,3), np.uint8)
        op = cv2.morphologyEx(m2, cv2.MORPH_OPEN, k)
        cl = cv2.morphologyEx(op, cv2.MORPH_CLOSE, k)
        return (cl > 0).astype(np.uint8).flatten()

    def f90(self, mask, w, h):
        import cv2
        m2 = mask.reshape(h, w).astype(np.uint8) * 255
        k = np.ones((3,3), np.uint8)
        dil = cv2.dilate(m2, k)
        return self.f89((dil > 0).astype(np.uint8).flatten(), w, h)

    def f91(self, mask, w, h, use_circ):
        import cv2
        m2 = mask.reshape(h, w).astype(np.uint8)
        num, labels, stats, centroids = cv2.connectedComponentsWithStats(m2, connectivity=4)
        best_label = 0; best_score = -1e30
        cw, ch = w/2, h/2
        for i in range(1, num):
            area = int(stats[i, cv2.CC_STAT_AREA])
            if use_circ:
                cx, cy = centroids[i]
                score = area - math.hypot(cx - cw, cy - ch) * 2.5
            else:
                score = area
            if score > best_score: best_score = score; best_label = i
        out = np.zeros(w*h, dtype=np.uint8)
        if best_label > 0:
            out[(labels == best_label).flatten()] = 1
            area = int(stats[best_label, cv2.CC_STAT_AREA])
        else: area = 0
        return {
            'mask': out,
            'width': w,
            'height': h,
            'area': area
        }

    def f92(self, img, w, h):
        m = self.f1316(img); s = self.f1317(img, m) or 1
        lo = min(m - 0.7*s, 100); hi = max(m + 0.55*s, 190)
        arr = np.asarray(img)
        mask = ((arr < lo) | (arr > hi)).astype(np.uint8)
        return self.f91(self.f90(mask, w, h), w, h, True)

    def f93(self, img, w, h):
        t = np.asarray(img, dtype=np.float64).reshape(h, w)
        gx = np.zeros((h, w)); gy = np.zeros((h, w))
        gx[1:-1,1:-1] = (-3*t[:-2,:-2] + 3*t[:-2,2:] - 10*t[1:-1,:-2] + 10*t[1:-1,2:]
                         - 3*t[2:,:-2] + 3*t[2:,2:])
        gy[1:-1,1:-1] = (-3*t[:-2,:-2] - 10*t[:-2,1:-1] - 3*t[:-2,2:]
                         + 3*t[2:,:-2] + 10*t[2:,1:-1] + 3*t[2:,2:])
        mag = np.sqrt(gx*gx + gy*gy)
        inner = mag[1:-1,1:-1]
        thr = max(float(inner.sum())/max(inner.size, 1) + 5, 22)
        mask = (mag >= thr).astype(np.uint8).flatten()
        return self.f91(self.f90(mask, w, h), w, h, True)

    def f94(self, img, dark_mode, rgba):
        T = img['data']; q = img['width']; S = img['height']
        total = q*S
        min_area = max(70, int(total * 0.025))
        best = {'mask': np.zeros(total, dtype=np.uint8), 'width': q, 'height': S, 'area': 0}
        if rgba and rgba.get('data') is not None:
            v = np.asarray(rgba['data'], dtype=np.int64).reshape(-1, 4)
            R = v[:,0]; G = v[:,1]; B = v[:,2]
            mx = np.maximum(np.maximum(R,G),B); mn = np.minimum(np.minimum(R,G),B)
            sat = np.where(mx == 0, 0, ((mx - mn)/np.maximum(mx,1))*255)
            c1 = ((mx-mn) >= 6) & (mx >= 35) & (mx <= 252)
            c2 = (mx < 70) & (sat < 50)
            mask = (c1 | c2).astype(np.uint8)
            best = self.f91(self.f89(mask, q, S), q, S, False)
        else:
            m = self.f1316(T); s = self.f1317(T, m) or 1
            thr = max(m + 0.35*s, 100) if dark_mode else min(m - 0.5*s, 110)
            arr = np.asarray(T)
            mask = ((arr > thr) if dark_mode else (arr < thr)).astype(np.uint8)
            best = self.f91(mask, q, S, False)
        if best['area'] >= min_area: return best
        if 60 <= best['area'] <= total*0.45: return best
        a1 = self.f92(T, q, S); a2 = self.f93(T, q, S)
        lim = int(total * 0.55)
        cur = best
        if a1['area'] > cur['area'] and a1['area'] <= lim: cur = a1
        if a2['area'] > cur['area'] and a2['area'] <= lim: cur = a2
        if cur['area'] < 40:
            if a1['area'] > cur['area']: cur = a1
            if a2['area'] > cur['area']: cur = a2
        return cur

    def f95(self, p3553, size, target_area):
        b = p3553['mask']; v = p3553['width']; C = p3553['height']
        m2 = np.asarray(b, dtype=np.uint8).reshape(C, v)
        ys, xs = np.where(m2 > 0)
        cnt = len(xs)
        out = np.zeros(size*size, dtype=np.uint8)
        if cnt == 0: return out
        scale = math.sqrt(target_area / cnt) if (target_area and cnt) else 1
        cx = float(xs.sum()) / cnt; cy = float(ys.sum()) / cnt; half = size/2
        dx = np.floor((xs - cx)*scale + half + 0.5).astype(np.int64)
        dy = np.floor((ys - cy)*scale + half + 0.5).astype(np.int64)
        valid = (dx >= 0) & (dx < size) & (dy >= 0) & (dy < size)
        out[dy[valid]*size + dx[valid]] = 1
        return out

    def _get_transform(self, size, deg):
        key = (size, deg)
        cached = self._TRANSFORM_CACHE.get(key)
        if cached is not None:
            return cached
        rad = deg * math.pi / 180
        c = math.cos(rad); s = math.sin(rad); half = size / 2
        yy, xx = np.meshgrid(np.arange(size), np.arange(size), indexing='ij')
        dx = xx - half; dy = yy - half
        sx = np.floor(dx * c + dy * s + half + 0.5).astype(np.int64)
        sy = np.floor(-dx * s + dy * c + half + 0.5).astype(np.int64)
        valid = (sx >= 0) & (sx < size) & (sy >= 0) & (sy < size)
        # Peta indeks penuh: piksel di luar area rotasi diarahkan ke sentinel nol.
        idx_map = np.full(size * size, size * size, dtype=np.int32)
        idx_map[np.flatnonzero(valid)] = (sy[valid] * size + sx[valid]).astype(np.int32)
        self._TRANSFORM_CACHE[key] = idx_map
        return idx_map

    def f96(self, src, size, deg):
        idx_map = self._get_transform(size, deg)
        n = size * size
        src_flat = np.asarray(src, dtype=np.uint8).reshape(size, size).reshape(-1)
        # Satu operasi fancy-index ke array dengan sentinel 0, lebih cepat
        # daripada zeros() + scatter assignment.
        src_ext = np.empty(n + 1, dtype=np.uint8)
        src_ext[:n] = src_flat
        src_ext[n] = 0
        return src_ext[idx_map]

    def f97(self, a, b):
        a = np.asarray(a, dtype=np.uint8) > 0
        b = np.asarray(b, dtype=np.uint8) > 0
        inter = int(np.count_nonzero(a & b))
        # |A u B| = |A| + |B| - |A n B|; hemat satu array sementara.
        union = int(np.count_nonzero(a)) + int(np.count_nonzero(b)) - inter
        return inter / union if union else 0

    def f98(self, p3632, size, step=5):
        n = len(p3632)
        deltas = [0]; prev = 0
        angles = range(-70, 71, step)
        for i in range(1, n):
            cur = p3632[i]
            cur_bin = cur > 0
            cur_cnt = int(np.count_nonzero(cur_bin))
            scores = []
            for deg in angles:
                rot = self.f96(p3632[i - 1], size, deg) > 0
                inter = int(np.count_nonzero(rot & cur_bin))
                union = int(np.count_nonzero(rot)) + cur_cnt - inter
                scores.append((deg, inter / union if union else 0))
            scores.sort(key=lambda x: -x[1])
            top = scores[0][1]
            thr = 0.15 if cur_cnt < 200 else 0.2
            if top < thr:
                deltas.append(0)
                continue
            cand = [x for x in scores if x[1] >= top - 0.06]
            best_d = cand[0][0]
            bd = abs(best_d - prev)
            for deg, _score in cand:
                d = abs(deg - prev)
                if d < bd:
                    bd = d
                    best_d = deg
            deltas.append(best_d)
            prev = best_d
        un = [0]
        for i in range(1, len(deltas)):
            un.append(un[i - 1] + deltas[i])
        path = sum(abs(un[i] - un[i - 1]) for i in range(1, len(un)))
        net = un[-1] - un[0]
        straight = 0 if path == 0 else abs(net) / path
        nz = [d for d in deltas if d != 0]
        sign = 0
        if nz:
            pos = sum(1 for d in nz if d > 0)
            sign = max(pos, len(nz) - pos) / len(nz)
        return {'type': 'swing' if (path < 25 or straight < 0.55) else ('clockwise' if net > 0 else 'counter-clockwise'),
                'unwrapped': un, 'deltas': deltas, 'pathLength': path,
                'straightness': straight, 'signConsistency': sign,
                'nonzeroCount': len(nz), 'net': net}

    def f99(self, p):
        v = [c for c in p if c and math.isfinite(c.get('cx', float('nan'))) and math.isfinite(c.get('cy', float('nan')))]
        if len(v) < 5:
            return {'type': None, 'dx': 0, 'dy': 0, 'relY': 0, 'relX': 0, 'changes': 0}
        xs = [c['cx'] for c in v]; ys = [c['cy'] for c in v]
        dx = max(xs) - min(xs); dy = max(ys) - min(ys)
        changes = 0
        for i in range(2, len(ys)):
            d1 = ys[i-1] - ys[i-2]; d2 = ys[i] - ys[i-1]
            if d1*d2 < 0 and abs(d1) > 0.8 and abs(d2) > 0.8: changes += 1
        if dy >= 12 and dy > dx*1.1 and (changes >= 1 or dy >= 15):
            return {'type': 'up-down', 'dx': dx, 'dy': dy, 'relY': dy/20, 'relX': dx/20, 'changes': changes}
        return {'type': None, 'dx': dx, 'dy': dy, 'relY': dy/20, 'relX': dx/20, 'changes': changes}

    def f100(self, p, areas):
        v = []
        for i in range(len(p)):
            c = p[i]; a = areas[i] if i < len(areas) else 0
            if c and math.isfinite(c.get('cx', float('nan'))) and math.isfinite(c.get('cy', float('nan'))) and a > 5:
                v.append({'cx': c['cx'], 'cy': c['cy'], 'a': a})
        if len(v) < 5: return self.f99(p)
        med = sorted(x['a'] for x in v)[len(v)//2] or 1
        filt = [x for x in v if med*0.28 <= x['a'] <= med*3.5]
        return self.f99(filt if len(filt) >= 5 else p)

    def f101(self, frames, step=5):
        n = len(frames)
        if n < 3:
            return {'type': 'swing', 'pathLength': 0, 'straightness': 0, 'signConsistency': 0,
                    'nonzeroCount': 0, 'net': 0, 'deltas': []}
        masks = []
        for fr in frames:
            j = fr['width']; G = fr['height']
            t = np.asarray(fr['data'], dtype=np.float64).reshape(G, j)
            gx = np.zeros((G, j)); gy = np.zeros((G, j))
            gx[1:-1,1:-1] = (-3*t[:-2,:-2] + 3*t[:-2,2:] - 10*t[1:-1,:-2] + 10*t[1:-1,2:]
                             - 3*t[2:,:-2] + 3*t[2:,2:])
            gy[1:-1,1:-1] = (-3*t[:-2,:-2] - 10*t[:-2,1:-1] - 3*t[:-2,2:]
                             + 3*t[2:,:-2] + 10*t[2:,1:-1] + 3*t[2:,2:])
            mag = np.sqrt(gx*gx + gy*gy)
            inner = mag[1:-1,1:-1]
            thr = max((float(inner.sum())/max(inner.size,1))*0.9, 20)
            m = np.zeros((96,96), dtype=np.uint8)
            ox = (96-j)//2; oy = (96-G)//2
            ys, xs = np.where(mag >= thr)
            ys = ys + oy; xs = xs + ox
            valid = (xs >= 0) & (xs < 96) & (ys >= 0) & (ys < 96)
            m[ys[valid], xs[valid]] = 1
            masks.append(m.flatten())
        return self.f98(masks, 96, step)

    def f102(self, areas):
        v = sorted([a for a in areas if a > 5])
        if len(v) < 4: return {'zooms': False, 'relSwing': 0}
        lo = v[int(len(v)*0.1)]; hi = v[min(len(v)-1, int(len(v)*0.9))]
        med = v[len(v)//2] or 1
        rel = (hi - lo)/med
        return {'zooms': rel >= 0.85, 'relSwing': rel}

    def f103(self, frames, roi):
        sub = [self.f86(fr, roi['left'], roi['top'], roi['right'], roi['bottom']) for fr in frames]
        n = len(sub)
        if n < 3:
            return {'type': 'swing', 'pathLength': 0, 'straightness': 0,
                    'zoom': {'relSwing': 0}, 'translation': {'dy':0,'dx':0,'changes':0}, 'meanArea': 0}
        areas=[]; cents=[]; angs=[]
        for fr in sub:
            o = fr['data']; w = fr['width']; h = fr['height']
            m = self.f1316(o); s = self.f1317(o, m) or 1
            thr = min(m - 0.25*s, 200)
            mask = (np.asarray(o) < thr).astype(np.uint8)
            comp = self.f91(self.f90(mask, w, h), w, h, True)
            areas.append(comp['area'])
            if comp['area'] < 8: cents.append(None); angs.append(None); continue
            m2 = comp['mask'].reshape(h, w)
            ys, xs = np.where(m2 > 0)
            nn = len(xs)
            cx = float(xs.sum())/nn; cy = float(ys.sum())/nn
            cents.append({'cx': roi['left']+cx, 'cy': roi['top']+cy})
            sxx = float((xs*xs).sum())/nn; syy = float((ys*ys).sum())/nn
            sxy = float((xs*ys).sum())/nn
            mu20 = sxx - cx*cx; mu02 = syy - cy*cy; mu11 = sxy - cx*cy
            tr = mu20+mu02; det = mu20*mu02 - mu11*mu11
            disc = math.sqrt(max(0, tr*tr/4 - det))
            m11b = mu11; lam = (tr/2 + disc) - mu20
            if abs(m11b) + abs(lam) < 1e-9: m11b = 1; lam = 0
            a = math.atan2(lam, m11b)*180/math.pi
            while a >= 90: a -= 180
            while a < -90: a += 180
            angs.append(a)
        z = self.f102(areas); trans = self.f100(cents, areas)
        dy = trans.get('dy',0) or 0; dx = trans.get('dx',0) or 0; changes = trans.get('changes',0) or 0
        valid = [a for a in angs if a is not None and math.isfinite(a)]
        path = 0; net = 0; sign = 0; nonzero = []
        if len(valid) >= 4:
            un = [valid[0]]
            for i in range(1, len(valid)):
                d = valid[i] - un[i-1]
                while d > 90: d -= 180
                while d < -90: d += 180
                if abs(d) > 55:
                    alt = valid[i] + 180
                    while alt >= 90: alt -= 180
                    while alt < -90: alt += 180
                    d2 = alt - un[i-1]
                    while d2 > 90: d2 -= 180
                    while d2 < -90: d2 += 180
                    if abs(d2) < abs(d): d = d2
                un.append(un[i-1] + d)
                if abs(d) >= 4: nonzero.append(d)
            path = sum(abs(un[i] - un[i-1]) for i in range(1, len(un)))
            net = un[-1] - un[0]
            if nonzero:
                pos = sum(1 for x in nonzero if x > 0)
                sign = max(pos, len(nonzero)-pos) / len(nonzero)
        # Hasil f98(mask64) di sini tidak pernah dipakai; komputasinya dihapus.
        va = [a for a in areas if a > 5]
        ma = sum(va)/max(1, len(va)) if va else 0
        if dy >= 10 and (changes >= 1 or dy >= 12):
            return {'type': 'up-down', 'reason': 'Q-dy', 'pathLength': path, 'straightness': sign, 'zoom': z, 'translation': trans, 'meanArea': ma}
        if z['relSwing'] >= 0.55:
            return {'type': 'zoom', 'reason': 'Q-relArea', 'pathLength': path, 'straightness': sign, 'zoom': z, 'translation': trans, 'meanArea': ma}
        if path >= 120 and sign >= 0.65:
            if abs(net) >= 8: typ = 'counter-clockwise' if net < 0 else 'clockwise'
            else:
                pos = sum(1 for x in nonzero if x > 0)
                typ = 'clockwise' if pos >= len(nonzero) - pos else 'counter-clockwise'
            return {'type': typ, 'reason': 'Q-pca', 'pathLength': path, 'straightness': sign, 'zoom': z, 'translation': trans, 'meanArea': ma}
        return {'type': 'swing', 'reason': 'Q-swing', 'pathLength': path, 'straightness': sign, 'zoom': z, 'translation': trans, 'meanArea': ma}

    def f104(self, frames, size=80):
        if not frames or len(frames) < 4:
            return {'type':'swing','pathLength':0,'straightness':0,'signConsistency':0,
                    'net':0,'deltas':[],'meanChromaArea':0}
        S = size or 80
        masks = []; total_area = 0; total_frames = 0
        for fr in frames:
            if not fr or fr.get('data') is None: masks.append(None); continue
            r = fr['width']; e = fr['height']
            arr = np.asarray(fr['data'], dtype=np.int64).reshape(-1, 4)
            R = arr[:,0]; G = arr[:,1]; B = arr[:,2]
            mx = np.maximum(np.maximum(R,G),B); mn = np.minimum(np.minimum(R,G),B)
            sat = (mx - mn) > 22
            dark = (mx < 55) | (mx > 250)
            sel = (~sat) & (~dark) & ((mx - ((R+G+B-mx)/2)) >= 12)
            cnt = int(sel.sum())
            if cnt < 20: masks.append(None); continue
            total_area += cnt; total_frames += 1
            ys, xs = np.where(sel.reshape(e, r))
            cx = float(xs.sum())/cnt; cy = float(ys.sum())/cnt
            px = np.floor((xs - cx) + S/2 + 0.5).astype(np.int64)
            py = np.floor((ys - cy) + S/2 + 0.5).astype(np.int64)
            out = np.zeros(S*S, dtype=np.uint8)
            valid = (px >= 0) & (px < S) & (py >= 0) & (py < S)
            out[py[valid]*S + px[valid]] = 1
            masks.append(out)
        if total_frames < 4:
            return {'type':'swing','pathLength':0,'straightness':0,'signConsistency':0,
                    'net':0,'deltas':[],'meanChromaArea':0}
        angles = [0,-5,5,-10,10,-15,15,-20,20,-25,25,-30,30]
        deltas = []; prev = None
        for m in masks:
            if m is None: deltas.append(0); continue
            if prev is None: prev = m; deltas.append(0); continue
            best_d=0; best_iou=-1
            for deg in angles:
                iou = self.f97(self.f96(prev, S, deg), m)
                if iou > best_iou: best_iou=iou; best_d=deg
            deltas.append(best_d); prev = m
        path = sum(abs(d) for d in deltas); net = sum(deltas)
        pos = sum(1 for d in deltas if d > 2); neg = sum(1 for d in deltas if d < -2)
        nz = pos + neg
        sign = max(pos,neg)/nz if nz else 0
        straight = abs(net)/path if path > 1 else 0
        return {'type': 'swing' if abs(net) < 10 else ('clockwise' if net >= 0 else 'counter-clockwise'),
                'pathLength': path, 'straightness': straight, 'signConsistency': sign,
                'net': net, 'deltas': deltas, 'nonzeroCount': nz,
                'meanChromaArea': total_area / total_frames if total_frames else 0}

    def f105(self, frames):
        if not frames or len(frames) < 4:
            return {'type':'swing','pathLength':0,'straightness':0,'signConsistency':0,
                    'net':0,'deltas':[],'meanChromaArea':0}
        angs=[]; counts=[]
        for fr in frames:
            if not fr or fr.get('data') is None: angs.append(None); counts.append(0); continue
            S=fr['width']; O=fr['height']
            arr = np.asarray(fr['data'], dtype=np.int64).reshape(-1, 4)
            R = arr[:,0]; G = arr[:,1]; B = arr[:,2]
            mx = np.maximum(np.maximum(R,G),B); mn = np.minimum(np.minimum(R,G),B)
            sel = ((mx - mn) >= 25) & (mx >= 60) & (mx <= 250) & ((mx - ((R+G+B-mx)/2)) >= 15)
            cnt = int(sel.sum())
            if cnt < 25:
                sel = ((mx - mn) >= 18) & (mx >= 50) & (mx <= 250)
                cnt = int(sel.sum())
            counts.append(cnt)
            if cnt < 25: angs.append(None); continue
            ys, xs = np.where(sel.reshape(O, S))
            cx = float(xs.sum())/cnt; cy = float(ys.sum())/cnt
            sxx = float((xs*xs).sum())/cnt; syy = float((ys*ys).sum())/cnt; sxy = float((xs*ys).sum())/cnt
            mu20 = sxx - cx*cx; mu02 = syy - cy*cy; mu11 = sxy - cx*cy
            angs.append(0.5*math.atan2(2*mu11, mu20-mu02)*180/math.pi)
        idxs = [i for i,a in enumerate(angs) if a is not None]
        if len(idxs) < 4:
            return {'type':'swing','pathLength':0,'straightness':0,'signConsistency':0,
                    'net':0,'deltas':[],'meanChromaArea':0}
        un = [angs[idxs[0]]]
        for i in range(1, len(idxs)):
            d = angs[idxs[i]] - angs[idxs[i-1]]
            while d > 90: d -= 180
            while d < -90: d += 180
            un.append(un[-1] + d)
        deltas = [un[i]-un[i-1] for i in range(1, len(un))]
        net = un[-1] - un[0]; path = sum(abs(d) for d in deltas)
        pos = sum(1 for d in deltas if d > 1.5); neg = sum(1 for d in deltas if d < -1.5)
        nz = pos+neg
        sign = max(pos,neg)/nz if nz else 0
        straight = abs(net)/path if path > 1 else 0
        return {'type': 'swing' if abs(net) < 5 else ('clockwise' if net >= 0 else 'counter-clockwise'),
                'pathLength': path, 'straightness': straight, 'signConsistency': sign,
                'net': net, 'deltas': deltas, 'nonzeroCount': nz, 'unwrapped': un,
                'meanChromaArea': sum(counts)/len(counts) if counts else 0}

    def _get(self, d, k, default=0):
        if isinstance(d, dict):
            v = d.get(k, default)
            return default if v is None else v
        return default

    def f106(self, frames, roi, darkMode, size=120, rgbaFrames=None, debug=False):
        v895 = [self.f86(fr, roi['left'], roi['top'], roi['right'], roi['bottom']) for fr in frames]
        v896 = [self.f87(fr, roi['left'], roi['top'], roi['right'], roi['bottom']) for fr in (rgbaFrames or [])]
        if not v896: v896 = [None]*len(v895)
        elif len(v896) < len(v895): v896 += [None]*(len(v895)-len(v896))
        v897 = [self.f94(v895[i], darkMode, v896[i]) for i in range(len(v895))]
        v898 = [c['area'] for c in v897]
        first = next((a for a in v898 if a > 10), None)
        v899 = first if first is not None else (v898[0] if v898 else 1) or 1
        v900 = [self.f95(c, size, v899) for c in v897]
        v901 = []
        for c in v897:
            if not c['area'] or c['area'] < 15: v901.append(None); continue
            w=c['width']; h=c['height']
            m2 = np.asarray(c['mask'], dtype=np.uint8).reshape(h, w)
            ys, xs = np.where(m2 > 0); cnt = len(xs)
            if cnt < 15: v901.append(None); continue
            v901.append({'cx': roi['left']+float(xs.sum())/cnt, 'cy': roi['top']+float(ys.sum())/cnt})
        vF9810 = self.f98(v900, size)
        vF10110 = self.f101(v895)
        vF10510 = self.f105(v896)
        vF10410 = self.f104(v896, size)
        vF10210 = self.f102(v898)
        vF10010 = self.f100(v901, v898)
        v902 = vF10210.get('relSwing') or 0
        def f107(r): return self._get(r,'pathLength') * self._get(r,'straightness') * self._get(r,'signConsistency')
        v903 = [a for a in v898 if a > 5]
        v904 = sum(v903)/len(v903) if v903 else 0
        vVF9810 = dict(vF9810)
        if (v902 < 1.2 and self._get(vF10110,'straightness') >= 0.55 and self._get(vF10110,'pathLength') >= 40
                and f107(vF10110) > f107(vVF9810)):
            vVF9810 = vF10110
        if (self._get(vF10110,'straightness') >= 0.9 and self._get(vF10110,'pathLength') >= 30
                and self._get(vF10110,'signConsistency') >= 0.7
                and (v902 < 0.7 or (v904 >= 900 and v902 < 1.55))
                and self._get(vF9810,'pathLength') < 150):
            vVF9810 = vF10110
        if (v904 >= 1000 and self._get(vF10110,'pathLength') >= 25
                and self._get(vF10110,'signConsistency') >= 0.7 and self._get(vF9810,'straightness') < 0.9):
            vVF9810 = vF10110
        if (v904 >= 700 and v904 < 900 and self._get(vF9810,'pathLength') >= 300
                and 0.55 <= self._get(vF9810,'straightness') < 0.75
                and self._get(vF10110,'pathLength') >= 40 and self._get(vF10110,'signConsistency') >= 0.7
                and vF10110.get('type') and vF10110['type'] != 'swing'
                and vF10110['type'] != vF9810.get('type')):
            vVF9810 = dict(vF10110)
            vVF9810['pathLength'] = max(self._get(vF9810,'pathLength'), self._get(vF10110,'pathLength'))
            vVF9810['straightness'] = max(self._get(vF9810,'straightness'), 0.7)
            vVF9810['reason'] = 'edge-large-mid'
        if (self._get(vF10510,'meanChromaArea') >= 150 and self._get(vF10510,'pathLength') >= 8
                and abs(self._get(vF10510,'net')) >= 10 and v904 >= 600
                and v904 > self._get(vF10510,'meanChromaArea')*2.5
                and self._get(vF10510,'meanChromaArea') >= v904*0.15):
            vVF9810 = {'type': vF10510.get('type'),
                       'pathLength': max(self._get(vF9810,'pathLength'), 50),
                       'straightness': max(self._get(vF9810,'straightness'), 0.85),
                       'signConsistency': max(self._get(vF10510,'signConsistency'), 0.85),
                       'net': vF10510.get('net'), 'deltas': vF10510.get('deltas'),
                       'nonzeroCount': vF10510.get('nonzeroCount', 5),
                       'unwrapped': vF10510.get('unwrapped'), 'reason': 'chroma-pca'}
        if (self._get(vF10410,'meanChromaArea') >= 300 and self._get(vF10410,'pathLength') >= 60
                and abs(self._get(vF10410,'net')) >= 60 and self._get(vF10410,'signConsistency') >= 0.6
                and 300 <= v904 < 600 and self._get(vF9810,'pathLength') <= 120):
            vVF9810 = {'type': vF10410.get('type'),
                       'pathLength': max(self._get(vF10410,'pathLength'), self._get(vF9810,'pathLength'), 50),
                       'straightness': max(self._get(vF10410,'straightness'), 0.7),
                       'signConsistency': max(self._get(vF10410,'signConsistency'), 0.7),
                       'net': vF10410.get('net'), 'deltas': vF10410.get('deltas'),
                       'nonzeroCount': vF10410.get('nonzeroCount', 5), 'reason': 'chroma-iou'}
        v905 = self._get(vF10410,'meanChromaArea'); v906 = self._get(vF10410,'pathLength')
        v907 = self._get(vF10410,'net'); v908 = self._get(vF10410,'straightness'); v909 = self._get(vF10410,'signConsistency')
        if (200 <= v905 < 450 and v906 >= 80 and abs(v907) >= 40
                and v904 >= v905*2.5 and v904 >= 700
                and (min(self._get(vF9810,'pathLength',999), self._get(vVF9810,'pathLength',999)) < 100
                     or self._get(vF9810,'straightness') < 0.4 or self._get(vVF9810,'straightness') < 0.4)):
            v910 = v908 < 0.4; v911 = -v907 if v910 else v907
            vVF9810 = {'type': 'clockwise' if v911 >= 0 else 'counter-clockwise',
                       'pathLength': max(v906, 200), 'straightness': max(v908, 0.7),
                       'signConsistency': max(v909, 0.8), 'net': v911,
                       'deltas': vF10410.get('deltas'),
                       'nonzeroCount': vF10410.get('nonzeroCount', 5),
                       'reason': 'chroma-thin-inv' if v910 else 'chroma-thin'}
        if (self._get(vF10110,'pathLength') >= self._get(vF9810,'pathLength')
                and self._get(vF10110,'straightness') >= 0.95
                and self._get(vF10110,'signConsistency') >= 0.9
                and self._get(vF10110,'pathLength') >= 35
                and 200 <= v904 < 500 and v902 < 0.5): vVF9810 = vF10110
        if (self._get(vF9810,'pathLength') < 40 and self._get(vF10110,'pathLength') >= 35
                and self._get(vF10110,'straightness') >= 0.9
                and self._get(vF10110,'signConsistency') >= 0.8): vVF9810 = vF10110
        if (self._get(vF9810,'pathLength') < 20 and self._get(vF10110,'pathLength') >= 35
                and self._get(vF10110,'signConsistency') >= 0.6
                and 450 <= v904 < 600 and self._get(vF10110,'straightness') >= 0.2): vVF9810 = vF10110
        if (self._get(vF9810,'straightness') < 0.45 and self._get(vF10110,'straightness') >= 0.65
                and self._get(vF10110,'pathLength') >= 50 and self._get(vF10110,'signConsistency') >= 0.6
                and v904 >= 200 and v902 < 0.6): vVF9810 = vF10110
        if (v904 >= 600 and self._get(vF9810,'pathLength') < 80 and self._get(vF9810,'straightness') < 0.55
                and self._get(vF10110,'pathLength') >= 50 and self._get(vF10110,'straightness') >= 0.9): vVF9810 = vF10110

        v912 = self._get(vVF9810,'pathLength'); v913 = self._get(vVF9810,'straightness')
        v914 = self._get(vF10010,'dy'); v915 = self._get(vF10010,'dx')
        v916 = self._get(vVF9810,'signConsistency'); v917 = self._get(vVF9810,'nonzeroCount')
        v918 = self._get(vF10010,'changes')
        v919 = False; v920 = False
        if (v912 < 20 and v915 > 30 and v914 > 10 and v901 and len(v901) >= 6):
            v921 = [p for p in v901 if p and math.isfinite(p['cx']) and math.isfinite(p['cy'])]
            if len(v921) >= 6:
                mx = sum(p['cx'] for p in v921)/len(v921)
                my = sum(p['cy'] for p in v921)/len(v921)
                total = 0; prev = math.atan2(v921[0]['cy']-my, v921[0]['cx']-mx)
                for i in range(1, len(v921)):
                    cur = math.atan2(v921[i]['cy']-my, v921[i]['cx']-mx)
                    d = cur - prev
                    while d > math.pi: d -= 2*math.pi
                    while d < -math.pi: d += 2*math.pi
                    total += d; prev = cur
                if abs(total) > 0.8:
                    v919 = True; v920 = total > 0
                    v912 = max(v912, 80); v913 = max(v913, 0.85); v916 = max(v916, 0.9)
                    if not vVF9810.get('type') or vVF9810.get('type') == 'swing':
                        vVF9810 = dict(vVF9810)
                        vVF9810['type'] = 'clockwise' if v920 else 'counter-clockwise'
                        vVF9810['pathLength'] = v912
                        vVF9810['straightness'] = v913
                        vVF9810['signConsistency'] = v916
                        vVF9810['net'] = 90 if v920 else -90
        v927 = [a for a in v898 if a > 5]
        v928 = sum(v927)/len(v927) if v927 else 0
        v929 = v928 >= 80
        v930 = (v913 >= 0.88 and v912 >= 160 and v916 >= 0.8 and v917 >= 5
                and ((v914 < 16 and v902 < 0.55) or (v913 >= 0.98 and v914 < 18 and v902 < 0.8 and v912 >= 250)))
        v931 = ((v913 >= 0.95 and 160 <= v912 <= 280 and v916 >= 0.95 and 120 <= v928 < 350 and v902 < 1 and v914 < 18)
                or (v913 >= 0.98 and 170 <= v912 <= 500 and v916 >= 0.95 and 140 <= v928 < 350
                    and v902 < 1.5 and 14 <= v914 < 22
                    and (not (v915 >= v914*0.95) or not (v914 >= 20))))
        v932 = v913 >= 0.9 and 150 <= v912 <= 220 and v914 >= 15 and v902 >= 1 and v928 < 250
        v933 = ((v913 >= 0.85 and 30 <= v912 <= 160 and v916 >= 0.8 and v902 < 1.5 and v928 >= 900
                 and (not (v902 >= 1.1) or not (v915 > v914*1.5) or not (v912 <= 100)))
                or (v913 >= 0.5 and 30 <= v912 <= 60 and v916 >= 0.8 and v928 >= 1000 and v902 < 1.4 and v914 < 12))
        v934 = sum(1 for d in (vVF9810.get('deltas') or []) if abs(d) >= 15)
        v935 = sum(abs(d) for d in (vVF9810.get('deltas') or []))
        v936 = vVF9810.get('unwrapped') or []
        v937 = abs(v936[-1]-v936[0]) if len(v936) > 1 else 0
        v938 = [d for d in (vVF9810.get('deltas') or []) if abs(d) >= 10]
        v939 = sum(1 for d in v938 if d > 0); v940 = sum(1 for d in v938 if d < 0)
        v941 = max(v939,v940)/len(v938) if v938 else 0
        v942 = any(d >= 10 for d in (vVF9810.get('deltas') or []))
        v943 = any(d <= -10 for d in (vVF9810.get('deltas') or []))
        v944 = (not v942) or (not v943)
        v945 = vVF9810.get('deltas') or []
        v946 = max(4, int(len(v945)*0.6))
        v947 = all(abs(d) < 10 for d in v945[:v946])
        v948 = any(abs(d) >= 15 for d in v945[v946:])
        v949 = (not v947) or (not v948)
        v950 = (v913 >= 0.95 and 30 <= v912 <= 150 and v916 >= 0.9 and 150 <= v928 < 400
                and ((v912 >= 55 and v902 < 0.7 and v914 < 14)
                     or (30 <= v912 < 55 and v928 >= 280 and v902 < 0.5 and v914 < 14)
                     or (40 <= v912 <= 55 and 200 <= v928 <= 260 and v944 and v949 and v941 >= 0.7
                         and (v934 >= 3 or v935 >= 40 or v937 >= 100) and v902 < 0.5 and v914 < 12)
                     or (v902 < 0.55 and v914 < 12 and v928 < 360 and v912 >= 55)))
        v951 = v913 >= 0.8 and v912 >= 200 and v916 >= 0.8 and v902 < 0.3 and v928 >= 150 and v914 < 12
        v952 = (v913 >= 0.48 and v912 >= 300 and v916 >= 0.65 and 150 <= v928 < 450
                and (not (v914 >= 16) or not (v915 < 2.5))
                and ((v914 < 14 and v902 < 0.7)
                     or (v913 >= 0.9 and v912 >= 300 and v902 < 0.4 and v914 < 22)
                     or (v912 >= 320 and v913 >= 0.6 and v916 >= 0.9 and v902 < 0.9 and v914 < 18 and v928 < 250)
                     or (v912 >= 330 and v913 >= 0.55 and v916 >= 0.65 and v902 < 1 and v914 < 20 and v928 < 350)
                     or (v912 >= 350 and v913 >= 0.6 and v902 < 1.35 and v914 < 22)
                     or (v912 >= 500 and v913 >= 0.75 and v916 >= 0.8 and v914 < 22)))
        v953 = (v913 >= 0.95 and 40 <= v912 <= 140 and v916 >= 0.9 and 600 <= v928 < 800 and v914 < 12
                and ((v912 <= 110 and (v902 < 0.4 or (v912 >= 80 and v902 < 0.5)))
                     or (v912 >= 120 and v928 >= 720 and v902 < 1.3)))
        v954 = ((v913 >= 0.5 and 200 <= v912 <= 400 and v916 >= 0.75 and v928 >= 700 and v914 < 14 and v902 < 1.5)
                or (v913 >= 0.95 and 150 <= v912 <= 200 and v916 >= 0.9 and 850 <= v928 < 1100 and v914 < 10 and v902 < 1.6)
                or (v913 >= 0.65 and 200 <= v912 <= 400 and v916 >= 0.75 and 700 <= v928 < 1300 and v902 < 1.5 and v914 < 15))
        v955 = ((v913 >= 0.25 and 200 <= v912 <= 280 and v916 >= 0.75 and v902 < 0.5 and v914 < 12 and 250 <= v928 < 400)
                or (v913 >= 0.2 and 250 <= v912 <= 320 and v916 >= 0.85 and v902 < 0.3 and v914 < 12 and 250 <= v928 < 300)
                or (v913 >= 0.5 and 180 <= v912 <= 230 and v916 >= 0.75 and v902 < 0.3 and v914 < 10 and 280 <= v928 < 350))
        v956 = ((v913 >= 0.65 and 180 <= v912 <= 280 and v916 >= 0.9 and 150 <= v928 < 250 and v902 < 1 and v914 < 18)
                or (v913 >= 0.65 and 250 <= v912 <= 300 and v916 >= 0.75 and 300 <= v928 < 400 and v902 < 0.2 and v914 < 12)
                or (v913 >= 0.6 and 250 <= v912 <= 290 and v916 >= 0.8 and 180 <= v928 < 260 and v902 < 0.4 and v914 < 14)
                or (v913 >= 0.6 and 240 <= v912 <= 280 and v916 >= 0.75 and 200 <= v928 < 280 and v902 < 0.3 and v914 < 12))
        v957 = (v913 >= 0.25 and 140 <= v912 <= 180 and v916 >= 0.45 and 150 <= v928 < 220
                and v902 >= 1.5 and v915 > 25 and v914 < 25)
        v958 = ((v913 >= 0.9 and 35 <= v912 <= 50 and v916 >= 0.8 and 400 <= v928 < 650
                 and (v902 < 0.7 or (600 <= v928 < 650 and v902 < 3)))
                or (v913 >= 0.9 and 50 <= v912 <= 130 and v916 >= 0.8 and 500 <= v928 < 650 and v902 < 0.7
                    and (not (v914 >= 16) or not (v914 >= v915*2)))
                or (v913 >= 0.92 and 50 <= v912 <= 80 and v916 >= 0.8 and 300 <= v928 < 400 and v902 < 0.4 and v914 < 10)
                or (v913 >= 0.2 and 35 <= v912 <= 50 and v916 >= 0.6 and 450 <= v928 < 600 and v902 < 3 and v914 < 12 and v915 > 20)
                or (v913 >= 0.15 and 60 <= v912 <= 100 and v916 >= 0.55 and v928 >= 1000 and v902 < 1.2 and v914 < 15 and v915 > 15))
        v959 = ((v912 >= 400 and v913 < 0.25 and v916 >= 0.7 and 150 <= v928 < 250 and v902 < 0.4 and v914 < 14)
                or (380 <= v912 <= 450 and 0.3 <= v913 < 0.45 and v916 >= 0.85 and 180 <= v928 < 280 and v902 < 0.4 and v914 < 12)
                or (330 <= v912 <= 380 and 0.25 <= v913 < 0.4 and v916 >= 0.75 and 150 <= v928 < 250 and v902 < 0.4 and v914 < 12)
                or (v912 >= 500 and 0.3 <= v913 < 0.4 and v916 >= 0.55 and 300 <= v928 < 360 and v902 < 0.85 and v914 < 18)
                or (v912 >= 550 and v913 < 0.15 and v916 >= 0.55 and 180 <= v928 < 280 and v902 < 1.5 and v914 < 20)
                or (280 <= v912 < 400 and 0.2 <= v913 < 0.3 and v916 >= 0.85 and 100 <= v928 < 160 and v902 < 0.7 and v914 < 25)
                or (v912 >= 440 and 0.1 <= v913 < 0.55 and v916 >= 0.6 and 200 <= v928 < 350 and v902 < 3.5 and v914 < 25))
        v960 = v919 and v912 >= 50 and v913 >= 0.8
        v961 = ((v928 >= 900 and 50 <= v912 <= 120 and 0.6 <= v913 < 0.9 and 1.1 <= v902 < 2.5 and v914 < 15)
                or (v928 >= 950 and 40 <= v912 <= 80 and 0.5 <= v913 < 0.9 and 1 <= v902 < 2 and v914 < 12)
                or (v928 >= 900 and 50 <= v912 <= 100 and v913 >= 0.9 and 1.1 <= v902 < 2 and v915 > v914*1.4 and v914 < 12)
                or (v928 >= 1100 and 100 <= v912 <= 160 and 0.8 <= v913 < 0.95 and v915 > v914*1.2 and v914 < 16 and v902 < 1))
        v962 = (30 <= v912 <= 70 and v913 >= 0.9 and v916 >= 0.9 and 240 <= v928 < 550
                and v902 < 0.4 and v914 < 10 and v915 < 8)
        v963 = (v930 or v933 or v950 or v951 or v952 or v953 or v954 or v955 or v956 or v957 or v958 or v959 or v931 or v960) \
               and not v932 and not v962 and not v961
        v964 = (30 <= v912 <= 50 and v913 >= 0.9 and 12 <= v914 < 17 and v915 >= 5
                and v915 >= v914*0.35 and v928 < 350 and v902 < 0.7)
        v965 = ((100 <= v912 <= 180 and v913 < 0.35 and v916 < 0.7 and v914 >= 8 and v915 >= 8
                 and abs(v914 - v915) < 6 and v902 < 0.4)
                or (180 <= v912 <= 220 and v913 < 0.15 and v916 < 0.75 and v914 >= 12 and v915 >= 12
                    and abs(v914 - v915) < 5 and v902 < 0.3))
        v966 = (v932 or v964 or v961 or v962 or v965
                or (v928 >= 750 and 250 <= v912 <= 320 and v913 < 0.55 and v902 >= 1.2 and v914 < 12)
                or (v912 >= 400 and 0.25 <= v913 < 0.4 and (not (v916 >= 0.85) or not (v928 < 250) or not (v902 < 0.4)))
                or (v912 >= 400 and v913 < 0.25 and (not (v916 >= 0.7) or not (v928 < 250) or not (v902 < 0.4)))
                or (v902 < 1 and ((350 <= v912 < 400 and v913 < 0.45)
                                  or (200 <= v912 < 350 and v913 < 0.5
                                      and (not (v914 >= 15) or not (v914 >= v915*0.85))
                                      and (not (v916 >= 0.85) or not (v928 < 300) or not (v902 < 0.3)))))
                or (100 <= v912 < 200 and v913 < 0.3 and v916 < 0.75 and v902 < 0.85 and v914 < 15)
                or (50 <= v912 < 100 and v913 < 0.15 and 0.6 <= v902 < 0.95 and v914 < 14)
                or (100 <= v912 < 160 and v913 < 0.25 and v915 > 15 and v902 < 0.3)
                or (140 <= v912 < 180 and v913 < 0.1 and 0.7 <= v902 < 1.2 and v914 < 12)
                or (140 <= v912 < 180 and v913 < 0.15 and v916 < 0.65 and v914 >= 15 and v902 < 1)
                or (140 <= v912 < 200 and v913 < 0.3 and v916 < 0.7 and 10 <= v914 < 16
                    and v915 < 8 and v902 < 0.4 and v928 < 250)
                or (200 <= v912 < 280 and 0.3 <= v913 < 0.7 and v916 < 0.75 and v902 < 0.4 and v914 < 12))
        v967 = (not v966 and not v951 and not v952 and not v956 and not v954 and not v959
                and not v931 and not v957 and not v964 and not v965
                and ((v914 >= 15 and v915 < 3.5 and v912 <= 100)
                     or (v914 >= 16 and v915 < 2.5 and v912 <= 400 and v902 < 0.7)
                     or (v914 >= 14 and v912 <= 50 and v913 >= 0.9 and v928 < 350 and v902 < 0.7 and v915 < 4)
                     or (v914 >= 18 and v902 >= 1.4 and v913 < 0.25 and v912 < 200)
                     or (v914 >= 5 and 500 <= v928 < 700 and v912 < 80 and v913 < 0.3 and v915 > 30)
                     or (v914 >= 16 and v914 >= v915*2 and v928 >= 450 and v912 <= 120)
                     or (not v950 and not v930 and not v933 and not v959
                         and ((v914 >= 13 and v918 >= 2 and v914 >= v915*0.55)
                              or (v914 >= 14 and v918 >= 1 and v914 >= v915*0.55)
                              or (v914 >= 14 and v914 >= v915*2)
                              or (v914 >= 11 and v914 >= v915*0.55 and v918 >= 1)
                              or (v914 >= 16 and v914 >= v915*0.6)))))
        v968 = v902 >= 0.7 and v929 and not v963
        v969 = v902 >= 1.5 and v929
        v970 = ((v902 >= 4 and v929)
                or (v902 >= 2 and v929 and (not (v912 >= 400) or not (v913 >= 0.7) or not (v916 >= 0.75))
                    and (not (v914 >= 15) or not (v913 < 0.4) or not (v902 < 4)))
                or (v902 >= 1.45 and v929 and v912 >= 300 and v913 < 0.15 and not (v914 >= 15)))
        vLSSwing2 = 'swing'; vLS4 = ''
        vLN0390 = vLN0391 = vLN0392 = 0
        if v963 and (v912 < 100 or v959) and len(v900) >= 6:
            vA107 = []
            for v971 in v900:
                if v971 is None: vA107.append(None); continue
                n = int(round(math.sqrt(len(v971))))
                m2 = v971.reshape(n, n)
                ys, xs = np.where(m2 > 0)
                cnt = len(xs)
                if cnt < 15: vA107.append(None); continue
                cx = float(xs.sum())/cnt; cy = float(ys.sum())/cnt
                mu20 = float((xs*xs).sum())/cnt - cx*cx
                mu02 = float((ys*ys).sum())/cnt - cy*cy
                mu11 = float((xs*ys).sum())/cnt - cx*cy
                tr = mu20+mu02; det = mu20*mu02 - mu11*mu11
                disc = math.sqrt(max(0, tr*tr/4 - det))
                lam1 = tr/2 + disc
                m11 = mu11; lam = lam1 - mu20
                if abs(m11)+abs(lam) < 1e-9: m11=1; lam=0
                a = math.atan2(lam, m11)*180/math.pi
                while a >= 90: a -= 180
                while a < -90: a += 180
                vA107.append(a)
            vA108 = [a for a in vA107 if a is not None and math.isfinite(a)]
            if len(vA108) >= 5:
                vA109 = [vA108[0]]; vA110 = []
                for i in range(1, len(vA108)):
                    d = vA108[i] - vA109[i-1]
                    while d > 90: d -= 180
                    while d < -90: d += 180
                    if abs(d) > 55:
                        alt = vA108[i] + 180
                        while alt >= 90: alt -= 180
                        while alt < -90: alt += 180
                        d2 = alt - vA109[i-1]
                        while d2 > 90: d2 -= 180
                        while d2 < -90: d2 += 180
                        if abs(d2) < abs(d): d = d2
                    vA109.append(vA109[i-1] + d)
                    if abs(d) >= 4: vA110.append(d)
                for i in range(1, len(vA109)): vLN0390 += abs(vA109[i] - vA109[i-1])
                vLN0391 = vA109[-1] - vA109[0]
                if vA110:
                    pos = sum(1 for d in vA110 if d > 0)
                    vLN0392 = max(pos, len(vA110)-pos) / len(vA110)
        if v902 >= 8 and v912 < 40 and v913 < 0.35:
            vLSSwing2='swing'; vLS4='extreme-flash-swing'
        elif v902 >= 3 and v912 < 200 and v913 < 0.5 and not (v913 >= 0.9 and v912 >= 200) and not (v912 < 40 and v902 >= 8):
            vLSSwing2='zoom'; vLS4='extreme-rel'
        elif v902 >= 3.5 and 300 <= v912 < 400 and v913 < 0.35 and v915 >= v914*0.85 and not v963:
            vLSSwing2='zoom'; vLS4='extreme-rel-long'
        elif v912 < 15 and v902 >= 1 and v929 and not v963 and v914 < 16 and v915 < v914*1.2:
            vLSSwing2='zoom'; vLS4='zero-path-rel'
        elif v902 >= 5 and v914 >= 18 and v929:
            vLSSwing2='up-down'; vLS4='extreme-rel-ud'
        elif v912 < 40 and v902 >= 8 and v913 < 0.35 and v929 and not v963:
            vLSSwing2='swing'; vLS4='extreme-flash-swing'
        elif v963:
            if vVF9810 and vVF9810.get('reason') in ('chroma-pca','chroma-iou','chroma-thin','chroma-thin-inv'):
                vLSSwing2 = vVF9810['type']; vLS4 = vVF9810['reason']
            elif v928 >= 900 and vF10110 and self._get(vF10110,'pathLength') >= 15:
                v989 = vF10110.get('net', 0)
                if not v989 and vF10110.get('unwrapped') and len(vF10110['unwrapped'])>1:
                    v989 = vF10110['unwrapped'][-1] - vF10110['unwrapped'][0]
                if not v989 and isinstance(vF10110.get('deltas'), list):
                    v989 = sum(vF10110['deltas'])
                if abs(v989) < 8 and isinstance(vF10110.get('deltas'), list):
                    pos = sum(1 for d in vF10110['deltas'] if d > 3)
                    neg = sum(1 for d in vF10110['deltas'] if d < -3)
                    if neg > pos: v989 = -max(8, neg)
                    elif pos > neg: v989 = max(8, pos)
                if abs(v989) >= 8:
                    vLSSwing2 = 'clockwise' if v989 >= 0 else 'counter-clockwise'; vLS4 = 'edge-net'
                elif vF10110.get('type') in ('clockwise','counter-clockwise'):
                    vLSSwing2 = vF10110['type']; vLS4 = 'edge-dir'
            if not (vLS4.startswith('edge-') or vLS4.startswith('chroma')):
                if v959 and isinstance(vVF9810.get('deltas'), list) and vVF9810['deltas']:
                    if v912 >= 500 and v913 >= 0.3:
                        pos = sum(abs(d) for d in vVF9810['deltas'] if d > 5)
                        neg = sum(abs(d) for d in vVF9810['deltas'] if d < -5)
                    else:
                        pos = sum(1 for d in vVF9810['deltas'] if d > 5)
                        neg = sum(1 for d in vVF9810['deltas'] if d < -5)
                    vLSSwing2 = 'clockwise' if pos >= neg else 'counter-clockwise'
                elif vVF9810.get('type') in ('clockwise','counter-clockwise'):
                    vLSSwing2 = vVF9810['type']
                else:
                    net2 = vVF9810.get('net', 0)
                    if not net2 and vVF9810.get('unwrapped') and len(vVF9810['unwrapped'])>1:
                        net2 = vVF9810['unwrapped'][-1] - vVF9810['unwrapped'][0]
                    vLSSwing2 = 'clockwise' if net2 >= 0 else 'counter-clockwise'
            if ((not (v912 < 100) and (not v959 or not (v912 >= 500) or not (v913 >= 0.3))
                 and (not (v928 >= 700) or not (300 <= v912 <= 400) or not (0.55 <= v913 < 0.75)))
                    or (v928 >= 900 and v912 < 100)
                    or vLS4.startswith('chroma')
                    or (v913 >= 0.95 and v916 >= 0.9 and 50 <= v912 < 200)
                    or v902 >= 2
                    or not (vLN0390 >= 80)
                    or not (vLN0392 >= 0.5)
                    or not (abs(vLN0391) >= 25)):
                vLS4 = 'path-summary'
            else:
                vLSSwing2 = 'clockwise' if vLN0391 >= 0 else 'counter-clockwise'; vLS4 = 'pca-dir'
        elif (not v970 or v930
              or (v914 >= 15 and v914 >= v915*0.95)
              or (v914 >= 18 and v914 >= v915*2.5)
              or (not (v902 >= 3) and v914 >= 15 and v914 >= v915*0.8)):
            if (not v967
                or (v969 and v914 < 12 and v915 > v914*2)
                or (v902 >= 2.5 and (not (v914 >= 18) or not (v914 >= v915*2.5)))
                or (v902 >= 0.9 and v915 >= v914*0.85 and v912 < 300 and not (v915 < 5)
                    and (not (v914 >= 18) or not (v902 >= 1.4))
                    and (not (v914 >= 15) or not (v928 >= 500)))
                or (v902 >= 1 and v914 < 16 and v915 >= v914*0.8 and v912 < 300)
                or (v902 >= 1.2 and v912 < 250 and v914 < 14 and not (v915 > 30))):
                if v966:
                    vLSSwing2='swing'; vLS4='swing-path'
                elif v914 >= 5 and 500 <= v928 < 700 and v912 < 80 and v913 < 0.3 and v915 > 30:
                    vLSSwing2='up-down'; vLS4='key-drift'
                elif ((not v969 and (not v968 or not (v912 < 100) or (v914 >= 11 and v928 >= 800)))
                      or (v914 >= 15 and v928 >= 500 and v912 < 50)
                      or (v914 >= 15 and 150 <= v912 < 300 and v913 < 0.45)
                      or (v914 >= 15 and 150 <= v912 < 350 and v913 < 0.2)
                      or (v914 >= 20 and v913 < 0.3)):
                    if v914 >= 15 and v928 >= 500 and v912 < 50:
                        vLSSwing2='up-down'; vLS4='largeA-short'
                    elif (not (v914 >= 15) or not (v913 < 0.4) or not (v912 >= 150) or not (v912 < 350)
                          or v963 or (v915 > v914*1.5 and v902 >= 1)):
                        if (not (v914 >= 20) or not (v913 < 0.3) or v963
                            or (v915 >= v914*0.85 and v902 >= 3.5)):
                            if (((v914 >= 11 and 800 <= v928 < 1100) or (v914 >= 10 and v928 >= 1100 and v913 >= 0.5))
                                    and v912 < 250 and not v963
                                    and (v914 >= v915*0.55 or (v928 < 1000 and v914 >= 11))):
                                vLSSwing2='up-down'; vLS4='largeA'
                            elif v913 >= 0.85 and v912 >= 200 and v916 >= 0.8:
                                vLSSwing2 = vVF9810['type']; vLS4='path-st'
                            elif v968:
                                vLSSwing2='zoom'; vLS4='relArea'
                            else:
                                vLSSwing2='swing'; vLS4='fallback'
                        else:
                            vLSSwing2='up-down'; vLS4='strong-vert'
                    else:
                        vLSSwing2='up-down'; vLS4='noisy-vert'
                else:
                    vLSSwing2='zoom'; vLS4='relArea'
            else:
                vLSSwing2='up-down'; vLS4='dy-dx-ch'
        else:
            vLSSwing2='zoom'; vLS4='relArea'
        
        if (vLSSwing2 in ('zoom', 'swing') and vLS4 == 'relArea'
            and vVF9810.get('type') in ('clockwise', 'counter-clockwise')
            and v912 >= 80 and v916 >= 0.8):
            vLSSwing2 = vVF9810['type']
            vLS4 = 'f98-override'
        
        if debug:
            print(f"\n[f106] roi=({roi['left']},{roi['top']})-({roi['right']},{roi['bottom']})")
            print(f"  meanArea(v928)={v928:.1f} relSwing(v902)={v902:.3f} "
                  f"dy(v914)={v914:.1f} dx(v915)={v915:.1f} changes(v918)={v918}")
            print(f"  path(v912)={v912:.1f} str(v913)={v913:.2f} sign(v916)={v916:.2f} nz(v917)={v917}")
            print(f"  f98={vF9810.get('type')}  f101={vF10110.get('type')}  "
                  f"f104={vF10410.get('type')}  f105={vF10510.get('type')}")
            print(f"  f101 path={self._get(vF10110,'pathLength'):.1f} str={self._get(vF10110,'straightness'):.2f} "
                  f"sign={self._get(vF10110,'signConsistency'):.2f}")
            print(f"  f104 path={self._get(vF10410,'pathLength'):.1f} net={self._get(vF10410,'net'):.1f} "
                  f"meanArea={self._get(vF10410,'meanChromaArea'):.1f}")
            print(f"  f105 path={self._get(vF10510,'pathLength'):.1f} net={self._get(vF10510,'net'):.1f} "
                  f"meanArea={self._get(vF10510,'meanChromaArea'):.1f}")
            print(f"  vF10010: type={vF10010.get('type')} "
                  f"dy={vF10010.get('dy',0):.1f} dx={vF10010.get('dx',0):.1f} "
                  f"changes={vF10010.get('changes',0)}")
            print(f"  vVF9810 -> type={vVF9810.get('type')} reason={vVF9810.get('reason','-')}")
            print(f"  flags: 930={v930} 931={v931} 932={v932} 933={v933} 950={v950} 951={v951}")
            print(f"         952={v952} 953={v953} 954={v954} 955={v955} 956={v956} 957={v957}")
            print(f"         958={v958} 959={v959} 960={v960} 961={v961} 962={v962} 963={v963}")
            print(f"         964={v964} 965={v965} 966={v966} 967={v967} 968={v968} 969={v969} 970={v970}")
            print(f"  ==> FINAL: type={vLSSwing2} reason={vLS4}")
        return {'areas': v898,
                'rotation': {'type': vLSSwing2, 'straightness': v913,
                             'unwrapped': vF9810.get('unwrapped'), 'deltas': vF9810.get('deltas'),
                             'pathLength': v912, 'signConsistency': v916, 'reason': vLS4},
                'zoom': vF10210, 'translation': vF10010, 'centers': v901, 'roi': roi,
                'meanArea': self.f1316([a for a in v898 if a > 0]) if any(a > 0 for a in v898) else 0}

    def f108_ori(self, frames_raw):
        # Versi lama: kembalikan [row, col] tanpa confidence.
        return [[r, c] for r, c, _ in self.f108(frames_raw)]

    def f108(self, frames_raw):
        import cv2
        debug = os.environ.get('DEBUG', False)
        v995 = [{
            'data': np.asarray(fr['data'], dtype=np.uint8).ravel(),
            'width': fr['width'],
            'height': fr['height']
        } for fr in frames_raw]
        v996 = [self.f85(self.f84(fr)) for fr in v995]
        v997 = v996[0]; v998 = v995[0]
        v999 = self.f88(v997, v998)['darkBg']
        v1000 = v997['width']; v1001 = v997['height']
        v1002 = min(v1001, max(40, int(v1001 * 0.45)))

        # Rata-rata baris dihitung sekali (vektor), bukan per iterasi slice.
        row_means = v997['data'].reshape(v1001, v1000).mean(axis=1)
        Sn = None
        for y in range(6, v1002 - 3):
            if row_means[y + 1] > 190 and row_means[y + 2] < 175 and row_means[y + 3] < 170:
                Sn = y + 2
                break
        if Sn is None:
            Sn = int(v1001 * 0.28)

        v1004 = max(10, min(Sn - 1, int(v1001 * 0.3)))
        v1005 = int(v1000 * 0.75)
        vw = v1000 - v1005
        vh = v1004 - 2
        arr = np.asarray(v998['data'], dtype=np.int64).reshape(v1001, v1000, 4)
        sub = arr[2:2 + vh, v1005:v1005 + vw]
        R = sub[..., 0]; G = sub[..., 1]; B = sub[..., 2]
        mx = np.maximum(np.maximum(R, G), B); mn = np.minimum(np.minimum(R, G), B)
        sat = (R + G + B) / 3
        sel = (((mx - mn) > 20) & (sat < 220)) | (sat < 80)
        v1006 = sel.astype(np.uint8)

        # Komponen terbesar via OpenCV (C), menggantikan BFS Python.
        v1013 = None
        num, _labels, stats, _centroids = cv2.connectedComponentsWithStats(v1006, connectivity=4)
        if num > 1:
            cc_areas = stats[1:, cv2.CC_STAT_AREA]
            candidates = np.flatnonzero(cc_areas >= 10)
            if candidates.size:
                candidate_areas = cc_areas[candidates]
                max_area = candidate_areas.max()
                tied = candidates[candidate_areas == max_area]
                # Samakan tie-break dengan BFS lama: komponen pertama urutan scan.
                order = np.lexsort((stats[tied + 1, cv2.CC_STAT_LEFT],
                                    stats[tied + 1, cv2.CC_STAT_TOP]))
                best = int(tied[order[0]])
                bx = int(stats[best + 1, cv2.CC_STAT_LEFT])
                by = int(stats[best + 1, cv2.CC_STAT_TOP])
                bw = int(stats[best + 1, cv2.CC_STAT_WIDTH])
                bh = int(stats[best + 1, cv2.CC_STAT_HEIGHT])
                v1013 = {'minX': bx, 'maxX': bx + bw - 1,
                         'minY': by, 'maxY': by + bh - 1,
                         'area': int(max_area)}

        if v1013:
            v1019 = {'left': max(0, (v1005 + v1013['minX']) - 6),
                     'top': max(0, (2 + v1013['minY']) - 4),
                     'right': min(v1000, (v1005 + v1013['maxX']) + 6),
                     'bottom': min(v1001, (2 + v1013['maxY']) + 4)}
        else:
            v1019 = {'left': int(v1000 * 0.8), 'top': 2,
                     'right': v1000 - 2, 'bottom': min(28, Sn - 1)}

        vO17 = {
            'left': max(0, v1019['left'] - 6),
            'top': max(0, v1019['top'] - 3),
            'right': min(v1000, v1019['right'] + 6),
            'bottom': min(v1001, max(v1019['bottom'] + 3, min(Sn - 1, int(v1001 * 0.32))))
        }
        vO18 = {
            'left': int(v1000 * 0.7),
            'top': 2,
            'right': v1000 - 2,
            'bottom': min(Sn - 1, int(v1001 * 0.34))
        }
        vVF1782 = self.f103(v996, vO17)
        vVF17822 = self.f103(v996, vO18)

        def score(r):
            t = r['type']
            if t == 'up-down': return 100 + (r.get('translation', {}).get('dy', 0) or 0)
            if t == 'zoom': return 90 + (r.get('zoom', {}).get('relSwing', 0) or 0) * 20
            if t in ('clockwise', 'counter-clockwise'): return 80 + (r.get('pathLength', 0) or 0) * 0.2
            return (r.get('pathLength', 0) or 0) * 0.05

        if score(vVF17822) > score(vVF1782):
            vVF1782 = vVF17822
        v1020 = vVF1782['type']
        if debug:
            print(f"[f108] REF v1020={v1020} reason={vVF1782.get('reason','-')} "
                  f"dy={vVF1782.get('translation',{}).get('dy',0):.1f} "
                  f"changes={vVF1782.get('translation',{}).get('changes',0)} "
                  f"relSwing={vVF1782.get('zoom',{}).get('relSwing',0):.3f}")

        vVF1816 = v1001 - Sn
        cw = v1000 / 3; chh = vVF1816 / 2
        result = []
        for r in range(2):
            for c in range(3):
                left = int(c * cw) + 2
                right = min(v1000, int((c + 1) * cw) - 2)
                cell_roi = {'left': left, 'top': int(Sn + r * chh) + 1,
                            'right': right, 'bottom': min(v1001, int(Sn + (r + 1) * chh) - 1)}
                out = self.f106(v996, cell_roi, v999, 120, v995, debug=debug)
                match = out['rotation']['type'] == v1020
                if debug:
                    print(f"[f108] cell [{r},{c}] type={out['rotation']['type']} "
                          f"reason={out['rotation']['reason']} matches_ref={match}")
                if match:
                    rotation = out['rotation']
                    straightness = rotation.get('straightness', 0.5) or 0.5
                    signConsistency = rotation.get('signConsistency', 0.5) or 0.5
                    conf = max(0.1, min(1.0, straightness * signConsistency))
                    result.append([r, c, conf])
        return result

    def f109(self, img, thr):
        h, w = img.shape[:2]
        # Border disusun dalam urutan yang sama dengan loop versi lama.
        top = img[0, :, :3].astype(np.int64)
        bottom = img[h - 1, :, :3].astype(np.int64)
        border = np.stack((top, bottom), axis=1).reshape(-1, 3)
        left = img[1:h - 1, 0, :3].astype(np.int64)
        right = img[1:h - 1, w - 1, :3].astype(np.int64)
        border = np.vstack((border, np.stack((left, right), axis=1).reshape(-1, 3)))

        lum_border = 0.2126 * border[:, 0] + 0.7152 * border[:, 1] + 0.0722 * border[:, 2]
        samples = border[np.argsort(lum_border, kind='stable')]
        n = len(samples)
        mid = n // 2
        bw = max(1, int(n * 0.05))
        med = samples[max(0, mid - bw):min(n, mid + bw + 1)]
        mr = int(round(float(med[:, 0].mean())))
        mg = int(round(float(med[:, 1].mean())))
        mb = int(round(float(med[:, 2].mean())))

        pix = img.reshape(-1, 4)
        keep_alpha = pix[:, 3] >= 16
        R = pix[keep_alpha, 0].astype(np.int64)
        G = pix[keep_alpha, 1].astype(np.int64)
        B = pix[keep_alpha, 2].astype(np.int64)
        d = np.sqrt((R - mr) ** 2 + (G - mg) ** 2 + (B - mb) ** 2)
        keep = d >= 25
        R = R[keep]; G = G[keep]; B = B[keep]
        if R.size == 0:
            return False

        lum_px = 0.2126 * R + 0.7152 * G + 0.0722 * B
        k = max(1, int(round(R.size * 0.1)))
        top_idx = np.argsort(lum_px, kind='stable')[:k]
        ar = float(R[top_idx].sum()) / k
        ag = float(G[top_idx].sum()) / k
        ab = float(B[top_idx].sum()) / k
        lum = ar * 0.2126 + ag * 0.7152 + ab * 0.0722
        chroma = max(ar, ag, ab) - min(ar, ag, ab)
        return lum <= thr and chroma <= thr

    def f110(self, x, y, w, h, gridW, gridH):
        gCols, gRows = 3, 2
        cw = gridW / gCols; ch = gridH / gRows
        min_area = w*h*0.7
        x1 = x + w; y1 = y + h
        c0 = max(0, int(x/cw)); c1 = min(gCols-1, int(x1/cw))
        r0 = max(0, int(y/ch)); r1 = min(gRows-1, int(y1/ch))
        best = None; best_ov = 0
        for r in range(r0, r1+1):
            for c in range(c0, c1+1):
                cx1=c*cw; cx2=(c+1)*cw; cy1=r*ch; cy2=(r+1)*ch
                ox1=max(x,cx1); ox2=min(x1,cx2); oy1=max(y,cy1); oy2=min(y1,cy2)
                ov = max(0, ox2-ox1) * max(0, oy2-oy1)
                if ov > best_ov: best_ov = ov; best = [r, c]
        if best_ov >= min_area and best: return best
        return self.f71(x, y, gridW, gridH)

    def f111_ori(self, frames_raw):
        # Versi lama: kembalikan [row, col] tanpa confidence.
        return [[r, c] for r, c, _ in self.f111(frames_raw)]

    def f111(self, frames_raw):
        import cv2
        if not frames_raw:
            return []
        debug = os.environ.get('DEBUG', False)

        # Data frame dipakai sebagai view; tidak ada penulisan ke array ini.
        mats = [np.asarray(fr['data'], dtype=np.uint8).reshape(fr['height'], fr['width'], 4)
                for fr in frames_raw]
        v1065 = mats[0]
        vA116 = [230, 200, 210, 240, 220, 180, 190]
        vA117 = [0.22, 0.18, 0.19, 0.20, 0.21]
        gray = cv2.cvtColor(v1065, cv2.COLOR_RGBA2GRAY)

        # Threshold + contour tidak bergantung headerY: hitung sekali per threshold.
        thresholded = []
        for th in vA116:
            _, thresh = cv2.threshold(gray, th, 255, cv2.THRESH_BINARY_INV)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            boxes = []
            for cnt in contours:
                x, y, bw, bh = cv2.boundingRect(cnt)
                if bw * bh > 2:
                    boxes.append({'x': x, 'y': y, 'width': bw, 'height': bh})
            boxes.sort(key=lambda b: b['x'])
            thresholded.append((thresh, boxes))

        vA118 = []
        found = False
        for mult in vA117:
            headerY = v1065.shape[0] * mult
            for thresh, all_boxes in thresholded:
                boxes = [b for b in all_boxes
                         if b['y'] < headerY and b['y'] + b['height'] < headerY]
                thin = []; other = []
                for b in boxes:
                    if 1 <= b['width'] <= 2 and 2 <= b['height'] <= 10:
                        top = max(0, b['y'] - 10)
                        bot = min(v1065.shape[0], b['y'] + b['height'] + 10)
                        up = thresh[top:b['y'], b['x']:b['x'] + b['width']]
                        dn = thresh[b['y'] + b['height']:bot, b['x']:b['x'] + b['width']]
                        if cv2.countNonZero(up) == 0 and cv2.countNonZero(dn) == 0:
                            thin.append(b)
                        else:
                            other.append(b)
                    else:
                        other.append(b)
                for i in range(0, len(thin) - 1, 2):
                    aEnd = thin[i]['x'] + thin[i]['width']
                    bStart = thin[i + 1]['x']
                    mnx = float('inf'); mny = float('inf')
                    mxx = -float('inf'); mxy = -float('inf')
                    fnd = False
                    for ob in other:
                        if ob['x'] >= aEnd - 2 and ob['x'] + ob['width'] <= bStart + 2:
                            fnd = True
                            mnx = min(mnx, ob['x']); mny = min(mny, ob['y'])
                            mxx = max(mxx, ob['x'] + ob['width'])
                            mxy = max(mxy, ob['y'] + ob['height'])
                    if fnd:
                        x0 = max(mnx - 2, aEnd + 1)
                        w = min(mxx - mnx + 4, bStart - x0 - 1)
                        h = max(w, 5)
                        if h <= 16:
                            vA118.append({'x': int(x0), 'y': int(mny - 3),
                                          'width': int(h), 'height': int(mxy - mny + 6)})
                if len(vA118) == 3:
                    found = True
                    break
            if found:
                break
        if debug:
            print(f"[f111] vA118 = {len(vA118)} objects")
        if not vA118:
            return self.f108(frames_raw)
        if debug:
            print(f"[f111] vA118 template matching")

        # Data frame 1-D tanpa copy, dipakai ulang untuk semua objek.
        padded = []
        for m in mats:
            p = np.full((m.shape[0] + 1, m.shape[1], 4), 255, dtype=np.uint8)
            p[:m.shape[0], :m.shape[1], :] = m
            padded.append({'rows': p.shape[0], 'cols': p.shape[1], 'data': p.reshape(-1)})

        # Siapkan semua template lebih dulu.
        templates = []
        for ob in vA118:
            crop = v1065[ob['y']:ob['y'] + ob['height'], ob['x']:ob['x'] + ob['width']]
            sw = int(round(ob['width'] * 3))
            sh = int(round(ob['height'] * 3))
            crop_resized = cv2.resize(crop, (sw, sh), interpolation=cv2.INTER_LINEAR)
            g = cv2.cvtColor(crop_resized, cv2.COLOR_RGBA2GRAY)
            _, th2 = cv2.threshold(g, 250, 255, cv2.THRESH_BINARY_INV)
            contours2, _ = cv2.findContours(th2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            tmpl = crop_resized.copy()
            inverted = False
            if contours2:
                best_a = 0; best_i = 0
                for j, cnt in enumerate(contours2):
                    a = cv2.contourArea(cnt)
                    if a > best_a:
                        best_a = a; best_i = j
                mask = np.zeros((sh, sw), dtype=np.uint8)
                cv2.drawContours(mask, [contours2[best_i]], -1, 255, -1)
                inverted = self.f109(crop_resized, 70)
                if inverted:
                    ch = cv2.split(crop_resized)
                    bgr = [cv2.bitwise_not(c) for c in ch[:3]]
                    merged = cv2.merge(bgr + [ch[3]])
                    tmpl[:] = 0
                    tmpl[..., :3] = merged[..., :3]
                    tmpl[..., 3] = np.where(mask > 0, merged[..., 3], 0)
                else:
                    tmpl[:] = 0
                    tmpl[mask > 0] = crop_resized[mask > 0]
            templates.append({
                'tmpl': {'rows': tmpl.shape[0], 'cols': tmpl.shape[1], 'data': tmpl.reshape(-1)},
                'inverted': inverted,
                'sw': sw, 'sh': sh,
                'base_roi': {'x': max(0, ob['x'] - 4), 'y': max(0, ob['y'] - 4),
                             'w': ob['width'] + 8, 'h': ob['height'] + 8},
                'objWidth': ob['width'], 'objHeight': ob['height'],
            })

        # Frame di loop luar: konversi RGB/biner full-frame cukup sekali per frame,
        # lalu dipakai untuk semua template. Hasil kandidat tetap urut per frame.
        total = len(templates)
        candidates_per_obj = [[] for _ in templates]
        need_rgb = any(not t['inverted'] for t in templates)
        need_bin = any(t['inverted'] for t in templates)
        for j, m in enumerate(padded):
            H = m['rows']; W = m['cols']
            data = np.asarray(m['data'], dtype=np.uint8)
            src_rgb = data.reshape(H, W, 4)[..., :3].astype(np.float32) if need_rgb else None
            src_bin = None
            if need_bin:
                src_gray = self.f76(data, W, H).reshape(H, W)
                src_bin = np.where(src_gray > 235, 255, 0).astype(np.uint8)
            for k, t in enumerate(templates):
                roi = t['base_roi'] if j == 0 else None
                if t['inverted']:
                    res = self.f79(m, t['tmpl'], roi, src_bin=src_bin)
                else:
                    res = self.f77(m, t['tmpl'], roi, src_rgb=src_rgb)
                coord = self.f110(res['x'], res['y'], t['sw'], t['sh'],
                                  v1065.shape[1], v1065.shape[0])
                candidates_per_obj[k].append({
                    'score': res['score'], 'coord': coord,
                    'px': res['x'], 'py': res['y'],
                    'isInverted': t['inverted'],
                    'objWidth': t['sw'], 'objHeight': t['sh'],
                })

        vA123 = []
        for k, t in enumerate(templates):
            candidates = candidates_per_obj[k]
            if t['inverted']:
                candidates.sort(key=lambda c: -c['score'])
            else:
                candidates.sort(key=lambda c: c['score'])
            vA123.append({'candidates': candidates, 'isInverted': t['inverted'],
                          'objWidth': t['objWidth'], 'objHeight': t['objHeight']})

        vA124 = [{'coord': o['candidates'][0]['coord'],
                  'score': o['candidates'][0]['score'],
                  'isInverted': o['candidates'][0]['isInverted'],
                  'currentCandidateIdx': 0,
                  'px': o['candidates'][0]['px'],
                  'py': o['candidates'][0]['py'],
                  'objWidth': o['candidates'][0]['objWidth'],
                  'objHeight': o['candidates'][0]['objHeight']}
                 for o in vA123]

        done = len({(c['coord'][0], c['coord'][1]) for c in vA124}) == total
        if not done:
            for _ in range(100):
                dup = None
                for i in range(len(vA124)):
                    for j in range(i + 1, len(vA124)):
                        if vA124[i]['coord'] == vA124[j]['coord']:
                            dup = (i, j)
                            break
                    if dup:
                        break
                if not dup:
                    break
                i1, i2 = dup
                if vA124[i1]['isInverted'] and vA124[i2]['isInverted']:
                    keep, drop = (i1, i2) if vA124[i1]['score'] >= vA124[i2]['score'] else (i2, i1)
                elif vA124[i1]['isInverted'] or vA124[i2]['isInverted']:
                    inv = i1 if vA124[i1]['isInverted'] else i2
                    non = i2 if vA124[i1]['isInverted'] else i1
                    keep, drop = (inv, non) if vA124[inv]['score'] > 0.7 else (non, inv)
                else:
                    keep, drop = (i1, i2) if vA124[i1]['score'] <= vA124[i2]['score'] else (i2, i1)
                used = {(c['coord'][0], c['coord'][1]) for i, c in enumerate(vA124) if i != drop}
                resolved = False
                cands = vA123[drop]['candidates']
                start = vA124[drop]['currentCandidateIdx'] + 1
                for k in list(range(start, len(cands))) + list(range(0, start)):
                    key = (cands[k]['coord'][0], cands[k]['coord'][1])
                    if key not in used:
                        vA124[drop] = {**cands[k], 'currentCandidateIdx': k}
                        resolved = True
                        break
                if not resolved:
                    break

        used = set()
        for idx in range(len(vA124)):
            key = (vA124[idx]['coord'][0], vA124[idx]['coord'][1])
            if key in used:
                fixed = False
                cands = vA123[idx]['candidates'] if idx < len(vA123) else []
                for k, c in enumerate(cands):
                    kk = (c['coord'][0], c['coord'][1])
                    if kk not in used:
                        vA124[idx] = {**c, 'currentCandidateIdx': k}
                        used.add(kk)
                        fixed = True
                        break
                if not fixed:
                    px = vA124[idx]['px']; py = vA124[idx]['py']
                    ow = vA124[idx]['objWidth']; oh = vA124[idx]['objHeight']
                    cw = v1065.shape[1] / 3; ch = v1065.shape[0] / 2
                    cx = px + ow / 2; cy = py + oh / 2
                    best = None; best_d = float('inf')
                    for r in range(2):
                        for c in range(3):
                            if (r, c) in used:
                                continue
                            gx = (c + 0.5) * cw; gy = (r + 0.5) * ch
                            d = math.hypot(gx - cx, gy - cy)
                            if d < best_d:
                                best_d = d; best = [r, c]
                    if best:
                        vA124[idx]['coord'] = best
                        used.add((best[0], best[1]))
            else:
                used.add(key)
        return [[c['coord'][0], c['coord'][1], 1.0] for c in vA124]

    def _generate_debug_gif_b64(self, frames, result_coords) -> str:
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            return ""

        if not frames:
            return ""

        pil_frames = []
        for fr in frames:
            w, h = fr['width'], fr['height']
            img_rgba = np.asarray(fr['data'], dtype=np.uint8).reshape((h, w, 4))
            img_rgb = Image.fromarray(img_rgba[:, :, :3], mode='RGB')
            draw = ImageDraw.Draw(img_rgb)
            
            for item in result_coords:
                r, c = item[0], item[1]
                cw = w / 3.0
                ch = h / 2.0
                cx = int((c + 0.5) * cw)
                cy = int((r + 0.5) * ch)
                
                radius = 8
                draw.ellipse(
                    [(cx - radius, cy - radius), (cx + radius, cy + radius)],
                    fill="red",
                    outline="white"
                )
            pil_frames.append(img_rgb)

        bio = io.BytesIO()
        pil_frames[0].save(
            bio, format='GIF', save_all=True, append_images=pil_frames[1:],
            optimize=False, duration=100, loop=0
        )
        return base64.b64encode(bio.getvalue()).decode('utf-8')

    async def _solve_common(self, base64_gif: str, debug: bool, expected: int, apply_expected: bool):
        loop = asyncio.get_running_loop()

        def _execute():
            try:
                start_time = time.perf_counter()

                raw = self.f70(base64_gif)
                frames = self.f65(raw)
                if not frames or len(frames) < 2:
                    return CaptchaError.badparams("Invalid or insufficient frames in GIF", "Solver failed to find any valid solution.")

                result_coords = self.f111(frames)
                if not result_coords:
                    return CaptchaError.unsolvable("Failed to find sequence objects", "Solver failed to find any valid solution.")

                if apply_expected:
                    result_coords.sort(key=lambda x: -x[2])
                    if expected and len(result_coords) > expected:
                        if os.environ.get('DEBUG'):
                            print(f"[solve] Truncate {len(result_coords)} > {expected}")
                        result_coords = result_coords[:expected]

                result_coords = [[item[0], item[1]] for item in result_coords]

                w = frames[0]['width']
                h = frames[0]['height']
                arr0 = np.frombuffer(frames[0]['data'], dtype=np.uint8).reshape(h, w, 4)
                Sn = self._detect_header_offset(arr0)

                cw = w / 3.0
                grid_h = h - Sn
                ch = grid_h / 2.0

                coords = []
                indices = []
                for r, c in result_coords:
                    x = int((c + 0.5) * cw)
                    y = int(Sn + (r + 0.5) * ch)
                    coords.append(f"{x}:{y}")
                    indices.append(f"{c}:{r}")

                res = {
                    "answer": {
                        "coord": coords,
                        "index": indices
                    }
                }

                if debug:
                    elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                    res["debug"] = {
                        "img": self._generate_debug_gif_b64(frames, result_coords),
                        "elapsed": elapsed_ms
                    }

                return res

            except CaptchaError as e:
                return e
            except Exception as e:
                return CaptchaError.unsolvable(str(e), "Internal solver error occurred")

        try:
            return await loop.run_in_executor(None, _execute)
        except CaptchaError as e:
            return e
        except Exception as e:
            return CaptchaError.unsolvable(str(e), "Internal solver error occurred")

    @staticmethod
    def _detect_header_offset(arr0):
        h = arr0.shape[0]
        Sn = 0
        for yy in range(0, h // 2):
            if not (arr0[yy, :, :3].min(axis=1) > 240).all():
                Sn = yy
                break

        if Sn > 0:
            for yy in range(Sn, h // 2):
                if (arr0[yy, :, :3].min(axis=1) > 240).all():
                    if yy + 1 < h and not (arr0[yy + 1, :, :3].min(axis=1) > 240).all():
                        Sn = yy + 1
                        break
        return Sn

    async def solve(self, base64_gif: str, debug: bool = False, expected: int = 0):
        return await self._solve_common(base64_gif, debug, expected, True)

    async def solve_ori(self, base64_gif: str, debug: bool = False):
        return await self._solve_common(base64_gif, debug, 0, False)

_solver_instance = None

def get_solver():
    global _solver_instance
    if _solver_instance is None:
        _solver_instance = AlcaptchaSolver()
    return _solver_instance

async def solve(base64_gif: str, debug: bool = False, expected: int = 0):
    solver = get_solver()
    return await solver.solve(base64_gif, debug, expected)

if __name__ == "__main__":
    gif_path = os.environ.get("GIF_PATH", "./../Adslab/cap/01.gif")

    try:
        with open(gif_path, "rb") as f:
            gif_data = f.read()
        
        base64_gif = base64.b64encode(gif_data).decode("utf-8")
        print(f"[*] Testing GIF: {gif_path} (Base64 length: {len(base64_gif)} chars)")
        
        result = asyncio.run(solve(base64_gif, debug=False))
        
        print("\n[+] Solver Result:")
        if isinstance(result, dict):
            print(json.dumps(result, indent=2))
        else:
            print(f"[-] Error: {result}")
            
    except FileNotFoundError:
        print(f"[-] Error: File '{gif_path}' tidak ditemukan. Sediakan path file GIF yang valid.")
    except Exception as e:
        print(f"[-] Exception: {e}")