#include "apps.h"
#include <Arduino.h>
#include <Preferences.h>
#include <string.h>

static bool enabled[APP_COUNT] = { true, true };
static bool side_hid = false;

static const char* const APP_SHORT[APP_COUNT] = { "meter", "focus" };
static const char* const APP_NAME[APP_COUNT]  = { "Meter", "Focus" };

const char* apps_name(app_id_t app)  { return (app >= 0 && app < APP_COUNT) ? APP_NAME[app]  : ""; }
const char* apps_short(app_id_t app) { return (app >= 0 && app < APP_COUNT) ? APP_SHORT[app] : ""; }

bool apps_enabled(app_id_t app) {
    return app >= 0 && app < APP_COUNT && enabled[app];
}

int apps_enabled_count(void) {
    int n = 0;
    for (int i = 0; i < APP_COUNT; i++) if (enabled[i]) n++;
    return n;
}

// Parse into `out` without touching the stored set. "meter" is always on.
static void parse_list(const char* csv, bool out[APP_COUNT]) {
    for (int i = 0; i < APP_COUNT; i++) out[i] = false;
    out[APP_METER] = true;
    if (!csv) return;
    const char* p = csv;
    while (*p) {
        while (*p == ' ' || *p == ',') p++;
        const char* start = p;
        while (*p && *p != ',') p++;
        const char* end = p;
        while (end > start && end[-1] == ' ') end--;
        size_t n = (size_t)(end - start);
        for (int i = 0; i < APP_COUNT && n > 0; i++) {
            if (strlen(APP_SHORT[i]) == n && strncmp(start, APP_SHORT[i], n) == 0) out[i] = true;
        }
    }
}

void apps_list_string(char* buf, size_t len) {
    if (!buf || len == 0) return;
    buf[0] = '\0';
    for (int i = 0; i < APP_COUNT; i++) {
        if (!enabled[i]) continue;
        if (buf[0]) strlcat(buf, ",", len);
        strlcat(buf, APP_SHORT[i], len);
    }
}

static void store_list(void) {
    char buf[32];
    apps_list_string(buf, sizeof(buf));
    Preferences prefs;
    prefs.begin(APPS_NVS_NAMESPACE, false);
    prefs.putString(APPS_NVS_KEY_APPS, buf);
    prefs.end();
}

bool apps_set_list(const char* csv) {
    bool next[APP_COUNT];
    parse_list(csv, next);
    bool changed = false;
    for (int i = 0; i < APP_COUNT; i++) if (next[i] != enabled[i]) changed = true;
    memcpy(enabled, next, sizeof(enabled));
    store_list();
    return changed;
}

bool apps_side_button_hid(void) { return side_hid; }

const char* apps_side_button_mode(void) { return side_hid ? "hid" : "apps"; }

bool apps_set_side_button(const char* mode) {
    if (!mode) return false;
    if (strcmp(mode, "apps") == 0)     side_hid = false;
    else if (strcmp(mode, "hid") == 0) side_hid = true;
    else return false;
    Preferences prefs;
    prefs.begin(APPS_NVS_NAMESPACE, false);
    prefs.putString(APPS_NVS_KEY_SIDE, mode);
    prefs.end();
    return true;
}

void apps_init(void) {
    char buf[32] = {0};
    Preferences prefs;
    prefs.begin(APPS_NVS_NAMESPACE, true);
    size_t n = prefs.getString(APPS_NVS_KEY_APPS, buf, sizeof(buf));
    if (n > 0 && buf[0]) parse_list(buf, enabled);   // absent key → every app on
    char mode[8] = {0};
    n = prefs.getString(APPS_NVS_KEY_SIDE, mode, sizeof(mode));
    side_hid = (n > 0 && strcmp(mode, "hid") == 0);
    prefs.end();
    char list[32];
    apps_list_string(list, sizeof(list));
    Serial.printf("apps: enabled=%s side_btn=%s\n", list, apps_side_button_mode());
}

void apps_focus_counter_load(uint8_t* blocks, uint32_t* day) {
    Preferences prefs;
    prefs.begin(APPS_NVS_NAMESPACE, true);
    *blocks = prefs.getUChar(APPS_NVS_KEY_FXCNT, 0);
    *day    = prefs.getUInt(APPS_NVS_KEY_FXDAY, 0);
    prefs.end();
}

void apps_focus_counter_store(uint8_t blocks, uint32_t day) {
    Preferences prefs;
    prefs.begin(APPS_NVS_NAMESPACE, false);
    prefs.putUChar(APPS_NVS_KEY_FXCNT, blocks);
    prefs.putUInt(APPS_NVS_KEY_FXDAY, day);
    prefs.end();
}
