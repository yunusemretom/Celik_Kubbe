#ifndef JOYSTICK_H
#define JOYSTICK_H

#include <Arduino.h>
#include "config.h"

// ====================================================================
// JOYSTICK GIRISI - YKI web arayuzundeki sanal joystick
//
// Zincir:
//   tarayici joystick.js  --WebSocket-->  server.js
//     --> joystickBridge.js  --UDP:5005-->  BU MODUL
//
// Satir bicimi:  "<pitch>,<yaw>,<fire>,<arm>\n"
//   pitch : -1..+1   yukari = +   (elevasyon)
//   yaw   : -1..+1   sag    = +   (azimut)
//   fire  :  0 / 1   tetik basili mi
//   arm   :  0 / 1   emniyet mandali acik mi
//
// 3 alanli eski bicim ("p,y,f") de kabul edilir; o durumda arm = 0
// varsayilir, yani ATES ETMEZ. Bu bilincli bir guvenlik varsayimidir.
//
// Eski joystick_motor.ino'daki UDP/WiFi katmani buraya tasindi.
// Fark: orada motorlar dogrudan bu dosyadan suruluyordu; burada modul
// SADECE veri okur, motor surme isi pid_control.cpp'de tek elde toplanir
// (LEDC ile bit-bang ayni pini surerse cakisir).
// ====================================================================

struct JoystickInput {
    float pitch;   // -1..+1
    float yaw;     // -1..+1
    bool  fire;
    bool  arm;
};

// WiFi'yi baglar (JOYSTICK_WIFI_MODE'a gore STA/AP) ve UDP portunu acar.
// WiFi baglanamazsa false doner ama sistem CALISMAYA DEVAM EDER:
// USB seri ve RPi UART yollari acik kalir.
bool joystick_init();

// Gelen UDP/seri paketleri isler. BLOKLAMAZ. Task icinde periyodik cagrilir.
void joystick_update();

// Son gecerli paketin uzerinden JOYSTICK_TIMEOUT_MS'den az gecti mi
bool joystick_isFresh();

// Son gecerli girdi. Veri bayatsa her alan sifir/false doner.
JoystickInput joystick_get();

// Son gecerli paketten bu yana gecen sure (ms)
unsigned long joystick_msSinceLastPacket();

bool joystick_isWifiConnected();

// PC'ye tek satirlik teshis mesaji (son paketi gonderen adrese)
void joystick_sendDebug(const char *mesaj);

#endif