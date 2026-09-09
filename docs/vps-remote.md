# Outbound remote access

`3dcam.thinhme.tech` can operate with **only the ESP32 at home and a datacenter VPS**. The ESP32 creates outbound HTTPS requests to the VPS; home router NAT needs no change and no LAN gateway/tunnel process is installed.

The repository currently includes the VPS protocol foundation in `remote-server/`: device HMAC authentication, timestamp + nonce replay protection, heartbeat status, one queued-command poll and JPEG upload storage. It binds only to loopback and must be placed behind VPS TLS proxy. Viewer authentication and ESP32 agent are intentionally not yet active, so the device remains local-only and safe by default.

Do not port-forward the ESP32 or expose its local WebUI. Do not run remote OTA until dual-slot rollback and stability soak tests exist.
