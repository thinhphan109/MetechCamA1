# MQTT over TLS direct to VPS

The ESP32 remote module supports a provisioned `mqtts://` endpoint as an alternative transport; HTTPS and MQTT are exclusive. The broker must expose **TLS only** on `8883`, require per-device credentials, and apply per-device ACLs.

## Topics

- Device subscribes: `metech/<device-id>/command` (QoS 1)
- Device publishes: `metech/<device-id>/status` and `metech/<device-id>/ack` (QoS 1) — command execution wiring is the next provisioning phase.

## Mosquitto baseline

```conf
listener 8883
cafile /etc/mosquitto/certs/ca.pem
certfile /etc/mosquitto/certs/server.pem
keyfile /etc/mosquitto/certs/server.key
allow_anonymous false
password_file /etc/mosquitto/passwd
acl_file /etc/mosquitto/acl
```

Never expose `1883` publicly. Provision the device's unique broker password and `mqtts://` endpoint via local USB/LAN configuration; do not commit either.
