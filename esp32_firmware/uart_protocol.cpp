#include "uart_protocol.h"
#include "config.h"
#include <string.h>

HardwareSerial rpiSerial(1);

// ====================================================================
// CRC-16/CCITT-FALSE
// poly 0x1021, init 0xFFFF, giris/cikis yansitma yok, final XOR 0.
// Test: crc16_ccitt_false({0x00,0x00}) == 0x1D0F 
// ====================================================================
uint16_t crc16_ccitt_false(const uint8_t *data, size_t length) {
    uint16_t crc = UART_CRC_INIT;
    for (size_t i = 0; i < length; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (uint8_t b = 0; b < 8; b++) {
            if (crc & 0x8000) {
                crc = (uint16_t)((crc << 1) ^ UART_CRC_POLY);
            } else {
                crc = (uint16_t)(crc << 1);
            }
        }
    }
    return crc;
}

#define FRAME_RAW_MAX (2 + 2 + UART_MAX_PAYLOAD + 2)  // preamble+id+len+payload+crc

enum ParserState {
    WAIT_A,
    WAIT_55,
    GET_ID,
    GET_LEN,
    GET_PAYLOAD,
    GET_CRC_LO,
    GET_CRC_HI
};

static ParserState parserState = WAIT_A;
static uint8_t  rxId = 0;
static uint8_t  rxLen = 0;
static uint8_t  rxIdx = 0;
static uint8_t  rxBuf[UART_MAX_PAYLOAD];
static uint16_t rxCrc = 0;

static uint8_t  frameRaw[FRAME_RAW_MAX];
static uint8_t  frameRawLen = 0;

static unsigned long lastValidPacketMillis = 0;
static uint16_t consecutiveCrcErrors = 0;
static bool     gotOneFlag = false;

static void feedByte(uint8_t c);

//bozuk/CRC hatali cercevede SADECE ILK BYTE atilir, tarama bir sonraki byte'tan devam eder. 
static void resyncAfterFailedFrame() {
    uint8_t saved[FRAME_RAW_MAX];
    uint8_t savedLen = frameRawLen;
    memcpy(saved, frameRaw, savedLen);

    parserState = WAIT_A;
    frameRawLen = 0;

    for (uint8_t i = 1; i < savedLen; i++) {
        feedByte(saved[i]);
    }
}

static void dispatchMessage(uint8_t id, const uint8_t *p, uint8_t len); // ileri bildirim (asagida tanimli)

static void feedByte(uint8_t c) {
    switch (parserState) {

        case WAIT_A:
            if (c == UART_PREAMBLE_1) {
                frameRawLen = 0;
                frameRaw[frameRawLen++] = c;
                parserState = WAIT_55;
            }
            break;

        case WAIT_55:
            if (frameRawLen < FRAME_RAW_MAX) frameRaw[frameRawLen++] = c;
            if (c == UART_PREAMBLE_2) {
                parserState = GET_ID;
            } else if (c == UART_PREAMBLE_1) {
                frameRawLen = 0;
                frameRaw[frameRawLen++] = c;
                parserState = WAIT_55;
            } else {
                parserState = WAIT_A;
                frameRawLen = 0;
            }
            break;

        case GET_ID:
            if (frameRawLen < FRAME_RAW_MAX) frameRaw[frameRawLen++] = c;
            rxId = c;
            parserState = GET_LEN;
            break;

        case GET_LEN:
            if (frameRawLen < FRAME_RAW_MAX) frameRaw[frameRawLen++] = c;
            rxLen = c;
            rxIdx = 0;
            if (rxLen > UART_MAX_PAYLOAD) {
                resyncAfterFailedFrame();
                return;
            }
            parserState = (rxLen > 0) ? GET_PAYLOAD : GET_CRC_LO;
            break;

        case GET_PAYLOAD:
            if (frameRawLen < FRAME_RAW_MAX) frameRaw[frameRawLen++] = c;
            rxBuf[rxIdx++] = c;
            if (rxIdx >= rxLen) {
                parserState = GET_CRC_LO;
            }
            break;

        case GET_CRC_LO:
            if (frameRawLen < FRAME_RAW_MAX) frameRaw[frameRawLen++] = c;
            rxCrc = c;
            parserState = GET_CRC_HI;
            break;

        case GET_CRC_HI: {
            if (frameRawLen < FRAME_RAW_MAX) frameRaw[frameRawLen++] = c;
            rxCrc |= (uint16_t)c << 8;

            uint8_t body[2 + UART_MAX_PAYLOAD];
            body[0] = rxId;
            body[1] = rxLen;
            memcpy(&body[2], rxBuf, rxLen);
            uint16_t calc = crc16_ccitt_false(body, (size_t)rxLen + 2);

            if (calc == rxCrc) {
                lastValidPacketMillis = millis();
                consecutiveCrcErrors = 0;
                parserState = WAIT_A;
                frameRawLen = 0;
                dispatchMessage(rxId, rxBuf, rxLen);
                gotOneFlag = true;
            } else {
                consecutiveCrcErrors++;
                if (consecutiveCrcErrors >= CRC_BURST_LIMIT) {
                    sendErr(ERR_CRC_BURST, consecutiveCrcErrors);
                    consecutiveCrcErrors = 0;
                }
                resyncAfterFailedFrame();
            }
            break;
        }
    }
}

bool uartProtocolPoll() {
    gotOneFlag = false;
    while (rpiSerial.available() > 0) {
        feedByte((uint8_t)rpiSerial.read());
    }
    return gotOneFlag;
}


// GONDERME

static void sendFrame(uint8_t msgId, const uint8_t *payload, uint8_t len) {
    uint8_t body[2 + UART_MAX_PAYLOAD];
    body[0] = msgId;
    body[1] = len;
    if (len > 0) {
        memcpy(&body[2], payload, len);
    }

    uint16_t crc = crc16_ccitt_false(body, (size_t)len + 2);

    rpiSerial.write(UART_PREAMBLE_1);
    rpiSerial.write(UART_PREAMBLE_2);
    rpiSerial.write(body, (size_t)len + 2);
    rpiSerial.write((uint8_t)(crc & 0xFF));        // CRC little-endian
    rpiSerial.write((uint8_t)((crc >> 8) & 0xFF));
}

void sendTlmState(uint8_t protoState, float azimuthDeg, float elevationDeg,
                   uint16_t lidarRangeMm, uint8_t ammo, uint8_t flags,
                   uint8_t lostPkts) {
    uint8_t p[14];
    p[0] = protoState;
    memcpy(&p[1], &azimuthDeg, 4);
    memcpy(&p[5], &elevationDeg, 4);
    memcpy(&p[9], &lidarRangeMm, 2);
    p[11] = ammo;
    p[12] = flags;
    p[13] = lostPkts;
    sendFrame(TLM_STATE, p, 14);
}

void sendAckFire(uint8_t shotsFired, uint8_t ammoLeft, uint8_t result) {
    uint8_t p[3] = { shotsFired, ammoLeft, result };
    sendFrame(ACK_FIRE, p, 3);
}

void sendAck(uint8_t ackedId, uint8_t status) {
    uint8_t p[2] = { ackedId, status };
    sendFrame(ACK, p, 2);
}

void sendErr(uint8_t code, uint16_t detail) {
    uint8_t p[3];
    p[0] = code;
    memcpy(&p[1], &detail, 2);
    sendFrame(ERR, p, 3);
}