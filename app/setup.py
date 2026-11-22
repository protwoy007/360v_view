"""Check requirements, install what is missing, check again. Stdlib only."""
import os, re, shutil, subprocess, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
VPY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
REQ = ROOT / "app" / "requirements.txt"
LIB = ROOT / "app" / "web" / "lib"
GPU_TRIED = VENV / ".gpu-tried"
PANN = ["https://cdnjs.cloudflare.com/ajax/libs/pannellum/2.5.6/pannellum.min.", "https://cdn.jsdelivr.net/npm/pannellum@2.5.6/build/pannellum."]
CHECK = ("import importlib.util as u,fastapi,uvicorn,numpy,PIL,qrcode,cryptography;"
         "assert u.find_spec('python_multipart') or u.find_spec('multipart')")


def say(m): print("[setup]", m, flush=True)


def missing():
    out = []
    if not VPY.exists():
        return ["venv"]
    if subprocess.run([str(VPY), "-c", CHECK], capture_output=True).returncode:
        out.append("packages")
    out += [f for f in ("pannellum.js", "pannellum.css") if not (LIB / f).exists()]
    return out


def fix(item):
    if item == "venv":
        say("Creating local environment...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV)])
    elif item == "packages":
        say("Installing packages (first run only)...")
        subprocess.run([str(VPY), "-m", "pip", "install", "-q", "--upgrade", "pip"])
        subprocess.run([str(VPY), "-m", "pip", "install", "-q", "-r", str(REQ)])
    else:
        say(f"Downloading {item}...")
        LIB.mkdir(parents=True, exist_ok=True)
        ext = item.split(".")[-1]
        for base in PANN:
            try:
                urllib.request.urlretrieve(base + ext, LIB / item)
                break
            except Exception as e:
                say(f"  failed: {e}")


def gpu_step():
    """Optional: NVIDIA GPU libraries. Failure just means CPU mode."""
    if GPU_TRIED.exists() or not shutil.which("nvidia-smi"):
        return
    try:
        txt = subprocess.run(["nvidia-smi"], capture_output=True, text=True).stdout
        ver = int(re.search(r"CUDA Version:\s*(\d+)", txt).group(1))
    except Exception:
        return
    pkg = "cupy-cuda12x" if ver >= 12 else "cupy-cuda11x"
    say(f"NVIDIA GPU found. Installing {pkg} (one time, large download)...")
    ok = subprocess.run([str(VPY), "-m", "pip", "install", "-q", pkg]).returncode == 0
    say("GPU libraries ready." if ok else "GPU libraries failed, CPU mode will be used.")
    GPU_TRIED.write_text("1")


for attempt in range(3):
    miss = missing()
    if not miss:
        gpu_step()
        say("All requirements OK.")
        sys.exit(0)
    say("Missing: " + ", ".join(miss))
    for m in miss:
        fix(m)
left = missing()
if left and all(x.startswith("pannellum") for x in left):
    gpu_step()
    say("360 viewer files could not be downloaded (no internet?). The app still works; the viewer will load them online.")
    sys.exit(0)
say("Still missing after 3 tries: " + ", ".join(left))
sys.exit(1)
