#ifndef LIDAR_H
#define LIDAR_H

#include <Arduino.h>
#include "config.h"

#ifndef LIDAR_UNIT_IS_DECIMETER
#define LIDAR_UNIT_IS_DECIMETER false
#endif

// ---------------- OKUMA SONUCU YAPISI ----------------
struct LidarReading {
    float    distanceCm;  
    uint16_t strength;     
    bool     valid;       
};

// UART portunu başlatır (config.h'deki pin/baud ile).
void lidar_init();


// Gelen bayt akışını tarar. Tam ve checksum'ı doğru bir frame varsa outReading'i doldurur ve true döner. BLOKLAMAZ - loop()/task içinde sürekli çağrılmaya uygundur. 
bool lidar_read(LidarReading &outReading);


// En son GEÇERLİ (checksum doğrulanmış) okumayı döndürür - yeni bir frame gelmemiş olsa bile son bilinen değeri verir. Telemetri göndermek için pratiktir 
//(her telemetri döngüsünde yeni frame gelmiş olması şart değil).
float lidar_getLastDistanceCm();
uint16_t lidar_getLastStrength();


// Son GEÇERLİ okumanın üzerinden ne kadar zaman geçtiğini kontrol eder.
bool lidar_isDataFresh(unsigned long maxAgeMs = 200);


// Sinyal kalitesi kontrolü (Benewake TF-serisi ortak davranışı):
bool lidar_isSignalReliable(uint16_t strength);

#endif 