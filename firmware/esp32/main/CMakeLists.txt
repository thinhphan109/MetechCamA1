idf_component_register(
    SRCS "app_main.c" "trigger.c" "metech_reliability.c" "metech_remote.c"
    INCLUDE_DIRS "."
    EMBED_FILES "logo.png"
    REQUIRES esp_timer driver esp_event esp_netif esp_http_server esp_wifi nvs_flash fatfs sdmmc esp_driver_gpio esp32-camera esp_psram esp_http_client mbedtls esp-tls mqtt
)
