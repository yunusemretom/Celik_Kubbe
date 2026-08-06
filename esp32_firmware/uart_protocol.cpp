#include "uart_protocol.h"
#include "config.h"
#include <string.h>


//UART1'i (num=1) config.h'deki RPI_UART_RX_PIN / RPI_UART_TX_PIN pinlerine atıyoruz:
HardwareSerial rpiSerial(1);


// Paket ayrıştırıcı (parser) durum makinesi
// Byte'lar tek tek geldikçe non-blocking şekilde işlenir; loop() içinde
// her çağrıda "elimde tam ve geçerli bir paket var mı?" diye bakılır.

enum ParserState {
    WAIT_SYNC1,   // 0x55 bekleniyor
    WAIT_SYNC2,   // 0xAA bekleniyor
    READ_BODY     // geri kalan byte'lar okunuyor 14 byte tamamlanana kadar toplanır
};

static ParserState parserState;
static uint8_t rxBuffer[UART_PACKET_SIZE];
static uint8_t rxIndex = 0;

void uartProtocolInit() {
    rpiSerial.begin(RPI_UART_BAUD, SERIAL_8N1, RPI_UART_RX_PIN, RPI_UART_TX_PIN);
    parserState = WAIT_SYNC1;
    rxIndex = 0;
}


// CRC-16/MODBUS hesabı:
uint16_t calculateCRC16(const uint8_t *data, size_t length) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < length; i++) {
        crc ^= (uint16_t)data[i];
        for (uint8_t bit = 0; bit < 8; bit++) {
            if (crc & 0x0001) {
                crc >>= 1;
                crc ^= UART_CRC_POLY;
            } else {
                crc >>= 1;
            }
        }
    }
    return crc;
}


//Bu fonksiyon BLOKLAMAZ (delay/bekleme yoktur) - loop() içinde sürekli çağrılmaya uygundur.
bool uartReceivePacket(UartPacket &packet) {
    while (rpiSerial.available() > 0) {
        uint8_t incoming = (uint8_t)rpiSerial.read();

        switch (parserState) {

            case WAIT_SYNC1:
                // Preamble 0xAA55 - bellekte little-endian saklanır,
                // ilk gelen byte 0x55
                if (incoming == 0x55) {
                    rxBuffer[0] = incoming;
                    parserState = WAIT_SYNC2;
                }
                break;

            case WAIT_SYNC2:
                if (incoming == 0xAA) {
                    rxBuffer[1] = incoming;
                    rxIndex = 2;
                    parserState = READ_BODY;
                } else if (incoming == 0x55) {
                    rxBuffer[0] = incoming;
                } else {
                    parserState = WAIT_SYNC1;
                }
                break;

            case READ_BODY:
                rxBuffer[rxIndex++] = incoming;

                if (rxIndex >= UART_PACKET_SIZE) {
                    // Paket tamamlandı - CRC doğrula
                    uint16_t receivedCrc;
                    memcpy(&receivedCrc, &rxBuffer[OFFSET_CRC16], sizeof(uint16_t));

                    uint16_t calcCrc = calculateCRC16(
                        &rxBuffer[OFFSET_MSG_ID],
                        OFFSET_CRC16 - OFFSET_MSG_ID  
                    );

                    // Durumu sıfırla - bir sonraki paket için hazır ol
                    parserState = WAIT_SYNC1;
                    rxIndex = 0;

                    if (calcCrc == receivedCrc) {
                        memcpy(&packet, rxBuffer, UART_PACKET_SIZE);
                        return true;  
                    }
                    // CRC uyuşmuyorsa paket sessizce atılır 
                }
                break;
        }
    }
    return false; 
}



// preamble ve crc16 alanları burada otomatik hesaplanıp yazılır, çağıran fonksiyonun bunlarla uğraşmasına gerek yoktur.
void uartSendPacket(UartPacket &packet) {
    packet.preamble = UART_PREAMBLE;

    uint8_t txBuffer[UART_PACKET_SIZE];
    memcpy(txBuffer, &packet, UART_PACKET_SIZE);

    uint16_t crc = calculateCRC16(&txBuffer[OFFSET_MSG_ID], OFFSET_CRC16 - OFFSET_MSG_ID);
    memcpy(&txBuffer[OFFSET_CRC16], &crc, sizeof(uint16_t));

    rpiSerial.write(txBuffer, UART_PACKET_SIZE);
}


// Telemetri gönderimi.
// Paket formatında sadece 2 adet float alanı var
// (targetAzimuth, targetElevation). Ama telemetri olarak 4 farklı bilgi
// (açı x2 + sistem durumu + LiDAR mesafesi) göndermemiz gerekiyor.
// Tek pakete sığmadığı için burada 2 ayrı paket gönderiyoruz:
//   1) MSG_TELEMETRY_STATUS  -> anlık açı + sistem durumu
//   2) MSG_LIDAR_RANGE       -> LiDAR mesafesi (azimuth alanını ödünç kullanır)
void uartSendTelemetry(float currentAzimuth, float currentElevation,
                        uint8_t systemState, float lidarRangeM) {

    UartPacket statusPkt;
    statusPkt.msgId = MSG_TELEMETRY_STATUS;
    statusPkt.targetAzimuth = currentAzimuth;
    statusPkt.targetElevation = currentElevation;
    statusPkt.ctrlBits = systemState;  
    uartSendPacket(statusPkt);

    UartPacket lidarPkt;
    lidarPkt.msgId = MSG_LIDAR_RANGE;
    lidarPkt.targetAzimuth = lidarRangeM; 
    lidarPkt.targetElevation = 0.0f;       
    lidarPkt.ctrlBits = 0;
    uartSendPacket(lidarPkt);
}


// Hata veya uyarı bayrağı gönderimi:
void uartSendErrorFlag(uint8_t errorCode) {
    UartPacket errPkt;
    errPkt.msgId = MSG_ERROR_FLAG;
    errPkt.targetAzimuth = 0.0f;
    errPkt.targetElevation = 0.0f;
    errPkt.ctrlBits = errorCode;
    uartSendPacket(errPkt);
}