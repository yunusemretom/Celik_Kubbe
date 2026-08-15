#include "encoder.h"
#include "uart_protocol.h"

#define AS5600_REG_RAW_ANGLE_H   0x0C
#define AS5600_REG_RAW_ANGLE_L   0x0D

#define I2C_READ_TIMEOUT_MS  5

// ---------------- DURUM DEGISKENLERI ----------------
static uint16_t lastAzRaw = 0;
static uint16_t lastElevRaw = 0;
static bool azOk = false;
static bool elevOk = false;

static float azZeroOffsetDeg = 0.0f;
static float elevZeroOffsetDeg = 0.0f;


// YARDIMCI: verilen Wire nesnesi ve I2C adresinden 12-bit ham açı değeri okur. Dönüş: true = başarılı okuma, outRaw12 geçerli.
static bool readRawAngle12(TwoWire &bus, uint8_t i2cAddr, uint16_t &outRaw12) {
    bus.beginTransmission(i2cAddr);
    bus.write(AS5600_REG_RAW_ANGLE_H);
    if (bus.endTransmission(false) != 0) {   
        return false;   
    }

    uint8_t received = bus.requestFrom((int)i2cAddr, 2);
    if (received != 2) {
        return false;
    }

    uint8_t angleH = bus.read();   // RAW ANGLE[11:8] üst 4 bit geçerli
    uint8_t angleL = bus.read();   // RAW ANGLE[7:0]

    outRaw12 = (((uint16_t)angleH & 0x0F) << 8) | (uint16_t)angleL;
    outRaw12 &= 0x0FFF;   // güvenlik: 12 bit ile sınırla (0..4095)
    return true;
}


// YARDIMCI: ham değeri (0..4095) + sıfır-offset'i dereceye (-180..+180) çevirir
static float rawToDegrees(uint16_t raw, float zeroOffsetDeg) {
    float deg = (raw * 360.0f) / (float)ENCODER_MAX_VALUE;   // 0..360 (ham, offsetsiz)
    deg -= zeroOffsetDeg;

    while (deg > 180.0f)  deg -= 360.0f;
    while (deg < -180.0f) deg += 360.0f;
    return deg;
}


bool encoder_init() {
    Wire.begin(AZ_I2C_SDA_PIN, AZ_I2C_SCL_PIN);       // Azimut - hat 1
    Wire.setTimeOut(I2C_READ_TIMEOUT_MS);

    Wire1.begin(ELEV_I2C_SDA_PIN, ELEV_I2C_SCL_PIN);  // Elevasyon - hat 2
    Wire1.setTimeOut(I2C_READ_TIMEOUT_MS);

    uint16_t rawTest;
    bool azFound   = readRawAngle12(Wire,  AZ_ENCODER_I2C_ADDR,   rawTest);
    bool elevFound = readRawAngle12(Wire1, ELEV_ENCODER_I2C_ADDR, rawTest);

    if (!azFound) {
       LOG_ERR("AZ encoder yanit yok adr=0x%02X", AZ_ENCODER_I2C_ADDR);
    }
    if (!elevFound) {
       LOG_ERR("ELEV encoder yanit yok adr=0x%02X", ELEV_ENCODER_I2C_ADDR);
    }

    azOk = azFound;
    elevOk = elevFound;

    azZeroOffsetDeg = 0.0f;
    elevZeroOffsetDeg = 0.0f;

    return azFound && elevFound;
}

uint16_t encoder_getAzimuthRaw() {
    uint16_t raw;
    if (readRawAngle12(Wire, AZ_ENCODER_I2C_ADDR, raw)) {
        lastAzRaw = raw;
        azOk = true;
    } else {
        azOk = false;   
    }
    return lastAzRaw;
}

uint16_t encoder_getElevationRaw() {
    uint16_t raw;
    if (readRawAngle12(Wire1, ELEV_ENCODER_I2C_ADDR, raw)) {
        lastElevRaw = raw;
        elevOk = true;
    } else {
        elevOk = false;
    }
    return lastElevRaw;
}


float encoder_getAzimuthDeg() {
    uint16_t raw = encoder_getAzimuthRaw();   // ok/hata bayrağını günceller
    return rawToDegrees(raw, azZeroOffsetDeg);
}

float encoder_getElevationDeg() {
    uint16_t raw = encoder_getElevationRaw();
    return rawToDegrees(raw, elevZeroOffsetDeg);
}

bool encoder_isAzimuthOk()   { return azOk; }
bool encoder_isElevationOk() { return elevOk; }


void encoder_calibrateZero() {
    // Taretin fiziksel olarak 0 derece azimut / 0 derece irtifa referans konumunda olduğu varsayılır.
    uint16_t azRaw, elevRaw;

    if (readRawAngle12(Wire, AZ_ENCODER_I2C_ADDR, azRaw)) {
        azZeroOffsetDeg = (azRaw * 360.0f) / (float)ENCODER_MAX_VALUE;
        LOG_INFO("AZ encoder kalibre edildi");
    } else {
        LOG_ERR("AZ encoder kalibrasyon basarisiz");
    }

    if (readRawAngle12(Wire1, ELEV_ENCODER_I2C_ADDR, elevRaw)) {
        elevZeroOffsetDeg = (elevRaw * 360.0f) / (float)ENCODER_MAX_VALUE;
        LOG_INFO("ELEV encoder kalibre edildi");
    } else {
        LOG_ERR("ELEV encoder kalibrasyon basarisiz");
    }
}

void encoder_setAzimuthZeroOffsetDeg(float offsetDeg)   { azZeroOffsetDeg = offsetDeg; }
void encoder_setElevationZeroOffsetDeg(float offsetDeg) { elevZeroOffsetDeg = offsetDeg; }
float encoder_getAzimuthZeroOffsetDeg()   { return azZeroOffsetDeg; }
float encoder_getElevationZeroOffsetDeg() { return elevZeroOffsetDeg; }