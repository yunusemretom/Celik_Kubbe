#ifndef PID_CONTROL_H
#define PID_CONTROL_H

#include <Arduino.h>
#include "config.h"

// ---------------- EKSEN KİMLİĞİ ----------------
enum AxisId {
    AXIS_AZIMUTH = 0,
    AXIS_ELEVATION = 1
};

// ---------------- KONTROL MODU ----------------
// PID_MODE_POSITION : encoder geri beslemeli kapali cevrim (RPi / CMD_AIM)
// PID_MODE_VELOCITY : ACIK CEVRIM hiz kontrolu (joystick / manuel)
//
// NEDEN IKI MOD VAR:
// Encoder takili degilken encoder_getAzimuthDeg() surekli 0 dondurur.
// PID hatayi "hedef - 0" olarak gorur, hata hic kucülmez ve motor
// tavan hizda kacar. Manuel modda bu yuzden PID devre disi kalir;
// joystick dogrudan HIZ komut eder, pozisyon ise komut edilen hizin
// integrali ile TAHMIN edilir (hareket limitleri calismaya devam etsin diye).
enum PidControlMode {
    PID_MODE_POSITION = 0,
    PID_MODE_VELOCITY = 1
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

    // --- acik cevrim hiz modu alanlari ---
    float velocityCmdDegS;      // istenen hiz
    float velocityActualDegS;   // rampa sonrasi uygulanan hiz
    float estimatedAngleDeg;    // adim integrasyonundan pozisyon TAHMINI
};

void pid_init();

// RPi'den gelen yeni hedef acilari ayarlar. Limitlere gore clamp yapar;
// clamp olursa pid_wasAzimuthClamped()/pid_wasElevationClamped() bir sonraki
// cagriya kadar true doner VE otomatik olarak ERR_AZ_LIMIT/ERR_EL_LIMIT gonderilir.
// NOT: PID_MODE_VELOCITY'de bu cagri YOK SAYILIR (iki efendi olmasin).
void pid_setTargetAngles(float azimuthDeg, float elevationDeg);

void pid_update();

// ---------------- KONTROL MODU ----------------
void pid_setControlMode(PidControlMode mode);
PidControlMode pid_getControlMode();

// Joystick'ten gelen hiz komutu (derece/saniye, isaretli).
// Sadece PID_MODE_VELOCITY'de etkilidir.
void pid_setVelocityCommand(float azDegS, float elevDegS);

// Pozisyon tahminini sifirlar. Taret MEKANIK OLARAK 0/0 referansindayken
// cagirilmalidir - encoder olmadigi icin baska referans yok.
void pid_zeroPositionEstimate();

float pid_getCurrentAzimuthDeg();
float pid_getCurrentElevationDeg();
float pid_getTargetAzimuthDeg();
float pid_getTargetElevationDeg();

// PID_MODE_VELOCITY'de "hedefte" demek, taret DURDU demektir.
// TLM_STATE.flags icin: FLAG_LOCKED
bool pid_isAtTarget(float toleranceDeg = 0.2f);

// TLM_STATE.flags icin: FLAG_AZ_LIMIT / FLAG_EL_LIMIT
bool pid_wasAzimuthClamped();
bool pid_wasElevationClamped();

float pid_getCommandedStepFreqHz(AxisId axis);
float pid_getVelocityDegS(AxisId axis);

void pid_emergencyStop();
bool pid_isEmergencyStopped();
void pid_resumeAfterEstop();
void pid_setGains(AxisId axis, float kp, float ki, float kd);

// Homing gibi ozel durumlarda cikis hizini gecici olarak sinirlamak icin.
// limitDegS <= 0 verilirse yok sayilir (guvenlik).
void pid_setVelocityLimitDegS(float limitDegS);
void pid_resetVelocityLimitDegS();   // normal VELOCITY_OUTPUT_LIMIT_DEG_S'e doner

#endif