#ifndef SAFETY_H
#define SAFETY_H

#include <Arduino.h>
#include "config.h"
#include "uart_protocol.h"   // FLAG_*, PROTO_ST_*, FIRE_RESULT_*, ERR_* sabitleri icin


// Sistemdeki TEK YETKİLİ güvenlik katmanı.


#ifndef MOSFET4_SOLENOID_PIN
#error "config.h icinde MOSFET4_SOLENOID_PIN eksik!"
#endif
#ifndef MAX_AMMO_COUNT
#error "config.h icinde MAX_AMMO_COUNT eksik!"
#endif
#ifndef NOFIRE_ZONE_MIN_DEG
#error "config.h icinde NOFIRE_ZONE_MIN_DEG eksik!"
#endif
#ifndef NOFIRE_ZONE_MAX_DEG
#error "config.h icinde NOFIRE_ZONE_MAX_DEG eksik!"
#endif

// ---------------- SOLENOID ATEŞLEME SÜRESİ ----------------
#define SOLENOID_PULSE_MS   50
#define SHOT_INTERVAL_MS    150

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
    FIRE_BLOCKED_ESTOP,
    FIRE_BLOCKED_AMMO_EMPTY,
    FIRE_BLOCKED_NOFIRE_ZONE,
    FIRE_BLOCKED_FRIENDLY_TARGET,
    FIRE_BLOCKED_LIDAR_STALE,
    FIRE_BLOCKED_LIDAR_UNRELIABLE,
    FIRE_BLOCKED_OUT_OF_RANGE
};

void safety_startHoming();

// ---------------- BAŞLATMA / PERİYODİK GÜNCELLEME ----------------
void safety_init();
void safety_update();

// Fiziksel E-Stop'un aksine bu yazılımsal ve geri donulebilir bir durdurmadir.
void safety_onCmdSafe(uint8_t reason);

// Yazilimsal (CMD_SAFE kaynakli) SAFE_STOP durumunu, fiziksel buton serbestse ve muhimmat varsa temizlemeye calisir (CMD_MODE veya CMD_HOME geldiginde
// tasks.cpp tarafindan cagrilir). Basarili olursa true doner ve state STANDBY olur.
bool safety_tryClearSoftwareSafeStop();

bool safety_isEstopActive();

SystemState safety_getSystemState();
void safety_setSystemState(SystemState newState);

// TLM_STATE.state alani icin: 6 durumlu SystemState'i PDF'in 5 durumuna indirir.
// Fiziksel/yazilimsal E-Stop ayrimi FLAG_ESTOP biti ile tasinir.
uint8_t safety_getProtocolState();

// TLM_STATE.flags alanini uretir (ARMED/MOTORS_ON/LOCKED/ESTOP/AZ_LIMIT/
// EL_LIMIT/LASER_ON/AMMO_EMPTY) - son CMD_AIM.ctrl bitlerine ve pid/ammo
// durumuna gore.
uint8_t safety_buildTelemetryFlags();

// Son gelen CMD_AIM.ctrl baytini saklar (flags uretimi ve CMD_FIRE kontrolu
// icin gereklidir - PDF'te ARM/NO_FIRE bilgisi CMD_AIM icinde tasinir).
void safety_setLastCtrlBits(uint8_t ctrl);
uint8_t safety_getLastCtrlBits();

// ---------------- MOD (CMD_MODE, PROTO_MODE_*) ----------------
void safety_setMode(uint8_t protoMode);
uint8_t safety_getMode();

// ---------------- CMD_HOME izin kontrolu ----------------
// PDF: "Yalnizca ST_INIT veya ST_STANDBY durumundayken kabul etsin."
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
bool safety_fireSolenoid();

#endif