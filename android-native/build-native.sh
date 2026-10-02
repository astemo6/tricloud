#!/bin/bash
# TriCloud Native 手动构建脚本（aapt2 + javac + d8，不依赖 Gradle daemon）
set -e
export JAVA_HOME="$HOME/jdk17"
export PATH="$JAVA_HOME/bin:$PATH"
A="$(dirname "$0")/app/src/main"
SDK="${ANDROID_HOME:-$HOME/android-sdk}"
BT="$SDK/build-tools/34.0.0"
LIBS="$(dirname "$0")/libs"
OUT="${OUT_DIR:-/tmp/nativebuild}"
APK_NAME="${APK_NAME:-TriCloud-native.apk}"

rm -rf "$OUT" && mkdir -p "$OUT/classes" "$OUT/dex"
CP="$SDK/platforms/android-34/android.jar"
for j in "$LIBS"/*.jar; do CP="$CP:$j"; done

echo "==> aapt2 compile"
"$BT/aapt2" compile --dir "$A/res" -o "$OUT/compiled.zip"
echo "==> aapt2 link"
"$BT/aapt2" link -o "$OUT/base.apk" -I "$SDK/platforms/android-34/android.jar" \
  --manifest "$A/AndroidManifest.xml" --java "$OUT/gen" "$OUT/compiled.zip" \
  --min-sdk-version 26 --target-sdk-version 34
echo "==> javac"
mkdir -p "$OUT/gen"
find "$A/java" "$OUT/gen" -name "*.java" > "$OUT/sources.txt"
javac -encoding UTF-8 -source 17 -target 17 -cp "$CP" -d "$OUT/classes" @"$OUT/sources.txt"
echo "==> d8"
"$BT/d8" --min-api 26 --lib "$SDK/platforms/android-34/android.jar" \
  --output "$OUT/dex" $(find "$OUT/classes" -name "*.class") \
  "$LIBS"/okhttp-4.12.0.jar "$LIBS"/okio-jvm-3.6.0.jar \
  "$LIBS"/kotlin-stdlib-1.9.24.jar "$LIBS"/gson-2.11.0.jar
echo "==> 打包签名"
cp "$OUT/base.apk" "$OUT/unsigned.apk"
(cd "$OUT/dex" && zip -q -0 ../unsigned.apk classes.dex)
if [ ! -f "$OUT/debug.keystore" ]; then
  keytool -genkeypair -keystore "$OUT/debug.keystore" -alias androiddebugkey \
    -keyalg RSA -keysize 2048 -validity 10950 -storepass android -keypass android \
    -dname "CN=TriCloud, OU=Dev, O=TriCloud, L=Local, ST=Local, C=CN" >/dev/null 2>&1
fi
"$BT/zipalign" -f 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"
"$BT/apksigner" sign --ks "$OUT/debug.keystore" --ks-pass pass:android \
  --key-pass pass:android --out "$OUT/$APK_NAME" "$OUT/aligned.apk"
cp "$OUT/$APK_NAME" "$(dirname "$0")/$APK_NAME"
echo "==> 完成: $(dirname "$0")/$APK_NAME"
ls -lh "$(dirname "$0")/$APK_NAME"
