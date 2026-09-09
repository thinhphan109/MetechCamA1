# Hardware profile

- MCU: ESP32-S3-WROOM-1-N16R8 (16 MB flash, 8 MB PSRAM).
- Sensor: OV5640, SCCB address `0x3c`.
- Wi-Fi: 2.4 GHz 802.11 b/g/n only.
- microSD: SDMMC 1-bit, `CMD=GPIO38`, `CLK=GPIO39`, `DAT0=GPIO40`.
- Onboard GPIO2 LED is active-low and forced off by firmware. The separate `ON` power LED is hardware-wired and cannot be turned off in software.

The installed OV5640 module does not advertise autofocus support. Lens focus and light contamination are physical issues; camera settings can tune colour and exposure but cannot repair an out-of-focus lens.