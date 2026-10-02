#!/bin/bash
# TriCloud APK 手动构建脚本（aapt2 + javac + d8 + apksigner，不依赖 Gradle）
set -e
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
A="$(dirname "$0")/app/src/main"
SDK="${ANDROID_HOME:-$HOME/android-sdk}"
BT="$SDK/build-tools/34.0.0"
OUT="${OUT_DIR:-/tmp/apkbuild}"
APK_NAME="${APK_NAME:-tricloud.apk}"

rm -rf "$OUT" && mkdir -p "$OUT/classes" "$OUT/dex"
echo "==> aapt2 compile"
"$BT/aapt2" compile --dir "$A/res" -o "$OUT/compiled.zip"
echo "==> aapt2 link"
"$BT/aapt2" link -o "$OUT/base.apk" -I "$SDK/platforms/android-34/android.jar" \
  --manifest "$A/AndroidManifest.xml" --java "$OUT/gen" "$OUT/compiled.zip" \
  --min-sdk-version 24 --target-sdk-version 34
echo "==> javac"
find "$A/java" "$OUT/gen" -name "*.java" > "$OUT/sources.txt"
"$JAVA_HOME/bin/javac" -encoding UTF-8 -source 17 -target 17 \
  -cp "$SDK/platforms/android-34/android.jar" -d "$OUT/classes" @"$OUT/sources.txt"
echo "==> d8"
"$BT/d8" --min-api 24 --output "$OUT/dex" $(find "$OUT/classes" -name "*.class")
echo "==> 打包签名"
cp "$OUT/base.apk" "$OUT/unsigned.apk"
(cd "$OUT/dex" && zip -q -0 ../unsigned.apk classes.dex)
if [ ! -f "$OUT/debug.keystore" ]; then
  "$JAVA_HOME/bin/keytool" -genkeypair -keystore "$OUT/debug.keystore" -alias androiddebugkey \
    -keyalg RSA -keysize 2048 -validity 10950 -storepass android -keypass android \
    -dname "CN=TriCloud, OU=Dev, O=TriCloud, L=Local, ST=Local, C=CN" >/dev/null 2>&1
fi
"$BT/zipalign" -f 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"
"$BT/apksigner" sign --ks "$OUT/debug.keystore" --ks-pass pass:android --key-pass pass:android \
  --out "$OUT/$APK_NAME" "$OUT/aligned.apk"
"$BT/apksigner" verify "$OUT/$APK_NAME"
echo "==> 完成: $OUT/$APK_NAME"
ls -la "$OUT/$APK_NAME"
