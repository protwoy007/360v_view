"""Place photos on a sphere using the phone's recorded orientation. CPU (numpy) or GPU (cupy)."""
import json, math, time
from pathlib import Path
import numpy as np
from PIL import Image

try:
    import cupy as cp
    cp.cuda.runtime.getDeviceCount()
    GPU = True
except Exception:
    cp, GPU = None, False


def gpu_info():
    if not GPU:
        return None
    try:
        return cp.cuda.runtime.getDeviceProperties(0)["name"].decode()
    except Exception:
        return "NVIDIA GPU"


def _render(d: Path, out: Path, use_gpu: bool, W: int, fov: float):
    xp = cp if use_gpu else np
    meta = json.loads((d / "meta.json").read_text())
    H = W // 2
    lon = (xp.arange(W, dtype=xp.float32) + .5) / W * 2 * math.pi - math.pi
    lat = math.pi / 2 - (xp.arange(H, dtype=xp.float32) + .5) / H * math.pi
    cl = xp.cos(lat)[:, None]
    D = xp.stack([cl * xp.sin(lon)[None, :], cl * xp.cos(lon)[None, :],
                  xp.broadcast_to(xp.sin(lat)[:, None], (H, W))], -1).reshape(-1, 3).astype(xp.float32)
    acc = xp.zeros((H * W, 3), xp.float32)
    wsum = xp.zeros(H * W, xp.float32)
    for m in meta:
        a = np.asarray(Image.open(d / m["file"]).convert("RGB"))
        h, w = a.shape[:2]
        a = xp.asarray(a, dtype=xp.float32)
        f = (max(w, h) / 2) / math.tan(math.radians(fov) / 2)
        Rm = xp.asarray(np.array([m["right"], m["up"], m["fwd"]], dtype=np.float32))
        c = D @ Rm.T
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
        px = (a[y0, x0] * (1 - fx) * (1 - fy) + a[y0, x1] * fx * (1 - fy)
              + a[y1, x0] * (1 - fx) * fy + a[y1, x1] * fx * fy)
        wt = xp.minimum(1 - xp.abs(2 * u / w - 1), 1 - xp.abs(2 * v / h - 1)) + 1e-3
        acc[idx] += px * wt[:, None]
        wsum[idx] += wt
    img = xp.where(wsum[:, None] > 0, acc / xp.maximum(wsum, 1e-6)[:, None], 28)
    cover = float((wsum > 0).mean())
    img = img.reshape(H, W, 3).clip(0, 255).astype(xp.uint8)
    if use_gpu:
        img = img.get()
        cp.get_default_memory_pool().free_all_blocks()
    Image.fromarray(img).save(out, quality=92)
    return cover


def render(d: Path, out: Path, mode="auto", width=2048, fov=65.0):
    if mode == "gpu" and not GPU:
        raise RuntimeError("No usable NVIDIA GPU found. Choose CPU.")
    use_gpu = GPU and mode in ("auto", "gpu")
    t = time.time()
    try:
        cover = _render(d, out, use_gpu, width, fov)
    except Exception:
        if not (use_gpu and mode == "auto"):
            raise
        use_gpu = False
        cover = _render(d, out, False, width, fov)
    return {"backend": "GPU" if use_gpu else "CPU", "secs": round(time.time() - t, 1), "coverage": round(cover, 3)}
