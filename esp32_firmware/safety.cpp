#include "safety.h"
#include "pid_control.h"
#include "lidar.h"
#include "trigger.h"
#include "uart_protocol.h"


static bool homingInProgress = false;
static void cancelHomingIfActive() {
    if (homingInProgress) {
        homingInProgress = false;
        pid_resetVelocityLimitDegS();
    }
}
static SystemState currentState = ST_INIT;
static uint16_t ammoRemaining = MAX_AMMO_COUNT;

// ---------------- E-STOP DURUMU ----------------
static volatile bool estopIsrFlag = false;
static bool estopPhysicalActive = false;
static bool estopSoftwareActive = false;   // CMD_SAFE kaynakli
static bool lastRawPinState = false;
static unsigned long lastPinChangeMillis = 0;

// ---------------- PROTOKOL DURUMU (CMD_AIM/CMD_MODE takibi) ----------------
static uint8_t lastCtrlBits = 0;
static uint8_t currentProtoMode = PROTO_MODE_IDLE;


void IRAM_ATTR estopPinISR() {
    estopIsrFlag = true;
}

void safety_init() {
    pinMode(ESTOP_PIN, INPUT_PULLUP);
    pinMode(MOSFET1_LASER_PIN, OUTPUT);
    pinMode(MOSFET2_FEED_MOTOR_PIN, OUTPUT);
    pinMode(MOSFET3_BEACON_PIN, OUTPUT);
    digitalWrite(MOSFET1_LASER_PIN, LOW);
    digitalWrite(MOSFET2_FEED_MOTOR_PIN, LOW);
    digitalWrite(MOSFET3_BEACON_PIN, LOW);

    // Tetik aktuatoru (eski solenoid valfin yerine)
    trigger_init();

    attachInterrupt(digitalPinToInterrupt(ESTOP_PIN), estopPinISR, CHANGE);

    ammoRemaining = MAX_AMMO_COUNT;
    currentState = ST_INIT;

    homingInProgress = false;
    estopSoftwareActive = false;
    lastCtrlBits = 0;

#if DEFAULT_BOOT_MODE_MANUAL
    // RPi bagli olmasa da joystick calissin diye. Sahada RPi ile
    // calisiyorsaniz config.h'de DEFAULT_BOOT_MODE_MANUAL 0 yapin.
    currentProtoMode = PROTO_MODE_MANUAL;
#else
    currentProtoMode = PROTO_MODE_IDLE;
#endif

    lastRawPinState = (digitalRead(ESTOP_PIN) == HIGH);
    estopPhysicalActive = lastRawPinState;
    lastPinChangeMillis = millis();

    if (estopPhysicalActive) {
        pid_emergencyStop();
        trigger_forceRelease();
        currentState = ST_EMERGENCY_SHUTDOWN;
        sendErr(ERR_ESTOP, 0);
        LOG_WARN("Baslangicta E-Stop basili");
    }
}


void safety_update() {
    estopIsrFlag = false;

    // ---------------- TETIK SERVOSU DURUM MAKINESI ----------------
    trigger_update();

    // ---------------- FIZIKSEL BUTON DEBOUNCE ----------------
    bool rawState = (digitalRead(ESTOP_PIN) == HIGH);
    if (rawState != lastRawPinState) {
        lastRawPinState = rawState;
        lastPinChangeMillis = millis();
    }

    if ((millis() - lastPinChangeMillis) >= ESTOP_DEBOUNCE_MS) {
        if (rawState != estopPhysicalActive) {
            estopPhysicalActive = rawState;

            if (estopPhysicalActive) {
                pid_emergencyStop();
                trigger_forceRelease();       // tetik cekiliyse ANINDA birak
                currentState = ST_EMERGENCY_SHUTDOWN;
                sendErr(ERR_ESTOP, 0);
                cancelHomingIfActive();
                LOG_WARN("Fiziksel E-Stop tetiklendi");
            }
            // fiziksel buton serbest kalmasi KENDI BASINA sistemi calisir hale getirmez.
        }
    }

    // ---------------- MUHIMMAT BITTI KONTROLU ----------------
    if (ammoRemaining == 0 &&
        currentState != ST_EMERGENCY_SHUTDOWN &&
        currentState != ST_SAFE_STOP) {

        currentState = ST_SAFE_STOP;
        pid_emergencyStop();
        trigger_forceRelease();
        sendErr(ERR_AMMO_DEPLETED, 0);
        cancelHomingIfActive();
        LOG_WARN("Muhimmat bitti");
    }

    // ---------------- HOMING TAMAMLANMA KONTROLU ----------------
    if (homingInProgress && pid_isAtTarget(HOMING_TOLERANCE_DEG)) {
        homingInProgress = false;
        pid_resetVelocityLimitDegS();
        currentState = ST_STANDBY;
        SLOG_INFO("CMD_HOME tamamlandi");
    }
}


// ---------------- CMD_SAFE (0x04) ----------------
void safety_onCmdSafe(uint8_t reason) {
    estopSoftwareActive = true;
    pid_emergencyStop();
    trigger_forceRelease();
    currentState = ST_SAFE_STOP;
    cancelHomingIfActive();
    LOG_WARN("CMD_SAFE alindi, sebep=%d", reason);
}

bool safety_tryClearSoftwareSafeStop() {
    if (estopPhysicalActive) return false;      // fiziksel buton hala basili
    if (ammoRemaining == 0) return false;        // muhimmat yoksa cikilmaz
    if (currentState != ST_SAFE_STOP) return false;
    if (!estopSoftwareActive) return false;      // SAFE_STOP baska sebepten

    estopSoftwareActive = false;
    pid_resumeAfterEstop();
    currentState = ST_STANDBY;
    LOG_INFO("SAFE_STOP temizlendi");
    return true;
}


bool safety_isEstopActive() {
    return (currentState == ST_EMERGENCY_SHUTDOWN) || estopPhysicalActive || estopSoftwareActive;
}


SystemState safety_getSystemState() {
    return currentState;
}

void safety_setSystemState(SystemState newState) {
    if (currentState == ST_EMERGENCY_SHUTDOWN || currentState == ST_SAFE_STOP) {
        return;
    }
    currentState = newState;
}

uint8_t safety_getProtocolState() {
    switch (currentState) {
        case ST_INIT:               return PROTO_ST_INIT;
        case ST_STANDBY:            return PROTO_ST_STANDBY;
        case ST_TRACKING:           return PROTO_ST_TRACKING;
        case ST_ENGAGING:           return PROTO_ST_ENGAGE;
        case ST_SAFE_STOP:          return PROTO_ST_SAFE_STOP;
        case ST_EMERGENCY_SHUTDOWN: return PROTO_ST_SAFE_STOP;  // ayrim FLAG_ESTOP ile
    }
    return PROTO_ST_SAFE_STOP;
}

uint8_t safety_buildTelemetryFlags() {
    uint8_t flags = 0;
    if (lastCtrlBits & CTRL_ARM)      flags |= FLAG_ARMED;
    if (lastCtrlBits & CTRL_MOTOR_EN) flags |= FLAG_MOTORS_ON;
    if (pid_isAtTarget())             flags |= FLAG_LOCKED;
    if (safety_isEstopActive())       flags |= FLAG_ESTOP;
    if (pid_wasAzimuthClamped())      flags |= FLAG_AZ_LIMIT;
    if (pid_wasElevationClamped())    flags |= FLAG_EL_LIMIT;
    if (lastCtrlBits & CTRL_LASER)    flags |= FLAG_LASER_ON;
    if (safety_isAmmoDepleted())      flags |= FLAG_AMMO_EMPTY;
    return flags;
}

void safety_setLastCtrlBits(uint8_t ctrl) {
    lastCtrlBits = ctrl;

    digitalWrite(MOSFET1_LASER_PIN, (ctrl & CTRL_LASER) ? HIGH : LOW);

    // Ikaz lambasi: sistem silahliyken (ARM) veya E-Stop aktifken yansin.
    bool beaconOn = (ctrl & CTRL_ARM) || safety_isEstopActive();
    digitalWrite(MOSFET3_BEACON_PIN, beaconOn ? HIGH : LOW);
}
uint8_t safety_getLastCtrlBits() { return lastCtrlBits; }

void safety_setMode(uint8_t protoMode) { currentProtoMode = protoMode; }
uint8_t safety_getMode() { return currentProtoMode; }

bool safety_isHomeAllowed() {
    return (currentState == ST_INIT) || (currentState == ST_STANDBY);
}


void safety_recordShotFired() {
    if (ammoRemaining > 0) {
        ammoRemaining--;
    }
}

uint16_t safety_getAmmoRemaining() {
    return ammoRemaining;
}

bool safety_isAmmoDepleted() {
    return ammoRemaining == 0;
}

void safety_resetAmmoCount(uint16_t newCount) {
    ammoRemaining = newCount;

    if (newCount > 0 && currentState == ST_SAFE_STOP && !estopSoftwareActive) {
        pid_resumeAfterEstop();
        currentState = ST_STANDBY;
        LOG_INFO("Muhimmat yenilendi");
    }
}


bool safety_isInNoFireZone(float azimuthDeg) {
    return (azimuthDeg >= NOFIRE_ZONE_MIN_DEG) && (azimuthDeg <= NOFIRE_ZONE_MAX_DEG);
}


bool safety_isRangeValidForTarget(TargetType type, float rangeM) {
    switch (type) {
        case TARGET_FIGHTER_JET:
            return (rangeM >= RANGE_F16_MIN_M) && (rangeM <= RANGE_F16_MAX_M);

        case TARGET_HELICOPTER:
        case TARGET_MISSILE:
            return (rangeM >= RANGE_HELI_MISSILE_MIN_M) && (rangeM <= RANGE_HELI_MISSILE_MAX_M);

        case TARGET_UAV:
            return (rangeM >= RANGE_UAV_MIN_M) && (rangeM <= RANGE_UAV_MAX_M);
    }
    return false;
}


FireBlockReason safety_canFire(float currentAzimuthDeg,
                                TargetType targetType,
                                float targetRangeM,
                                bool targetIsFriendly,
                                bool lidarDataFresh,
                                bool lidarSignalReliable) {

    // Sira onemli: en agir/en kesin engel once donmeli ki operatore
    // dogru sebep gosterilsin.
    if (!(lastCtrlBits & CTRL_ARM))                 return FIRE_BLOCKED_NO_ARM;
    if (safety_isEstopActive())                     return FIRE_BLOCKED_ESTOP;
    if (safety_isAmmoDepleted())                    return FIRE_BLOCKED_AMMO_EMPTY;
    if (safety_isInNoFireZone(currentAzimuthDeg))   return FIRE_BLOCKED_NOFIRE_ZONE;
    if (targetIsFriendly)                           return FIRE_BLOCKED_FRIENDLY_TARGET;
    if (trigger_isBusy())                           return FIRE_BLOCKED_ACTUATOR_BUSY;

#if REQUIRE_LIDAR_FOR_FIRE
    if (!lidarDataFresh)                            return FIRE_BLOCKED_LIDAR_STALE;
    if (!lidarSignalReliable)                       return FIRE_BLOCKED_LIDAR_UNRELIABLE;
    if (!safety_isRangeValidForTarget(targetType, targetRangeM))
                                                    return FIRE_BLOCKED_OUT_OF_RANGE;
#else
    (void)lidarDataFresh; (void)lidarSignalReliable;
    (void)targetType;     (void)targetRangeM;
#endif

    if (!pid_isAtTarget())                          return FIRE_BLOCKED_NOT_LOCKED;

    return FIRE_OK;
}

uint8_t safety_fireResultCode(FireBlockReason reason) {
    switch (reason) {
        case FIRE_OK:                       return FIRE_RESULT_OK;
        case FIRE_BLOCKED_NO_ARM:           return FIRE_RESULT_NO_ARM;
        case FIRE_BLOCKED_ESTOP:            return FIRE_RESULT_NO_ARM;
        case FIRE_BLOCKED_AMMO_EMPTY:       return FIRE_RESULT_NO_AMMO;
        case FIRE_BLOCKED_NOFIRE_ZONE:      return FIRE_RESULT_NO_FIRE_ZONE;
        case FIRE_BLOCKED_FRIENDLY_TARGET:  return FIRE_RESULT_NO_FIRE_ZONE;
        case FIRE_BLOCKED_LIDAR_STALE:      return FIRE_RESULT_NOT_LOCKED;
        case FIRE_BLOCKED_LIDAR_UNRELIABLE: return FIRE_RESULT_NOT_LOCKED;
        case FIRE_BLOCKED_OUT_OF_RANGE:     return FIRE_RESULT_OUT_OF_LIMIT;
        case FIRE_BLOCKED_NOT_LOCKED:       return FIRE_RESULT_NOT_LOCKED;
        case FIRE_BLOCKED_ACTUATOR_BUSY:    return FIRE_RESULT_NOT_LOCKED;
    }
    return FIRE_RESULT_NOT_LOCKED;
}


// ---------------- FIZIKSEL ATESLEME ----------------
// Eski safety_fireSolenoid()'in yerini alir. Kapinin kendisi degismedi,
// sadece en alttaki aktuator cagrisi solenoid yerine tetik servosu.
bool safety_fireTrigger() {
    if (safety_isEstopActive() || safety_isAmmoDepleted()) {
        return false;
    }
    if (!trigger_pull()) {
        return false;   // servo hala onceki cekiste - atis SAYILMAZ
    }

    // Tetik gercekten cekildi; mühimmati simdi dus.
    // NOT: bu sayim tufek YARI OTOMATIK ise dogrudur (1 cekis = 1 mermi).
    // Tam otomatikse config.h > RIFLE_IS_SEMI_AUTO 0 yapin ve sayaca guvenmeyin.
    safety_recordShotFired();
    return true;
}

void safety_startHoming() {
    homingInProgress = true;
    pid_setVelocityLimitDegS(HOMING_VELOCITY_LIMIT_DEG_S);
}