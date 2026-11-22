@echo off
cd /d "%~dp0"
call npm install
if errorlevel 1 goto fail
call node prepare.js
if errorlevel 1 goto fail
cd android
call gradlew.bat assembleDebug
if errorlevel 1 goto fail
echo.
echo APK: %cd%\app\build\outputs\apk\debug\app-debug.apk
pause
exit /b 0
:fail
echo Build failed. See the message above.
pause
exit /b 1
