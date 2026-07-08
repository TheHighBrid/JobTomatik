# Building the JobTomatik Android APK

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Node.js | 18+ | https://nodejs.org |
| Java (JDK) | 17 | `brew install openjdk@17` or https://adoptium.net |
| Android Studio | Latest | https://developer.android.com/studio |
| Android SDK | API 34+ | Install via Android Studio SDK Manager |

> Tip: set `ANDROID_HOME` and add `$ANDROID_HOME/tools` and `$ANDROID_HOME/platform-tools` to your `PATH`.

---

## Step 1 — Deploy the Backend

The APK connects to your backend over the network. Run the backend somewhere reachable from your phone:

```bash
# On your LAN (development)
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Or with Docker
docker-compose up -d backend db redis
```

Note your server's local IP address (e.g. `192.168.1.100`).

---

## Step 2 — Configure the Backend URL in the App

After installing the APK on your phone, open **Settings → Backend Connection** and enter:

```
http://192.168.1.100:8000
```

This is persisted in the device's local storage and used for all API calls.

---

## Step 3 — Build the APK

### Quick start (all-in-one script)

```bash
./build-apk.sh
```

### Manual steps

```bash
cd frontend

# Install deps (first time only)
npm install

# Build the React app
npm run build

# Add Android platform (first time only)
npx cap add android

# Sync web assets into Android project
npx cap sync android
```

---

## Step 4 — Generate the APK

### Option A: Android Studio (easiest)

```bash
cd frontend
npx cap open android
```

Inside Android Studio:
1. Wait for Gradle sync to complete
2. **Build → Generate Signed Bundle / APK**
3. Choose **APK**, create or use an existing keystore
4. Build the **release** variant

The APK will be in:
```
frontend/android/app/build/outputs/apk/release/app-release.apk
```

### Option B: Debug APK via Gradle (no signing needed)

```bash
cd frontend/android
./gradlew assembleDebug
```

APK location:
```
frontend/android/app/build/outputs/apk/debug/app-debug.apk
```

Transfer to your phone and install:
```bash
adb install frontend/android/app/build/outputs/apk/debug/app-debug.apk
```

---

## After Every Frontend Change

```bash
cd frontend
npm run build:apk   # = npm run build + cap sync android
# Then rebuild in Android Studio or via Gradle
```

---

## Troubleshooting

### "Network request failed" in the APK
- Make sure the backend is running and reachable from your phone
- In **Settings → Backend Connection** enter the correct IP + port
- Make sure your phone and server are on the same Wi-Fi network (for LAN setup)

### "Cleartext traffic not permitted"
- The backend must be served over **HTTPS** for production, OR
- Keep `"cleartext": true` in `capacitor.config.json` for local/dev builds

### "CORS error" from the backend
- The backend already allows `*` — no change needed
- If you harden CORS later, add `capacitor://localhost` and `http://localhost` to `allow_origins`

### White screen after install
- Run `npx cap sync` then rebuild — the web assets may be out of date

### Android SDK not found
```bash
export ANDROID_HOME=$HOME/Library/Android/sdk   # macOS
export PATH=$PATH:$ANDROID_HOME/tools:$ANDROID_HOME/platform-tools
```
