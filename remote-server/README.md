# VPS-only remote access

The ESP32 will initiate HTTPS requests to this service. Do not bind this development server to the Internet and do not terminate TLS in it. Run it only behind Caddy or Nginx at `127.0.0.1:8080`.

## Initial VPS checklist

1. Create DNS `A` record: `3dcam.thinhme.tech` -> VPS public IPv4.
2. Install Caddy (or Nginx) on the VPS and proxy TLS traffic to `127.0.0.1:8080`.
3. Create a dedicated Unix user and persistent data directory with `0700` permissions.
4. Provision each device directly into the SQLite `device` table with a random 32-byte secret. This bootstrap must run locally on the VPS, never via a public endpoint.
5. Set ESP32 remote endpoint and secret only after the outbound agent lands. The current firmware is deliberately remote-disabled.

## API contract

ESP requests include `X-Metech-Device`, `X-Metech-Time`, `X-Metech-Nonce`, and `X-Metech-Signature`. The signature is HMAC-SHA256 over `timestamp + "\\n" + nonce + "\\n" + raw-body`. Requests outside a 5-minute window or repeated nonce fail. JPEGs are limited to 800 KB.

`server.py` is a minimal protocol foundation. It is not a public viewer yet: browser authentication and access policy must exist before serving images or commands.

## Local test

```sh
python test_remote.py
```
