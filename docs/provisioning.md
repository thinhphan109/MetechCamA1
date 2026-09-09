# Provisioning and development

## Firmware prerequisites

- ESP-IDF 5.5.5.
- ESP32-S3 board on `COM19` (choose the actual port on another machine).

## Local Recovery AP credentials

`firmware/esp32/main/local_defaults.h` is intentionally ignored. It holds the Recovery AP credentials used for a private board. Create or edit it locally from `firmware/config/local_defaults.h.example`; never commit it.

If the ignored file is absent, firmware uses the development fallback from `network_defaults.h`. Change it before deploying outside a trusted LAN.

## Build and flash

```powershell
$env:IDF_TOOLS_PATH='C:\Espressif'
& 'C:\Espressif\frameworks\esp-idf-v5.5.5\export.ps1'
idf.py -C firmware/esp32 build
idf.py -C firmware/esp32 -p COM19 flash
```

Configure home Wi-Fi through the local WebUI. The SSID/password are stored in the board's NVS, never in this repository.