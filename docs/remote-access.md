# Remote access and OTA boundaries

`3dcam.thinhme.tech` must not point directly at the ESP32 or a router port-forward. Run Cloudflare Tunnel on an always-on gateway inside the camera LAN, route it to `http://192.168.1.27`, and require Cloudflare Access authentication. Store tunnel credentials only in the gateway secret store, never Git.

OTA is intentionally not enabled. The current factory-only partition table cannot roll back a failed update. First stabilize the microSD and camera, then switch by USB to dual OTA slots, add HTTPS manifest/hash verification and boot health checkpoint/rollback. USB Web Flash remains recovery even after OTA.
