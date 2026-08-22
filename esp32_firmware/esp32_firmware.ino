// ====================================================================
// esp32_firmware.ino
// ESP32-S3 ana giris noktasi (entry point)
//
// Bu dosya SADECE baslatma (init) sirasini yonetir ve FreeRTOS
// gorevlerini ayaga kaldirir.
//
// GEREKEN KUTUPHANE:
//   Arduino IDE > Araclar > Kutuphane Yoneticisi > "ESP32Servo"
//   (tetik servosu icin - trigger.cpp)
//
// KART AYARLARI:
//   Kart      : ESP32S3 Dev Module
//   USB CDC On Boot : Enabled   (seri monitor USB'den gorunsun)
//   PSRAM     : modulunuze gore
// ====================================================================

#include "config.h"
#include "encoder.h"
#include "lidar.h"
#include "pid_control.h"
#include "safety.h"
#include "trigger.h"
#include "joystick.h"
#include "uart_protocol.h"
#include "tasks.h"

void setup() {
    // ---------------- DEBUG SERIAL (USB) ----------------
    Serial.begin(115200);
    unsigned long serialWaitStart = millis();
    while (!Serial && (millis() - serialWaitStart) < 2000) {
        ; // USB-CDC'nin baglanmasini en fazla 2sn bekle, sonra devam et
    }
    delay(300);

    Serial.println();
    Serial.println("========================================");
    Serial.println("  PARS MCU - ESP32-S3 baslatiliyor");
    Serial.println("  UART Protokolu v1.3 + Joystick (UDP)");
    Serial.println("========================================");

    // ---------------- CRC SELF-TEST ----------------
    uint8_t crcTestData[2] = {0x00, 0x00};
    uint16_t crcTestResult = crc16_ccitt_false(crcTestData, 2);
    Serial.print("[SELFTEST] CRC dogrulama (beklenen 0x1D0F): 0x");
    Serial.println(crcTestResult, HEX);
    if (crcTestResult != 0x1D0F) {
        Serial.println("[KRITIK HATA] CRC fonksiyonu YANLIS! Devam etmiyorum.");
        while (true) { delay(1000); }
    }

    // ---------------- DONANIM MODULLERI ----------------
    Serial.println("[INIT] Enkoderler baslatiliyor (AS5600 x2)...");
    bool encodersOk = encoder_init();
    if (!encodersOk) {
        Serial.println("[UYARI] En az bir enkoder yanit vermedi.");
        Serial.println("        Manuel (joystick) modda sorun degil: acik cevrim hiz");
        Serial.println("        kontrolu kullanilir ve pozisyon TAHMIN edilir.");
        Serial.println("        Otonom modlarda PID encoder'siz CALISMAZ.");
    }

    Serial.println("[INIT] LiDAR (TF03-180) baslatiliyor...");
    lidar_init();

    Serial.println("[INIT] Guvenlik katmani (E-Stop, mosfet, tetik servosu)...");
    safety_init();   // icinde trigger_init() cagriliyor

    Serial.println("[INIT] Motor kontrol baslatiliyor...");
    pid_init();

    Serial.println("[INIT] Joystick (WiFi/UDP) baslatiliyor...");
    if (!joystick_init()) {
        Serial.println("[UYARI] Joystick UDP yolu acilamadi (WiFi yok).");
    }

    // ---------------- FREERTOS GOREVLERI ----------------
    Serial.println("[INIT] FreeRTOS gorevleri baslatiliyor...");
    tasks_startAll();

    Serial.println("[INIT] Baslatma tamamlandi. Sistem calisiyor.");
    Serial.println("========================================");
    Serial.println("!! Ilk calistirmada motor kayislarini SOKUN ve tufegin");
    Serial.println("!! sarjorunu BOSALTIN. Once E-Stop'un gercekten kestigini,");
    Serial.println("!! sonra eksen yonlerini dogrulayin.");
    Serial.println("========================================");
}

void loop() {
    // Tum is FreeRTOS gorevlerinde (tasks.cpp):
    //   CommRPi   (core 0): UART protokolu + telemetri
    //   Lidar     (core 0): lidar_read()
    //   Joystick  (core 0): UDP joystick + tetik
    //   MotorCtrl (core 1): safety_update() + pid_update()
    vTaskDelay(pdMS_TO_TICKS(1000));
}
