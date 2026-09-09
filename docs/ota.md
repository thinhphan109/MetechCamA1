# OTA policy

Production OTA requires dual application slots, `otadata`, HTTPS transport, manifest and SHA-256 verification, user confirmation, and rollback when camera/network/storage health checkpoint does not complete. Do not enable remote OTA while microSD health checks fail.
