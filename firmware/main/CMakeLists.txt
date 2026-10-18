idf_component_register(
    SRCS "main.cc" "detector.cc" "mfcc.c" "mic.c" "alert.c" "generated/model_data.cc"
    INCLUDE_DIRS "."
    REQUIRES esp_driver_i2s esp_wifi esp_netif esp_event esp_timer nvs_flash mqtt)
