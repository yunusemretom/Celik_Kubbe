#ifndef SAFETY_H
#define SAFETY_H

#include <Arduino.h>
#include "config.h"
#include "uart_protocol.h"   // FLAG_*, PROTO_ST_*, FIRE_RESULT_*, ERR_* sabitleri icin


// Sistemdeki TEK YETKİLİ güvenlik katmanı.
//
// DEGISIKLIK: solenoid valf (MOSFET4) KALDIRILDI. Ateşleme artık ip ile
// tüfek tetiğine bağlı servo ile yapılıyor (bkz. trigger.cpp).
// ATEŞLEME KAPISI (ARM / E-Stop / mühimmat / yasak bölge / menzil / kilit)
// AYNEN KORUNDU - değişen sadece en alttaki aktüatör çağrısıdır.

#ifndef MAX_AMMO_COUNT
#error "config.h icinde MAX_AMMO_COUNT eksik!"
#endif
#ifndef NOFIRE_ZONE_MIN_DEG
#error "config.h icinde NOFIRE_ZONE_MIN_DEG eksik!"
#endif
#ifndef NOFIRE_ZONE_MAX_DEG
#error "config.h icinde NOFIRE_ZONE_MAX_DEG eksik!"
#endif
#ifndef TRIGGER_SERVO_PIN
#error "config.h icinde TRIGGER_SERVO_PIN eksik!"
#endif

// ---------------- ATIŞLAR ARASI MİNİMUM SÜRE ----------------
// Tetik servosunun çekip bırakması + beslemenin oturması.
#define SHOT_INTERVAL_MS    (TRIGGER_PULL_MS + TRIGGER_RELEASE_MS + 40)

// E-Stop fiziksel buton icin yazilimsal debounce suresi
#define ESTOP_DEBOUNCE_MS   50

#define HOMING_TOLERANCE_DEG   0.5f

// HEDEF TİPLERİ - angajman menzilleri hedef tipine göre.
enum TargetType {
    TARGET_FIGHTER_JET,
    TARGET_HELICOPTER,
    TARGET_MISSILE,
    TARGET_UAV
};


// ATEŞ ENGELLENME NEDENİ
enum FireBlockReason {
    FIRE_OK = 0,
    FIRE_BLOCKED_NO_ARM,            // emniyet mandali kapali
    FIRE_BLOCKED_ESTOP,
    FIRE_BLOCKED_AMMO_EMPTY,
    FIRE_BLOCKED_NOFIRE_ZONE,
    FIRE_BLOCKED_FRIENDLY_TARGET,
    FIRE_BLOCKED_LIDAR_STALE,
    FIRE_BLOCKED_LIDAR_UNRELIABLE,
    FIRE_BLOCKED_OUT_OF_RANGE,
    FIRE_BLOCKED_NOT_LOCKED,        // taret hala hareket halinde
    FIRE_BLOCKED_ACTUATOR_BUSY      // tetik servosu onceki cekisi bitirmedi
};

void safety_startHoming();

// ---------------- BAŞLATMA / PERİYODİK GÜNCELLEME ----------------
void safety_init();
void safety_update();

// Fiziksel E-Stop'un aksine bu yazılımsal ve geri donulebilir bir durdurmadir.
void safety_onCmdSafe(uint8_t reason);

bool safety_tryClearSoftwareSafeStop();

bool safety_isEstopActive();

SystemState safety_getSystemState();
void safety_setSystemState(SystemState newState);

uint8_t safety_getProtocolState();

uint8_t safety_buildTelemetryFlags();

void safety_setLastCtrlBits(uint8_t ctrl);
uint8_t safety_getLastCtrlBits();

// ---------------- MOD (CMD_MODE, PROTO_MODE_*) ----------------
void safety_setMode(uint8_t protoMode);
uint8_t safety_getMode();

// ---------------- CMD_HOME izin kontrolu ----------------
bool safety_isHomeAllowed();

// ---------------- MÜHİMMAT ----------------
void safety_recordShotFired();
uint16_t safety_getAmmoRemaining();
bool safety_isAmmoDepleted();
void safety_resetAmmoCount(uint16_t newCount = MAX_AMMO_COUNT);

// ---------------- ATIŞA YASAK ALAN ----------------
bool safety_isInNoFireZone(float azimuthDeg);

// ---------------- MENZİL DOĞRULAMA ----------------
bool safety_isRangeValidForTarget(TargetType type, float rangeM);

// ---------------- ATEŞLEME KARAR KAPISI ----------------
FireBlockReason safety_canFire(float currentAzimuthDeg,
                                TargetType targetType,
                                float targetRangeM,
                                bool targetIsFriendly,
                                bool lidarDataFresh,
                                bool lidarSignalReliable);

uint8_t safety_fireResultCode(FireBlockReason reason);

// ---------------- FİZİKSEL ATEŞLEME ----------------
// Tetik servosuna bir çekiş yaptırır ve mühimmat sayacını düşürür.
// (eski adı: safety_fireSolenoid)
bool safety_fireTrigger();

#endif