// Copies the phone page into the app, adds the camera permission, syncs Capacitor.
const fs = require("fs"), path = require("path"), { execSync } = require("child_process");
const run = (c) => execSync(c, { stdio: "inherit", cwd: __dirname });
fs.mkdirSync(path.join(__dirname, "www"), { recursive: true });
const web = path.join(__dirname, "..", "app", "web");
fs.copyFileSync(path.join(web, "capture.html"), path.join(__dirname, "www", "index.html"));
const lib = path.join(__dirname, "www", "lib");
fs.rmSync(lib, { recursive: true, force: true });
fs.mkdirSync(path.join(lib, "fonts"), { recursive: true });
for (const f of ["theme.css", "jsqr.js"]) fs.copyFileSync(path.join(web, "lib", f), path.join(lib, f));
for (const f of fs.readdirSync(path.join(web, "lib", "fonts"))) fs.copyFileSync(path.join(web, "lib", "fonts", f), path.join(lib, "fonts", f));
if (!fs.existsSync(path.join(__dirname, "android"))) run("npx cap add android");
const mf = path.join(__dirname, "android", "app", "src", "main", "AndroidManifest.xml");
let x = fs.readFileSync(mf, "utf8");
if (!x.includes("android.permission.CAMERA")) {
  x = x.replace("<application", '<uses-permission android:name="android.permission.CAMERA" />\n    <uses-permission android:name="android.permission.VIBRATE" />\n    <uses-feature android:name="android.hardware.camera" android:required="false" />\n    <application');
  fs.writeFileSync(mf, x);
}
run("npx cap sync android");
console.log("\nReady. Build with: cd android && gradlew assembleDebug");
