#ifndef ENCODER_H
#define ENCODER_H

#include <Arduino.h>
#include <Wire.h>
#include "config.h"

// in config.h or encoder.h
#define AZ_ENCODER_I2C_ADDR    0x36   // AS5600 default I2C address
#define ELEV_ENCODER_I2C_ADDR  0x36   // same chip, different bus (Wire1) so same addr is fine

// I2C hatlarını (Wire=Azimut, Wire1=Elevasyon) config.h'deki pinlerle başlatır, her iki AS5600'ün de kendi hattında cevap verdiğini doğrular:
bool encoder_init();

// Her çağrıda I2C'den taze bir okuma yapar; okuma başarısız olursa son geçerli değeri döndürür:
float encoder_getAzimuthDeg();
float encoder_getElevationDeg();

// Son okumanın başarılı olup olmadığını bildirir:
bool encoder_isAzimuthOk();
bool encoder_isElevationOk();

uint16_t encoder_getAzimuthRaw();
uint16_t encoder_getElevationRaw();

// Taret mekanik olarak 0° Azimut / 0° İrtifa referans noktasına getirildikten sonra çağrılır. O anki ham sensör okumasını sıfır noktası olarak kaydeder:
void encoder_calibrateZero();

// Kaydedilmiş offset değerlerini manuel olarak ayarlamak istenirse:
void encoder_setAzimuthZeroOffsetDeg(float offsetDeg);
void encoder_setElevationZeroOffsetDeg(float offsetDeg);
float encoder_getAzimuthZeroOffsetDeg();
float encoder_getElevationZeroOffsetDeg();

#endif 