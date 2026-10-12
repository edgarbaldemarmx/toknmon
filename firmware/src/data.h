#pragma once
#include <Arduino.h>

// Provider slots. The daemon tags each payload with "p" (missing ⇒ claude);
// the firmware keeps one UsageData per provider and shows them as a carousel.
#define PROVIDER_COUNT 3
enum provider_t {
    PROVIDER_CLAUDE = 0,
    PROVIDER_CODEX  = 1,
    PROVIDER_KIMI   = 2,
};

// Display name ("Claude") and wire id ("claude", the value of the payload's
// "p" key). Out-of-range indices fall back to the Claude strings.
static inline const char* provider_name(int i) {
    switch (i) {
    case PROVIDER_CODEX: return "Codex";
    case PROVIDER_KIMI:  return "Kimi";
    default:             return "Claude";
    }
}
static inline const char* provider_short(int i) {
    switch (i) {
    case PROVIDER_CODEX: return "codex";
    case PROVIDER_KIMI:  return "kimi";
    default:             return "claude";
    }
}

struct UsageData {
    uint8_t provider;        // PROVIDER_* slot this payload belongs to
    // Window presence: the payload carried the "s" / "w" key. A missing key
    // means the plan has no such window (e.g. weekly-only Codex plans), so
    // the UI omits that bar instead of drawing an empty one. Claude payloads
    // always carry both.
    bool has_session;
    bool has_weekly;
    float session_pct;       // utilization 0-100 (5h window Pro/Max; spending % Enterprise)
    int session_reset_mins;  // minutes until reset
    float weekly_pct;        // 7-day utilization (Pro/Max only; 0 for Enterprise)
    int weekly_reset_mins;   // minutes until weekly reset (Pro/Max only)
    bool has_third;          // payload carried "f": a third, model-scoped weekly bar
    float third_pct;         // scoped weekly utilization ("f")
    int third_reset_mins;    // minutes until the scoped weekly reset ("fr")
    char third_label[12];    // pill text for the third bar ("fl"; defaults to "Fable")
    char status[16];         // "allowed", "limited", etc.
    bool chime;              // play the session-reset chime; false unless daemon opts in
    bool beep;               // Claude needs attention: play the chime once for this packet
    char alert_msg[128];     // attention message for the status line; empty = no alert
    bool alert_clear;        // the session moved on: end the alert
    bool enterprise;         // true = Enterprise spending-limit account
    int time_pct;            // 0-100: fraction of billing period elapsed (Enterprise)
    int period_days;         // total billing period length in days (Enterprise)
    char reset_date[12];     // formatted reset date e.g. "Jul 1" (Enterprise)
    long clock_epoch;        // local wall-clock epoch (s) from daemon; 0 = not provided
    int  clock_fmt;          // 12 or 24 (hour format from daemon); defaults to 24
    bool ok;                 // data parse succeeded
    bool valid;              // false until first successful parse
};
