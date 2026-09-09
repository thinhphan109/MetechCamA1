# USB Web Flash

Host `web-flasher/` over HTTPS. Open it in Chrome or Edge, connect the board by data USB cable, select `COM19` / `USB-Enhanced-SERIAL CH343`, then install the selected signed release manifest.

The page only uses a three-part release manifest: bootloader, partition table and application binary. It does not accept arbitrary local firmware files. Keep USB `idf.py -p COM19 flash` as recovery.
