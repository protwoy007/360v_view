# Pano360

Capture a full 360 sphere with your phone, then render it into a viewable panorama on your PC. No cloud, no account: everything stays on your own devices.

## How it works

1. **Phone app (Android)** guides you with on-screen rings. Point at a ring, hold still, and it takes the photo by itself. Dark or blurry shots are rejected so you can retake them. Photos and the phone's orientation for each shot are stored on the phone, so you can capture on a trip with no PC around.
2. **Back home**, run the PC app, scan its QR code from the phone app, and press **Send to PC**.
3. **The PC** places every photo on a sphere using the recorded orientation and writes one equirectangular image. Open it in the built-in 360 viewer.

The renderer has two modes, chosen automatically or by hand on the PC page:

- **CPU** works everywhere (NumPy).
- **GPU** uses an NVIDIA card through CuPy and falls back to CPU if anything fails.

## Run the PC app

Needs internet on the first run. Everything is installed inside the project folder.

- **Linux:** `chmod +x run.sh` then `./run.sh`
- **Windows:** double-click `run.bat`

The launcher checks the requirements, installs whatever is missing (Python on Windows, packages, the GPU libraries on Linux with an NVIDIA card), checks again, and then starts the app. The PC page opens in your browser with the QR code and the app address. On Windows, allow the firewall prompt the first time.

## Build the Android app

Needs Node.js and Android Studio.

- **Windows:** `apk\build-apk.bat`
- **Linux/Mac:** `apk/build-apk.sh`

The APK is created at `apk/android/app/build/outputs/apk/debug/app-debug.apk`. If Gradle cannot find the SDK, open `apk/android` once in Android Studio and run the script again.

## Project layout

```
run.sh / run.bat     launchers (check, install, start)
app/setup.py         requirement checker and installer
app/server.py        web server, QR code, uploads, render jobs
app/render.py        CPU / GPU panorama renderer
app/web/             PC page, phone page, 360 viewer, theme and fonts
apk/                 Capacitor wrapper that builds the Android app
```

## Known limits

- Photos are placed using the phone's gyroscope only, with no image matching, so expect small seams or exposure differences.
- The phone and the PC must be on the same Wi-Fi to send photos.
- Tested on Linux with CPU rendering. The GPU path, Windows launcher and the Android build have not been verified on every setup.

## Third-party

- [Cormorant Garamond](https://github.com/CatharsisFonts/Cormorant) and [Cabin](https://github.com/impallari/Cabin) fonts, SIL Open Font License (licenses in `app/web/lib/fonts/`)
- [jsQR](https://github.com/cozmo/jsQR), Apache-2.0 (license in `app/web/lib/`)
- [Pannellum](https://pannellum.org), MIT, downloaded on first run for the 360 viewer
- FastAPI, Uvicorn, NumPy, Pillow, qrcode, cryptography, CuPy, Capacitor

## Contribution

Designed and developed by **Khaled (Protwoy)**, 2026.
