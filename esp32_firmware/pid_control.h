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
    float targetAngleDeg;        // RPi'den gelen hedef açı 
    float currentAngleDeg;       // encoder.h'den okunan mevcut açı
    float integral;            
    float previousError;         
    unsigned long lastUpdateMicros;  
    float commandedStepFreqHz;  
    bool  movingPositive;        // step yönü (DIR pini bu bilgiden türetilir)
};

// GPIO pinlerini (STEP/DIR), LEDC step-üretim kanallarını ve PID durumlarını başlangıç değerlerine ayarlar:
void pid_init();

// RPi'den gelen yeni hedef açıları ayarlar:
// Fonksiyon içeride AZIMUTH_MIN_DEG/MAX_DEG ve ELEVATION_MIN_DEG/MAX_DEG limitlerine göre otomatik kırpma (clamp) yapar
void pid_setTargetAngles(float azimuthDeg, float elevationDeg);

// Tek bir PID hesap adımı yapar ve step/dir çıkışlarını günceller:
void pid_update();

// Mevcut (encoder'dan okunan) açı değerlerini döndürür:
float pid_getCurrentAzimuthDeg();
float pid_getCurrentElevationDeg();

// Hedef açıları döndürür:
float pid_getTargetAzimuthDeg();
float pid_getTargetElevationDeg();


// Telemetride taret kilit durumu alanı ve atış-öncesi kontrol için kullanılır:
bool pid_isAtTarget(float toleranceDeg = 0.2f);

// Şu an komuta edilen step frekansını (Hz) döndürür - debug amaçlı yazılacak
float pid_getCommandedStepFreqHz(AxisId axis);

// ---------------- GÜVENLİK / E-STOP ----------------
// safety.cpp E-Stop tetiklendiğinde bunu çağırır: LEDC step üretimini ANINDA durdurur (duty=0) ve pid_update()'in yeni step üretmesini engeller. Motor sürücü ENABLE pinini de (varsa) devre dışı bırakır.
void pid_emergencyStop();

// Hakem onayı + fiziksel buton serbest bırakıldıktan sonra safety.cpp tarafından çağrılır - pid_update()'in tekrar hareket üretmesine izin verir. 
void pid_resumeAfterEstop();

// PID katsayılarını çalışma zamanında değiştirmek için (saha testinde ayar yapmak amacıyla). Varsayılan değerler config.h'deki PID_KP/PID_KI/PID_KD sabitleridir.
void pid_setGains(AxisId axis, float kp, float ki, float kd);

#endif 