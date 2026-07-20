---
status: blocked
subject: Browser-playable game builds with Pixel 6a release gate
created: 2026-07-20
mode: pipeline
artifact_contract: visual-runtime
---

# Evidence: Browser-playable game builds with Pixel 6a release gate

## Verdict

Blocked: Portal's browser-playable release is proven in a real browser and the full test suite passes, but Android rejected the specified APK because the Pixel already has the same package signed by a different key, so the required same-APK native install/launch gate is not proven.

## What Changed

- Releases can carry an optional, contained Vite web bundle and serve it through a public opaque-origin sandbox with CORS-enabled assets.
- The release page provides one interactive device preview at a time, five real viewport presets, portrait/landscape switching, explicit states, and a visible native-proof disclaimer.
- Existing APK-only releases remain downloadable and render without broken preview controls.

## Evidence Captured

| Type | Artifact / Command | Result |
|------|--------------------|--------|
| browser video | `assets/browser-playthrough.webm` | passed: fresh post-polish 8-second sequence shows Marble Run menu, Level 1 launch, populated gameplay, and attempted pointer input inside Portal |
| browser frames | `assets/browser-frame-1.png` through `assets/browser-frame-4.png` | passed: 1400 x 2117 frames show the playable release and Portal preview surface after commit `b06d6b3` |
| tests | `UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q` | passed: 362 tests, 1 dependency deprecation warning, 5.83 seconds |
| device identity | `adb devices -l`; `getprop ro.product.model`; `getprop ro.product.device` | passed: authorized serial `27091JEGR22183`, model `Pixel 6a`, device `bluejay`, 1080 x 2400 at density 420 |
| APK identity | SHA-256 of `fabrikav2/games/marble_run/android/app/build/outputs/apk/debug/app-debug.apk` | observed: `d5796663b478558dd1f9e8fdf22dd951b8c9db2fa1b3c53424e4c8075649dd0d`, 7,643,255 bytes |
| APK install | `adb -s 27091JEGR22183 install -r app-debug.apk` | blocked: `INSTALL_FAILED_UPDATE_INCOMPATIBLE`; installed `com.appletolye.marblerun.dev` signature differs from the supplied APK |
| existing device app | launcher intent + `dumpsys activity activities` + `pidof` | observed only: existing package resumed `.MainActivity` with PID 22999; `assets/pixel-existing-install.png` records that state but does not prove the supplied APK |

## Reviewer Assessments

| Reviewer | Status | Result |
|----------|--------|--------|
| game aesthetics reviewer | passed | The exact fresh post-polish browser artifacts showed menu, Level 1, sustained gameplay, pointer interaction, adequate controls, visible disclaimer, and restrained safe-area guide; no Portal-owned P1 or P2 finding remained. |

## Analysis

The browser half of the visual-runtime contract is strong: the durable video and frame sequence are the same fresh post-polish artifacts accepted by the independent aesthetics review, and the current branch passes all 362 tests. The named Pixel is connected and authorized, and an already-installed Marble Run package launches successfully. However, Android refused to install the supplied release APK over that package because their signing certificates differ. Launching the pre-existing package cannot establish that the supplied APK still installs and launches. Uninstalling the existing package may remove or disturb device app data and was not explicitly authorized, so this evidence run stopped rather than turning an installation failure into a false pass.

## Gaps

- The supplied APK has not installed or launched on Pixel 6a `27091JEGR22183`.
- Consequently, native parity remains an unfulfilled release gate even though the Portal browser preview itself is verified.

## Next Action

Authorize removal of `com.appletolye.marblerun.dev` from Pixel 6a `27091JEGR22183` (accepting possible app-data loss), then install the supplied APK, launch `.MainActivity`, and capture a fresh device screenshot or recording plus activity/process evidence; alternatively provide an APK signed with the certificate already installed on the Pixel.
