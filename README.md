# MetechCamA1

Metech Camera A1 is an ESP32-S3 + OV5640 timelapse camera with microSD storage, a local WebUI, and a Windows image-import/timelapse application.

## Repository layout

- `firmware/esp32/` — ESP-IDF 5.5.5 firmware for ESP32-S3-WROOM-1-N16R8.
- `desktop/` — Windows Tkinter application: safe image download and MP4 timelapse rendering.
- `docs/` — hardware, provisioning and architecture notes.

## Capabilities

- OV5640 preview, QSXGA still capture and 180-degree sensor rotation.
- microSD health check, atomic JPEG writes, restart-safe sequence recovery and gallery.
- Live camera profiles/settings persisted only after explicit save.
- Home Wi-Fi plus fallback Recovery AP.
- Safe incremental image download to Windows; source files on microSD are never deleted.

## Quick start

See [provisioning](docs/provisioning.md) for ESP-IDF setup, local credentials and flashing. The normal camera page is `http://192.168.1.27/` on the configured LAN.

```powershell
python -m pip install -r desktop/requirements.txt
python desktop/timelapse.py --selftest

$env:IDF_TOOLS_PATH='C:\Espressif'
& 'C:\Espressif\frameworks\esp-idf-v5.5.5\export.ps1'
idf.py -C firmware/esp32 build
```

## Security

Do not commit `firmware/esp32/main/local_defaults.h`, Wi-Fi details, NVS dumps, build folders, captured media or generated videos. Do not expose the ESP32 through router port forwarding. A public remote-view feature must use authenticated Cloudflare Access or an equivalent reverse proxy.