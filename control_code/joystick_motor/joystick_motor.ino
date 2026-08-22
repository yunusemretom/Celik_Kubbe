/*
 * Celik Kubbe - joystick ile 2 step motor kontrolu
 *
 * joyistik_control.py'nin --send ile gonderdigi "x,y\n" satirlarini okur,
 * iki step motoru hiz kontrollu surer.
 *
 *   PC:  python3 joyistik_control.py --send --port /dev/ttyACM0 --deadzone 0
 *   Kart: 115200 baud, "<dikey>,<yatay>,<rt>\n"  or. "0.420,-0.130,0.750"
 *
 * DONANIMSAL DURDURMA: DUR_PIN'e (GPIO 3) 3.3 V gelince tum hareket durur.
 * Bu, PC/WiFi'dan bagimsiz calisir; yazilim kilitlense bile motorlar durur.
 *
 * EK KUTUPHANE GEREKMEZ. (Atis mekanizmasi artik servo degil, BTS7960 surucu
 * uzerinden PWM ile surulen bir DC motor oldugu icin ESP32Servo kaldirildi.)
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

// ==================== TELEMETRI (YKI arayuzu) ====================
// Kartin anlik durumu JSON olarak YKI backend'ine (YKI/backend/server.js)
// UDP ile gonderilir; arayuzdeki telemetri sayfasi bunu canli gosterir.
// Backend varsayilan olarak 5001'i dinler (yki_config.json > rpi.udpPort).
//
// HEDEF ADRES: "0.0.0.0" birakilirsa paket, komut gonderen PC'ye yollanir -
// yani joyistik_control.py hangi bilgisayarda calisiyorsa oraya. YKI baska
// bir makinede calisiyorsa buraya o makinenin IP'sini yazin.
#define TELEMETRI_HZ     5            // saniyede kac paket. 0 = telemetri kapali
#define TELEMETRI_PORT   5001
#define TELEMETRI_IP     "0.0.0.0"

// ==================== PINLER ====================
#define STEP1_PIN 4
#define DIR1_PIN  5
#define EN1_PIN   8    // surucunun ENABLE pini (aktif LOW). Kullanmiyorsan -1 yap.

#define STEP2_PIN 6
#define DIR2_PIN  7
#define EN2_PIN   9    // Kullanmiyorsan -1 yap.

// ==================== ACIL DURDURMA (STOP) PINI ====================
// Butona basilinca pine 3.3 V gelir ve TUM hareket durur: iki step motor da
// aninda durdurulur, atis motoru kesilir. Buton birakilinca (0 V)
// sistem kendiliginden calismaya devam eder.
//
// KABLOLAMA: buton pinin bir ucunu 3.3 V'a baglar. Buton basili degilken pin
// havada kalmasin diye asagida dahili PULLDOWN aciliyor; disaridan 10k
// pulldown direnci de koyarsan (tavsiye edilir) daha guruluye dayanikli olur.
// Pine ASLA 5 V verme, ESP32 girisleri 3.3 V toleransli.
//
// NOT: GPIO3 ESP32-S3'te bir strapping pinidir (JTAG kaynak secimi). Fabrika
// eFuse ayarlariyla (varsayilan) acilista okunmaz, bu yuzden giris olarak
// kullanmak guvenlidir. Yine de kart acilirken butona basili tutmaktan kacin.
#define DUR_PIN          3      // -1 yaparsan ozellik tamamen kapanir
#define DUR_AKTIF_HIGH  true    // true: 3.3 V = DUR | false: 0 V = DUR (NC buton)
#define DUR_DEBOUNCE_MS   20    // buton zipllamasini (bounce) filtrele

// Durdurma sirasinda surucu ENABLE pinleri de kesilsin mi?
//   false (varsayilan): bobinler enerjili kalir, motorlar konumunu TUTAR.
//                       Dikey eksen yerçekimiyle asagi kaymaz.
//   true              : surucu tamamen kapanir (sessiz, isinmaz) ama motor
//                       serbest kalir; yuklu bir eksen kendi agirligiyla duser.
#define DUR_SURUCU_KAPAT false

// Teshis: pinin o anki halini duzenli olarak seri porta (ve WiFi modunda PC'ye)
// basar. Buton calismiyorsa once bunu acip degerin butona basinca 0 -> 1
// degistigini dogrula. Sorun cozulunce 0 yapip kapatabilirsin.
#define DUR_DEBUG      1
#define DUR_DEBUG_MS 500    // kac ms'de bir basilsin

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

// ==================== ATIS MOTORU (BTS7960 / IBT-2) ====================
// Atis mekanizmasi servo degil, BTS7960 surucu karti uzerinden surulen bir DC
// motordur. Motor tek yonde KISA DARBELERLE calisir; her darbe bir "atis"tir.
// RT tetigi darbenin gucunu degil, saniyede kac darbe atilacagini belirler:
// tetigi az cekersen darbeler seyrek, sonuna kadar cekersen sik gelir.
//
// BAGLANTI (calistigi dogrulanmis sekil):
//   VCC   -> kartin 5V pini      (modulun mantik beslemesi)
//   GND   -> kart GND            ORTAK GND SART, yoksa surucu tetiklenmez
//   R_EN  -> modulun 5V'u        (jumper ile; kart pini harcamaz)
//   L_EN  -> modulun 5V'u        (jumper ile)
//   RPWM  -> ATIS_RPWM_PIN
//   LPWM  -> ATIS_LPWM_PIN       BOSTA BIRAKMA - kod bu pini 0'da tutar
//   B+/B- -> 5.5-27 V motor besleme (step motor beslemesiyle ortak olabilir)
//   M+/M- -> motor
//
// NOT: ESP32 cikislari 3.3 V'tur. IBT-2 girisleri 3.3 V mantikla calisir ama
// motor zayif kalirsa ATIS_GUC'u yukselt; yine olmazsa RPWM/LPWM'e 5 V seviye
// cevirici gerekir.
#define ATIS_RPWM_PIN     10    // ileri yon PWM (eski servo pini)
#define ATIS_LPWM_PIN     11    // geri yon PWM - normalde 0'da durur
#define ATIS_GUC         170    // 0-255 darbe gucu. 255 = tam guc
#define ATIS_CALISMA_MS  200    // her darbede motorun dondugu sure
#define ATIS_ARA_YAVAS_MS 1500  // RT esigi yeni gecildiginde iki darbe arasi
#define ATIS_ARA_HIZLI_MS  150  // RT sonuna kadar cekildiginde iki darbe arasi
#define ATIS_TERS       false   // motor ters yone donuyorsa true yap
#define RT_ESIK         0.05f   // bunun altindaki RT = atis yok, motor durur

#define ATIS_PWM_HZ     1000    // BTS7960 icin 1-25 kHz arasi uygundur
#define ATIS_PWM_BIT       8    // 8 bit cozunurluk -> 0..255 (analogWrite olcegi)
#define ATIS_LEDC_KANAL_R  4    // yalnizca eski ESP32 cekirdeklerinde (2.x)
#define ATIS_LEDC_KANAL_L  5

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

// ==================== ATIS MOTORU ====================
float atisRT   = 0.0f;       // PC'den gelen tetik degeri, 0..1 (0 = atis yok)
uint8_t atisPwm = 0;         // suruculere en son yazilan guc (teshis icin)
bool atisCaliyor = false;    // su an bir darbe suruyor mu
unsigned long atisFazBaslangic = 0;   // ms - suren fazin baslangici
unsigned long atisAraSuresi = 0;      // ms - bir sonraki darbeye kalan bekleme
unsigned long atisSayaci = 0;         // tamamlanan darbe (atis) sayisi

// PWM cikisi. ESP32'de analogWrite cekirdek surumune gore degistigi icin
// dogrudan LEDC kullaniyoruz; AVR kartlarda analogWrite zaten yeterli.
void atisPwmBaslat() {
#if defined(ARDUINO_ARCH_ESP32)
  #if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcAttach(ATIS_RPWM_PIN, ATIS_PWM_HZ, ATIS_PWM_BIT);
    ledcAttach(ATIS_LPWM_PIN, ATIS_PWM_HZ, ATIS_PWM_BIT);
  #else
    ledcSetup(ATIS_LEDC_KANAL_R, ATIS_PWM_HZ, ATIS_PWM_BIT);
    ledcAttachPin(ATIS_RPWM_PIN, ATIS_LEDC_KANAL_R);
    ledcSetup(ATIS_LEDC_KANAL_L, ATIS_PWM_HZ, ATIS_PWM_BIT);
    ledcAttachPin(ATIS_LPWM_PIN, ATIS_LEDC_KANAL_L);
  #endif
#else
  pinMode(ATIS_RPWM_PIN, OUTPUT);
  pinMode(ATIS_LPWM_PIN, OUTPUT);
#endif
}

// Tek yonde guc verir. BTS7960'ta bir yon PWM alirken diger yon MUTLAKA 0
// olmali; ikisi birden surulurse kopru kisa devre olur ve surucu isinir.
void atisGucYaz(uint8_t guc) {
  atisPwm = guc;
  uint8_t r = ATIS_TERS ? 0 : guc;
  uint8_t l = ATIS_TERS ? guc : 0;

#if defined(ARDUINO_ARCH_ESP32)
  #if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcWrite(ATIS_RPWM_PIN, r);
    ledcWrite(ATIS_LPWM_PIN, l);
  #else
    ledcWrite(ATIS_LEDC_KANAL_R, r);
    ledcWrite(ATIS_LEDC_KANAL_L, l);
  #endif
#else
  analogWrite(ATIS_RPWM_PIN, r);
  analogWrite(ATIS_LPWM_PIN, l);
#endif
}

void atisBaslat() {
  atisPwmBaslat();
  atisGucYaz(0);             // guvenli baslangic: motor durur
}

// Motoru aninda keser. Suren darbe varsa yarida biter - yalnizca acil
// durdurmada kullanilir.
void atisDurdur() {
  atisRT = 0.0f;
  atisCaliyor = false;
  atisAraSuresi = 0;
  atisGucYaz(0);
}

// RT'den iki darbe arasindaki bekleme suresini (ms) hesaplar.
// Tetik ne kadar cok cekilirse bekleme o kadar kisalir, yani atis siklasir.
unsigned long atisAralikHesapla() {
  float oran = (atisRT - RT_ESIK) / (1.0f - RT_ESIK);
  if (oran < 0.0f) oran = 0.0f;
  if (oran > 1.0f) oran = 1.0f;
  return (unsigned long)(ATIS_ARA_YAVAS_MS -
                         oran * (ATIS_ARA_YAVAS_MS - ATIS_ARA_HIZLI_MS));
}

// Calis/dur dongusunu delay() olmadan yurutur; step motorlarin adim zamanlamasi
// bozulmasin diye hicbir yerde beklenmez.
void atisGuncelle() {
  unsigned long simdi = millis();

  if (atisCaliyor) {
    // Baslayan darbe, tetik birakilsa bile tamamlanir: mekanizma yarim
    // konumda kalmasin.
    if (simdi - atisFazBaslangic >= ATIS_CALISMA_MS) {
      atisGucYaz(0);
      atisCaliyor = false;
      atisFazBaslangic = simdi;
      atisAraSuresi = atisAralikHesapla();
      atisSayaci++;
    }
    return;
  }

  atisGucYaz(0);

  if (atisRT < RT_ESIK) {
    atisAraSuresi = 0;       // tetik birakildi: tekrar cekilince hemen atsin
    return;
  }
  if (simdi - atisFazBaslangic < atisAraSuresi) return;

  atisCaliyor = true;
  atisFazBaslangic = simdi;
  atisGucYaz(ATIS_GUC);
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

// ==================== ACIL DURDURMA ====================
bool durAktif = false;       // debounce'lanmis gecerli durum (true = DURDURULDU)
bool durHam   = false;       // pinden okunan ham (filtresiz) durum
unsigned long durHamZaman = 0;

// Butun kanallara ayni satiri bas (USB + varsa WiFi).
void durHaberVer(const char *mesaj) {
  SERI.println(mesaj);
#if BAGLANTI_MODU
  udpYaz(mesaj);
#endif
}

// ENABLE aktif-LOW: ac=true -> LOW (surucu calisir), ac=false -> HIGH (serbest).
void surucuEnable(bool ac) {
  if (EN1_PIN >= 0) digitalWrite(EN1_PIN, ac ? LOW : HIGH);
  if (EN2_PIN >= 0) digitalWrite(EN2_PIN, ac ? LOW : HIGH);
}

// Butonu okur, zipllamasini (bounce) filtreler, durum degisince tepki verir.
// Her donguden cagrilir, bloklamaz.
void durPiniGuncelle() {
#if DUR_PIN >= 0
  unsigned long simdi = millis();

  int  ham    = digitalRead(DUR_PIN);          // pinin fiziksel hali (0/1)
  bool okunan = (ham == HIGH);
  if (!DUR_AKTIF_HIGH) okunan = !okunan;

#if DUR_DEBUG
  // Pinin ham degerini duzenli bas. Butona basinca burada 0 -> 1 gormuyorsan
  // sorun yazilimda degil kablolamadadir (asagidaki notlara bak).
  static unsigned long sonDurBasim = 0;
  if (simdi - sonDurBasim >= DUR_DEBUG_MS) {
    sonDurBasim = simdi;
    char satir[80];
    snprintf(satir, sizeof(satir), "stop pini GPIO%d = %d (%s) | durum: %s",
             DUR_PIN, ham, ham ? "3.3V var" : "0V",
             durAktif ? "DURDURULDU" : "serbest");
    durHaberVer(satir);
  }
#endif

  // Sinyal her degistiginde sayaci sifirla; DUR_DEBOUNCE_MS boyunca sabit
  // kalirsa gercek durum olarak kabul et.
  if (okunan != durHam) {
    durHam = okunan;
    durHamZaman = simdi;
    return;
  }
  if (okunan == durAktif) return;                  // zaten bu durumdayiz
  if (simdi - durHamZaman < DUR_DEBOUNCE_MS) return;

  durAktif = okunan;

  if (durAktif) {
    // Rampayi beklemeden hizi sifirla: fren mesafesi bile birakma.
    motorDurdur(m1);
    motorDurdur(m2);
    atisDurdur();                                  // atis motorunu aninda kes
#if DUR_SURUCU_KAPAT
    surucuEnable(false);
#endif
    durHaberVer("DURDURMA AKTIF (stop pini)");
  } else {
    surucuEnable(true);
    durHaberVer("DURDURMA KALKTI - kontrol geri verildi");
  }
#endif
}

// ==================== TELEMETRI ====================
// Kartin anlik durumunu JSON olarak YKI backend'ine yollar. Backend'in
// telemetryBridge'i JSON bekledigi icin burada dogrudan JSON uretiyoruz;
// boylece arayuz tarafinda ek bir ayristiriciya gerek kalmiyor.
#if BAGLANTI_MODU && TELEMETRI_HZ > 0
unsigned long telemetriSon = 0;
unsigned long telemetriSeq = 0;

void telemetriGonder() {
  unsigned long simdi = millis();
  if (simdi - telemetriSon < (1000UL / TELEMETRI_HZ)) return;
  telemetriSon = simdi;

  // Hedef: sabit IP verilmisse oraya, verilmemisse komutu gonderen PC'ye.
  // Henuz komut gelmediyse ag yayin adresine gonderilir; boylece YKI, joystick
  // yazilimi hic acilmadan da veri gorur.
  IPAddress hedef;
  if (!hedef.fromString(TELEMETRI_IP) || hedef == IPAddress(0, 0, 0, 0)) {
  #if BAGLANTI_MODU == 2
    hedef = pcPortu ? pcAdresi : WiFi.softAPBroadcastIP();
  #else
    hedef = pcPortu ? pcAdresi : WiFi.broadcastIP();
  #endif
  }

#if BAGLANTI_MODU == 2
  int rssi = 0;                       // AP modunda kartin kendi RSSI'si yok
#else
  int rssi = (int)WiFi.RSSI();
#endif

  // Arayuzun grafikleri "rssi" alanini kullanir; digerleri ham tabloda cikar.
  char j[300];
  snprintf(j, sizeof(j),
    "{\"src\":\"esp\",\"seq\":%lu,\"uptime\":%lu,"
    "\"m1_hiz\":%d,\"m2_hiz\":%d,\"m1_hedef\":%d,\"m2_hedef\":%d,"
    "\"rt\":%.2f,\"atis_sayisi\":%lu,\"atis_pwm\":%d,\"atis_aktif\":%s,"
    "\"stop\":%s,\"rssi\":%d,\"komut_yasi\":%lu}",
    telemetriSeq++, simdi,
    (int)m1.hiz, (int)m2.hiz, (int)m1.hedefHiz, (int)m2.hedefHiz,
    atisRT, atisSayaci, (int)atisPwm, atisCaliyor ? "true" : "false",
    durAktif ? "true" : "false", rssi, simdi - sonVeri);

  udp.beginPacket(hedef, TELEMETRI_PORT);
  udp.print(j);
  udp.endPacket();
}
#endif  // BAGLANTI_MODU && TELEMETRI_HZ

// ==================== SERI ====================
// "0.42,-0.87\n" formatindaki satiri ayristirir.
// Beklenen bicim: "<dikey>,<yatay>,<rt>\n"  or. "0.000,1.000,0.750"
// Ucuncu alan yoksa (eski surum PC yazilimi) rt = 0 kabul edilir: atis olmaz.
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
  atisRT = rt;
  sonVeri = millis();

#if DEBUG_SERI
  static unsigned long sonBasim = 0;
  if (millis() - sonBasim > 200) {     // ~5 Hz; hatti bogmamak icin
    sonBasim = millis();
    char satir[80];
    snprintf(satir, sizeof(satir), "rx %.3f,%.3f,%.2f hiz %d,%d atis pwm %d",
             eksen1, eksen2, rt, (int)m1.hiz, (int)m2.hiz, atisPwm);
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

  // Durdurma butonu. Dahili pulldown, buton basili degilken pinin havada
  // kalip gurultuyle rastgele tetiklenmesini onler.
#if DUR_PIN >= 0
  #if defined(ARDUINO_ARCH_ESP32)
    pinMode(DUR_PIN, DUR_AKTIF_HIGH ? INPUT_PULLDOWN : INPUT_PULLUP);
  #else
    pinMode(DUR_PIN, DUR_AKTIF_HIGH ? INPUT : INPUT_PULLUP);
  #endif
  // Acilista butona basili ise sistem DURDURULMUS baslasin.
  durHam = (digitalRead(DUR_PIN) == HIGH);
  if (!DUR_AKTIF_HIGH) durHam = !durHam;
  durAktif = durHam;
  durHamZaman = millis();
  SERI.print("stop pini   : GPIO "); SERI.print(DUR_PIN);
  SERI.print(" acilis degeri = "); SERI.println(digitalRead(DUR_PIN));
  if (durAktif) {
  #if DUR_SURUCU_KAPAT
    surucuEnable(false);
  #endif
    SERI.println("DIKKAT: stop pini acilista aktif - motorlar kilitli");
  }
#endif

  // Atis motoru: PWM 0 ile baslar, yani komut gelene kadar DURUR.
  atisBaslat();

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
  // Durdurma butonu her seyden once okunur.
  durPiniGuncelle();

#if BAGLANTI_MODU && TELEMETRI_HZ > 0
  // YKI arayuzune anlik durum. Test modlarinda da calisir ki kablolama
  // testi sirasinda da arayuzden izleyebilesin.
  telemetriGonder();
#endif

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
    if (durAktif) { motorDurdur(m1); motorDurdur(m2); return; }

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
  // Atis da durur: kablo/WiFi kopunca atis mekanizmasi kendi basina calismaya
  // devam etmemeli. Suren darbe varsa tamamlanir, yenisi baslamaz.
  if (millis() - sonVeri > VERI_TIMEOUT) {
    motorDurdur(m1);
    motorDurdur(m2);
    atisRT = 0.0f;
  }

  // --- Guvenlik: stop pini basiliyken hicbir komut uygulanmaz ---
  // Gelen veri yukarida okunmaya DEVAM eder (okunmazsa USB/UDP tamponu dolar
  // ve PC tarafi "Write timeout" verir), sadece motora yansitilmaz.
  if (durAktif) {
    motorDurdur(m1);
    motorDurdur(m2);
    atisRT = 0.0f;
  }

  // --- Rampa: sabit 1 kHz'de guncelle (her dongude float hesabi yavaslatir) ---
  unsigned long simdi = micros();
  if (simdi - sonRampa >= 1000) {
    float dt = (simdi - sonRampa) / 1000000.0;
    sonRampa = simdi;
    if (dt > 0.05) dt = 0.05;         // takilma/tasma sonrasi sicramayi engelle
    rampaGuncelle(m1, dt);
    rampaGuncelle(m2, dt);
    atisGuncelle();                   // atis motoru da ayni saatte guncellenir
  }

  // --- Motorlari sur ---
  motorCalistir(m1);
  motorCalistir(m2);
}
