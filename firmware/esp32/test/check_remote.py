from pathlib import Path
root=Path(__file__).resolve().parents[1]
s=(root/'main'/'metech_remote.c').read_text(encoding='utf-8')
assert 'crt_bundle_attach=esp_crt_bundle_attach' in s
assert 'https://' in s and 'mqtts://' in s
assert 'timeout_ms=8000' in s
assert 'strlen(secret)>=32' in s
assert 'X-Metech-Signature' in s
assert 'esp_mqtt_client_subscribe' in s
assert 'enabled=load_config' in s
assert 'esp_http_client_set_header(c,"X-Metech-Device"' in s
print('PASS: remote TLS transport contracts')
