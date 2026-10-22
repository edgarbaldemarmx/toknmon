#pragma once
// In-memory stand-in for ESP32 NVS Preferences (used by brightness.cpp,
// ble.cpp's device name, main.cpp's `name` serial command, the picked usage
// view and the app-center / Focus settings in apps.cpp).
// State lasts for the process lifetime only — the sim boots with defaults.
#include <stdint.h>
#include <stddef.h>
#include <string.h>

class Preferences {
public:
    bool begin(const char* name, bool read_only = false) {
        (void)name; (void)read_only;
        return true;
    }
    void end(void) {}
    uint8_t  getUChar(const char* key, uint8_t def = 0);
    size_t   putUChar(const char* key, uint8_t value);
    uint32_t getUInt(const char* key, uint32_t def = 0);
    size_t   putUInt(const char* key, uint32_t value);

    // C-buffer string API (same signatures as the ESP32 core). One shared
    // in-memory slot table, defined inline so the shim stays header-only.
    size_t getString(const char* key, char* value, size_t maxLen) {
        for (auto& s : str_store())
            if (s.used && strcmp(s.key, key) == 0) {
                strncpy(value, s.val, maxLen - 1);
                value[maxLen - 1] = '\0';
                return strlen(value);
            }
        return 0;
    }
    size_t putString(const char* key, const char* value) {
        for (auto& s : str_store())
            if (s.used && strcmp(s.key, key) == 0) {
                strncpy(s.val, value, sizeof(s.val) - 1);
                s.val[sizeof(s.val) - 1] = '\0';
                return strlen(s.val);
            }
        for (auto& s : str_store())
            if (!s.used) {
                s.used = true;
                strncpy(s.key, key, sizeof(s.key) - 1);
                s.key[sizeof(s.key) - 1] = '\0';
                strncpy(s.val, value, sizeof(s.val) - 1);
                s.val[sizeof(s.val) - 1] = '\0';
                return strlen(s.val);
            }
        return 0;
    }

private:
    struct StrSlot { char key[16]; char val[64]; bool used; };
    static StrSlot (&str_store())[8] {
        static StrSlot store[8] = {};
        return store;
    }
};
