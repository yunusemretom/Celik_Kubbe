#ifndef TRIGGER_H
#define TRIGGER_H

#include <Arduino.h>
#include "config.h"

// ====================================================================
// TETIK AKTUATORU - ip ile tufek tetigine bagli aci servosu
//
// Eski solenoid valf (MOSFET4) yerine gecer. Davranis sekli AYNIDIR:
//   bosta -> TRIGGER_REST_DEG
//   cekis -> TRIGGER_PULL_DEG'e git, TRIGGER_PULL_MS bekle
//   birak -> TRIGGER_REST_DEG'e don, TRIGGER_RELEASE_MS bekle
//   sonra tekrar hazir.
//
// Bloklamaz: trigger_pull() hemen doner, isi trigger_update() yapar.
// ====================================================================

void trigger_init();

// Yeni bir tetik cekis dongusu baslatir.
// false doner: onceki dongu bitmemis (mesgul) -> atis SAYILMAMALIDIR.
bool trigger_pull();

// Durum makinesini ilerletir. Periyodik olarak (<=10 ms) cagrilmalidir.
void trigger_update();

// Bir cekis dongusu devam ediyor mu
bool trigger_isBusy();

// E-Stop / failsafe: servoyu aninda bos konuma al, dongüyü iptal et.
void trigger_forceRelease();

// Tamamlanmis cekis sayisi (teshis icin)
uint32_t trigger_getPullCount();

#endif