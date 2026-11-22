"""Photos -> one equirectangular panorama.

1. Start from the phone's recorded orientation of every photo.
2. Refine: match features between overlapping photos and solve all rotations (and the lens FOV) together.
3. Even out exposure between photos.
4. Blend in two bands: smooth colours, sharp detail with hard seams (no ghosting).
CPU uses numpy. GPU (NVIDIA, cupy) is used for the projection and blending when available.
"""
import json, math, time
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter

try:
    import cupy as cp
    cp.cuda.runtime.getDeviceCount()
    GPU = True
except Exception:
    cp, GPU = None, False
try:
    import cv2
    from scipy.optimize import least_squares
    from scipy.sparse import lil_matrix
    from scipy.spatial.transform import Rotation as Rot
    ALIGN = True
except Exception:
    ALIGN = False


def gpu_info():
    if not GPU:
        return None
    try:
        return cp.cuda.runtime.getDeviceProperties(0)["name"].decode()
    except Exception:
        return "NVIDIA GPU"


# ---------------------------------------------------------------- alignment
def _fn0(fov):  # focal length in units of the long image side
    return 1.0 / (2 * math.tan(math.radians(fov) / 2))


def _load_small(path, side=1300):
    im = Image.open(path).convert("RGB")
    s = side / max(im.size)
    return np.asarray(im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS))


def _match_pairs(Rs, imgs):
    """Feature matches between overlapping photos. Returns list of (i, j, pts_i, pts_j) in normalised coords."""
    sift = cv2.SIFT_create(nfeatures=2500)
    feats = []
    for im in imgs:
        g = cv2.cvtColor(im, cv2.COLOR_RGB2GRAY)
        k, d = sift.detectAndCompute(g, None)
        feats.append((np.float32([p.pt for p in k]), d))
    bf = cv2.BFMatcher(cv2.NORM_L2)
    out = []
    n = len(imgs)
    for i in range(n):
        for j in range(i + 1, n):
            if Rs[i][:, 2] @ Rs[j][:, 2] < math.cos(math.radians(85)):
                continue
            (pi, di), (pj, dj) = feats[i], feats[j]
            if di is None or dj is None or len(pi) < 20 or len(pj) < 20:
                continue
            good = [m for m, n2 in (p for p in bf.knnMatch(di, dj, k=2) if len(p) == 2) if m.distance < .75 * n2.distance]
            if len(good) < 15:
                continue
            a = pi[[m.queryIdx for m in good]]; b = pj[[m.trainIdx for m in good]]
            H, mask = cv2.findHomography(a, b, cv2.RANSAC, 4.0)
            if H is None or mask.sum() < 12:
                continue
            keep = mask.ravel() > 0
            a, b = a[keep], b[keep]
            if len(a) > 80:
                sel = np.random.default_rng(0).choice(len(a), 80, replace=False); a, b = a[sel], b[sel]
            out.append((i, j, a, b))
    return out, feats


def _norm(pts, im):
    h, w = im.shape[:2]; m = max(w, h)
    return np.stack([(pts[:, 0] - w / 2) / m, -(pts[:, 1] - h / 2) / m], 1)


def _refine(Rs, imgs, fov, progress):
    n = len(Rs)
    progress("Matching photos")
    pairs, _ = _match_pairs(Rs, imgs)
    if sum(len(p[2]) for p in pairs) < 40:
        return Rs, fov, 0, []
    I = np.concatenate([np.full(len(p[2]), p[0]) for p in pairs]); J = np.concatenate([np.full(len(p[2]), p[1]) for p in pairs])
    A = np.concatenate([_norm(p[2], imgs[p[0]]) for p in pairs]); B = np.concatenate([_norm(p[3], imgs[p[1]]) for p in pairs])
    R0 = np.stack(Rs)
    fn0 = _fn0(fov)
    M = len(I)

    def rays(xy, s):
        v = np.concatenate([xy / (fn0 * s), np.ones((len(xy), 1))], 1)
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    def fun(x):
        Rm = Rot.from_rotvec(x[:3 * n].reshape(n, 3)).as_matrix() @ R0
        s = math.exp(x[-1])
        ri = np.einsum("mab,mb->ma", Rm[I], rays(A, s)); rj = np.einsum("mab,mb->ma", Rm[J], rays(B, s))
        return np.concatenate([(ri - rj).ravel(), 0.03 * x[:3 * n], [0.01 * x[-1]]])

    sp = lil_matrix((3 * M + 3 * n + 1, 3 * n + 1), dtype=int)
    for m in range(M):
        for r in range(3):
            row = 3 * m + r
            sp[row, 3 * I[m]:3 * I[m] + 3] = 1; sp[row, 3 * J[m]:3 * J[m] + 3] = 1; sp[row, 3 * n] = 1
    for k in range(3 * n + 1):
        sp[3 * M + k, k] = 1
    progress("Aligning photos")
    lo = np.full(3 * n + 1, -np.inf); hi = np.full(3 * n + 1, np.inf); lo[-1], hi[-1] = -.7, .7
    # the FOV is only a guess, so scan it first: the right one makes the matches agree best
    ps = np.linspace(-.6, .6, 25)
    cost = [np.sum(np.minimum(fun(np.r_[np.zeros(3 * n), p])[:3 * M] ** 2, .003)) for p in ps]
    x0 = np.zeros(3 * n + 1); x0[-1] = ps[int(np.argmin(cost))]
    sol = least_squares(fun, x0, jac_sparsity=sp, bounds=(lo, hi), max_nfev=40)          # coarse, plain least squares
    sol = least_squares(fun, sol.x, jac_sparsity=sp, loss="soft_l1", f_scale=.004, bounds=(lo, hi), max_nfev=40)  # fine, ignores bad matches
    Rn = Rot.from_rotvec(sol.x[:3 * n].reshape(n, 3)).as_matrix() @ R0
    s = math.exp(sol.x[-1])
    fov2 = math.degrees(2 * math.atan(1 / (2 * fn0 * s)))
    connected = sorted(set(I.tolist()) | set(J.tolist()))
    # tiny per-match samples for exposure matching, returned in image pixel coordinates
    return list(Rn), fov2, len(connected), pairs


def _gains(pairs, imgs):
    """Per-photo, per-channel gain so overlapping photos agree in brightness and colour."""
    n = len(imgs)
    if not pairs:
        return np.ones((n, 3), np.float32)
    blur = [cv2.blur(im, (9, 9)).astype(np.float32) for im in imgs]
    rows = []
    for i, j, a, b in pairs:
        ci = blur[i][np.clip(a[:, 1].astype(int), 0, blur[i].shape[0] - 1), np.clip(a[:, 0].astype(int), 0, blur[i].shape[1] - 1)]
        cj = blur[j][np.clip(b[:, 1].astype(int), 0, blur[j].shape[0] - 1), np.clip(b[:, 0].astype(int), 0, blur[j].shape[1] - 1)]
        ok = (ci.min(1) > 12) & (cj.min(1) > 12) & (ci.max(1) < 245) & (cj.max(1) < 245)
        if ok.sum() >= 8:
            rows.append((i, j, np.log(np.median(ci[ok], 0) + 1) - np.log(np.median(cj[ok], 0) + 1), ok.sum()))
    g = np.zeros((n, 3), np.float32)
    if not rows:
        return np.ones((n, 3), np.float32)
    for c in range(3):
        A = np.zeros((len(rows) + n, n)); y = np.zeros(len(rows) + n)
        for r, (i, j, d, w) in enumerate(rows):
            wt = math.sqrt(min(w, 60))
            A[r, i] = wt; A[r, j] = -wt; y[r] = -wt * d[c]  # a_i - a_j = log(cj) - log(ci)
        A[len(rows):] = np.eye(n) * 0.15
        g[:, c] = np.linalg.lstsq(A, y, rcond=None)[0]
    g -= g.mean(0)
    return np.exp(np.clip(g, -.5, .5)).astype(np.float32)


# ---------------------------------------------------------------- projection + blending
def _bilinear(xp, a, x0, y0, x1, y1, fx, fy):
    return (a[y0, x0] * (1 - fx) * (1 - fy) + a[y0, x1] * fx * (1 - fy) + a[y1, x0] * (1 - fx) * fy + a[y1, x1] * fx * fy)


def _blend(d, meta, Rs, fov, gains, use_gpu, W, progress):
    xp = cp if use_gpu else np
    H = W // 2
    lon = (xp.arange(W, dtype=xp.float32) + .5) / W * 2 * math.pi - math.pi
    lat = math.pi / 2 - (xp.arange(H, dtype=xp.float32) + .5) / H * math.pi
    cl = xp.cos(lat)[:, None]
    D = xp.stack([cl * xp.sin(lon)[None, :], cl * xp.cos(lon)[None, :],
                  xp.broadcast_to(xp.sin(lat)[:, None], (H, W))], -1).reshape(-1, 3).astype(xp.float32)
    lo_acc = xp.zeros((H * W, 3), xp.float32); hi_acc = xp.zeros((H * W, 3), xp.float32)
    lo_w = xp.zeros(H * W, xp.float32); hi_w = xp.zeros(H * W, xp.float32)
    fn = _fn0(fov)
    for k, m in enumerate(meta):
        progress(f"Blending {k + 1} of {len(meta)}")
        im = Image.open(d / m["file"]).convert("RGB")
        w, h = im.size
        low = np.asarray(im.filter(ImageFilter.GaussianBlur(max(w, h) / 45)), dtype=np.float32) * gains[k]
        high = np.asarray(im, dtype=np.float32) * gains[k] - low
        low, high = xp.asarray(low), xp.asarray(high)
        f = fn * max(w, h)
        c = D @ xp.asarray(np.ascontiguousarray(Rs[k], dtype=np.float32))
        z = c[:, 2]
        ok = z > 1e-3
        zz = xp.where(ok, z, 1)
        u = w / 2 + f * c[:, 0] / zz
        v = h / 2 - f * c[:, 1] / zz
        ok &= (u >= 0) & (u <= w - 1) & (v >= 0) & (v <= h - 1)
        idx = xp.nonzero(ok)[0]
        if idx.size == 0:
            continue
        u, v = u[idx], v[idx]
        x0 = xp.floor(u).astype(xp.int32); y0 = xp.floor(v).astype(xp.int32)
        x1 = xp.minimum(x0 + 1, w - 1); y1 = xp.minimum(y0 + 1, h - 1)
        fx = (u - x0)[:, None]; fy = (v - y0)[:, None]
        e = xp.minimum(1 - xp.abs(2 * u / w - 1), 1 - xp.abs(2 * v / h - 1)) + 1e-4
        wl, wh = e, e ** 6
        lo_acc[idx] += _bilinear(xp, low, x0, y0, x1, y1, fx, fy) * wl[:, None]; lo_w[idx] += wl
        hi_acc[idx] += _bilinear(xp, high, x0, y0, x1, y1, fx, fy) * wh[:, None]; hi_w[idx] += wh
    cover = lo_w > 0
    out = lo_acc / xp.maximum(lo_w, 1e-6)[:, None] + hi_acc / xp.maximum(hi_w, 1e-6)[:, None]
    out = xp.where(cover[:, None], out, 20)
    cov = float(cover.mean())
    out = out.reshape(H, W, 3).clip(0, 255).astype(xp.uint8)
    if use_gpu:
        out = out.get()
        cp.get_default_memory_pool().free_all_blocks()
    return out, cov


def _render(d: Path, out: Path, use_gpu, W, fov, progress):
    meta = json.loads((d / "meta.json").read_text())
    Rs = [np.stack([m["right"], m["up"], m["fwd"]], 1) for m in meta]
    aligned, gains, pairs = 0, np.ones((len(meta), 3), np.float32), []
    if ALIGN and len(meta) > 1:
        try:
            progress("Reading photos")
            small = [_load_small(d / m["file"]) for m in meta]
            Rs, fov, aligned, pairs = _refine(Rs, small, fov, progress)
            gains = _gains(pairs, small)
        except Exception as e:  # never lose the render because alignment failed
            print("alignment skipped:", e)
    img, cov = _blend(d, meta, Rs, fov, gains, use_gpu, W, progress)
    progress("Saving")
    Image.fromarray(img).save(out, quality=93)
    return cov, aligned, fov


def render(d: Path, out: Path, mode="auto", width=2048, fov=65.0, progress=lambda m: None):
    if mode == "gpu" and not GPU:
        raise RuntimeError("No usable NVIDIA GPU found. Choose CPU.")
    use_gpu = GPU and mode in ("auto", "gpu")
    t = time.time()
    try:
        cov, aligned, fov2 = _render(d, out, use_gpu, width, fov, progress)
    except Exception:
        if not (use_gpu and mode == "auto"):
            raise
        use_gpu = False
        cov, aligned, fov2 = _render(d, out, False, width, fov, progress)
    n = len(json.loads((d / "meta.json").read_text()))
    return {"backend": "GPU" if use_gpu else "CPU", "secs": round(time.time() - t, 1), "coverage": round(cov, 3),
            "aligned": aligned, "photos": n, "fov": round(fov2, 1)}
