#pragma once
#include <stdint.h>
#include <stddef.h>

// User-configurable BLE device name, persisted in NVS. Shared between ble.cpp
// (reads it at init, advertises it) and main.cpp (the `name` serial command
// writes it). Max 18 bytes: the primary advertising packet is 31 bytes and
// flags + appearance + HID UUID already take 11, name header takes 2.
#define BLE_NAME_NVS_NAMESPACE   "clawdmeter"
#define BLE_NAME_NVS_KEY         "dev_name"
#define BLE_DEFAULT_DEVICE_NAME  "TokenMon"
#define BLE_DEVICE_NAME_MAX_LEN  18

enum ble_state_t {
    BLE_STATE_INIT,
    BLE_STATE_ADVERTISING,
    BLE_STATE_CONNECTED,
    BLE_STATE_DISCONNECTED,
};

void ble_init(void);
void ble_tick(void);
ble_state_t ble_get_state(void);
const char* ble_get_device_name(void);
const char* ble_get_mac_address(void);
void ble_clear_bonds(void);
bool ble_has_bonds(void);
// RX queue. The daemon writes one payload per provider back-to-back (~350 ms
// apart), so received packets are queued instead of overwriting one buffer.
// ble_next_packet() copies the oldest pending packet into `out` (NUL
// terminated, truncated to cap) and returns false when the queue is empty;
// callers drain it in a loop once per main-loop iteration.
#define BLE_RX_ITEM_SIZE   512
#define BLE_RX_QUEUE_DEPTH 4
bool ble_has_data(void);
bool ble_next_packet(char* out, size_t cap);
void ble_send_ack(void);
void ble_send_nack(void);
void ble_request_refresh(void);

void ble_set_battery_level(int pct);

// BLE HID keyboard
void ble_keyboard_press(uint8_t key, uint8_t modifier);
void ble_keyboard_release(void);
