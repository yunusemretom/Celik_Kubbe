#ifndef UART_PROTOCOL_H
#define UART_PROTOCOL_H

#include <Arduino.h>

// ====================================================================
// PARS - SBC (RPi) <-> MCU (ESP32) UART Haberlesme Protokolu
// Surum: 1.3  (bkz. PARS_UART_Haberlesme_Protokolu_v1_3.pdf)
// Bu dosya PDF'teki Ek A sabitleriyle bire bir eslesir.
// ====================================================================

// ---------------- CERCEVE SABITLERI ----------------
#define UART_PREAMBLE_1     0xAA
#define UART_PREAMBLE_2     0x55
#define UART_MAX_PAYLOAD    32
#define UART_FRAME_OVERHEAD 6      // preamble(2) + msgId(1) + len(1) + crc(2)

// CRC-16/CCITT-FALSE parametreleri (PDF Bolum 3)
#define UART_CRC_POLY       0x1021
#define UART_CRC_INIT       0xFFFF

// ---------------- MSG_ID (yon: bit7 set ise ESP32 -> RPi) ----------------
// RPi -> ESP32
#define CMD_HEARTBEAT   0x00   // LEN 0
#define CMD_AIM         0x01   // LEN 10
#define CMD_FIRE        0x02   // LEN 2
#define CMD_MODE        0x03   // LEN 1
#define CMD_SAFE        0x04   // LEN 1
#define CMD_HOME        0x05   // LEN 0
#define CMD_PID         0x06   // LEN 13

// ESP32 -> RPi (0x80 biti set)
#define TLM_STATE       0x81   // LEN 14
#define ACK_FIRE        0x82   // LEN 3
#define ACK             0x83   // LEN 2
#define ERR             0xE0   // LEN 3

// ---------------- ctrl bitleri (CMD_AIM payload, offset 9) ----------------
#define CTRL_ARM        0x01   // bit0 - emniyet mandali, 0 iken ates yok
#define CTRL_LASER      0x02   // bit1 - hedefleme lazeri
#define CTRL_MOTOR_EN   0x04   // bit2 - motor surucular etkin
#define CTRL_NO_FIRE    0x08   // bit3 - hedef yasak bolgede
// bit4-7 reserved, her zaman 0

// ---------------- flags bitleri (TLM_STATE payload, offset 12) ----------------
#define FLAG_ARMED       0x01  // bit0
#define FLAG_MOTORS_ON   0x02  // bit1
#define FLAG_LOCKED      0x04  // bit2 - ATES ICIN BU BIT BEKLENIR (RPi tarafi)
#define FLAG_ESTOP       0x08  // bit3
#define FLAG_AZ_LIMIT    0x10  // bit4
#define FLAG_EL_LIMIT    0x20  // bit5
#define FLAG_LASER_ON    0x40  // bit6
#define FLAG_AMMO_EMPTY  0x80  // bit7

// ---------------- CMD_MODE degerleri ----------------
#define PROTO_MODE_IDLE                 0
#define PROTO_MODE_MANUAL               1
#define PROTO_MODE_AUTONOMOUS_SWARM     2
#define PROTO_MODE_AUTONOMOUS_LAYERED   3

// ---------------- TLM_STATE.state degerleri ----------------
// NOT: config.h'deki SystemState enum'unda ekstra ST_EMERGENCY_SHUTDOWN var.
// Telemetriye yazarken protocolStateFromSystemState() ile bu 5 degere indirilir;
// fiziksel/yazilimsal E-Stop ayrimi FLAG_ESTOP biti ile tasinir (bkz. PDF Bolum 6).
#define PROTO_ST_INIT       0
#define PROTO_ST_STANDBY    1
#define PROTO_ST_TRACKING   2
#define PROTO_ST_ENGAGE     3
#define PROTO_ST_SAFE_STOP  4

// ---------------- ACK_FIRE.result degerleri ----------------
#define FIRE_RESULT_OK              0
#define FIRE_RESULT_NO_ARM          1
#define FIRE_RESULT_NO_AMMO         2
#define FIRE_RESULT_OUT_OF_LIMIT    3
#define FIRE_RESULT_NO_FIRE_ZONE    4
#define FIRE_RESULT_NOT_LOCKED      5

// ---------------- CMD_SAFE.reason degerleri ----------------
#define SAFE_REASON_OPERATOR      1
#define SAFE_REASON_AMMO_EMPTY    2
#define SAFE_REASON_TARGET_LOST   3
#define SAFE_REASON_RPI_ERROR     4

// ---------------- ACK.status degerleri ----------------
#define ACK_STATUS_OK        0
#define ACK_STATUS_REJECTED  1
#define ACK_STATUS_BAD_PARAM 2

// ---------------- ERR.code degerleri ----------------
#define ERR_ESTOP           0x01  // detail: 0
#define ERR_AZ_LIMIT        0x02  // detail: talep edilen aci x10, int16
#define ERR_EL_LIMIT        0x03  // detail: talep edilen aci x10, int16
#define ERR_AMMO_DEPLETED   0x04  // detail: 0
#define ERR_UART_TIMEOUT    0x05  // detail: sessiz kalinan ms
#define ERR_CRC_BURST       0x06  // detail: hata sayisi
#define ERR_DRIVER_FAULT    0x07  // detail: 0 azimut, 1 elevasyon
#define ERR_LIDAR_TIMEOUT   0x08  // detail: 0

// ---------------- Zamanlama sabitleri (PDF Ek A) ----------------
#define UART_BAUD_RATE      115200
#define AIM_PERIOD_MS       20     // 50 Hz
#define TLM_PERIOD_MS       20     // 50 Hz
#define HEARTBEAT_MS        50     // 20 Hz, CMD_AIM akmiyorken RPi tarafinda kullanilir
#define UART_FAILSAFE_MS    200    // sessizlik siniri (10 ardisik CMD_AIM kaybi)
#define ACK_TIMEOUT_MS       100    // RPi'nin ACK icin bekleme suresi (RPi tarafi bilgisi, referans)
#define CRC_BURST_LIMIT      20     // ardisik CRC hatasi esigi -> ERR_CRC_BURST

// ====================================================================
// AYRISTIRILMIS (CAGIRANA HAZIR) PAYLOAD YAPILARI
// Bunlar tel uzerindeki formatla AYNI DEGIL (tel formati little-endian
// ham byte dizisi + degisken LEN). Bu structlar sadece parser'in
// handleMessage() cagirana verdigi kolay-kullanim goruntusudur.
// ====================================================================

struct CmdAimPayload {
    uint8_t seq;
    float   azimuthDeg;
    float   elevationDeg;
    uint8_t ctrl;
};

struct CmdFirePayload {
    uint8_t shotCount;
    uint8_t targetId;
};

struct CmdPidPayload {
    uint8_t axis;   // 0: azimut, 1: elevasyon
    float   kp;
    float   ki;
    float   kd;
};

// ---------------- API ----------------

// UART hattini baslatir (Serial1, config.h'deki RPI_UART_* pin/baud ile)
void uartProtocolInit();

// CRC-16/CCITT-FALSE hesaplar. data: MSG_ID'den basliyor (LEN + PAYLOAD dahil,
// preamble ve CRC alaninin kendisi HARIC). PDF Bolum 3 dogrulama testi:
// crc16_ccitt_false({0x00, 0x00}) == 0x1D0F  olmali.
uint16_t crc16_ccitt_false(const uint8_t *data, size_t length);

// Gelen byte akisini isler (BLOKLAMAZ). Tam ve CRC'si dogru bir cerceve
// bulundugunda ilgili on_XXX callback'i (asagida) cagirir ve true doner.
// Bulunamadiysa false doner. loop()/task icinde surekli cagrilmalidir.
bool uartProtocolPoll();

// ---------------- GELEN MESAJ CALLBACK'LERI ----------------
// tasks.cpp bunlari kendi handleMessage() mantigina baglar - task.cppde tanımlandılar
void onCmdHeartbeat();
void onCmdAim(const CmdAimPayload &p);
void onCmdFire(const CmdFirePayload &p);
void onCmdMode(uint8_t mode);
void onCmdSafe(uint8_t reason);
void onCmdHome();
void onCmdPid(const CmdPidPayload &p);

// Son gecerli paketten bu yana gecen sure (ms). 
unsigned long uartProtocolMsSinceLastValidPacket();

// ---------------- GONDERME FONKSIYONLARI (ESP32 -> RPi) ----------------

void sendTlmState(uint8_t protoState, float azimuthDeg, float elevationDeg,
                   uint16_t lidarRangeMm, uint8_t ammo, uint8_t flags,
                   uint8_t lostPkts);

void sendAckFire(uint8_t shotsFired, uint8_t ammoLeft, uint8_t result);

void sendAck(uint8_t ackedId, uint8_t status);

void sendErr(uint8_t code, uint16_t detail);

#endif