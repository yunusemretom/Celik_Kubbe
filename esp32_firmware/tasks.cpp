#include "tasks.h"
#include "uart_protocol.h"
#include "pid_control.h"
#include "lidar.h"
#include "safety.h"


// ---------------- ZAMANLAMA SABİTLERİ ----------------
// TELEMETRY_INTERVAL_MS / UART_FAILSAFE_MS artik uart_protocol.h'den geliyor
// (TLM_PERIOD_MS, UART_FAILSAFE_MS) 
#define TASK_LOOP_DELAY_MS   2


// ---------------- seq / paket kaybi takibi ----------------
static bool     haveLastAimSeq   = false;
static uint8_t  lastAimSeq       = 0;
static uint16_t lostPktsAccum    = 0;   // son 1 saniyelik pencerede
static unsigned long lostPktsWindowStart = 0;

static bool commLostFreezeActive = false;

// uart_protocol.h'nin bekledigi CALLBACK'LER - gelen her mesaj turu icin

void onCmdHeartbeat() {
    // uartProtocolPoll() zaten "son gecerli paket zamani"ni gunceller.
}

void onCmdAim(const CmdAimPayload &p) {
    // ---- seq atlama / paket kaybi sayaci (TLM_STATE.lost_pkts icin) ----
    if (haveLastAimSeq) {
        uint8_t expected = (uint8_t)(lastAimSeq + 1);
        if (p.seq != expected) {
            uint8_t gap = (uint8_t)(p.seq - expected);   // wraparound-safe (uint8_t farki)
            lostPktsAccum = (uint16_t)(lostPktsAccum + gap + 1);
        }
    }
    lastAimSeq = p.seq;
    haveLastAimSeq = true;

    safety_setLastCtrlBits(p.ctrl);

    // CMD_AIM 50 Hz geldigi icin, motor zaten calisiyorken her
    // pakette pid_resumeAfterEstop() cagirmak PID'in integral/derivative
    // durumunu her 20ms'de sifirlardi. Bu yuzden resume SADECE motor
    // GERCEKTEN durdurulmus durumdaysa (pid_isEmergencyStopped()) cagirilir.
    if (!(p.ctrl & CTRL_MOTOR_EN)) {
        pid_emergencyStop();
    } else if (pid_isEmergencyStopped() &&
               !safety_isEstopActive() && !safety_isAmmoDepleted()) {
        pid_resumeAfterEstop();
    }

    // pid_setTargetAngles kendi icinde AZIMUTH/ELEVATION limitlerine kirpar ve gerekirse ERR_AZ_LIMIT/ERR_EL_LIMIT gonderir (pid_control.cpp).
    pid_setTargetAngles(p.azimuthDeg, p.elevationDeg);
}

void onCmdFire(const CmdFirePayload &p) {
    uint8_t ctrl = safety_getLastCtrlBits();
    bool noFireRequested = (ctrl & CTRL_NO_FIRE) != 0;   // PDF: dost/yasak bolge biti RPi'den gelir
    float rangeM = lidar_getLastDistanceCm() / 100.0f;

    uint8_t shotsFired = 0;
    FireBlockReason lastReason = FIRE_OK;

    for (uint8_t i = 0; i < p.shotCount; i++) {
    lastReason = safety_canFire(
    pid_getCurrentAzimuthDeg(),
    TARGET_UAV,
    rangeM,
    noFireRequested,
    lidar_isDataFresh(),
    lidar_isSignalReliable(lidar_getLastStrength())
);

    if (lastReason != FIRE_OK) {
        break;
    }
    if (!safety_fireSolenoid()) {
        lastReason = FIRE_BLOCKED_AMMO_EMPTY;
        break;
    }
    shotsFired++;

    // Son atis degilse, solenoidin fiziksel olarak kapanip besleme mekanizmasinin bir sonraki boncuga gecmesi icin bekle.
    if (i + 1 < p.shotCount) {
        vTaskDelay(pdMS_TO_TICKS(SHOT_INTERVAL_MS));
    }
}

    if (p.shotCount == 0) {
        lastReason = FIRE_OK;   // istek yoksa hata yok, 0 atis onaylanir
    }

    sendAckFire(shotsFired, (uint8_t)safety_getAmmoRemaining(),
                safety_fireResultCode(lastReason));
}

void onCmdMode(uint8_t mode) {
    // Yazilimsal SAFE_STOP'tan cikis yolu: mod degisikligi geldiginde, fiziksel buton serbest ve muhimmat varsa temizlenmeye calisilir.
    safety_tryClearSoftwareSafeStop();

    safety_setMode(mode);
    sendAck(CMD_MODE, ACK_STATUS_OK);
}

void onCmdSafe(uint8_t reason) {
    safety_onCmdSafe(reason);
    sendAck(CMD_SAFE, ACK_STATUS_OK);
}

void onCmdHome() {
    safety_tryClearSoftwareSafeStop();

    if (!safety_isHomeAllowed()) {
        sendAck(CMD_HOME, ACK_STATUS_REJECTED);
        return;
    }

    pid_setTargetAngles(0.0f, 0.0f);
    safety_startHoming();
    sendAck(CMD_HOME, ACK_STATUS_OK);
}

void onCmdPid(const CmdPidPayload &p) {
    uint8_t mode = safety_getMode();
    if (mode != PROTO_MODE_IDLE && mode != PROTO_MODE_MANUAL) {
        sendAck(CMD_PID, ACK_STATUS_REJECTED);
        return;
    }
    if (p.axis != 0 && p.axis != 1) {
        sendAck(CMD_PID, ACK_STATUS_BAD_PARAM);
        return;
    }

    AxisId axis = (p.axis == 0) ? AXIS_AZIMUTH : AXIS_ELEVATION;
    pid_setGains(axis, p.kp, p.ki, p.kd);
    sendAck(CMD_PID, ACK_STATUS_OK);
}


// GOREV 1: RPi HABERLESMESI
static void taskCommRpi(void *pvParameters) {
    (void)pvParameters;

    lostPktsWindowStart = millis();

    for (;;) {

        // Gelen tum paketleri isle (callback'ler yukarida cagirilir)
        uartProtocolPoll();

        unsigned long silenceMs = uartProtocolMsSinceLastValidPacket();

        // ---------------- BAGLANTI KOPMA IZLEME (Failsafe) ----------------
        if (!commLostFreezeActive && silenceMs > UART_FAILSAFE_MS) {
            pid_emergencyStop();
            commLostFreezeActive = true;
            sendErr(ERR_UART_TIMEOUT, (uint16_t)silenceMs);
            Serial.println("[COMM] RPi'den veri kesildi (timeout)! Motor guvenlik icin donduruldu.");
        }

        // ---------------- BAGLANTI GERI GELDI (herhangi bir gecerli paket - ----------------
        // CMD_HEARTBEAT dahil - hattin canli oldugunu kanitlar
        if (commLostFreezeActive && silenceMs <= UART_FAILSAFE_MS) {
            commLostFreezeActive = false;
            if (!safety_isEstopActive() && !safety_isAmmoDepleted()) {
                pid_resumeAfterEstop();
                Serial.println("[COMM] RPi baglantisi geri geldi, motor serbest birakildi.");
            }
        }

        // ---------------- 1 SANIYELIK lost_pkts PENCERESI ----------------
        if (millis() - lostPktsWindowStart >= 1000) {
            lostPktsWindowStart = millis();
            lostPktsAccum = 0;   // yeni pencere - TLM_STATE bir onceki toplami zaten gonderdi
        }

        // ---------------- PERIYODIK TELEMETRI (TLM_STATE, PDF 0x81) ----------------
        static unsigned long lastTelemetryMillis = 0;
        if (millis() - lastTelemetryMillis >= TLM_PERIOD_MS) {
            lastTelemetryMillis = millis();

            float distM = lidar_getLastDistanceCm() / 100.0f;
            uint16_t lidarMm = lidar_isDataFresh() ? (uint16_t)(distM * 1000.0f) : 0xFFFF;

            sendTlmState(
                safety_getProtocolState(),
                pid_getCurrentAzimuthDeg(),
                pid_getCurrentElevationDeg(),
                lidarMm,
                (uint8_t)safety_getAmmoRemaining(),
                safety_buildTelemetryFlags(),
                (uint8_t)(lostPktsAccum > 255 ? 255 : lostPktsAccum)
            );
        }

        vTaskDelay(pdMS_TO_TICKS(TASK_LOOP_DELAY_MS));
    }
}


// GOREV 2: MOTOR KONTROL (safety + PID) - EN YUKSEK ONCELIK, AYRI CEKIRDEK
static void taskMotorControl(void *pvParameters) {
    (void)pvParameters;

    for (;;) {
        safety_update();
        pid_update();

        vTaskDelay(pdMS_TO_TICKS(TASK_LOOP_DELAY_MS));
    }
}


// GOREV 3: LIDAR OKUMA
static void taskLidar(void *pvParameters) {
    (void)pvParameters;

    LidarReading reading;
    static bool lidarTimeoutReported = false;

    for (;;) {
        lidar_read(reading);

        if (!lidar_isDataFresh(1000)) {
            if (!lidarTimeoutReported) {
                sendErr(ERR_LIDAR_TIMEOUT, 0);
                lidarTimeoutReported = true;
            }
        } else {
            lidarTimeoutReported = false;
        }

        vTaskDelay(pdMS_TO_TICKS(TASK_LOOP_DELAY_MS));
    }
}


void tasks_startAll() {
    uartProtocolInit();

    xTaskCreatePinnedToCore(taskCommRpi,     "CommRPi",   TASK_STACK_UART,  NULL, TASK_PRIORITY_UART,  NULL, 0);
    xTaskCreatePinnedToCore(taskMotorControl,"MotorCtrl", TASK_STACK_MOTOR, NULL, TASK_PRIORITY_MOTOR, NULL, 1);
    xTaskCreatePinnedToCore(taskLidar,       "Lidar",     TASK_STACK_LIDAR, NULL, TASK_PRIORITY_LIDAR, NULL, 0);

    Serial.println("[TASKS] Tum FreeRTOS gorevleri baslatildi (CommRPi:core0, MotorCtrl:core1, Lidar:core0).");
}