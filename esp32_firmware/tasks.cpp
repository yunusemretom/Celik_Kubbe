#include "tasks.h"
#include "uart_protocol.h"
#include "pid_control.h"
#include "lidar.h"
#include "safety.h"


#define FIRE_BLOCK_ERROR_OFFSET   0x10

// ---------------- ZAMANLAMA SABİTLERİ ----------------
#define TELEMETRY_INTERVAL_MS     50     
#define COMM_TIMEOUT_MS           1000   
#define TASK_LOOP_DELAY_MS        2


// GOREV 1: RPi HABERLESMESI (komut alma + telemetri gonderme)
// Aynı HardwareSerial nesnesini (rpiSerial) hem okuma hem yazma için kullanıyoruz 
static void taskCommRpi(void *pvParameters) {
    (void)pvParameters;

    UartPacket rxPacket;
    unsigned long lastTelemetryMillis = millis();
    unsigned long lastValidPacketMillis = millis();
    bool commLostFreezeActive = false;

    for (;;) {

        // ---------------- KOMUT ALMA ----------------
        if (uartReceivePacket(rxPacket)) {
            lastValidPacketMillis = millis();

            if (commLostFreezeActive) {
                commLostFreezeActive = false;
                if (!safety_isEstopActive() && !safety_isAmmoDepleted()) {
                    pid_resumeAfterEstop();
                    Serial.println("[COMM] RPi baglantisi geri geldi, motor serbest birakildi.");
                }
            }

            switch (rxPacket.msgId) {

                case MSG_MOVE_TARGET_ANGLES:
                    pid_setTargetAngles(rxPacket.targetAzimuth, rxPacket.targetElevation);
                    break;

                case MSG_TRIGGER_FIRE: {
                    bool isFriendly = (rxPacket.ctrlBits & CTRL_BIT_TARGET_FRIENDLY) != 0;
                    float rangeM = lidar_getLastDistanceCm() / 100.0f;

                   
                    TargetType assumedType = TARGET_UAV;

                    FireBlockReason reason = safety_canFire(
                        pid_getCurrentAzimuthDeg(),
                        assumedType,
                        rangeM,
                        isFriendly,
                        lidar_isDataFresh(),
                        lidar_isSignalReliable(lidar_getLastStrength())
                    );

                    if (reason == FIRE_OK) {
                        safety_fireSolenoid();
                    } else {
                        uartSendErrorFlag((uint8_t)(FIRE_BLOCK_ERROR_OFFSET + (uint8_t)reason));
                        Serial.print("[ATES] Engellendi, sebep kodu: ");
                        Serial.println((int)reason);
                    }
                    break;
                }

                case MSG_ESTOP_COMMAND: {
                    bool activate = (rxPacket.ctrlBits & CTRL_BIT_ESTOP_ACTIVE) != 0;
                    safety_onEstopCommandFromRPi(activate);
                    break;
                }

                case MSG_HEARTBEAT:
                   
                    break;

                default:
                  
                    break;
            }
        }

        // ---------------- BAGLANTI KOPMA IZLEME ----------------
        if (!commLostFreezeActive && (millis() - lastValidPacketMillis > COMM_TIMEOUT_MS)) {
            pid_emergencyStop();
            commLostFreezeActive = true;
            Serial.println("[COMM] RPi'den veri kesildi (timeout)! Motor guvenlik icin donduruldu.");
        }

        // ---------------- PERIYODIK TELEMETRI ----------------
        if (millis() - lastTelemetryMillis >= TELEMETRY_INTERVAL_MS) {
            lastTelemetryMillis = millis();
            uartSendTelemetry(
                pid_getCurrentAzimuthDeg(),
                pid_getCurrentElevationDeg(),
                (uint8_t)safety_getSystemState(),
                lidar_getLastDistanceCm() / 100.0f   // cm -> metre
            );
        }

        vTaskDelay(pdMS_TO_TICKS(TASK_LOOP_DELAY_MS));
    }
}


// GOREV 2: MOTOR KONTROL (safety + PID) - EN YUKSEK ONCELIK, AYRI CEKIRDEK
// Bilerek core 1'de, tek başına çalışır - RPi haberleşmesi veya LiDAR
// okuma yavaşlasa/gecikse bile taretin hareket kalitesi etkilenmesin.
static void taskMotorControl(void *pvParameters) {
    (void)pvParameters;

    for (;;) {
        safety_update();   // E-Stop debounce, hakem onay akışı, mühimmat kontrolü, solenoid auto-off
        pid_update();       // PID hesap + step üretimi 

        vTaskDelay(pdMS_TO_TICKS(TASK_LOOP_DELAY_MS));
    }
}

// GOREV 3: LIDAR OKUMA

static void taskLidar(void *pvParameters) {
    (void)pvParameters;

    LidarReading reading;
    for (;;) {
        lidar_read(reading);   // ic cache'i gunceller
        vTaskDelay(pdMS_TO_TICKS(TASK_LOOP_DELAY_MS));
    }
}


void tasks_startAll() {
    xTaskCreatePinnedToCore(taskCommRpi,     "CommRPi",   TASK_STACK_UART,  NULL, TASK_PRIORITY_UART,  NULL, 0);
    xTaskCreatePinnedToCore(taskMotorControl,"MotorCtrl", TASK_STACK_MOTOR, NULL, TASK_PRIORITY_MOTOR, NULL, 1);
    xTaskCreatePinnedToCore(taskLidar,       "Lidar",     TASK_STACK_LIDAR, NULL, TASK_PRIORITY_LIDAR, NULL, 0);

    Serial.println("[TASKS] Tum FreeRTOS gorevleri baslatildi (CommRPi:core0, MotorCtrl:core1, Lidar:core0).");
}