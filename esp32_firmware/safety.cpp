#include "safety.h"
#include "pid_control.h"
#include "lidar.h"
#include "uart_protocol.h"



static SystemState currentState = ST_INIT;
static uint16_t ammoRemaining = MAX_AMMO_COUNT;

// ---------------- E-STOP DURUMU ----------------
static volatile bool estopIsrFlag = false;   // ISR sadece bunu set eder, agir is yapmaz
static bool estopPhysicalActive = false;      // debounce edilmis fiziksel buton durumu
static bool estopSoftwareActive = false;      
static bool refereeResetRequested = false;    
static bool lastRawPinState = false;
static unsigned long lastPinChangeMillis = 0;

// ---------------- SOLENOID DURUMU ----------------
static bool solenoidActive = false;
static unsigned long solenoidStartMillis = 0;


// ISR: sadece bayrak set eder: 
void IRAM_ATTR estopPinISR() {
    estopIsrFlag = true;
}

void safety_init() {
    pinMode(ESTOP_PIN, INPUT_PULLUP);
    pinMode(MOSFET4_SOLENOID_PIN, OUTPUT);
    digitalWrite(MOSFET4_SOLENOID_PIN, LOW);

    attachInterrupt(digitalPinToInterrupt(ESTOP_PIN), estopPinISR, CHANGE);

    ammoRemaining = MAX_AMMO_COUNT;
    currentState = ST_INIT;

    estopSoftwareActive = false;
    refereeResetRequested = false;
    solenoidActive = false;

    lastRawPinState = (digitalRead(ESTOP_PIN) == HIGH);
    estopPhysicalActive = lastRawPinState;
    lastPinChangeMillis = millis();

    if (estopPhysicalActive) {
        pid_emergencyStop();
        currentState = ST_EMERGENCY_SHUTDOWN;
        Serial.println("[GUVENLIK] Baslangicta E-Stop basili tespit edildi! Once serbest birakin.");
    }
}


void safety_update() {
    estopIsrFlag = false;   

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
                currentState = ST_EMERGENCY_SHUTDOWN;
                uartSendErrorFlag(ERR_CODE_EMERGENCY_SHUTDOWN);
                Serial.println("[GUVENLIK] Fiziksel E-Stop tetiklendi! Sistem kilitlendi.");
            }
        }
    }

    // ---------------- HAKEM ONAYLI SIFIRLAMA ----------------
    if (currentState == ST_EMERGENCY_SHUTDOWN) {
        bool physicalReleased = !estopPhysicalActive;
        if (physicalReleased && refereeResetRequested) {
            estopSoftwareActive = false;
            refereeResetRequested = false;
            pid_resumeAfterEstop();
            currentState = ST_STANDBY;
            Serial.println("[GUVENLIK] E-Stop sifirlandi (fiziksel serbest + hakem onayi). Sistem STANDBY.");
        }
    }

    // ---------------- SOLENOID OTOMATIK KAPATMA ----------------
    if (solenoidActive && (millis() - solenoidStartMillis >= SOLENOID_PULSE_MS)) {
        digitalWrite(MOSFET4_SOLENOID_PIN, LOW);
        solenoidActive = false;
    }

    // ---------------- MUHIMMAT BITTI KONTROLU ----------------
    if (ammoRemaining == 0 &&
        currentState != ST_EMERGENCY_SHUTDOWN &&
        currentState != ST_SAFE_STOP) {

        currentState = ST_SAFE_STOP;
        pid_emergencyStop();  
        uartSendErrorFlag(ERR_CODE_AMMO_DEPLETED);
        Serial.println("[GUVENLIK] Muhimmat bitti! ST_SAFE_STOP.");
    }
}


void safety_onEstopCommandFromRPi(bool activateRequested) {
    if (activateRequested) {
        estopSoftwareActive = true;
        pid_emergencyStop();
        currentState = ST_EMERGENCY_SHUTDOWN;
        Serial.println("[GUVENLIK] RPi'den yazilimsal E-Stop komutu alindi.");
    } else {
       
        refereeResetRequested = true;
        Serial.println("[GUVENLIK] Hakem/operator onay istegi alindi, fiziksel buton kontrol ediliyor...");
    }
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

    if (newCount > 0 && currentState == ST_SAFE_STOP) {
        pid_resumeAfterEstop();
        currentState = ST_STANDBY;
        Serial.println("[GUVENLIK] Muhimmat yenilendi, sistem STANDBY moduna donuyor.");
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

    if (safety_isEstopActive())                    return FIRE_BLOCKED_ESTOP;
    if (safety_isAmmoDepleted())                    return FIRE_BLOCKED_AMMO_EMPTY;
    if (safety_isInNoFireZone(currentAzimuthDeg))   return FIRE_BLOCKED_NOFIRE_ZONE;
    if (targetIsFriendly)                            return FIRE_BLOCKED_FRIENDLY_TARGET;
    if (!lidarDataFresh)                             return FIRE_BLOCKED_LIDAR_STALE;
    if (!lidarSignalReliable)                        return FIRE_BLOCKED_LIDAR_UNRELIABLE;
    if (!safety_isRangeValidForTarget(targetType, targetRangeM))
                                                       return FIRE_BLOCKED_OUT_OF_RANGE;

    return FIRE_OK;
}

bool safety_fireSolenoid() {
    // Son savunma hatti: cagiran taraf safety_canFire() kontrolunu
    // atlamis/eskitmis olsa bile temel guvenlik burada TEKRAR kontrol edilir.
    if (safety_isEstopActive() || safety_isAmmoDepleted()) {
        return false;
    }

    digitalWrite(MOSFET4_SOLENOID_PIN, HIGH);
    solenoidActive = true;
    solenoidStartMillis = millis();

    safety_recordShotFired();
    return true;
}