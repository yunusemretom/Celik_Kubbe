#ifndef PID_CONTROL_H
#define PID_CONTROL_H

#include <Arduino.h>
#include "config.h"

// ---------------- EKSEN KİMLİĞİ ----------------
enum AxisId {
    AXIS_AZIMUTH = 0,
    AXIS_ELEVATION = 1
};

// ---------------- TEK BİR EKSENİN PID + HAREKET DURUMU ----------------
struct AxisControlState {
    float targetAngleDeg;
    float currentAngleDeg;
    float integral;
    float previousError;
    unsigned long lastUpdateMicros;
    float commandedStepFreqHz;
    bool  movingPositive;
};

void pid_init();

// RPi'den gelen yeni hedef acilari ayarlar. Limitlere gore clamp yapar;
// clamp olursa pid_wasAzimuthClamped()/pid_wasElevationClamped() bir sonraki cagriya kadar true doner VE otomatik olarak ERR / ERR_AZ_LIMIT|ERR_EL_LIMIT gonderilir
void pid_setTargetAngles(float azimuthDeg, float elevationDeg);

void pid_update();

float pid_getCurrentAzimuthDeg();
float pid_getCurrentElevationDeg();
float pid_getTargetAzimuthDeg();
float pid_getTargetElevationDeg();

// TLM_STATE.flags icin: FLAG_LOCKED
bool pid_isAtTarget(float toleranceDeg = 0.2f);

// TLM_STATE.flags icin: FLAG_AZ_LIMIT / FLAG_EL_LIMIT
bool pid_wasAzimuthClamped();
bool pid_wasElevationClamped();

float pid_getCommandedStepFreqHz(AxisId axis);

void pid_emergencyStop();
bool pid_isEmergencyStopped(); 
void pid_resumeAfterEstop();
void pid_setGains(AxisId axis, float kp, float ki, float kd);
// Homing ozel durumlarda cikis hizini gecici olarak sinirlamak icin.
// limitDegS <= 0 verilirse yok sayilir (guvenlik).
void pid_setVelocityLimitDegS(float limitDegS);
void pid_resetVelocityLimitDegS();   // normal VELOCITY_OUTPUT_LIMIT_DEG_S'e doner

#endif