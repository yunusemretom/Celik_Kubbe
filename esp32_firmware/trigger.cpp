#include "trigger.h"
#include "uart_protocol.h"

// GEREKEN KUTUPHANE: Arduino IDE > Kutuphane Yoneticisi > "ESP32Servo"
// (Kevin Harrington). Eski joystick_motor.ino da bunu kullaniyordu.
#include <ESP32Servo.h>

static Servo tetikServo;

enum TriggerState {
    TRG_IDLE,       // bosta, hazir
    TRG_PULLING,    // ip gergin, tetik cekili
    TRG_RELEASING   // geri donuyor, henuz hazir degil
};

static TriggerState state = TRG_IDLE;
static unsigned long stateStartMillis = 0;
static uint32_t pullCount = 0;
static bool initialized = false;


static void writeAngle(int deg) {
    if (!initialized) return;
    tetikServo.write(deg);
}


void trigger_init() {
    tetikServo.setPeriodHertz(TRIGGER_SERVO_PWM_HZ);
    tetikServo.attach(TRIGGER_SERVO_PIN, TRIGGER_SERVO_MIN_US, TRIGGER_SERVO_MAX_US);
    initialized = true;

    // attach'tan HEMEN sonra bos konum yaz - aksi halde servo acilista
    // tetigi cekili tutabilir.
    writeAngle(TRIGGER_REST_DEG);

    state = TRG_IDLE;
    stateStartMillis = millis();
    pullCount = 0;

    LOG_INFO("TETIK hazir pin=%d bos=%d cekili=%d",
              TRIGGER_SERVO_PIN, TRIGGER_REST_DEG, TRIGGER_PULL_DEG);
}


bool trigger_pull() {
    if (!initialized) return false;
    if (state != TRG_IDLE) return false;   // mesgul - cift sayim olmasin

    writeAngle(TRIGGER_PULL_DEG);
    state = TRG_PULLING;
    stateStartMillis = millis();
    return true;
}


void trigger_update() {
    if (!initialized) return;

    switch (state) {
        case TRG_IDLE:
            break;

        case TRG_PULLING:
            if (millis() - stateStartMillis >= TRIGGER_PULL_MS) {
                writeAngle(TRIGGER_REST_DEG);
                state = TRG_RELEASING;
                stateStartMillis = millis();
            }
            break;

        case TRG_RELEASING:
            if (millis() - stateStartMillis >= TRIGGER_RELEASE_MS) {
                state = TRG_IDLE;
                pullCount++;
            }
            break;
    }
}


bool trigger_isBusy() {
    return state != TRG_IDLE;
}


void trigger_forceRelease() {
    if (!initialized) return;
    writeAngle(TRIGGER_REST_DEG);
    state = TRG_IDLE;
    stateStartMillis = millis();
}


uint32_t trigger_getPullCount() {
    return pullCount;
}