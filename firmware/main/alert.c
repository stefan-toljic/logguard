#include "alert.h"

#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <sys/time.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "mqtt_client.h"
#include "sdkconfig.h"

static const char *TAG = "alert";

#define BIT_WIFI_UP   BIT0
#define BIT_MQTT_UP   BIT1
#define BIT_PUBLISHED BIT2

#define WIFI_TIMEOUT_MS 15000
#define MQTT_TIMEOUT_MS 10000
#define PENDING_MAX 16

static EventGroupHandle_t s_events;
static QueueHandle_t s_queue;
static esp_mqtt_client_handle_t s_mqtt;
static bool s_mqtt_running;
static volatile int s_published_id = -1;
static bool s_time_synced;
static bool s_wifi_wanted;

// Alerts that could not be delivered, resent on the next connection.
static char s_pending[PENDING_MAX][256];
static int s_pending_n;

static char s_topic_alert[64];
static char s_topic_status[64];

int64_t alert_now_us(void)
{
    if (!s_time_synced) return esp_timer_get_time();
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (int64_t)tv.tv_sec * 1000000 + tv.tv_usec;
}

static void on_wifi(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(s_events, BIT_WIFI_UP);
        if (s_wifi_wanted) esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        xEventGroupSetBits(s_events, BIT_WIFI_UP);
    }
}

static void on_mqtt(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    esp_mqtt_event_handle_t ev = data;
    switch ((esp_mqtt_event_id_t)id) {
    case MQTT_EVENT_CONNECTED:
        xEventGroupSetBits(s_events, BIT_MQTT_UP);
        break;
    case MQTT_EVENT_DISCONNECTED:
        xEventGroupClearBits(s_events, BIT_MQTT_UP);
        break;
    case MQTT_EVENT_PUBLISHED:
        if (ev->msg_id == s_published_id) xEventGroupSetBits(s_events, BIT_PUBLISHED);
        break;
    default:
        break;
    }
}

static bool wifi_up(void)
{
    if (xEventGroupGetBits(s_events) & BIT_WIFI_UP) return true;
    s_wifi_wanted = true;
    esp_wifi_start();
    EventBits_t b = xEventGroupWaitBits(s_events, BIT_WIFI_UP, pdFALSE, pdTRUE,
                                        pdMS_TO_TICKS(WIFI_TIMEOUT_MS));
    if (!(b & BIT_WIFI_UP)) ESP_LOGW(TAG, "Wi-Fi '%s' not reachable", CONFIG_LOGGUARD_WIFI_SSID);
    return b & BIT_WIFI_UP;
}

static void wifi_down(void)
{
    s_wifi_wanted = false;
    esp_wifi_stop();
    xEventGroupClearBits(s_events, BIT_WIFI_UP);
}

static bool mqtt_up(void)
{
    if (xEventGroupGetBits(s_events) & BIT_MQTT_UP) return true;
    if (!s_mqtt) {
        esp_mqtt_client_config_t cfg = {
            .broker.address.uri = CONFIG_LOGGUARD_MQTT_URI,
            .credentials.username = CONFIG_LOGGUARD_MQTT_USER,
            .credentials.authentication.password = CONFIG_LOGGUARD_MQTT_PASSWORD,
            .credentials.client_id = CONFIG_LOGGUARD_DEVICE_ID,
        };
        s_mqtt = esp_mqtt_client_init(&cfg);
        esp_mqtt_client_register_event(s_mqtt, ESP_EVENT_ANY_ID, on_mqtt, NULL);
    }
    if (!s_mqtt_running) {
        esp_mqtt_client_start(s_mqtt);
        s_mqtt_running = true;
    }
    EventBits_t b = xEventGroupWaitBits(s_events, BIT_MQTT_UP, pdFALSE, pdTRUE,
                                        pdMS_TO_TICKS(MQTT_TIMEOUT_MS));
    if (!(b & BIT_MQTT_UP)) ESP_LOGW(TAG, "MQTT broker %s not reachable", CONFIG_LOGGUARD_MQTT_URI);
    return b & BIT_MQTT_UP;
}

static void mqtt_down(void)
{
    if (s_mqtt_running) {
        esp_mqtt_client_stop(s_mqtt);
        s_mqtt_running = false;
        xEventGroupClearBits(s_events, BIT_MQTT_UP);
    }
}

// QoS 1 publish that waits for the broker's PUBACK.
static bool publish(const char *topic, const char *payload)
{
    xEventGroupClearBits(s_events, BIT_PUBLISHED);
    s_published_id = esp_mqtt_client_publish(s_mqtt, topic, payload, 0, 1, 0);
    if (s_published_id < 0) return false;
    EventBits_t b = xEventGroupWaitBits(s_events, BIT_PUBLISHED, pdTRUE, pdTRUE,
                                        pdMS_TO_TICKS(MQTT_TIMEOUT_MS));
    return b & BIT_PUBLISHED;
}

static int wifi_rssi(void)
{
    wifi_ap_record_t ap;
    return esp_wifi_sta_get_ap_info(&ap) == ESP_OK ? ap.rssi : 0;
}

static void keep_pending(const char *payload)
{
    if (s_pending_n == PENDING_MAX) {
        memmove(s_pending[0], s_pending[1], sizeof(s_pending[0]) * (PENDING_MAX - 1));
        s_pending_n--;
    }
    strlcpy(s_pending[s_pending_n++], payload, sizeof(s_pending[0]));
    ESP_LOGW(TAG, "alert kept for retry (%d pending)", s_pending_n);
}

static void flush_pending(void)
{
    int sent = 0;
    while (sent < s_pending_n && publish(s_topic_alert, s_pending[sent])) sent++;
    if (sent) {
        memmove(s_pending[0], s_pending[sent], sizeof(s_pending[0]) * (s_pending_n - sent));
        s_pending_n -= sent;
        ESP_LOGI(TAG, "resent %d pending alerts", sent);
    }
}

// Connects if needed, sends, and drops the radio again in on-demand mode.
static bool deliver(const char *topic, const char *payload)
{
    bool ok = false;
    for (int attempt = 0; attempt < 3 && !ok; attempt++) {
        if (attempt) vTaskDelay(pdMS_TO_TICKS(2000));
        if (!wifi_up() || !mqtt_up()) continue;
        flush_pending();
        ok = publish(topic, payload);
    }
#if CONFIG_LOGGUARD_WIFI_ON_DEMAND
    mqtt_down();
    wifi_down();
#endif
    return ok;
}

static void alert_task(void *arg)
{
    const TickType_t wait = CONFIG_LOGGUARD_HEARTBEAT_MIN > 0
        ? pdMS_TO_TICKS(CONFIG_LOGGUARD_HEARTBEAT_MIN * 60 * 1000) : portMAX_DELAY;
    char payload[256];
    alert_t a;
    for (;;) {
        if (xQueueReceive(s_queue, &a, wait) == pdTRUE) {
            int64_t t0 = esp_timer_get_time();
            // Connect first so the payload can carry the Wi-Fi RSSI.
            bool up = wifi_up();
            snprintf(payload, sizeof(payload),
                     "{\"device_id\":\"%s\",\"ts_us\":%lld,\"time_synced\":%s,"
                     "\"class\":\"chainsaw\",\"score\":%.3f,\"score_int8\":%d,"
                     "\"windows\":%lu,\"rssi\":%d}",
                     CONFIG_LOGGUARD_DEVICE_ID, (long long)a.ts_us,
                     s_time_synced ? "true" : "false", a.score, a.raw,
                     (unsigned long)a.windows, up ? wifi_rssi() : 0);
            bool ok = deliver(s_topic_alert, payload);
            if (!ok) keep_pending(payload);
            ESP_LOGI(TAG, "alert score=%.2f mqtt=%s in %lld ms", a.score, ok ? "ok" : "FAIL",
                     (long long)((esp_timer_get_time() - t0) / 1000));
        } else {
            snprintf(payload, sizeof(payload),
                     "{\"device_id\":\"%s\",\"ts_us\":%lld,\"uptime_s\":%lld,"
                     "\"free_heap\":%lu,\"pending\":%d}",
                     CONFIG_LOGGUARD_DEVICE_ID, (long long)alert_now_us(),
                     (long long)(esp_timer_get_time() / 1000000),
                     (unsigned long)esp_get_free_heap_size(), s_pending_n);
            deliver(s_topic_status, payload);
        }
    }
}

esp_err_t alert_init(void)
{
    snprintf(s_topic_alert, sizeof(s_topic_alert), "logguard/alerts/%s", CONFIG_LOGGUARD_DEVICE_ID);
    snprintf(s_topic_status, sizeof(s_topic_status), "logguard/status/%s", CONFIG_LOGGUARD_DEVICE_ID);
    s_events = xEventGroupCreate();
    s_queue = xQueueCreate(8, sizeof(alert_t));

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_wifi, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_wifi, NULL));
    wifi_config_t wc = {0};
    strlcpy((char *)wc.sta.ssid, CONFIG_LOGGUARD_WIFI_SSID, sizeof(wc.sta.ssid));
    strlcpy((char *)wc.sta.password, CONFIG_LOGGUARD_WIFI_PASSWORD, sizeof(wc.sta.password));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));

    // Sync the clock once so ts_us is wall-clock time and the receiver can
    // compute end-to-end latency.
    if (wifi_up()) {
        esp_sntp_config_t sntp = ESP_NETIF_SNTP_DEFAULT_CONFIG("pool.ntp.org");
        esp_netif_sntp_init(&sntp);
        s_time_synced = esp_netif_sntp_sync_wait(pdMS_TO_TICKS(10000)) == ESP_OK;
        esp_netif_sntp_deinit();
        ESP_LOGI(TAG, "time %s", s_time_synced ? "synced" : "NOT synced, ts_us = time since boot");
    }
#if CONFIG_LOGGUARD_WIFI_ON_DEMAND
    wifi_down();
#endif

    xTaskCreatePinnedToCore(alert_task, "alert", 6144, NULL, 4, NULL, 0);
    return ESP_OK;
}

void alert_post(const alert_t *a)
{
    if (xQueueSend(s_queue, a, 0) != pdTRUE) ESP_LOGW(TAG, "alert queue full, dropped");
}
