import datetime, ipaddress, json, platform, re, socket, sys, threading, webbrowser
from io import BytesIO
from pathlib import Path

import qrcode, qrcode.image.svg, uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent))
import render

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WEB = Path(__file__).parent / "web"
(DATA / "sessions").mkdir(parents=True, exist_ok=True)
(DATA / "out").mkdir(exist_ok=True)
HTTP_PORT, HTTPS_PORT = 8000, 8443
LOCK = threading.Lock()
JOBS = {}
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def clean(s): return re.sub(r"[^A-Za-z0-9_-]", "_", s)[:60] or "spot"


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1)); return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


IP = lan_ip()
PHONE_URL = f"https://{IP}:{HTTPS_PORT}/capture"


def ensure_cert(ip):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    c, k, t = DATA / "cert.pem", DATA / "key.pem", DATA / "cert.ip"
    if c.exists() and k.exists() and t.exists() and t.read_text() == ip:
        return c, k
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "pano360")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address(ip))]), critical=False)
            .sign(key, hashes.SHA256()))
    k.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                    serialization.NoEncryption()))
    c.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    t.write_text(ip)
    return c, k


@app.get("/")
def home(): return FileResponse(WEB / "index.html")


@app.get("/capture")
def capture(): return FileResponse(WEB / "capture.html")


@app.get("/view")
def view(): return FileResponse(WEB / "viewer.html")


@app.get("/api/info")
def info():
    return {"os": platform.system(), "gpu": render.gpu_info(), "phone_url": PHONE_URL, "app_url": f"{IP}:{HTTP_PORT}"}


@app.get("/qr.svg")
def qr():
    buf = BytesIO()
    qrcode.make(PHONE_URL + f"?app={IP}:{HTTP_PORT}", image_factory=qrcode.image.svg.SvgPathImage, box_size=10).save(buf)
    return Response(buf.getvalue(), media_type="image/svg+xml")


@app.post("/api/upload")
async def upload(session: str = Form(...), shot: str = Form(...), meta: str = Form(...), file: UploadFile = File(...)):
    data = await file.read()
    d = DATA / "sessions" / clean(session)
    d.mkdir(parents=True, exist_ok=True)
    with LOCK:
        mf = d / "meta.json"
        items = json.loads(mf.read_text()) if mf.exists() else []
        sid = clean(shot)
        if any(i["id"] == sid for i in items):
            return {"ok": True, "dup": True}
        name = f"{len(items):03d}.jpg"
        (d / name).write_bytes(data)
        m = json.loads(meta); m.update(id=sid, file=name)
        items.append(m)
        mf.write_text(json.dumps(items))
    return {"ok": True}


@app.get("/api/sessions")
def sessions():
    out = []
    for d in sorted((DATA / "sessions").iterdir()):
        mf = d / "meta.json"
        if not mf.exists():
            continue
        out.append({"name": d.name, "count": len(json.loads(mf.read_text())),
                    "rendered": (DATA / "out" / f"{d.name}.jpg").exists(), "job": JOBS.get(d.name)})
    return out


class RenderReq(BaseModel):
    session: str
    mode: str = "auto"
    width: int = 2048
    fov: float = 65.0


@app.post("/api/render")
def start(r: RenderReq):
    s = clean(r.session)
    d = DATA / "sessions" / s
    if not (d / "meta.json").exists():
        raise HTTPException(404, "No photos for this spot")
    if (JOBS.get(s) or {}).get("state") == "running":
        raise HTTPException(409, "Already rendering")
    JOBS[s] = {"state": "running"}

    def work():
        try:
            def prog(m): JOBS[s] = {"state": "running", "msg": m}
            JOBS[s] = {"state": "done", **render.render(d, DATA / "out" / f"{s}.jpg", r.mode,
                                                        min(max(r.width, 512), 8192), r.fov, progress=prog)}
        except Exception as e:
            JOBS[s] = {"state": "error", "msg": str(e)}
    threading.Thread(target=work, daemon=True).start()
    return {"ok": True}


app.mount("/lib", StaticFiles(directory=WEB / "lib"), name="lib")
app.mount("/out", StaticFiles(directory=DATA / "out"), name="out")

if __name__ == "__main__":
    cert, key = ensure_cert(IP)
    local = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=HTTP_PORT, log_level="warning"))
    threading.Thread(target=local.run, daemon=True).start()
    print(f"\nPano360 running.\n  PC page:    http://localhost:{HTTP_PORT}\n  Phone page: {PHONE_URL}\n  APK address: {IP}:{HTTP_PORT}\n  Press Ctrl+C to stop.\n")
    threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{HTTP_PORT}")).start()
    uvicorn.run(app, host="0.0.0.0", port=HTTPS_PORT, ssl_keyfile=str(key), ssl_certfile=str(cert), log_level="warning")
