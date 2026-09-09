# Architecture

```text
Browser / Windows app
        │ HTTP on trusted LAN
ESP32 WebUI + HTTP API
        ├─ camera mutex ─ OV5640 preview / QSXGA stills
        ├─ storage ─ microSD atomic JPEG and strict gallery names
        ├─ network ─ NVS home Wi-Fi and Recovery AP
        └─ NVS ─ camera settings saved only by explicit user action
```

`firmware/esp32/main/app_main.c` is currently the integration point. Future feature work should extract only cohesive modules: camera service, storage service, network service and HTTP API. Keep `web_ui.h` dependency-free because it is compiled into firmware flash.

GitHub Actions builds firmware and runs desktop checks. CI artifacts are for manual review/flash. OTA is not enabled yet: it requires dual OTA partitions, HTTPS manifest/download verification, signed firmware and a tested rollback/recovery path.