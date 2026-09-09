# Metech Capture firmware

ESP-IDF firmware baseline for ESP32-S3 + OV5640 + microSD + Hall trigger.

## Status

The trigger state machine and host test are implemented. Camera, SD, GPIO, WebUI and remote relay remain disabled because the exact board has not been selected. Camera/SD pinouts vary and enabling arbitrary pins can corrupt SD writes or prevent boot.

## Board acceptance checklist

Before setting `METECH_BOARD_READY` in `main/board_profile.h`, record:

- Product URL and revision.
- ESP32-S3 module marking, ideally `N16R8`.
- OV5640 **DVP**, not MIPI CSI.
- Vendor camera pin map.
- Vendor microSD pin map and tested mode.
- One unused GPIO safe for Hall input.

## Current trigger guarantees

- Hall LOW must remain stable 15 ms.
- Camera waits 300 ms after confirmation for printer vibration to settle.
- One capture only while magnet is present.
- Hall must be HIGH for 40 ms before re-arm.
- A 5 second minimum frame interval blocks abnormal repeated triggers.

Run host test with any C compiler:

```powershell
clang -std=c11 -Wall -Wextra -I main test/test_trigger.c main/trigger.c -o test_trigger.exe
.\test_trigger.exe
```

## ESP-IDF build

Install ESP-IDF 5.x first, open an ESP-IDF PowerShell, then:

```powershell
idf.py set-target esp32s3
idf.py build
```

Do not flash until `board_profile.h` contains verified pins.
