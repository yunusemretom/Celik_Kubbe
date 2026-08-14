#include "tasks.h"
#include "uart_protocol.h"
#include "pid_control.h"
#include "lidar.h"
#include "safety.h"
#include "joystick.h"
#include "trigger.h"


// ---------------- ZAMANLAMA SABİTLERİ ----------------
#define TASK_LOOP_DELAY_MS   2


// ---------------- seq / paket kaybi takibi ----------------
static bool     haveLastAimSeq   = false;
static uint8_t  lastAimSeq       = 0;
static uint16_t lostPktsAccum    = 0;   // son 1 saniyelik pencerede
static unsigned long lostPktsWindowStart = 0;

static bool commLostFreezeActive = false;

// ---------------- joystick tetik durumu ----------------
static bool          prevFirePressed = false;
static unsigned long lastShotMillis  = 0;


// ====================================================================
// MOD -> KONTROL MODU ESLEMESI
//
// MANUAL      : joystick, encoder yok  -> ACIK CEVRIM HIZ
// digerleri   : RPi CMD_AIM, encoder   -> KAPALI CEVRIM POZISYON
//
// Bu iki yolun ayni anda motoru surmesi "iki efendi" problemidir;
// mod tek bir yeri sahibi yapar.
// ====================================================================
static void applyModeToController(uint8_t protoMode) {
    if (protoMode == PROTO_MODE_MANUAL) {
        pid_setControlMode(PID_MODE_VELOCITY);
    } else {
        pid_setControlMode(PID_MODE_POSITION);
    }
}


// uart_protocol.h'nin bekledigi CALLBACK'LER

void onCmdHeartbeat() {
    // uartProtocolPoll() zaten "son gecerli paket zamani"ni gunceller.
}

void onCmdAim(const CmdAimPayload &p) {
    // ---- seq atlama / paket kaybi sayaci (TLM_STATE.lost_pkts icin) ----
    if (haveLastAimSeq) {
        uint8_t expected = (uint8_t)(lastAimSeq + 1);
        if (p.seq != expected) {
            uint8_t gap = (uint8_t)(p.seq - expected);   // wraparound-safe
            lostPktsAccum = (uint16_t)(lostPktsAccum + gap + 1);
        }
    }
    lastAimSeq = p.seq;
    haveLastAimSeq = true;

    // MANUEL MODDA CMD_AIM YOK SAYILIR.
    // Joystick UDP ile dogrudan gelirken RPi de aci komutu gonderirse
    // ikisi birbirini ezer ve taret titrer.
    if (safety_getMode() == PROTO_MODE_MANUAL) {
        return;
    }

    safety_setLastCtrlBits(p.ctrl);

    // CMD_AIM 50 Hz geldigi icin her pakette pid_resumeAfterEstop()
    // cagirmak PID durumunu 20 ms'de bir sifirlardi. Resume SADECE motor
    // gercekten durdurulmus durumdaysa cagirilir.
    if (!(p.ctrl & CTRL_MOTOR_EN)) {
        pid_emergencyStop();
    } else if (pid_isEmergencyStopped() &&
               !safety_isEstopActive() && !safety_isAmmoDepleted()) {
        pid_resumeAfterEstop();
    }

    pid_setTargetAngles(p.azimuthDeg, p.elevationDeg);
}

void onCmdFire(const CmdFirePayload &p) {
    // Manuel modda ates joystick'ten gelir; RPi'nin CMD_FIRE'i kabul edilmez.
    if (safety_getMode() == PROTO_MODE_MANUAL) {
        sendAckFire(0, (uint8_t)safety_getAmmoRemaining(), FIRE_RESULT_NO_ARM);
        return;
    }

    uint8_t ctrl = safety_getLastCtrlBits();
    bool noFireRequested = (ctrl & CTRL_NO_FIRE) != 0;
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
        if (!safety_fireTrigger()) {
            lastReason = FIRE_BLOCKED_ACTUATOR_BUSY;
            break;
        }
        shotsFired++;

        // Tetik servosunun cekip birakmasi ve beslemenin oturmasi icin bekle.
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
    safety_tryClearSoftwareSafeStop();

    safety_setMode(mode);
    applyModeToController(mode);

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

    if (pid_getControlMode() == PID_MODE_VELOCITY) {
        // Encoder yokken "eve donus" diye bir sey yok; yapabilecegimiz tek
        // sey pozisyon TAHMINININ sifirini burasi kabul etmek. Taret
        // mekanik olarak 0/0'a getirilmis olmalidir.
        pid_zeroPositionEstimate();
        sendAck(CMD_HOME, ACK_STATUS_OK);
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

        uartProtocolPoll();

        unsigned long silenceMs = uartProtocolMsSinceLastValidPacket();

        // ---------------- BAGLANTI KOPMA IZLEME (Failsafe) ----------------
        // MANUEL MODDA RPi FAILSAFE'I DEVRE DISI.
        // Joystick dogrudan UDP ile geldigi icin RPi hic bagli olmayabilir;
        // eski kod bu durumda motoru surekli dondurup joystick'i olduruyordu.
        // Manuel modda gorevi joystick_isFresh() watchdog'u ustlenir.
        bool rpiFailsafeActive = (safety_getMode() != PROTO_MODE_MANUAL);

        if (rpiFailsafeActive && !commLostFreezeActive && silenceMs > UART_FAILSAFE_MS) {
            pid_emergencyStop();
            trigger_forceRelease();
            commLostFreezeActive = true;
            sendErr(ERR_UART_TIMEOUT, (uint16_t)silenceMs);
            Serial.println("[COMM] RPi'den veri kesildi (timeout)! Motor guvenlik icin donduruldu.");
        }

        // ---------------- BAGLANTI GERI GELDI ----------------
        if (commLostFreezeActive && (!rpiFailsafeActive || silenceMs <= UART_FAILSAFE_MS)) {
            commLostFreezeActive = false;
            if (!safety_isEstopActive() && !safety_isAmmoDepleted()) {
                pid_resumeAfterEstop();
                Serial.println("[COMM] RPi baglantisi geri geldi, motor serbest birakildi.");
            }
        }

        // ---------------- 1 SANIYELIK lost_pkts PENCERESI ----------------
        if (millis() - lostPktsWindowStart >= 1000) {
            lostPktsWindowStart = millis();
            lostPktsAccum = 0;
        }

        // ---------------- PERIYODIK TELEMETRI (TLM_STATE) ----------------
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


// GOREV 2: MOTOR KONTROL (safety + PID) - AYRI CEKIRDEK
static void taskMotorControl(void *pvParameters) {
    (void)pvParameters;

    for (;;) {
        safety_update();    // icinde trigger_update() de var
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


// ====================================================================
// JOYSTICK TETIK MANTIGI
//
// fire biti basili tutuldugu surece tarayici 25 Hz'de "fire=1" gonderir.
// Her pakette atis yapmak olmaz; bu yuzden:
//   - ilk 0->1 gecisinde bir atis
//   - basili kalmaya devam ederse SHOT_INTERVAL_MS'de bir tekrar
//     (JOYSTICK_FIRE_AUTOREPEAT 0 ise sadece tek atis)
//   - birakildiginda durur
// ACK_FIRE sadece gercek bir olayda gonderilir, 50 Hz spam yapilmaz.
// ====================================================================
static void handleJoystickFire(bool firePressed) {

    if (!firePressed) {
        prevFirePressed = false;
        return;
    }

    bool edge = !prevFirePressed;
    prevFirePressed = true;

    if (!edge) {
        if (!JOYSTICK_FIRE_AUTOREPEAT) return;
        if ((millis() - lastShotMillis) < SHOT_INTERVAL_MS) return;
    }

    if (trigger_isBusy()) return;

    float rangeM = lidar_getLastDistanceCm() / 100.0f;

    FireBlockReason reason = safety_canFire(
        pid_getCurrentAzimuthDeg(),
        TARGET_UAV,
        rangeM,
        false,                                    // manuel modda dost/dusman karari operatorun
        lidar_isDataFresh(),
        lidar_isSignalReliable(lidar_getLastStrength())
    );

    if (reason != FIRE_OK) {
        // Sadece tusa ilk basista bildir; basili tutarken hatti bogmasin.
        if (edge) {
            sendAckFire(0, (uint8_t)safety_getAmmoRemaining(),
                        safety_fireResultCode(reason));
        }
        return;
    }

    if (safety_fireTrigger()) {
        lastShotMillis = millis();
        sendAckFire(1, (uint8_t)safety_getAmmoRemaining(), FIRE_RESULT_OK);
    }
}


// GOREV 4: JOYSTICK (YKI arayuzunden UDP)
static void taskJoystick(void *pvParameters) {
    (void)pvParameters;

    const TickType_t periyot = pdMS_TO_TICKS(JOYSTICK_TASK_PERIOD_MS);
    TickType_t sonUyanma = xTaskGetTickCount();

    static bool timeoutReported = false;

    for (;;) {
        joystick_update();

        if (safety_getMode() != PROTO_MODE_MANUAL) {
            // Manuel disi modlarda joystick sessizdir.
            prevFirePressed = false;
            vTaskDelayUntil(&sonUyanma, periyot);
            continue;
        }

        // ---------------- WATCHDOG ----------------
        // Paket akisi kesilirse (WiFi koptu, tarayici kapandi) taret durur
        // ve tetik birakilir. Son paket "fire=1" olsa bile.
        if (!joystick_isFresh()) {
            pid_setVelocityCommand(0.0f, 0.0f);
            trigger_forceRelease();
            prevFirePressed = false;
            safety_setLastCtrlBits(0);   // ARM ve MOTOR_EN dus

            if (!timeoutReported) {
                timeoutReported = true;
                Serial.println("[JOYSTICK] Veri kesildi - eksenler durduruldu, tetik birakildi.");
            }
            vTaskDelayUntil(&sonUyanma, periyot);
            continue;
        }
        timeoutReported = false;

        JoystickInput js = joystick_get();

        // ---------------- CTRL BITLERI ----------------
        // ARM artik KOSULSUZ set edilmiyor: operator arayuzden acmali.
        // (eski taslak surekli CTRL_ARM|CTRL_MOTOR_EN yaziyordu, yani
        //  emniyet mandali hep aciktı.)
        uint8_t ctrl = CTRL_MOTOR_EN;
        if (js.arm) ctrl |= CTRL_ARM;
        safety_setLastCtrlBits(ctrl);

        // ---------------- HAREKET ----------------
        if (safety_isEstopActive() || safety_isAmmoDepleted()) {
            pid_setVelocityCommand(0.0f, 0.0f);
            prevFirePressed = false;
            vTaskDelayUntil(&sonUyanma, periyot);
            continue;
        }

        if (pid_isEmergencyStopped()) {
            pid_resumeAfterEstop();
        }

        // yaw  -> azimut (sag = +)
        // pitch-> elevasyon (yukari = +)
        pid_setVelocityCommand(js.yaw   * JOYSTICK_AZ_RATE_DEG_S,
                               js.pitch * JOYSTICK_EL_RATE_DEG_S);

        // ---------------- ATES ----------------
        handleJoystickFire(js.fire);

        vTaskDelayUntil(&sonUyanma, periyot);
    }
}


void tasks_startAll() {
    uartProtocolInit();

    // Acilis modunu kontrolcuye uygula (config.h > DEFAULT_BOOT_MODE_MANUAL)
    applyModeToController(safety_getMode());

    xTaskCreatePinnedToCore(taskCommRpi,      "CommRPi",   TASK_STACK_UART,     NULL, TASK_PRIORITY_UART,     NULL, 0);
    xTaskCreatePinnedToCore(taskMotorControl, "MotorCtrl", TASK_STACK_MOTOR,    NULL, TASK_PRIORITY_MOTOR,    NULL, 1);
    xTaskCreatePinnedToCore(taskLidar,        "Lidar",     TASK_STACK_LIDAR,    NULL, TASK_PRIORITY_LIDAR,    NULL, 0);
    xTaskCreatePinnedToCore(taskJoystick,     "Joystick",  TASK_STACK_JOYSTICK, NULL, TASK_PRIORITY_JOYSTICK, NULL, 0);

    Serial.println("[TASKS] Gorevler basladi (CommRPi/Lidar/Joystick:core0, MotorCtrl:core1).");
}