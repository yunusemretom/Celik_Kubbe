#ifndef SAFETY_H
#define SAFETY_H

#include <Arduino.h>
#include "config.h"


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

// ---------------- RPi'YE GÖNDERİLEN SAYISAL HATA KODLARI ---------------- GÖZDEN GEÇİRİLECEK
#define ERR_CODE_AMMO_DEPLETED         0x01
#define ERR_CODE_EMERGENCY_SHUTDOWN    0x02
#define ERR_CODE_LIDAR_LOST            0x03

// ---------------- SOLENOID ATEŞLEME SÜRESİ ----------------
// Airtac solenoid valfin BB'yi firlatmak icin acik kalmasi gereken sure. Tune edilecek
#define SOLENOID_PULSE_MS   50


// E-Stop fiziksel buton icin yazilimsal debounce suresi
#define ESTOP_DEBOUNCE_MS   50

// HEDEF TİPLERİ - angajman menzilleri hedef tipine göre
enum TargetType {
    TARGET_FIGHTER_JET,   // F16 vb.  -> RANGE_F16_MIN_M .. RANGE_F16_MAX_M
    TARGET_HELICOPTER,    // Helikopter/Füze -> RANGE_HELI_MISSILE_MIN_M..MAX_M
    TARGET_MISSILE,
    TARGET_UAV             // İHA -> RANGE_UAV_MIN_M .. RANGE_UAV_MAX_M
};


// ATEŞ ENGELLENME NEDENİ 
enum FireBlockReason {
    FIRE_OK = 0,                    // ates edilebilir
    FIRE_BLOCKED_ESTOP,              // E-Stop aktif
    FIRE_BLOCKED_AMMO_EMPTY,         // muhimmat bitti
    FIRE_BLOCKED_NOFIRE_ZONE,        // taret yasakli aciya bakiyor
    FIRE_BLOCKED_FRIENDLY_TARGET,    // hedef dost unsur olarak etiketli (Asama-3 IFF)
    FIRE_BLOCKED_LIDAR_STALE,        // LiDAR verisi taze değil
    FIRE_BLOCKED_LIDAR_UNRELIABLE,   // LiDAR sinyal gucu yetersiz
    FIRE_BLOCKED_OUT_OF_RANGE        // hedef, o hedef tipi icin tanimli menzilin disinda
};


// BAŞLATMA / PERİYODİK GÜNCELLEME

// ESTOP_PIN'i INPUT_PULLUP olarak ayarlar, harici kesmeyi (interrupt) bağlar, mühimmat sayacını MAX_AMMO_COUNT'a ayarlar, sistem durumunu ST_INIT yapar:
void safety_init();

// Debounce işini bitirir, solenoid'in süresi dolmuşsa otomatik kapatır, ve E-Stop/mühimmat durumuna göre sistem durumu geçişlerini uygular.
void safety_update();


// UART görevi  MSG_ESTOP_COMMAND paketini gördüğünde bunu çağırır. 
//activateRequested=true -> acil durdurmayı TETİKLE, activateRequested=false -> hakem/operatör onayı olarak SIFIRLAMA DENE.
void safety_onEstopCommandFromRPi(bool activateRequested);

// E-Stop şu an aktif mi? - true ise pid_control zaten hareket üretmiyor
bool safety_isEstopActive();


// SİSTEM DURUMU (State Machine - config.h'deki SystemState enum'u)

SystemState safety_getSystemState();

// tasks.cpp normal akış geçişlerini (ST_STANDBY <-> ST_TRACKING <-> ST_ENGAGING) bu fonksiyonla yapar.
void safety_setSystemState(SystemState newState);


// MÜHİMMAT 

void safety_recordShotFired();          // her basarili atistan sonra tasks.cpp cagirir
uint16_t safety_getAmmoRemaining();
bool safety_isAmmoDepleted();
void safety_resetAmmoCount(uint16_t newCount = MAX_AMMO_COUNT);  // magazin degisince cagirin


// ATIŞA YASAK ALAN (Rapor Bölüm 6 - "dinamik atışa yasak alan")

bool safety_isInNoFireZone(float azimuthDeg);


// MENZİL DOĞRULAMA (Rapor Tablo 4.3)

bool safety_isRangeValidForTarget(TargetType type, float rangeM);


// ATEŞLEME KARAR KAPISI - HERKESİN AteŞTEN ÖNCE ÇAĞIRMASI GEREKEN TEK FONKSİYON.

FireBlockReason safety_canFire(float currentAzimuthDeg,
                                TargetType targetType,
                                float targetRangeM,
                                bool targetIsFriendly,
                                bool lidarDataFresh,
                                bool lidarSignalReliable);


// FİZİKSEL ATEŞLEME

// safety_canFire() FIRE_OK döndürdüyse çağır. Fonksiyon kendi içinde
// de E-Stop/mühimmat kontrolünü TEKRAR yapar (defensive programming -
// çağıran taraf kontrolü unutmuş/eskimiş olsa bile son savunma hattı).
// Solenoid'i SOLENOID_PULSE_MS süresinde açar, safety_update() süre
// dolunca otomatik kapatır (BLOKLAMAZ, delay() kullanılmaz).
// Dönüş: true = tetiklendi, false = son kontrolde de reddedildi.

bool safety_fireSolenoid();

#endif 