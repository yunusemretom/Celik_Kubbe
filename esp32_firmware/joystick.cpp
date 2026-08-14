#include "joystick.h"

#if JOYSTICK_WIFI_MODE
  #include <WiFi.h>
  #include <WiFiUdp.h>
  #include <ESPmDNS.h>
  static WiFiUDP udp;
  static IPAddress pcAdresi;
  static uint16_t  pcPortu = 0;
  static char      udpBuf[128];
  static bool      wifiOk = false;
#endif

// ---------------- SON GECERLI GIRDI ----------------
static volatile float lastPitch = 0.0f;
static volatile float lastYaw   = 0.0f;
static volatile bool  lastFire  = false;
static volatile bool  lastArm   = false;
static volatile unsigned long lastPacketMillis = 0;
static bool haveEverReceived = false;

#if JOYSTICK_ALLOW_SERIAL
static char seriBuf[64];
static uint8_t seriIdx = 0;
#endif


static float clampBirim(float v) {
    if (v >  1.0f) return  1.0f;
    if (v < -1.0f) return -1.0f;
    return v;
}

static float uygulaOluBolge(float v) {
    if (fabs(v) < JOYSTICK_DEADZONE) return 0.0f;
    return clampBirim(v);
}


// "pitch,yaw,fire,arm" satirini ayristirir. Eksik alanlar 0 kabul edilir.
static void satirIsle(char *s) {
    if (!s || !*s) return;

    float alan[4] = { 0.0f, 0.0f, 0.0f, 0.0f };
    uint8_t n = 0;

    char *bas = s;
    while (n < 4 && bas) {
        char *virgul = strchr(bas, ',');
        if (virgul) *virgul = '\0';
        alan[n++] = atof(bas);
        bas = virgul ? (virgul + 1) : nullptr;
    }

    // En az pitch + yaw gelmeli, yoksa bozuk paket
    if (n < 2) return;

    lastPitch = uygulaOluBolge(alan[0]);
    lastYaw   = uygulaOluBolge(alan[1]);
    lastFire  = (alan[2] >= 0.5f);
    // 4. alan yoksa (eski 3 alanli bicim) arm = 0 -> ATES YOK
    lastArm   = (n >= 4) && (alan[3] >= 0.5f);

    lastPacketMillis = millis();
    haveEverReceived = true;
}


// Bir tampondaki birden fazla satiri ayri ayri isler.
static void tamponIsle(char *buf) {
    char *bas = buf;
    for (char *p = buf; *p; p++) {
        if (*p == '\n' || *p == '\r') {
            *p = '\0';
            if (*bas) satirIsle(bas);
            bas = p + 1;
        }
    }
    if (*bas) satirIsle(bas);   // satir sonu ile bitmeyen paket
}


bool joystick_init() {
    lastPitch = lastYaw = 0.0f;
    lastFire = lastArm = false;
    lastPacketMillis = 0;
    haveEverReceived = false;

#if JOYSTICK_WIFI_MODE == 2
    // AP modu: kart kendi agini kurar, adresi her zaman 192.168.4.1.
    // Sahada router yoksa bunu kullanin.
    WiFi.mode(WIFI_AP);
    WiFi.softAP(JOYSTICK_WIFI_SSID, JOYSTICK_WIFI_PASS);
    Serial.print("[JOYSTICK] AP kuruldu: ");
    Serial.println(JOYSTICK_WIFI_SSID);
    Serial.print("[JOYSTICK] Kart adresi: ");
    Serial.println(WiFi.softAPIP());
    wifiOk = true;

#elif JOYSTICK_WIFI_MODE == 1
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);   // guc tasarrufu gecikmeyi 100 ms'ye cikarir
    WiFi.begin(JOYSTICK_WIFI_SSID, JOYSTICK_WIFI_PASS);

    Serial.print("[JOYSTICK] WiFi baglaniyor");
    unsigned long baslangic = millis();
    while (WiFi.status() != WL_CONNECTED &&
           (millis() - baslangic) < JOYSTICK_WIFI_TIMEOUT_MS) {
        delay(250);
        Serial.print(".");
    }
    Serial.println();

    wifiOk = (WiFi.status() == WL_CONNECTED);
    if (wifiOk) {
        Serial.print("[JOYSTICK] Kart adresi: ");
        Serial.println(WiFi.localIP());
        if (MDNS.begin(JOYSTICK_MDNS_NAME)) {
            Serial.print("[JOYSTICK] mDNS: ");
            Serial.print(JOYSTICK_MDNS_NAME);
            Serial.println(".local");
        }
    } else {
        Serial.println("[UYARI] WiFi BAGLANAMADI - joystick UDP yolu kapali.");
        Serial.println("        USB seri ve RPi UART yollari calismaya devam ediyor.");
    }
#endif

#if JOYSTICK_WIFI_MODE
    udp.begin(JOYSTICK_UDP_PORT);
    Serial.print("[JOYSTICK] UDP portu: ");
    Serial.println(JOYSTICK_UDP_PORT);
    return wifiOk;
#else
    Serial.println("[JOYSTICK] WiFi devre disi (JOYSTICK_WIFI_MODE=0).");
    return false;
#endif
}


void joystick_update() {

#if JOYSTICK_WIFI_MODE
    int boyut = udp.parsePacket();
    while (boyut > 0) {
        pcAdresi = udp.remoteIP();
        pcPortu  = udp.remotePort();

        int n = udp.read(udpBuf, sizeof(udpBuf) - 1);
        if (n > 0) {
            udpBuf[n] = '\0';
            tamponIsle(udpBuf);
        }
        boyut = udp.parsePacket();
    }
#endif

#if JOYSTICK_ALLOW_SERIAL
    // Tezgah testi: USB'den de "p,y,f,a" satiri kabul edilir.
    // Dongu basina sinirli okuma - surekli veri gelirse task'i aciktirmasin.
    uint8_t okunan = 0;
    while (Serial.available() && okunan < 32) {
        char c = (char)Serial.read();
        okunan++;

        if (c == '\n' || c == '\r') {
            if (seriIdx > 0) {
                seriBuf[seriIdx] = '\0';
                satirIsle(seriBuf);
                seriIdx = 0;
            }
        } else if (seriIdx < sizeof(seriBuf) - 1) {
            seriBuf[seriIdx++] = c;
        } else {
            seriIdx = 0;   // tasma: satiri at
        }
    }
#endif
}


bool joystick_isFresh() {
    if (!haveEverReceived) return false;
    return (millis() - lastPacketMillis) <= JOYSTICK_TIMEOUT_MS;
}


JoystickInput joystick_get() {
    JoystickInput out;

    // Veri bayatsa HER SEY sifir. WiFi koparsa taret durur ve
    // tetik birakilir - son paket "fire=1" olsa bile.
    if (!joystick_isFresh()) {
        out.pitch = 0.0f;
        out.yaw   = 0.0f;
        out.fire  = false;
        out.arm   = false;
        return out;
    }

    out.pitch = lastPitch;
    out.yaw   = lastYaw;
    out.fire  = lastFire;
    out.arm   = lastArm;
    return out;
}


unsigned long joystick_msSinceLastPacket() {
    if (!haveEverReceived) return 0xFFFFFFFF;
    return millis() - lastPacketMillis;
}


bool joystick_isWifiConnected() {
#if JOYSTICK_WIFI_MODE
    return wifiOk;
#else
    return false;
#endif
}


void joystick_sendDebug(const char *mesaj) {
#if JOYSTICK_WIFI_MODE
    if (pcPortu == 0) return;
    udp.beginPacket(pcAdresi, pcPortu);
    udp.print(mesaj);
    udp.print('\n');
    udp.endPacket();
#else
    (void)mesaj;
#endif
}#include "joystick.h"

#if JOYSTICK_WIFI_MODE
  #include <WiFi.h>
  #include <WiFiUdp.h>
  #include <ESPmDNS.h>
  static WiFiUDP udp;
  static IPAddress pcAdresi;
  static uint16_t  pcPortu = 0;
  static char      udpBuf[128];
  static bool      wifiOk = false;
#endif

// ---------------- SON GECERLI GIRDI ----------------
static volatile float lastPitch = 0.0f;
static volatile float lastYaw   = 0.0f;
static volatile bool  lastFire  = false;
static volatile bool  lastArm   = false;
static volatile unsigned long lastPacketMillis = 0;
static bool haveEverReceived = false;

#if JOYSTICK_ALLOW_SERIAL
static char seriBuf[64];
static uint8_t seriIdx = 0;
#endif


static float clampBirim(float v) {
    if (v >  1.0f) return  1.0f;
    if (v < -1.0f) return -1.0f;
    return v;
}

static float uygulaOluBolge(float v) {
    if (fabs(v) < JOYSTICK_DEADZONE) return 0.0f;
    return clampBirim(v);
}


// "pitch,yaw,fire,arm" satirini ayristirir. Eksik alanlar 0 kabul edilir.
static void satirIsle(char *s) {
    if (!s || !*s) return;

    float alan[4] = { 0.0f, 0.0f, 0.0f, 0.0f };
    uint8_t n = 0;

    char *bas = s;
    while (n < 4 && bas) {
        char *virgul = strchr(bas, ',');
        if (virgul) *virgul = '\0';
        alan[n++] = atof(bas);
        bas = virgul ? (virgul + 1) : nullptr;
    }

    // En az pitch + yaw gelmeli, yoksa bozuk paket
    if (n < 2) return;

    lastPitch = uygulaOluBolge(alan[0]);
    lastYaw   = uygulaOluBolge(alan[1]);
    lastFire  = (alan[2] >= 0.5f);
    // 4. alan yoksa (eski 3 alanli bicim) arm = 0 -> ATES YOK
    lastArm   = (n >= 4) && (alan[3] >= 0.5f);

    lastPacketMillis = millis();
    haveEverReceived = true;
}


// Bir tampondaki birden fazla satiri ayri ayri isler.
static void tamponIsle(char *buf) {
    char *bas = buf;
    for (char *p = buf; *p; p++) {
        if (*p == '\n' || *p == '\r') {
            *p = '\0';
            if (*bas) satirIsle(bas);
            bas = p + 1;
        }
    }
    if (*bas) satirIsle(bas);   // satir sonu ile bitmeyen paket
}


bool joystick_init() {
    lastPitch = lastYaw = 0.0f;
    lastFire = lastArm = false;
    lastPacketMillis = 0;
    haveEverReceived = false;

#if JOYSTICK_WIFI_MODE == 2
    // AP modu: kart kendi agini kurar, adresi her zaman 192.168.4.1.
    // Sahada router yoksa bunu kullanin.
    WiFi.mode(WIFI_AP);
    WiFi.softAP(JOYSTICK_WIFI_SSID, JOYSTICK_WIFI_PASS);
    Serial.print("[JOYSTICK] AP kuruldu: ");
    Serial.println(JOYSTICK_WIFI_SSID);
    Serial.print("[JOYSTICK] Kart adresi: ");
    Serial.println(WiFi.softAPIP());
    wifiOk = true;

#elif JOYSTICK_WIFI_MODE == 1
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);   // guc tasarrufu gecikmeyi 100 ms'ye cikarir
    WiFi.begin(JOYSTICK_WIFI_SSID, JOYSTICK_WIFI_PASS);

    Serial.print("[JOYSTICK] WiFi baglaniyor");
    unsigned long baslangic = millis();
    while (WiFi.status() != WL_CONNECTED &&
           (millis() - baslangic) < JOYSTICK_WIFI_TIMEOUT_MS) {
        delay(250);
        Serial.print(".");
    }
    Serial.println();

    wifiOk = (WiFi.status() == WL_CONNECTED);
    if (wifiOk) {
        Serial.print("[JOYSTICK] Kart adresi: ");
        Serial.println(WiFi.localIP());
        if (MDNS.begin(JOYSTICK_MDNS_NAME)) {
            Serial.print("[JOYSTICK] mDNS: ");
            Serial.print(JOYSTICK_MDNS_NAME);
            Serial.println(".local");
        }
    } else {
        Serial.println("[UYARI] WiFi BAGLANAMADI - joystick UDP yolu kapali.");
        Serial.println("        USB seri ve RPi UART yollari calismaya devam ediyor.");
    }
#endif

#if JOYSTICK_WIFI_MODE
    udp.begin(JOYSTICK_UDP_PORT);
    Serial.print("[JOYSTICK] UDP portu: ");
    Serial.println(JOYSTICK_UDP_PORT);
    return wifiOk;
#else
    Serial.println("[JOYSTICK] WiFi devre disi (JOYSTICK_WIFI_MODE=0).");
    return false;
#endif
}


void joystick_update() {

#if JOYSTICK_WIFI_MODE
    int boyut = udp.parsePacket();
    while (boyut > 0) {
        pcAdresi = udp.remoteIP();
        pcPortu  = udp.remotePort();

        int n = udp.read(udpBuf, sizeof(udpBuf) - 1);
        if (n > 0) {
            udpBuf[n] = '\0';
            tamponIsle(udpBuf);
        }
        boyut = udp.parsePacket();
    }
#endif

#if JOYSTICK_ALLOW_SERIAL
    // Tezgah testi: USB'den de "p,y,f,a" satiri kabul edilir.
    // Dongu basina sinirli okuma - surekli veri gelirse task'i aciktirmasin.
    uint8_t okunan = 0;
    while (Serial.available() && okunan < 32) {
        char c = (char)Serial.read();
        okunan++;

        if (c == '\n' || c == '\r') {
            if (seriIdx > 0) {
                seriBuf[seriIdx] = '\0';
                satirIsle(seriBuf);
                seriIdx = 0;
            }
        } else if (seriIdx < sizeof(seriBuf) - 1) {
            seriBuf[seriIdx++] = c;
        } else {
            seriIdx = 0;   // tasma: satiri at
        }
    }
#endif
}


bool joystick_isFresh() {
    if (!haveEverReceived) return false;
    return (millis() - lastPacketMillis) <= JOYSTICK_TIMEOUT_MS;
}


JoystickInput joystick_get() {
    JoystickInput out;

    // Veri bayatsa HER SEY sifir. WiFi koparsa taret durur ve
    // tetik birakilir - son paket "fire=1" olsa bile.
    if (!joystick_isFresh()) {
        out.pitch = 0.0f;
        out.yaw   = 0.0f;
        out.fire  = false;
        out.arm   = false;
        return out;
    }

    out.pitch = lastPitch;
    out.yaw   = lastYaw;
    out.fire  = lastFire;
    out.arm   = lastArm;
    return out;
}


unsigned long joystick_msSinceLastPacket() {
    if (!haveEverReceived) return 0xFFFFFFFF;
    return millis() - lastPacketMillis;
}


bool joystick_isWifiConnected() {
#if JOYSTICK_WIFI_MODE
    return wifiOk;
#else
    return false;
#endif
}


void joystick_sendDebug(const char *mesaj) {
#if JOYSTICK_WIFI_MODE
    if (pcPortu == 0) return;
    udp.beginPacket(pcAdresi, pcPortu);
    udp.print(mesaj);
    udp.print('\n');
    udp.endPacket();
#else
    (void)mesaj;
#endif
}