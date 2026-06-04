#include <Arduino.h>
#include <WiFi.h>
#include <WiFiManager.h>
#include <WebSocketsClient.h>
#include <driver/i2s.h>
#include "freertos/stream_buffer.h"
#include "soc/rtc_cntl_reg.h"  // for brownout disable

// ============================================================
//  CẤU HÌNH WIFI — WiFiManager (auto portal khi chưa có WiFi)
// ============================================================
#define WIFI_AP_NAME "ESP32-Audio-Setup"
#define WIFI_PORTAL_TIMEOUT 180  // 3 phút timeout portal

// ============================================================
//  CẤU HÌNH WEBSOCKET SERVER (public cloud host — no mDNS)
// ============================================================
#define SERVER_HOST "49.213.89.44"   // 4090 server public IP
#define SERVER_PORT 2108             // backend WS/API port
const char* wsPath = "/ws";

// Device identity — derived from MAC at boot (shared firmware, unique per chip)
String deviceId   = "esp32-unknown";
String deviceName = "ESP32";

// ============================================================
//  CẤU HÌNH CHÂN I2S MIC
// ============================================================
#define I2S_WS   15
#define I2S_SD   32
#define I2S_SCK  14
#define I2S_PORT I2S_NUM_0

// ============================================================
//  THAM SỐ
// ============================================================
#define RESET_PIN 0  // nút BOOT trên board — giữ 3s để xóa WiFi
#define SAMPLE_RATE 16000
#define STREAM_BUF_SIZE (SAMPLE_RATE * 2 * 1)  // 32KB (1 giây)
#define SEND_BUF_SIZE 512  // 512 samples = 32ms audio per WS frame

// FreeRTOS StreamBuffer - thread-safe cho producer-consumer
StreamBufferHandle_t audioStream = NULL;

WebSocketsClient webSocket;

// Statistics
volatile uint32_t samplesRead    = 0;
volatile uint32_t samplesSent    = 0;
volatile uint32_t lastStatTime   = 0;
volatile uint32_t packetsSent    = 0;
volatile uint32_t disconnectCount = 0;


// ============================================================
//  WEBSOCKET EVENTS
// ============================================================
void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
  switch(type) {
    case WStype_DISCONNECTED:
      Serial.println("WebSocket disconnected (auto-reconnect in 5s)");
      disconnectCount++;
      break;
    case WStype_CONNECTED: {
      Serial.println("WebSocket connected");
      disconnectCount = 0;
      String hello = String("{\"type\":\"hello\",\"device_id\":\"") +
                     deviceId + "\",\"name\":\"" + deviceName + "\"}";
      webSocket.sendTXT(hello);
      Serial.println("Sent hello: " + hello);
      break;
    }
    case WStype_TEXT:
      Serial.printf("Received: %s\n", payload);
      break;
    case WStype_BIN:
    case WStype_ERROR:
    case WStype_FRAGMENT_TEXT_START:
    case WStype_FRAGMENT_BIN_START:
    case WStype_FRAGMENT:
    case WStype_FRAGMENT_FIN:
      break;
  }
}

// ============================================================
//  I2S Task - Chạy trên Core 0, đọc mic liên tục
// ============================================================
void i2sTask(void* param) {
  int32_t raw[128];
  int16_t pcm[128];
  
  while (true) {
    size_t bytes_read;
    esp_err_t err = i2s_read(I2S_PORT, raw, sizeof(raw), &bytes_read, pdMS_TO_TICKS(100));
    
    if (err != ESP_OK || bytes_read == 0) {
      continue;
    }
    
    int count  = bytes_read / sizeof(int32_t);   // total int32 samples (L,R interleaved)
    int frames = count / 2;                        // stereo -> mono output
    samplesRead += frames;

    // INMP441 drives only ONE channel (left or right, set by its L/R pin). Read both and
    // pick whichever has signal, so the SAME firmware works regardless of how L/R is wired.
    // >> 11 gives ~8x gain for the quiet INMP441; clamp prevents clipping distortion.
    for (int i = 0; i < frames; i++) {
      int32_t l = raw[2 * i]     >> 11;
      int32_t r = raw[2 * i + 1] >> 11;
      int32_t al = l < 0 ? -l : l;
      int32_t ar = r < 0 ? -r : r;
      int32_t val = (al >= ar) ? l : r;
      if (val > 32767)  val = 32767;
      if (val < -32768) val = -32768;
      pcm[i] = (int16_t)val;
    }

    // Ghi vào stream buffer (non-blocking)
    size_t bytesToWrite = frames * sizeof(int16_t);
    xStreamBufferSend(audioStream, pcm, bytesToWrite, 0);
  }
}

// ============================================================
//  Network Task - Chạy trên Core 1, gửi WebSocket
// ============================================================
void networkTask(void* param) {
  int16_t sendBuf[SEND_BUF_SIZE];
  const size_t SEND_BYTES = SEND_BUF_SIZE * sizeof(int16_t);  // 1024 bytes

  while (true) {
    webSocket.loop();

    if (webSocket.isConnected()) {
      // Drain the stream buffer as fast as possible — no artificial delay.
      // I2S produces 16000 samples/s; we send 512 samples the moment they are ready.
      // That gives ~100% duty cycle → no silence gaps → clean audio.
      if (xStreamBufferBytesAvailable(audioStream) >= SEND_BYTES) {
        size_t received = xStreamBufferReceive(audioStream, sendBuf, SEND_BYTES, pdMS_TO_TICKS(5));
        if (received > 0) {
          webSocket.sendBIN((uint8_t*)sendBuf, received);
          samplesSent += received / sizeof(int16_t);
          packetsSent++;
          // No delay — brownout disabled, drain at production rate (100% duty cycle)
        }
      } else {
        vTaskDelay(pdMS_TO_TICKS(2));
      }
    } else {
      vTaskDelay(pdMS_TO_TICKS(100));
    }

    uint32_t now = millis();
    if (now - lastStatTime > 5000) {
      lastStatTime = now;
      Serial.printf("[STATS] Read:%lu Sent:%lu | Packets:%lu | Buf:%.1fKB | %s\n",
        samplesRead, samplesSent, packetsSent,
        xStreamBufferBytesAvailable(audioStream) / 1024.0,
        webSocket.isConnected() ? "Connected" : "Disconnected");
    }
  }
}

// ============================================================
//  SETUP
// ============================================================
void setup() {
  // Disable brownout detector — prevents reset loops on marginal USB power
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);

  Serial.begin(115200);
  pinMode(RESET_PIN, INPUT_PULLUP);
  delay(1000);
  Serial.println("=== ESP32 BOOTING ===");
  
  // Tạo stream buffer
  audioStream = xStreamBufferCreate(STREAM_BUF_SIZE, 1);
  if (!audioStream) {
    Serial.println("Failed to create stream buffer!");
    while(1) delay(1000);
  }

  // Giữ nút BOOT khi khởi động → xóa WiFi đã lưu
  delay(500);  // cho phép nhấn nút
  if (digitalRead(RESET_PIN) == LOW) {
    Serial.println(">>> BOOT held — erasing WiFi settings...");
    WiFiManager wmReset;
    wmReset.resetSettings();
    delay(500);
    ESP.restart();
  }

  // WiFi — dùng WiFiManager: tự connect WiFi đã lưu,
  // nếu chưa có hoặc fail → tạo AP "ESP32-Audio-Setup" để config qua browser
  WiFiManager wm;
  wm.setConfigPortalTimeout(WIFI_PORTAL_TIMEOUT);
  wm.setConnectTimeout(10);

  Serial.println("Connecting to WiFi...");
  if (!wm.autoConnect(WIFI_AP_NAME)) {
    Serial.println("WiFi failed — restarting in 5s...");
    delay(5000);
    ESP.restart();
  }
  Serial.println("Connected! IP: " + WiFi.localIP().toString());

  // Derive stable device id from MAC (last 6 hex), e.g. B0:CB:D8:CF:39:24 -> esp32-CF3924
  String mac = WiFi.macAddress();      // "B0:CB:D8:CF:39:24"
  mac.replace(":", "");                 // "B0CBD8CF3924"
  String suffix = mac.substring(mac.length() - 6);   // "CF3924"
  deviceId   = "esp32-" + suffix;
  deviceName = "ESP32 " + suffix;
  Serial.println("Device ID: " + deviceId);
  Serial.printf("Server: %s:%d%s\n", SERVER_HOST, SERVER_PORT, wsPath);

  // I2S Mic
  i2s_config_t i2s_config = {
    .mode             = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate      = SAMPLE_RATE,
    .bits_per_sample  = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format   = I2S_CHANNEL_FMT_RIGHT_LEFT,  // read BOTH channels; pick the active one (works for any L/R wiring)
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count    = 4,
    .dma_buf_len      = 128,
    .use_apll         = false
  };
  i2s_pin_config_t pin_config = {
    .bck_io_num   = I2S_SCK,
    .ws_io_num    = I2S_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num  = I2S_SD
  };
  i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL);
  i2s_set_pin(I2S_PORT, &pin_config);
  i2s_start(I2S_PORT);

  // WebSocket — direct to public host, library auto-reconnects every 5s
  webSocket.begin(SERVER_HOST, SERVER_PORT, wsPath);
  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(5000);
  
  Serial.println("Starting tasks...");
  
  // I2S task on Core 0, high priority
  xTaskCreatePinnedToCore(i2sTask, "i2s", 4096, NULL, 10, NULL, 0);
  
  // Network task on Core 1, medium priority  
  xTaskCreatePinnedToCore(networkTask, "net", 8192, NULL, 5, NULL, 1);
  
  Serial.println("=== ESP32 READY ===");
}

// ============================================================
//  LOOP - Monitor + giữ BOOT (GPIO0) 3 giây → xóa WiFi + restart
// ============================================================
void loop() {
  vTaskDelay(pdMS_TO_TICKS(1000));
}
