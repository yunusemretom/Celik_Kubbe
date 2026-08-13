/*
 * Celik Kubbe - joystick ile 2 step motor kontrolu
 *
 * joyistik_control.py'nin --send ile gonderdigi "x,y\n" satirlarini okur,
 * iki step motoru hiz kontrollu surer.
 *
 *   PC:  python3 joyistik_control.py --send --port /dev/ttyACM0 --deadzone 0
 *   Kart: 115200 baud, "<dikey>,<yatay>,<rt>\n"  or. "0.420,-0.130,0.750"
 *
 * GEREKEN KUTUPHANE (ESP32 icin):
 *   Arduino IDE > Araclar > Kutuphane Yoneticisi > "ESP32Servo" (Kevin Harrington)
 *   AVR kartlarda IDE ile gelen Servo kutuphanesi kullanilir, ek kurulum yok.
 *
 * Onceki surume gore duzeltilenler (motorlarin donmeme sebepleri):
 *   1) ENABLE pini surulmuyordu. A4988/DRV8825/TMC2208 surucularde EN aktif-LOW'dur
 *      ve bosta birakilinca (ozellikle TMC2208) surucu KAPALI kalir; step palsi
 *      gonderilir ama motor donmez. Artik setup()'ta LOW cekiliyor.
 *   2) Hiz basamak basamak degil, aninda uygulanıyordu. Duran bir step motora
 *      dogrudan 3000 adim/sn vermek motoru dondurmez, sadece titretir (stall).
 *      Artik IVME ile rampalı hizlanma/yavaslama var.
 *   3) Seri veri geldigi surece while dongusu adim atmayi aciktirabiliyordu;
 *      okuma artik dongu basina sinirli.
 *   4) TEST_MODU ile joystick ve seri hat olmadan kablolama dogrulanabiliyor.
 *
 * ---------------------------------------------------------------------------
 * ESP32-S3 NOTLARI (bu projede kullanilan kart)
 *
 *   1) "USB CDC On Boot" kapaliyken Serial, USB portuna degil UART0'a
 *      (GPIO 43/44) gider; PC veriyi gonderir ama sketch hicbir sey almaz,
 *      motorlar donmez ve PC "Write timeout" verir. Asagidaki SERI secimi
 *      bunu otomatik cozer, menu ayarinin bir onemi kalmaz.
 *   2) Yerlesik USB-JTAG portu kullanildiginda PC portu her actiginda cip
 *      resetlenir (rst:0x15 USB_UART_CHIP_RESET). Bu normaldir; python
 *      tarafi acilistan sonra --reset-delay kadar bekler.
 *   3) Kullanilamayacak pinler: GPIO 19/20 (USB D-/D+), GPIO 26-32 (SPI flash),
 *      Octal PSRAM'li modullerde ayrica 33-37. Asagidaki 4-9 arasi pinler
 *      S3'te serbesttir. Klasik ESP32 (S3 degil) kullanirsan GPIO 6-11 flash
 *      pinleridir, mutlaka degistir.
 *   4) Motorlar donmeye baslayinca kart resetleniyor / PC "bagli degil" diyorsa
 *      sebep besleme cokmesidir: surucu motor gucunu ESP32'nin 5V'undan degil
 *      ayri bir kaynaktan al, GND'leri ortakla. Asagidaki reset sebebi ciktisi
 *      bunu dogrudan soyler (BROWNOUT).
 */

// ==================== HANGI SERI PORT ====================
// ESP32-S3'te "USB CDC On Boot" KAPALIYKEN (derleme ayari CDCOnBoot=default)
// Serial nesnesi USB portuna degil UART0'a (GPIO 43/44) baglanir. O zaman
// USB'den gelen veriyi hicbir kod okumaz: PC'nin yazdiklari cipin FIFO'sunda
// birikir, host NAK yer ve PC tarafinda "Write timeout" hatasi cikar; kartin
// bastigi mesajlar da USB'de gorunmez.
//
// HWCDCSerial her zaman USB portudur. Asagidaki secim sayesinde sketch, IDE'de
// USB CDC On Boot ister acik ister kapali olsun dogru porttan konusur.
#if defined(ARDUINO_ARCH_ESP32) && !ARDUINO_USB_CDC_ON_BOOT && \
    defined(ARDUINO_USB_MODE) && ARDUINO_USB_MODE == 1
  #define SERI     HWCDCSerial   // USB Mode = "Hardware CDC and JTAG", CDC On Boot kapali
  #define SERI_USB 1
#elif defined(ARDUINO_ARCH_ESP32) && ARDUINO_USB_CDC_ON_BOOT
  #define SERI     Serial        // CDC On Boot acik: Serial zaten USB portu
  #define SERI_USB 1
#else
  #define SERI     Serial        // AVR veya UART uzerinden haberlesen kartlar
  #define SERI_USB 0
#endif

// ==================== BAGLANTI YOLU ====================
// 0 : USB kablosu (varsayilan)
// 1 : WiFi istemci - kart mevcut bir agi/router'a baglanir (STA)
// 2 : WiFi erisim noktasi - kart kendi agini kurar (AP). Sahada router
//     olmadiginda bunu kullanin; kartin adresi her zaman 192.168.4.1 olur.
//
// WiFi modlarinda USB'den komut okumaya da devam edilir; ikisi birlikte
// calisir, hangisinden veri gelirse o gecerlidir.
#define BAGLANTI_MODU 1

#define WIFI_SSID   "yunus"      // MODU 1: baglanilacak ag | MODU 2: kurulacak ag
#define WIFI_SIFRE  "1234567890"  // en az 8 karakter (AP modunda sart)
#define UDP_PORT    5005              // PC tarafindaki --udp-port ile ayni olmali
#define MDNS_ADI    "celikkubbe"      // STA modunda "celikkubbe.local" olarak bulunur

// ==================== PINLER ====================
#define STEP1_PIN 4
#define DIR1_PIN  5
#define EN1_PIN   8    // surucunun ENABLE pini (aktif LOW). Kullanmiyorsan -1 yap.

#define STEP2_PIN 6
#define DIR2_PIN  7
#define EN2_PIN   9    // Kullanmiyorsan -1 yap.

// ==================== AYARLAR ====================
#define OLU_BOLGE   0.12    // bu degerin altindaki cubuk degeri = dur
#define MIN_HIZ      150    // en yavas: adim/sn (kalkis hizi - motor bunu duruştan cekebilmeli)

// Tavan hiz her eksen icin AYRI. MOTORUN KALDIRABILECEGINDEN YUKSEK OLMAMALI:
// ustune cikilirsa motor senkronu kaybeder, titrer, donmez, hatta rastgele
// yone kayar. Yatay eksen (azimut) genelde daha agir yuk tasidigi icin daha
// dusuk tutulur. Dogru degerleri TEST_MODU 2 ile olcun.
#define MAX_HIZ1    1000    // 1. motor (dikey / eksen1)
#define MAX_HIZ2     600    // 2. motor (yatay / eksen2)
#define IVME        2500    // adim/sn^2 hizlanma - motor kalkista zorlanirsa dusurun
#define FREN_IVME  10000    // adim/sn^2 yavaslama. Hizlanmadan yuksek olmali, yoksa
                            // tusu birakinca motor uzun sure kayarak devam eder.
#define PALS_US        3    // step palsi genisligi (us), surucu datasheet'ine gore
#define DIR_OTURMA_US 20    // yon degisiminden sonra ilk adima kadar beklenen sure
#define VERI_TIMEOUT 500    // ms - veri kesilirse motorlari durdur

// ==================== ATIS SERVOSU (360 / surekli donus) ====================
// SUREKLI DONUS servosu aciya degil HIZA komut alir:
//   1500 us      -> DUR (notr)
//   1500'den uzaklastikca hizlanir; hangi tarafa gidildigi donus yonunu belirler
// Bu yuzden burada aci yoktur; RT dogrudan donus hizini ayarlar.
#define SERVO_PIN         10
#define SERVO_DURUS_US  1500    // notr pals. Servo RT birakilinca yavasca
                                // kayiyorsa buradan ince ayar yapin (1490/1510).
#define SERVO_ARALIK_US  500    // notrden en fazla sapma -> tam hiz
#define SERVO_MIN_SAPMA   40    // olu bant: bu sapmanin altinda servo donmez,
                                // boylece cok kucuk RT degerleri bosuna zorlamaz
#define SERVO_TERS     false    // donus yonu ters geliyorsa true yapin
#define RT_ESIK        0.05f    // bunun altindaki RT = atis yok, servo durur

#define SERVO_MIN_US     500    // attach() alt siniri (ESP32Servo varsayilani)
#define SERVO_MAX_US    2500    // attach() ust siniri
#define SERVO_PWM_HZ      50    // standart analog servo darbe frekansi

//: Tam hizda yaklasik devir/dakika. Yalnizca PC'deki titresim geri bildirimi
//: (her turda bir tik) icin kullanilir; joyistik_control.py'deki
//: SERVO_TAM_TUR_RPM ile ayni tutulmalidir. Servonun datasheet degerini yazin.
#define SERVO_TAM_TUR_RPM 60

// Motorlarin yonu terse calisiyorsa bunlari true yap
#define TERS1 false
#define TERS2 false

// Teshis anahtarlari
#define TEST_MODU   0   // 0: normal | 1: kablolama testi | 2: hiz tarama testi
#define DEBUG_SERI  0   // 1: gelen degerleri ve hesaplanan hizi geri bas (~5 Hz)

// TEST_MODU 2 (hiz tarama) ayarlari: hizi yavasca artirir ve o anki hizi basar.
// Motorun titremeye baslayip donmeyi biraktigi hizi not edin; MAX_HIZ'i o
// degerin %70'i kadar yapin (yuk altinda pay birakmak icin).
#define TARAMA_BASLANGIC  100    // adim/sn
#define TARAMA_BITIS     3000    // adim/sn
#define TARAMA_SURE_MS  20000    // bu surede baslangictan bitise cikar

// ==================== MOTOR ====================
struct Motor {
  uint8_t stepPin;
  uint8_t dirPin;
  int8_t  enPin;         // -1 = yok
  bool    ters;
  float   maxHiz;        // bu eksenin tavan hizi (adim/sn)
  float   hedefHiz;      // adim/sn, isaretli (- = ters yon)
  float   hiz;           // adim/sn, isaretli - rampa ile hedefe yaklasir
  bool    sonYon;        // DIR pininin son hali (bosuna yazmamak icin)
  unsigned long sonAdim; // us
  unsigned long aralik;  // us, iki adim arasi sure. 0 = duruyor
};

Motor m1 = {STEP1_PIN, DIR1_PIN, EN1_PIN, TERS1, MAX_HIZ1, 0, 0, false, 0, 0};
Motor m2 = {STEP2_PIN, DIR2_PIN, EN2_PIN, TERS2, MAX_HIZ2, 0, 0, false, 0, 0};

char  buf[32];
uint8_t bufIdx = 0;
unsigned long sonVeri = 0;
unsigned long sonRampa = 0;   // us - rampa guncellemesinin son zamani

// ==================== HEDEF HIZ ====================
// Cubugun -1.0 .. +1.0 degerini isaretli hedef hiza (adim/sn) cevirir.
void hedefAyarla(Motor &m, float deger) {
  float buyukluk = fabs(deger);

  if (buyukluk < OLU_BOLGE) {
    m.hedefHiz = 0;
    return;
  }
  if (buyukluk > 1.0) buyukluk = 1.0;

  // Olu bolge sonrasini 0..1'e yeniden olcekle, sonra hiza cevir.
  float oran = (buyukluk - OLU_BOLGE) / (1.0 - OLU_BOLGE);
  float hiz = MIN_HIZ + oran * (m.maxHiz - MIN_HIZ);

  m.hedefHiz = (deger > 0) ? hiz : -hiz;
}

// ==================== RAMPA ====================
// Anlik hizi hedefe dogru IVME kadar yaklastirir ve adim araligini gunceller.
// Yon degisiminde once sifira inilir, sonra ters yone cikilir.
void rampaGuncelle(Motor &m, float dt) {
  float hedef = m.hedefHiz;

  // Ters yone gecis: once durmak gerekir, yoksa surucu adim kacirir.
  if (hedef != 0 && m.hiz != 0 && ((hedef > 0) != (m.hiz > 0))) {
    hedef = 0;
  }

  // Yavaslarken (hedef, mevcut hizdan kucukse) daha sert ivme kullanilir:
  // tus birakildiginda motorun kayarak devam etmemesi icin.
  float ivme = (fabs(hedef) >= fabs(m.hiz)) ? IVME : FREN_IVME;

  float fark = hedef - m.hiz;
  float adim = ivme * dt;

  if (fark > adim)       m.hiz += adim;
  else if (fark < -adim) m.hiz -= adim;
  else                   m.hiz = hedef;

  // Duruyorken harekete gecerken en dusuk hizdan basla, yoksa ilk anda
  // aralik cok buyuk olur ve motor gec tepki veriyormus gibi gorunur.
  if (m.hiz == 0 && m.hedefHiz != 0) {
    m.hiz = (m.hedefHiz > 0) ? MIN_HIZ : -MIN_HIZ;
  }

  if (fabs(m.hiz) < 1.0) {
    m.hiz = 0;
    m.aralik = 0;
    return;
  }

  bool yon = (m.hiz > 0);
  if (m.ters) yon = !yon;

  // DIR pini HER guncellemede (1 kHz) yazilir, sadece yon degisince degil.
  // Boylece pinin gercek seviyesi ile kodun sandigi seviye asla ayrisamaz:
  // bir gurultu, brownout veya baska bir kod pini oynatsa bile bir sonraki
  // milisaniyede duzelir. Tek seferlik yazmada bu ayrisma, motorun basista
  // rastgele yone gitmesi olarak gorunur.
  digitalWrite(m.dirPin, yon ? HIGH : LOW);

  if (yon != m.sonYon) {
    m.sonYon = yon;
    // Surucu, DIR'i STEP'in yukselen kenarindan once gormeli (A4988 200 ns,
    // DRV8825 650 ns). Bir sonraki adimi tam bir aralik kadar oteleyerek
    // yon degisiminin kesinlikle oturmasini sagla.
    m.sonAdim = micros();
    delayMicroseconds(DIR_OTURMA_US);
  }

  m.aralik = (unsigned long)(1000000.0 / fabs(m.hiz));
}

// Zamani geldiyse tek adim atar, beklemez.
void motorCalistir(Motor &m) {
  if (m.aralik == 0) return;

  unsigned long simdi = micros();
  if (simdi - m.sonAdim >= m.aralik) {
    m.sonAdim = simdi;
    digitalWrite(m.stepPin, HIGH);
    delayMicroseconds(PALS_US);
    digitalWrite(m.stepPin, LOW);
  }
}

void motorDurdur(Motor &m) {
  m.hedefHiz = 0;
  m.hiz = 0;
  m.aralik = 0;
}

// ==================== ATIS SERVOSU ====================
float servoRT = 0.0f;        // PC'den gelen tetik degeri, 0..1 (0 = dur)
int   servoUs = SERVO_DURUS_US;   // servoya en son yazilan pals (teshis icin)

// Servo kutuphanesi. ESP32'de LEDC'yi elle surmek yerine ESP32Servo kullaniyoruz:
// kutuphane zamanlayici/kanal tahsisini kendi yapiyor ve donanimda calistigi
// dogrulandi. Arduino IDE > Kutuphane Yoneticisi > "ESP32Servo" ile kurulur.
#if defined(ARDUINO_ARCH_ESP32)
  #include <ESP32Servo.h>
#else
  #include <Servo.h>
#endif

Servo atisServo;

void servoDonanimaYaz(int us) {
  servoUs = us;
  atisServo.writeMicroseconds(us);
}

void servoBaslat() {
#if defined(ARDUINO_ARCH_ESP32)
  atisServo.setPeriodHertz(SERVO_PWM_HZ);   // standart analog servo: 50 Hz
#endif
  atisServo.attach(SERVO_PIN, SERVO_MIN_US, SERVO_MAX_US);
  // Attach'tan hemen sonra notr yaz: aksi halde servo acilista donmeye baslar.
  servoDonanimaYaz(SERVO_DURUS_US);
}

// RT'yi dogrudan donus hizina cevirir. Surekli donus servosunda "konum" yoktur,
// bu yuzden dt'ye veya rampaya gerek kalmaz: pals ne ise servo o hizda doner.
void servoGuncelle() {
  if (servoRT < RT_ESIK) {
    servoDonanimaYaz(SERVO_DURUS_US);       // DUR
    return;
  }

  // RT_ESIK..1 araligini 0..1'e yay, sonra olu bandin ustunden tam hiza kadar
  // olan sapmaya cevir.
  float oran = (servoRT - RT_ESIK) / (1.0f - RT_ESIK);
  if (oran > 1.0f) oran = 1.0f;
  int sapma = (int)(SERVO_MIN_SAPMA + oran * (SERVO_ARALIK_US - SERVO_MIN_SAPMA));

  servoDonanimaYaz(SERVO_TERS ? SERVO_DURUS_US - sapma : SERVO_DURUS_US + sapma);
}

// ==================== WIFI / UDP ====================
#if BAGLANTI_MODU
#include <WiFi.h>
#include <WiFiUdp.h>
#include <ESPmDNS.h>

WiFiUDP udp;
IPAddress pcAdresi;          // son komutu gonderen PC - durum satirlari buraya doner
uint16_t  pcPortu = 0;
char      udpBuf[64];

void wifiBaslat() {
#if BAGLANTI_MODU == 2
  // Kart kendi agini kurar. Router gerekmez, adres sabittir.
  WiFi.mode(WIFI_AP);
  WiFi.softAP(WIFI_SSID, WIFI_SIFRE);
  SERI.print("AP kuruldu: "); SERI.println(WIFI_SSID);
  SERI.print("kart adresi: "); SERI.println(WiFi.softAPIP());
#else
  // Mevcut aga baglan.
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);      // guc tasarrufu gecikmeyi 100 ms'ye kadar cikarir
  WiFi.begin(WIFI_SSID, WIFI_SIFRE);
  SERI.print("WiFi baglaniyor");
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) {
    delay(250);
    SERI.print(".");
  }
  SERI.println();
  if (WiFi.status() == WL_CONNECTED) {
    SERI.print("kart adresi: "); SERI.println(WiFi.localIP());
    if (MDNS.begin(MDNS_ADI)) {
      SERI.print("mDNS adi   : "); SERI.print(MDNS_ADI); SERI.println(".local");
    }
  } else {
    SERI.println("WiFi BAGLANAMADI - USB'den kontrol devam ediyor");
  }
#endif
  udp.begin(UDP_PORT);
  SERI.print("udp portu  : "); SERI.println(UDP_PORT);
}

void satirIsle(char *s);     // asagida tanimli

// Gelen UDP paketlerini isler. Bir pakette birden fazla satir olabilir.
void udpOku() {
  int boyut = udp.parsePacket();
  while (boyut > 0) {
    pcAdresi = udp.remoteIP();
    pcPortu  = udp.remotePort();

    int n = udp.read(udpBuf, sizeof(udpBuf) - 1);
    if (n > 0) {
      udpBuf[n] = '\0';
      // Paket icindeki her satiri ayri ayri isle.
      char *bas = udpBuf;
      for (char *p = udpBuf; *p; p++) {
        if (*p == '\n' || *p == '\r') {
          *p = '\0';
          if (*bas) satirIsle(bas);
          bas = p + 1;
        }
      }
      if (*bas) satirIsle(bas);   // sonu satir sonu ile bitmeyen paket
    }
    boyut = udp.parsePacket();
  }
}

// PC'ye tek satirlik durum/teshis mesaji yollar (USB'deki gibi).
void udpYaz(const char *mesaj) {
  if (pcPortu == 0) return;
  udp.beginPacket(pcAdresi, pcPortu);
  udp.print(mesaj);
  udp.print('\n');
  udp.endPacket();
}
#endif  // BAGLANTI_MODU

// ==================== SERI ====================
// "0.42,-0.87\n" formatindaki satiri ayristirir.
// Beklenen bicim: "<dikey>,<yatay>,<rt>\n"  or. "0.000,1.000,0.750"
// Ucuncu alan yoksa (eski surum PC yazilimi) rt = 0 kabul edilir: servo durur.
void satirIsle(char *s) {
  char *virgul = strchr(s, ',');
  if (!virgul) return;

  *virgul = '\0';
  char *ikinci = virgul + 1;

  float rt = 0.0f;
  char *virgul2 = strchr(ikinci, ',');
  if (virgul2) {
    *virgul2 = '\0';
    rt = atof(virgul2 + 1);
    if (rt < 0.0f) rt = 0.0f;
    if (rt > 1.0f) rt = 1.0f;
  }

  float eksen1 = atof(s);
  float eksen2 = atof(ikinci);

  hedefAyarla(m1, eksen1);
  hedefAyarla(m2, eksen2);
  servoRT = rt;
  sonVeri = millis();

#if DEBUG_SERI
  static unsigned long sonBasim = 0;
  if (millis() - sonBasim > 200) {     // ~5 Hz; hatti bogmamak icin
    sonBasim = millis();
    char satir[80];
    snprintf(satir, sizeof(satir), "rx %.3f,%.3f,%.2f hiz %d,%d servo %d us",
             eksen1, eksen2, rt, (int)m1.hiz, (int)m2.hiz, servoUs);
    SERI.println(satir);
#if BAGLANTI_MODU
    udpYaz(satir);          // WiFi ile baglaniyorsa teshis PC'ye geri doner
#endif
  }
#endif
}

// ESP32 + USB CDC: host hatti okumazsa SERI.print varsayilan olarak
// 100 ms'ye kadar bloklar ve adim dongusunu durdurur. Zaman asimini sifirla.
#if defined(ARDUINO_ARCH_ESP32)
#include "esp_system.h"

const char *resetSebebi() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON:  return "POWERON (guc verildi)";
    case ESP_RST_SW:       return "SW (yazilimsal reset)";
    case ESP_RST_PANIC:    return "PANIC (kod coktu)";
    case ESP_RST_INT_WDT:  return "INT_WDT (kesme watchdog)";
    case ESP_RST_TASK_WDT: return "TASK_WDT (gorev watchdog)";
    case ESP_RST_BROWNOUT: return "BROWNOUT (besleme coktu - motor akimi!)";
    case ESP_RST_USB:      return "USB (PC portu acti, normal)";
    default:               return "DIGER";
  }
}
#endif

void setup() {
  SERI.begin(115200);
#if defined(ARDUINO_ARCH_ESP32) && SERI_USB
  SERI.setTxTimeoutMs(0);   // PC dinlemese bile print bloklamasin
#endif

  pinMode(STEP1_PIN, OUTPUT);
  pinMode(DIR1_PIN, OUTPUT);
  pinMode(STEP2_PIN, OUTPUT);
  pinMode(DIR2_PIN, OUTPUT);

  digitalWrite(STEP1_PIN, LOW);
  digitalWrite(STEP2_PIN, LOW);

  // DIR pinlerini bilinen bir seviyeye cek ve kodun sandigi degerle esitle.
  // Yazilmadan birakilirsa surucu, ilk adimda pinin o anki (belirsiz) halini
  // ornekler; motor rastgele yone kalkar.
  digitalWrite(DIR1_PIN, LOW);  m1.sonYon = false;
  digitalWrite(DIR2_PIN, LOW);  m2.sonYon = false;

  // ENABLE aktif-LOW: surucuyu ac. Bu satirlar olmadan bircok surucu
  // step palslerini gormezden gelir ve motor hic donmez.
  if (EN1_PIN >= 0) { pinMode(EN1_PIN, OUTPUT); digitalWrite(EN1_PIN, LOW); }
  if (EN2_PIN >= 0) { pinMode(EN2_PIN, OUTPUT); digitalWrite(EN2_PIN, LOW); }

  // Atis servosu: notr palsle baslar, yani komut gelene kadar DURUR.
  servoBaslat();

  sonVeri = millis();
  sonRampa = micros();

  // PC tarafinda "kart :" satirinda gorunur. Motorlar donerken bu satirin
  // yeniden basilmasi = kart resetlendi demektir; sebebi hemen altinda yazar.
  SERI.println("HAZIR");
#if defined(ARDUINO_ARCH_ESP32)
  SERI.print("RESET SEBEBI: ");
  SERI.println(resetSebebi());
#endif

#if BAGLANTI_MODU
  wifiBaslat();
#endif
}

void loop() {
#if TEST_MODU == 1
  // --- Kablolama testi: seri hat ve joystick olmadan calisir ---
  // Iki motor da 2 sn ileri, 2 sn geri doner. Donmuyorsa sorun PC'de degil;
  // sirasiyla sunlara bak: ENABLE pini, surucu Vref/akim ayari, motor
  // kablolarinin faz eslesmesi (A+/A-/B+/B-), surucu besleme voltaji.
  unsigned long faz = (millis() / 2000) % 2;
  float deger = faz ? 0.6 : -0.6;
  hedefAyarla(m1, deger);
  hedefAyarla(m2, deger);
  sonVeri = millis();

#elif TEST_MODU == 2
  // --- Hiz tarama testi: MAX_HIZ'i deneyerek bulmak icin ---
  // Hiz TARAMA_BASLANGIC'tan TARAMA_BITIS'e dogru yavasca artar. Motor hangi
  // hizda titremeye baslayip donmeyi birakiyorsa (senkron kaybi), MAX_HIZ'i
  // o degerin ~%70'i yapin. Rampa devre disi: hedef dogrudan uygulanir.
  {
    unsigned long t = millis() % TARAMA_SURE_MS;
    float oran = (float)t / TARAMA_SURE_MS;
    float hiz = TARAMA_BASLANGIC + oran * (TARAMA_BITIS - TARAMA_BASLANGIC);

    m1.hiz = m1.hedefHiz = hiz;
    m2.hiz = m2.hedefHiz = hiz;
    for (Motor *m : {&m1, &m2}) {
      bool yon = m->ters ? false : true;
      if (yon != m->sonYon) { digitalWrite(m->dirPin, yon ? HIGH : LOW); m->sonYon = yon; }
      m->aralik = (unsigned long)(1000000.0 / hiz);
    }
    sonVeri = millis();

    static unsigned long sonBasim = 0;
    if (millis() - sonBasim >= 500) {
      sonBasim = millis();
      SERI.print("tarama hizi: "); SERI.print((int)hiz); SERI.println(" adim/sn");
    }
    motorCalistir(m1);
    motorCalistir(m2);
    return;                       // asagidaki rampa/timeout mantigini atla
  }

#else
#if BAGLANTI_MODU
  // --- WiFi/UDP'den komut oku ---
  udpOku();
#endif

  // --- Seri veriyi oku (bloklamadan, dongu basina sinirli) ---
  // Sinir olmazsa surekli veri geldiginde bu dongu adim atmayi aciktirir.
  uint8_t okunan = 0;
  while (SERI.available() && okunan < 16) {
    char c = SERI.read();
    okunan++;

    if (c == '\n' || c == '\r') {
      if (bufIdx > 0) {
        buf[bufIdx] = '\0';
        satirIsle(buf);
        bufIdx = 0;
      }
    } else if (bufIdx < sizeof(buf) - 1) {
      buf[bufIdx++] = c;
    } else {
      bufIdx = 0;              // tasma: satiri at
    }
  }
#endif

  // --- Guvenlik: veri kesilirse durdur ---
  // Servo da durur ve bekleme konumuna doner: kablo/WiFi kopunca atis
  // mekanizmasi kendi basina calismaya devam etmemeli.
  if (millis() - sonVeri > VERI_TIMEOUT) {
    motorDurdur(m1);
    motorDurdur(m2);
    servoRT = 0.0f;
  }

  // --- Rampa: sabit 1 kHz'de guncelle (her dongude float hesabi yavaslatir) ---
  unsigned long simdi = micros();
  if (simdi - sonRampa >= 1000) {
    float dt = (simdi - sonRampa) / 1000000.0;
    sonRampa = simdi;
    if (dt > 0.05) dt = 0.05;         // takilma/tasma sonrasi sicramayi engelle
    rampaGuncelle(m1, dt);
    rampaGuncelle(m2, dt);
    servoGuncelle();                  // atis servosu da ayni saatte guncellenir
  }

  // --- Motorlari sur ---
  motorCalistir(m1);
  motorCalistir(m2);
}
