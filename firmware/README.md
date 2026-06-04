# ESP32 Mic Firmware — Hướng dẫn từ đầu đến cuối

Firmware chung cho **mọi** ESP32 mic. Flash y hệt cho con nào cũng được — mỗi con tự sinh ID riêng từ MAC chip, tự kết nối lên server. Không cần sửa code, không cần config riêng từng con.

> Phần cứng (ESP32 + mic INMP441, đấu dây) đã giống nhau sẵn. Bạn chỉ cần **upload code + nhập WiFi 1 lần**.

---

## 0. Cần chuẩn bị

- 1 board **ESP32** đã gắn mic **INMP441** (đấu dây như mục [Sơ đồ chân](#sơ-đồ-chân-i2s) bên dưới — vốn đã giống nhau).
- 1 cáp **USB → máy tính** (cáp truyền dữ liệu, không phải cáp chỉ sạc).
- Máy tính cài **PlatformIO** (xem bước 1).
- ESP32 sẽ cần **một WiFi có internet** (vì server ở trên cloud — không cần chung mạng với ai).

---

## 1. Cài PlatformIO (1 lần duy nhất)

**Cách A — VS Code (dễ nhất):**
1. Cài [VS Code](https://code.visualstudio.com/).
2. Mở VS Code → Extensions (Ctrl+Shift+X) → tìm **"PlatformIO IDE"** → Install.

**Cách B — CLI:**
```bash
pip install platformio
```
Kiểm tra: `pio --version`.

---

## 2. Lấy code firmware

Code nằm trong repo này, thư mục `firmware/`. Mở **đúng thư mục `firmware/`** trong PlatformIO (không phải thư mục gốc repo).

```bash
cd firmware
```

Lần đầu PlatformIO sẽ tự tải toolchain ESP32 + 2 thư viện (`WebSockets`, `WiFiManager`) — chờ vài phút.

---

## 3. Cắm ESP32 + Upload code

1. Cắm ESP32 vào máy bằng cáp USB.
2. Chạy:
   ```bash
   pio run -t upload
   ```
   (Trong VS Code: bấm nút **→ Upload** ở thanh dưới.)

PlatformIO **tự dò cổng** — không cần chỉnh gì. Khi thấy `[SUCCESS]` và `Hard resetting...` là xong.

> Nếu báo không tìm thấy cổng: rút cắm lại cáp, hoặc cài driver USB-serial (CP210x / CH340 tùy board).

---

## 4. Nhập WiFi lần đầu (qua điện thoại/máy tính)

Sau khi flash, ESP32 **chưa biết WiFi** nên nó phát một WiFi cấu hình:

1. Trên điện thoại → vào WiFi → kết nối tới **`ESP32-Audio-Setup`** (mở, không mật khẩu).
2. Cửa sổ cấu hình tự bật (nếu không, mở trình duyệt vào `192.168.4.1`).
3. Chọn WiFi nhà/văn phòng (phải có internet) → nhập mật khẩu → **Save**.
4. ESP32 tự khởi động lại và kết nối.

> WiFi chỉ cần nhập **1 lần** — nó nhớ luôn. Muốn đổi WiFi sau này: **giữ nút `BOOT`** trên board ~3 giây lúc khởi động để xóa WiFi cũ, rồi làm lại bước 4.

---

## 5. Kiểm tra đã kết nối

**Cách A — xem Serial (chắc chắn nhất):**
```bash
pio device monitor
```
Phải thấy:
```
=== ESP32 BOOTING ===
Connected! IP: 192.168.x.x
Device ID: esp32-XXXXXX
Server: 49.213.89.44:2108/ws
WebSocket connected
Sent hello: {"type":"hello","device_id":"esp32-XXXXXX",...}
[STATS] ... | Connected
```
`WebSocket connected` + `Connected` = đã lên server thành công.

**Cách B — xem trên web:**
Mở `http://49.213.89.44:2108` → đăng nhập → sidebar **Devices**. Mic sẽ hiện thành một dòng `esp32-XXXXXX` với chấm xanh "online".

---

## 6. Cùng nói chung một phiên (share / join)

1. **Người chủ**: vào web → tạo session → bấm **Start** → bấm **Share** để lấy **mã 8 ký tự** → gửi mã cho người kia.
2. **Người kia**: đăng nhập web → **Sessions → Join** → nhập mã → thấy phiên chung.
3. Khi session đang **Start**, **mọi mic đang online** đều đổ tiếng nói vào phiên đó — transcript hiện theo từng `device_id`. Không cần thao tác gì trên ESP32.

> Hiện tại hệ thống chạy **1 phiên active tại một thời điểm**. Nhiều phòng độc lập song song là tính năng sẽ làm sau.

---

## Thông tin kỹ thuật

- **Server (hardcode trong firmware):** `49.213.89.44:2108`, WebSocket path `/ws`. Đổi server thì sửa `SERVER_HOST` / `SERVER_PORT` đầu file `src/main.cpp` rồi flash lại.
- **device_id:** sinh từ 6 hex cuối của MAC chip, dạng `esp32-XXXXXX` — duy nhất mỗi con, không cần cấu hình.
- **Audio:** 16 kHz, PCM 16-bit mono, gửi qua WebSocket; server khử nhiễu + chuyển thành chữ bằng model Zipformer trên GPU.
- **Tự kết nối lại:** mất mạng/server tắt → tự thử lại mỗi 5s (không treo).

### Sơ đồ chân I2S
Mic **INMP441** → ESP32:

| INMP441 | ESP32 |
|---------|-------|
| VDD     | 3V3   |
| GND     | GND   |
| L/R     | GND   |
| WS      | GPIO 15 |
| SCK     | GPIO 14 |
| SD      | GPIO 32 |

---

## Sự cố thường gặp

| Triệu chứng | Cách xử lý |
|-------------|-----------|
| Không thấy WiFi `ESP32-Audio-Setup` | ESP32 đã nhớ WiFi cũ → giữ nút **BOOT** 3s lúc khởi động để xóa, rồi làm lại bước 4 |
| Serial in ký tự rác | Đúng baud chưa? Phải là **115200** (`pio device monitor` tự dùng đúng) |
| `WebSocket disconnected` lặp lại | WiFi không có internet, hoặc server `49.213.89.44:2108` chưa chạy. Kiểm tra `http://49.213.89.44:2108/api/health` |
| Upload báo lỗi cổng | Rút/cắm lại cáp; cài driver CP210x/CH340; thử cáp khác (cáp chỉ sạc sẽ không upload được) |
| Mic không hiện trong Devices | Xem Serial xem có `WebSocket connected` không; nếu có mà web không thấy → bấm **Scan** lại |
