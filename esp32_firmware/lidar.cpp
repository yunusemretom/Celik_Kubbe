#include "lidar.h"




// LiDAR icin ayri bir donanimsal UART kullaniyoruz. uart_protocol.cpp
// RPi icin HardwareSerial(1) kullaniyor, biz burada HardwareSerial(2)
// kullaniyoruz (ESP32-S3'un 3 donanimsal UART'indan sonuncusu).

HardwareSerial lidarSerial(2);

#ifndef LIDAR_MIN_VALID_STRENGTH
#define LIDAR_MIN_VALID_STRENGTH 100
#endif

#define FRAME_SIZE        9
#define HEADER_BYTE        0x59

// ---------------- PARSER DURUM MAKINESI ----------------
enum LidarParserState {
    LWAIT_HDR1,
    LWAIT_HDR2,
    LREAD_BODY
};

static LidarParserState parserState = LWAIT_HDR1;
static uint8_t rxBuffer[FRAME_SIZE];
static uint8_t rxIndex = 0;

// ---------------- SON GECERLI OKUMA (cache) ----------------
static float    lastDistanceCm = -1.0f;
static uint16_t lastStrength   = 0;
static unsigned long lastValidReadMillis = 0;
static bool hasEverReadValid = false;


void lidar_init() {
    lidarSerial.begin(LIDAR_UART_BAUD, SERIAL_8N1, LIDAR_UART_RX_PIN, LIDAR_UART_TX_PIN);
    parserState = LWAIT_HDR1;
    rxIndex = 0;
    lastDistanceCm = -1.0f;
    lastStrength = 0;
    lastValidReadMillis = 0;
    hasEverReadValid = false;
}


bool lidar_read(LidarReading &outReading) {
    outReading.valid = false;

    while (lidarSerial.available() > 0) {
        uint8_t incoming = (uint8_t)lidarSerial.read();

        switch (parserState) {

            case LWAIT_HDR1:
                if (incoming == HEADER_BYTE) {
                    rxBuffer[0] = incoming;
                    parserState = LWAIT_HDR2;
                }
                break;

            case LWAIT_HDR2:
                if (incoming == HEADER_BYTE) {
                    rxBuffer[1] = incoming;
                    rxIndex = 2;
                    parserState = LREAD_BODY;
                } else {
                    // ikinci bayt header degilse, gelen bayt yeni bir HDR1 adayi olabilir 
                    parserState = (incoming == HEADER_BYTE) ? LWAIT_HDR2 : LWAIT_HDR1;
                }
                break;

            case LREAD_BODY:
                rxBuffer[rxIndex++] = incoming;

                if (rxIndex >= FRAME_SIZE) {
                    uint8_t checksum = 0;
                    for (uint8_t i = 0; i < FRAME_SIZE - 1; i++) {
                        checksum += rxBuffer[i];   
                    }

                    parserState = LWAIT_HDR1;
                    rxIndex = 0;

                    if (checksum != rxBuffer[FRAME_SIZE - 1]) {
                        return false;   
                    }

                    uint16_t distRaw = (uint16_t)rxBuffer[2] | ((uint16_t)rxBuffer[3] << 8);
                    uint16_t strength = (uint16_t)rxBuffer[4] | ((uint16_t)rxBuffer[5] << 8);

                    float distanceCm;
                    distanceCm = (float)distRaw;   
                    

                    outReading.distanceCm = distanceCm;
                    outReading.strength = strength;
                    outReading.valid = true;

                    lastDistanceCm = distanceCm;
                    lastStrength = strength;
                    lastValidReadMillis = millis();
                    hasEverReadValid = true;

                    return true;
                }
                break;
        }
    }

    return false;  
}


float lidar_getLastDistanceCm() {
    return lastDistanceCm;
}

uint16_t lidar_getLastStrength() {
    return lastStrength;
}


bool lidar_isDataFresh(unsigned long maxAgeMs) {
    if (!hasEverReadValid) {
        return false;  
    }
    return (millis() - lastValidReadMillis) <= maxAgeMs;
}


bool lidar_isSignalReliable(uint16_t strength) {
    if (strength < LIDAR_MIN_VALID_STRENGTH) {
        return false;   // sinyal cok zayif
    }
    if (strength == 65535) {
        return false;   // ortam isigi doygunlugu (Benewake TF-serisi ortak davranisi)
    }
    return true;
}