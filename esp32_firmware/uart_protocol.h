#ifndef UART_PROTOCOL_H
#define UART_PROTOCOL_H

#include <Arduino.h>


// ---------------- PAKET SABİTLERİ ----------------
#define UART_PREAMBLE          0xAA55
#define UART_PACKET_SIZE       14      
#define UART_CRC_POLY          0xA001  // CRC-16/MODBUS 

// Byte offsetleri 
#define OFFSET_PREAMBLE         0   // 2 byte
#define OFFSET_MSG_ID           2   // 1 byte
#define OFFSET_TARGET_AZIMUTH   3   // 4 byte (float32)
#define OFFSET_TARGET_ELEVATION 7   // 4 byte (float32)
#define OFFSET_CTRL_BITS        11  // 1 byte
#define OFFSET_CRC16             12  // 2 byte

// ---------------- MSG_ID ----------------
enum UartMsgId : uint8_t {
    MSG_MOVE_TARGET_ANGLES   = 0x01,  // SBC -> MCU: hedef azimuth/elevasyon komutu
    MSG_TRIGGER_FIRE         = 0x02,  // SBC -> MCU: ateşleme emri
    MSG_ESTOP_COMMAND        = 0x03,  // SBC -> MCU: yazılımsal acil durdurma
    MSG_HEARTBEAT            = 0x04,  // Çift yönlü: bağlantı canlılık kontrolü

    MSG_TELEMETRY_STATUS     = 0x10,  // MCU -> SBC: açı, mod, durum telemetrisi
    MSG_LIDAR_RANGE          = 0x11,  // MCU -> SBC: LiDAR mesafe verisi
    MSG_AMMO_STATUS          = 0x12,  // MCU -> SBC: kalan mühimmat bilgisi
    MSG_ERROR_FLAG           = 0x13,  // MCU -> SBC: hata kodu 
};

// ---------------- CTRL_BITS BIT ----------------
#define CTRL_BIT_FIRE_REQUEST     (1 << 0)  // Ateşleme isteği aktif
#define CTRL_BIT_LASER_ON         (1 << 1)  // Hedefleme lazeri açık
#define CTRL_BIT_AUTONOMOUS_MODE  (1 << 2)  // 1: otonom mod, 0: manuel mod
#define CTRL_BIT_TARGET_FRIENDLY  (1 << 3)  // 1: dost unsur (ateş bloklanır)
#define CTRL_BIT_ESTOP_ACTIVE     (1 << 4)  // 1: E-Stop tetiklenmiş


#pragma pack(push, 1)
struct UartPacket {
    uint16_t preamble;         
    uint8_t  msgId;           
    float    targetAzimuth;   
    float    targetElevation;  
    uint8_t  ctrlBits;         
    uint16_t crc16;           
};
#pragma pack(pop)

static_assert(sizeof(UartPacket) == UART_PACKET_SIZE,
              "UartPacket boyutu 14 byte olmalı - pragma pack kontrol edin");


// UART hattını başlatır
void uartProtocolInit();

// CRC-16/MODBUS hesaplar (preamble hariç, msgId'den ctrlBits'e kadar 9 byte üzerinden
// veya tüm paket üzerinden - implementasyonda netleştirilecek)
// Hangi byte aralığının CRC'ye dahil edileceği: (msgId -> ctrlBits, preamble ve crc alanlarının kendisi HARİÇ) 
uint16_t calculateCRC16(const uint8_t *data, size_t length);

// Gelen byte akışını dinler, tam ve geçerli bir paket varsa true döner ve packet parametresine doldurur. 
bool uartReceivePacket(UartPacket &packet);

// Bir UartPacket'i binary formata çevirip UART üzerinden gönderir.
void uartSendPacket(UartPacket &packet);

// Telemetri gönderimi için yardımcı - esp nin düzenli rapor gönderim için
void uartSendTelemetry(float currentAzimuth, float currentElevation,
                        uint8_t systemState, float lidarRangeM);

// Hata-uyarı kodu gönderimi için yardımcı fonksiyon
void uartSendErrorFlag(uint8_t errorCode);

#endif