#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
npm install && node prepare.js && cd android && chmod +x gradlew && ./gradlew assembleDebug \
  && echo && echo "APK: $(pwd)/app/build/outputs/apk/debug/app-debug.apk"
