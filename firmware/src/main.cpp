#include <Arduino.h>
#include <Wire.h>
#include <lvgl.h>
#include <ArduinoJson.h>
#include <esp_heap_caps.h>
#include <Preferences.h>

#include "data.h"
#include "ui.h"
#include "ble.h"
#include "splash.h"
#include "usage_rate.h"
#include "idle.h"
#include "idle_cfg.h"
#include "brightness.h"

#include "hal/board_caps.h"
#include "hal/display_hal.h"
#include "hal/touch_hal.h"
#include "hal/input_hal.h"
#include "hal/power_hal.h"
#include "hal/imu_hal.h"
#include "hal/sound_hal.h"

// One usage slot per provider (see data.h). Slot 0 (Claude) is the only one
// that drives the usage-rate tracker, chime, alerts, and splash picking.
static UsageData slots[PROVIDER_COUNT] = {};

// ---- LVGL draw buffers (partial render mode) ----
// PSRAM-equipped boards (S3) can comfortably hold larger strips. PSRAM-free
// boards (e.g. ESP32-C6) allocate from internal SRAM, so we shrink the strip
// — 480×20 RGB565 = 19 KB × 2 buffers = 38 KB, fits beside everything else.
#ifdef BOARD_HAS_PSRAM
#define BUF_LINES 40
#define LV_BUF_CAPS (MALLOC_CAP_SPIRAM)
#else
#define BUF_LINES 20
#define LV_BUF_CAPS (MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)
#endif
static uint16_t* buf1 = nullptr;
static uint16_t* buf2 = nullptr;

static uint32_t my_tick(void) { return millis(); }

static void my_flush_cb(lv_display_t* disp, const lv_area_t* area, uint8_t* px_map) {
    int32_t w = area->x2 - area->x1 + 1;
    int32_t h = area->y2 - area->y1 + 1;
    display_hal_draw_bitmap(area->x1, area->y1, w, h, (uint16_t*)px_map);
    lv_display_flush_ready(disp);
}

static void rounder_cb(lv_event_t* e) {
    lv_area_t* area = (lv_area_t*)lv_event_get_param(e);
    display_hal_round_area(&area->x1, &area->y1, &area->x2, &area->y2);
}

// Touch policy is driven by IDLE_WAKE_ON_TOUCH:
//   true  → a press edge while asleep wakes the device and the first touch is
//           swallowed (mirrors the button wake-consumption); a press while
//           awake counts as activity.
//   false → touch never counts as activity and is fully swallowed while the
//           panel is dark, so pets/sleeves can't wake it overnight and LVGL
//           can't quietly toggle splash<->usage on a black panel.
static void my_touch_cb(lv_indev_t* indev, lv_indev_data_t* data) {
    uint16_t x, y;
    bool pressed;
    touch_hal_read(&x, &y, &pressed);
    const bool raw_pressed = pressed;

    if (IDLE_WAKE_ON_TOUCH) {
        static bool touch_was = false;
        static bool touch_wake_swallowed = false;
        if (raw_pressed && !touch_was) {
            // Press edge — consume as wake if asleep.
            if (idle_consume_wake_press()) {
                touch_wake_swallowed = true;
                pressed = false;
            }
        } else if (!raw_pressed && touch_was) {
            // Release edge.
            if (touch_wake_swallowed) {
                touch_wake_swallowed = false;
                pressed = false;
            }
        } else if (raw_pressed && touch_wake_swallowed) {
            // Held finger through wake — keep hiding until release.
            pressed = false;
        }
        touch_was = raw_pressed;
    } else if (idle_is_asleep()) {
        pressed = false;
    }

    if (pressed) {
        data->point.x = x;
        data->point.y = y;
        data->state = LV_INDEV_STATE_PRESSED;
    } else {
        data->state = LV_INDEV_STATE_RELEASED;
    }
}

// Map the payload's "p" key to a provider slot. Missing/"claude" → 0 keeps
// p-less upstream daemons working; unknown ids are reported as -1.
static int provider_index(const char* p) {
    if (!p || !p[0]) return PROVIDER_CLAUDE;
    for (int i = 0; i < PROVIDER_COUNT; i++) {
        if (strcmp(p, provider_short(i)) == 0) return i;
    }
    return -1;
}

enum parse_result_t {
    PARSE_OK,       // *out_idx names the slot that was filled
    PARSE_ERROR,    // malformed JSON → nack
    PARSE_IGNORED,  // well-formed but for an unknown provider → ack and skip
};

// Parse a JSON line into the provider slot it names.
static parse_result_t parse_json(const char* json, UsageData* slots_out, int* out_idx) {
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, json);
    if (err) {
        Serial.printf("JSON parse error: %s\n", err.c_str());
        return PARSE_ERROR;
    }

    const char* p = doc["p"] | "";
    int idx = provider_index(p);
    if (idx < 0) {
        Serial.printf("JSON: unknown provider \"%s\" — packet ignored\n", p);
        return PARSE_IGNORED;
    }
    *out_idx = idx;
    UsageData* out = &slots_out[idx];
    out->provider = (uint8_t)idx;

    // Window presence flags (see data.h): a key the daemon omitted means the
    // plan has no such window.
    out->has_session = !doc["s"].isNull();
    out->has_weekly  = !doc["w"].isNull();
    out->session_pct = doc["s"] | 0.0f;
    out->session_reset_mins = doc["sr"] | -1;
    out->weekly_pct = doc["w"] | 0.0f;
    out->weekly_reset_mins = doc["wr"] | -1;
    // Transitional rule: daemons older than H5 send "s":0,"sr":0 for Codex
    // plans that report no 5h window instead of omitting the keys. Treat that
    // exact pair as "no window" on the Codex slot only; drop this once every
    // deployed daemon omits the keys.
    if (idx == PROVIDER_CODEX && out->has_session &&
        out->session_pct == 0.0f && out->session_reset_mins == 0) {
        out->has_session = false;
    }
    // Optional third bar: a model-scoped weekly limit ("f"/"fr"), labelled by
    // "fl" when the daemon sends one, "Fable" otherwise.
    out->has_third = !doc["f"].isNull();
    out->third_pct = doc["f"] | 0.0f;
    out->third_reset_mins = doc["fr"] | -1;
    strlcpy(out->third_label, doc["fl"] | "Fable", sizeof(out->third_label));
    strlcpy(out->status, doc["st"] | "unknown", sizeof(out->status));
    // as<bool>, not `| false`: daemons send 1, and `|` only accepts a JSON bool.
    out->chime = doc["c"].as<bool>();   // absent (old daemon / chime off) → stay silent
    out->beep = doc["b"].as<bool>();
    strlcpy(out->alert_msg, doc["m"] | "", sizeof(out->alert_msg));
    out->alert_clear = doc["x"].as<bool>();
    const char* acct = doc["acct"] | "pro";
    out->enterprise = (strcmp(acct, "ent") == 0);
    out->time_pct = doc["tp"] | 0;
    out->period_days = doc["pd"] | 30;
    strlcpy(out->reset_date, doc["rd"] | "", sizeof(out->reset_date));
    out->clock_epoch = doc["t"] | 0L;
    out->clock_fmt = doc["tf"] | 24;
    out->ok = doc["ok"] | false;
    out->valid = true;
    return PARSE_OK;
}

// Slot-0 (Claude) side effects: usage-rate sampling, the session-reset chime,
// attention beep/alert, and the splash re-pick when the rate group changes.
// Other providers only feed the carousel.
static void handle_claude_packet(const UsageData& usage) {
    int g_before = usage_rate_group();
    bool session_reset = usage_rate_sample(usage.session_pct);
    int g_after = usage_rate_group();
    // 5-hour session limit refilled → chime so the user knows they can
    // use Claude again (no-op on boards without a buzzer). Gated on the
    // daemon's opt-in `chime` config; the `buzz` serial cmd ignores it.
    if (session_reset && usage.chime) {
        Serial.println("session reset detected — chime");
        sound_hal_play_reset();
    }
    // Claude Code hook fired on the host. Not gated on `chime`: the daemon
    // only sets `b` when that hook ran.
    if (usage.beep) {
        Serial.println("attention — chime");
        sound_hal_play_reset();
    }
    if (usage.alert_msg[0]) {
        Serial.println("attention — mascot");
        idle_note_activity();
        ui_show_alert(usage.alert_msg);
    }
    if (usage.alert_clear) ui_hide_alert();
    if (g_after != g_before) {
        Serial.printf("usage rate: group %d -> %d (s=%.2f%%)\n",
            g_before, g_after, usage.session_pct);
        if (splash_is_active()) splash_pick_for_current_rate();
    }
}

// ---- Serial command buffer ----
#define CMD_BUF_SIZE 64
static char cmd_buf[CMD_BUF_SIZE];
static int cmd_pos = 0;

static void send_screenshot() {
#ifndef BOARD_HAS_PSRAM
    // A full RGB565 framebuffer doesn't fit in internal SRAM on PSRAM-free
    // boards (e.g. 480×480×2 = 460 KB). Capture is unsupported there.
    Serial.println("SCREENSHOT_UNSUPPORTED");
    return;
#else
    const uint32_t w = board_caps().width;
    const uint32_t h = board_caps().height;
    const uint32_t row_bytes = w * 2;
    const uint32_t buf_size = row_bytes * h;
    uint8_t* sbuf = (uint8_t*)heap_caps_malloc(buf_size, MALLOC_CAP_SPIRAM);
    if (!sbuf) {
        Serial.println("SCREENSHOT_ERR");
        return;
    }

    lv_draw_buf_t draw_buf;
    lv_draw_buf_init(&draw_buf, w, h, LV_COLOR_FORMAT_RGB565, row_bytes, sbuf, buf_size);

    lv_result_t res = lv_snapshot_take_to_draw_buf(lv_screen_active(), LV_COLOR_FORMAT_RGB565, &draw_buf);
    if (res != LV_RESULT_OK) {
        heap_caps_free(sbuf);
        Serial.println("SCREENSHOT_ERR");
        return;
    }

    Serial.printf("SCREENSHOT_START %lu %lu %lu\n",
        (unsigned long)w, (unsigned long)h, (unsigned long)buf_size);
    Serial.flush();
    Serial.write(sbuf, buf_size);
    Serial.flush();
    Serial.println();
    Serial.println("SCREENSHOT_END");
    heap_caps_free(sbuf);
#endif
}

// `name` prints the stored BLE device name; `name <text>` validates, persists
// it to NVS and reboots so the new name is advertised (NimBLE takes the GAP
// name at init, and a restart also drops any client holding the old name).
static void print_device_name() {
    char buf[BLE_DEVICE_NAME_MAX_LEN + 1] = {0};
    Preferences prefs;
    prefs.begin(BLE_NAME_NVS_NAMESPACE, true);
    size_t n = prefs.getString(BLE_NAME_NVS_KEY, buf, sizeof(buf));
    prefs.end();
    Serial.printf("BLE: name=%s\n", (n > 0 && buf[0]) ? buf : BLE_DEFAULT_DEVICE_NAME);
}

static bool device_name_valid(const char* s) {
    size_t len = strlen(s);
    if (len == 0 || len > BLE_DEVICE_NAME_MAX_LEN) return false;
    for (size_t i = 0; i < len; i++) {
        if (s[i] < 0x20 || s[i] > 0x7E) return false;  // printable ASCII only
        if (s[i] == '#') return false;                  // comment marker in the host config
    }
    return true;
}

static void set_device_name(char* text) {
    while (*text == ' ') text++;                       // trim leading spaces
    size_t len = strlen(text);
    while (len > 0 && text[len - 1] == ' ') text[--len] = '\0';  // trim trailing
    if (!device_name_valid(text)) {
        Serial.printf("BLE: name rejected (need 1-%d printable ASCII chars, no '#')\n",
                      BLE_DEVICE_NAME_MAX_LEN);
        return;
    }
    Preferences prefs;
    prefs.begin(BLE_NAME_NVS_NAMESPACE, false);
    prefs.putString(BLE_NAME_NVS_KEY, text);
    prefs.end();
    Serial.printf("BLE: name set to \"%s\", restarting\n", text);
    Serial.flush();
    delay(100);
    ESP.restart();
}

// Hands-free QA: `screen usage|splash [claude|codex|kimi|grok]` (a provider name
// opens mascot mode for it; bare `splash` is the default Claude splash),
// `parade on|off`, `next` (page the carousel like a tap), `slot <0-4>` (show
// that provider slot if fresh), `splash next|prev` (step the splash like a
// tap / horizontal swipe), `swipe up|down|left|right` (the touch gesture
// handler). Reply `ok` / `err <why>`.
static void qa_reply(bool ok, const char* why) {
    if (ok) Serial.println("ok");
    else    Serial.printf("err %s\n", why);
}

static void cmd_screen(const char* arg) {
    if (strcmp(arg, "usage") == 0)       { ui_show_screen(SCREEN_USAGE);  qa_reply(true, NULL); }
    else if (strcmp(arg, "splash") == 0) { ui_show_mascot(-1);            qa_reply(true, NULL); }
    else if (strncmp(arg, "splash ", 7) == 0) {
        const char* prov = arg + 7;
        while (*prov == ' ') prov++;
        for (int i = 0; i < PROVIDER_COUNT; i++) {
            if (strcmp(prov, provider_short(i)) == 0) {
                ui_show_mascot(i);
                qa_reply(true, NULL);
                return;
            }
        }
        qa_reply(false, "unknown provider (claude|codex|kimi|grok)");
    }
    else                                   qa_reply(false, "unknown screen (usage|splash [provider])");
}

static void cmd_parade(const char* arg) {
    if (strcmp(arg, "on") == 0)       qa_reply(ui_parade_start(), "no fresh slot");
    else if (strcmp(arg, "off") == 0) { ui_show_screen(SCREEN_USAGE); qa_reply(true, NULL); }
    else                              qa_reply(false, "parade on|off");
}

static void cmd_slot(const char* arg) {
    char* end = NULL;
    long idx = strtol(arg, &end, 10);
    if (end == arg || *end != '\0' || idx < 0 || idx >= UI_VIEW_COUNT) {
        qa_reply(false, "slot must be 0-4");
        return;
    }
    qa_reply(ui_show_slot((int)idx), "slot not fresh");
}

static void cmd_splash(const char* arg) {
    if (ui_get_current_screen() != SCREEN_SPLASH) { qa_reply(false, "splash not on screen"); return; }
    if (strcmp(arg, "next") == 0)      { splash_next(); qa_reply(true, NULL); }
    else if (strcmp(arg, "prev") == 0) { splash_prev(); qa_reply(true, NULL); }
    else                               qa_reply(false, "splash next|prev");
}

static void cmd_swipe(const char* arg) {
    lv_dir_t dir;
    if (strcmp(arg, "up") == 0)         dir = LV_DIR_TOP;
    else if (strcmp(arg, "down") == 0)  dir = LV_DIR_BOTTOM;
    else if (strcmp(arg, "left") == 0)  dir = LV_DIR_LEFT;
    else if (strcmp(arg, "right") == 0) dir = LV_DIR_RIGHT;
    else { qa_reply(false, "swipe up|down|left|right"); return; }
    qa_reply(ui_handle_swipe(dir), "nothing to do (alert on screen or single provider)");
}

static void check_serial_cmd() {
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            cmd_buf[cmd_pos] = '\0';
            if (strcmp(cmd_buf, "screenshot") == 0) send_screenshot();
            else if (strcmp(cmd_buf, "buzz") == 0)  sound_hal_play_reset();
            else if (strcmp(cmd_buf, "name") == 0)  print_device_name();
            else if (strncmp(cmd_buf, "name ", 5) == 0) set_device_name(cmd_buf + 5);
            else if (strncmp(cmd_buf, "screen ", 7) == 0) cmd_screen(cmd_buf + 7);
            else if (strcmp(cmd_buf, "next") == 0) qa_reply(ui_carousel_next(), "need usage view with 2+ fresh slots");
            else if (strncmp(cmd_buf, "slot ", 5) == 0) cmd_slot(cmd_buf + 5);
            else if (strncmp(cmd_buf, "parade ", 7) == 0) cmd_parade(cmd_buf + 7);
            else if (strncmp(cmd_buf, "splash ", 7) == 0) cmd_splash(cmd_buf + 7);
            else if (strncmp(cmd_buf, "swipe ", 6) == 0)  cmd_swipe(cmd_buf + 6);
            cmd_pos = 0;
        } else if (cmd_pos < CMD_BUF_SIZE - 1) {
            cmd_buf[cmd_pos++] = c;
        }
    }
}

// Each board provides this. Must bring up the shared I2C bus (Wire.begin
// with the board's SDA/SCL pins) and any board-private hardware that has
// to settle before display/touch (e.g. an IO expander gating the LCD
// reset line). Called exactly once at the start of setup().
extern "C" void board_init(void);

void setup() {
    Serial.begin(115200);
    delay(300);
    Serial.println("{\"ready\":true}");

    board_init();

    display_hal_init();
    display_hal_begin();
    idle_init();        // takes over panel brightness and starts the idle timer
    brightness_init();  // load the user's saved brightness level and apply via idle

    power_hal_init();
    imu_hal_init();
    sound_hal_init();
    touch_hal_init();

    // ---- LVGL ----
    const int W = board_caps().width;
    const int H = board_caps().height;

    lv_init();
    lv_tick_set_cb(my_tick);

    buf1 = (uint16_t*)heap_caps_malloc(W * BUF_LINES * 2, LV_BUF_CAPS);
    buf2 = (uint16_t*)heap_caps_malloc(W * BUF_LINES * 2, LV_BUF_CAPS);

    lv_display_t* disp = lv_display_create(W, H);
    lv_display_set_color_format(disp, LV_COLOR_FORMAT_RGB565);
    lv_display_set_flush_cb(disp, my_flush_cb);
    lv_display_set_buffers(disp, buf1, buf2, W * BUF_LINES * 2,
                           LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_add_event_cb(disp, rounder_cb, LV_EVENT_INVALIDATE_AREA, NULL);

    lv_indev_t* indev = lv_indev_create();
    lv_indev_set_type(indev, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(indev, my_touch_cb);

    ble_init();
    input_hal_init();

    ui_init();
    ui_update_ble_status(ble_get_state(), ble_get_device_name(), ble_get_mac_address());
    ui_update_battery(power_hal_battery_pct(), power_hal_is_charging(), power_hal_is_vbus_in());
    ui_show_screen(SCREEN_SPLASH);

    Serial.printf("Dashboard ready (%s, %dx%d), waiting for data on BLE...\n",
        board_caps().name, W, H);
}

static ble_state_t last_ble_state = BLE_STATE_INIT;

// Hold-to-pair gesture: hold the PWR button ~3s, then RELEASE → clear all BLE
// bonds and re-advertise. Clearing on *release* (not while held) is deliberate:
// holding to power the device OFF (AXP hardware shutdown at 8s) must not wipe
// the bond — a power-off hold never releases before shutdown. To stop a
// "chicken-out" release just before 8s from pairing, the gesture disarms at 6s.
//
//   ~1.5s long-press edge → PENDING
//   3.0s (+1500)          → ARMED   (release from here clears bonds)
//   6.0s (+4500)          → DISARMED (no clear; AXP powers off at 8s)
#define PAIR_ARM_AFTER_LONG_MS    1500   // 3.0s total
#define PAIR_DISARM_AFTER_LONG_MS 4500   // 6.0s total
enum pair_state_t { PAIR_IDLE, PAIR_PENDING, PAIR_ARMED };
static pair_state_t pair_state        = PAIR_IDLE;
static uint32_t     pair_long_seen_ms = 0;

static void pair_tick(void) {
    if (pair_state == PAIR_IDLE && power_hal_pwr_long_pressed()) {
        pair_state = PAIR_PENDING;
        pair_long_seen_ms = millis();
        (void)power_hal_pwr_released();  // drain any stale release edge
        Serial.println("PWR long-press: hold to ~3s then release to pair");
        return;
    }
    if (pair_state == PAIR_IDLE) return;

    if (power_hal_pwr_released()) {
        if (pair_state == PAIR_ARMED) {
            Serial.println("Pair: released in window — clearing bonds, advertising");
            ble_clear_bonds();
        } else {
            Serial.println("Pair: released too early — cancelled");
        }
        pair_state = PAIR_IDLE;
        return;
    }

    uint32_t held = millis() - pair_long_seen_ms;
    if (pair_state == PAIR_PENDING && held >= PAIR_ARM_AFTER_LONG_MS) {
        pair_state = PAIR_ARMED;
        Serial.println("Pair: armed — release to pair");
    } else if (pair_state == PAIR_ARMED && held >= PAIR_DISARM_AFTER_LONG_MS) {
        pair_state = PAIR_IDLE;  // power-off territory; don't pair
        Serial.println("Pair: disarmed (holding toward power-off)");
    }
}

void loop() {
    idle_tick();
    lv_timer_handler();
    ui_tick_anim();
    ble_tick();
    power_hal_tick();
    imu_hal_tick();
    sound_hal_tick();
    splash_tick();
    splash_mascot_tick();
    // Rotation transition (blank + ramp) would fight the idle fade — skip
    // ticks while the panel is dark. A rotation that happens during sleep
    // is detected by the next tick after wake and ramped in then.
    if (!idle_is_asleep()) display_hal_tick();

    // ---- Physical buttons ----
    //   PRIMARY   → HID Space  (Claude Code voice-mode PTT)
    //   SECONDARY → HID Shift+Tab  (mode toggle; only if the board has one)
    //   PWR       → on splash: cycle animations; on usage: cycle brightness;
    //               hold ~3s + release: pairing mode
    // First press from sleep is consumed as a wake-only event by
    // idle_consume_wake_press(); the normal action fires from the second
    // press. Activity bookkeeping happens inside idle_consume_wake_press
    // so no separate idle_note_activity() call is needed here.
    {
        static bool primary_was = false;
        static bool primary_wake_swallowed = false;
        bool primary_now = input_hal_is_held(INPUT_BTN_PRIMARY);
        if (primary_now != primary_was) {
            if (primary_now) {
                if (idle_consume_wake_press()) primary_wake_swallowed = true;
                else                            ble_keyboard_press(0x2C, 0);  // HID Space, no mods
            } else {
                if (primary_wake_swallowed) primary_wake_swallowed = false;
                else                        ble_keyboard_release();
            }
            primary_was = primary_now;
        }

        if (board_caps().button_count >= 2) {
            static bool secondary_was = false;
            static bool secondary_wake_swallowed = false;
            bool secondary_now = input_hal_is_held(INPUT_BTN_SECONDARY);
            if (secondary_now != secondary_was) {
                if (secondary_now) {
                    if (idle_consume_wake_press()) secondary_wake_swallowed = true;
                    else                            ble_keyboard_press(0x2B, 0x02);  // HID Tab + LEFT_SHIFT
                } else {
                    if (secondary_wake_swallowed) secondary_wake_swallowed = false;
                    else                          ble_keyboard_release();
                }
                secondary_was = secondary_now;
            }
        }

        if (power_hal_pwr_pressed()) {
            if (!idle_consume_wake_press()) {
                // On splash: cycle animations. On the usage view: cycle
                // screen brightness (single non-splash view, no more screens).
                if (ui_get_current_screen() == SCREEN_SPLASH) splash_next();
                else                                          brightness_cycle();
            }
        }

        pair_tick();
    }

    ble_state_t bs = ble_get_state();
    if (bs != last_ble_state) {
        last_ble_state = bs;
        ui_update_ble_status(bs, ble_get_device_name(), ble_get_mac_address());
    }

    static int  last_pct      = -2;
    static bool last_charging = false;
    static bool last_vbus     = false;
    int  pct      = power_hal_battery_pct();
    bool charging = power_hal_is_charging();
    bool vbus     = power_hal_is_vbus_in();
    if (pct != last_pct || charging != last_charging || vbus != last_vbus) {
        if (pct != last_pct) ble_set_battery_level(pct);
        last_pct = pct;
        last_charging = charging;
        last_vbus = vbus;
        ui_update_battery(pct, charging, vbus);
    }

    check_serial_cmd();

    // Drain every queued BLE packet this pass: the daemon writes one payload
    // per provider back-to-back, and each one lands in its own slot.
    static char packet[BLE_RX_ITEM_SIZE];
    while (ble_next_packet(packet, sizeof(packet))) {
        int idx = PROVIDER_CLAUDE;
        parse_result_t r = parse_json(packet, slots, &idx);
        if (r == PARSE_ERROR) {
            ble_send_nack();
            continue;
        }
        if (r == PARSE_IGNORED) {
            ble_send_ack();   // acknowledged so the daemon does not retry it
            continue;
        }
        const UsageData& usage = slots[idx];
        Serial.printf("BLE: packet p=%s ok=%d s=%.1f%%%s\n", provider_short(idx),
            usage.ok ? 1 : 0, usage.session_pct, usage.has_third ? " +third" : "");
        if (idx == PROVIDER_CLAUDE) handle_claude_packet(usage);
        ui_update_slot(idx, &usage);
        ble_send_ack();
    }

    delay(5);
}
