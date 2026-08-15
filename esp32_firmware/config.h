#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>

//pinler uyumlu 
#define AZ_ENCODER_I2C_ADDR    0x36   // AS5600, Wire (hat 1) - yaty eksen
#define ELEV_ENCODER_I2C_ADDR  0x36   // AS5600, Wire1 (hat 2) - dikey açı
#define AZ_STEP_PIN      6
#define AZ_DIR_PIN       7
#define AZ_EN_PIN        9
#define ELEV_STEP_PIN    4
#define ELEV_DIR_PIN     5
#define ELEV_EN_PIN      8

//pinler uyumlu  
#define AZ_I2C_SDA_PIN     1
#define AZ_I2C_SCL_PIN     2
#define ELEV_I2C_SDA_PIN   41
#define ELEV_I2C_SCL_PIN   42

//USB Bağlantısı var kullanılmayacak
#define RPI_UART_RX_PIN     16
#define RPI_UART_TX_PIN     17
#define RPI_UART_BAUD       115200  //saniyede gönderilen bit veri

// ==================== UART - LiDAR (TF03-180) PINLERI ====================
#define LIDAR_UART_RX_PIN   18
#define LIDAR_UART_TX_PIN   15      
#define LIDAR_UART_BAUD     115200

// ==================== MOTOR SÜRÜCÜ I2C (SU AN KULLANILMIYOR) ====================
// Kodun hicbir yerinde bu iki pin kullanilmiyor. MKS Servo42C step/dir
// ile suruluyor. Yine de gecerli pinlere tasindi (eski SCL=22 S3'te yok).
#define MOTOR_I2C_SDA_PIN   47
#define MOTOR_I2C_SCL_PIN   48

// ==================== MOSFET ÇIKIŞ PINLERI ====================
// MOSFET4 (solenoid valf) KALDIRILDI - artik tufek + ip/servo tetik var.
#define MOSFET1_LASER_PIN      12   // Lazer            (eski 25 -> gecersiz)
#define MOSFET2_FEED_MOTOR_PIN 13   // Mühimmat besleme (eski 26 -> flash)
#define MOSFET3_BEACON_PIN     14   // İkaz kulesi      (eski 27 -> flash)

// ==================== TETIK SERVOSU (ip ile tufek tetigi) ====================
#define TRIGGER_SERVO_PIN        10
#define TRIGGER_REST_DEG         20      // ip bos - tetik serbest
#define TRIGGER_PULL_DEG         75      // ip gergin - tetik cekili
#define TRIGGER_PULL_MS          90      // cekili kalma suresi
#define TRIGGER_RELEASE_MS      110      // geri donup oturma suresi
#define TRIGGER_SERVO_MIN_US    500
#define TRIGGER_SERVO_MAX_US   2500
#define TRIGGER_SERVO_PWM_HZ     50

// 1 = tufek yari otomatik: bir tetik cekisi = bir mermi (mühimmat sayaci dogru)
// 0 = tam otomatik: tetik cekili kaldigi surece mermi gider, sayac GUVENILMEZ
#define RIFLE_IS_SEMI_AUTO        1

// ==================== E-STOP PINI ====================
#define ESTOP_PIN           3     

// ==================== WIFI / JOYSTICK (YKI arayuzu) ====================
// YKI backend'indeki joystickBridge.js buraya UDP ile
// "pitch,yaw,fire,arm\n" satiri gonderir.
#define JOYSTICK_WIFI_MODE      1        // 0: kapali | 1: STA (agi kullan) | 2: AP (kendi agi)
#define JOYSTICK_WIFI_SSID      "yunus"
#define JOYSTICK_WIFI_PASS      "1234567890"
#define JOYSTICK_UDP_PORT       5005     // yki_config.json > esp32.udpPort ile ayni
#define JOYSTICK_MDNS_NAME      "celikkubbe"   // -> celikkubbe.local
#define JOYSTICK_WIFI_TIMEOUT_MS 10000

// Bu sure boyunca joystick paketi gelmezse eksenler durur, tetik birakilir.
#define JOYSTICK_TIMEOUT_MS      300
#define JOYSTICK_DEADZONE        0.08f   // tarayicidaki OLU_BOLGE ile ayni
#define JOYSTICK_TASK_PERIOD_MS  20      // 50 Hz
#define JOYSTICK_ALLOW_SERIAL    1       // USB'den de "p,y,f,a" satiri kabul et (tezgah testi)
#define JOYSTICK_FIRE_AUTOREPEAT 1       // tetik basili tutulunca SHOT_INTERVAL_MS'de bir tekrar

// Joystick tam saptirildiginda eksen hizi (derece/saniye).
// Eski joystick_motor.ino: MAX_HIZ1=1000, MAX_HIZ2=600 adim/sn
//   -> 1000 * 0.1125 = 112.5 °/s ,  600 * 0.1125 = 67.5 °/s
// Buraya emniyetli baslangic degerleri konuldu, TESTLE ARTIRIN.
#define JOYSTICK_AZ_RATE_DEG_S   45.0f
#define JOYSTICK_EL_RATE_DEG_S   30.0f

// ==================== ACIK CEVRIM HIZ MODU (encoder yokken) ====================
// Encoder takili olmadigi icin manuel modda PID kapali cevrim CALISMAZ
// (encoder_getAzimuthDeg() surekli 0 doner, PID motoru tavan hizda surer).
// Manuel modda acik cevrim hiz kontrolu + rampali ivme kullanilir ve
// pozisyon, komut edilen hizin integrali ile TAHMIN edilir.
#define VEL_ACCEL_DEG_S2        300.0f   // hizlanma
#define VEL_DECEL_DEG_S2       1200.0f   // yavaslama (hizlanmadan buyuk olmali)

// ==================== ELEKTRIKSEL SABITLER ====================
#define BATTERY_NOMINAL_VOLTAGE   14.8f   // 4S LiPo nominal voltaj
#define BATTERY_FULL_VOLTAGE      16.8f   // 4S LiPo tam şarj voltaj

// ==================== PID KATSAYILARI ====================
#define PID_KP              1.0f
#define PID_KI              0.0f
#define PID_KD              0.1f

// ==================== HOMING (CMD_HOME) HIZ LIMITI ====================
#define HOMING_VELOCITY_LIMIT_DEG_S   15.0f

// ==================== HAREKET SINIRLARI ====================
#define AZIMUTH_MIN_DEG     -180.0f
#define AZIMUTH_MAX_DEG      180.0f
#define ELEVATION_MIN_DEG    -10.0f
#define ELEVATION_MAX_DEG     45.0f

// ==================== ATIŞA YASAK ALAN SINIRLARI ====================
#define NOFIRE_ZONE_MIN_DEG  -30.0f
#define NOFIRE_ZONE_MAX_DEG   30.0f

// ==================== ANGAJMAN MENZİLLERİ (metre) ====================
#define RANGE_F16_MIN_M       10.0f
#define RANGE_F16_MAX_M       15.0f
#define RANGE_HELI_MISSILE_MIN_M   5.0f
#define RANGE_HELI_MISSILE_MAX_M  15.0f
#define RANGE_UAV_MIN_M        0.0f
#define RANGE_UAV_MAX_M       15.0f

// LiDAR takili degilken manuel atis testi yapabilmek icin 0 yapin.
// SAHADA 1 OLMALI - aksi halde menzil kapisi devre disi kalir.
#define REQUIRE_LIDAR_FOR_FIRE   1

// ==================== MÜHIMMAT SINIRI ====================
#define MAX_AMMO_COUNT       100     // ŞARJÖR KAPASİTESİNE GÖRE AYARLAYIN

// ==================== ENCODER ====================
#define ENCODER_RESOLUTION_BITS   12
#define ENCODER_MAX_VALUE     4096   // 2^12

// ==================== SISTEM MODLARI ====================
enum SystemMode {
  MANUAL,                // Aşama-1: Operatör joystick kontrolü
  AUTONOMOUS_SWARM,       // Aşama-2: Otonom sürü tespiti/imhası
  AUTONOMOUS_LAYERED      // Aşama-3: Dost/düşman ayrımı + otonom angajman
};

// RPi bagli degilken de joystick calissin diye acilis modu.
// Sahada RPi ile calisiyorsanız PROTO_MODE_IDLE yapin.
#define DEFAULT_BOOT_MODE_MANUAL   1

// ==================== SISTEM DURUMLARI (State Machine) ====================
enum SystemState {
  ST_INIT,                    // Başlangıç
  ST_STANDBY,                 // Beklemede, hedef aranıyor
  ST_TRACKING,                // Hedef takip ediliyor
  ST_ENGAGING,                 // Atış süreci
  ST_SAFE_STOP,                // Mühimmat bitti veya hedef kayboldu, güvenli durdurma
  ST_EMERGENCY_SHUTDOWN        // E-Stop tetiklendi, hakem onayı bekleniyor
};

// ==================== HATA KODLARI ====================
#define ERR_AMMO_DEPLETED        "ERR_AMMO_DEPLETED"
#define SYS_EMERGENCY_SHUTDOWN   "SYS_EMERGENCY_SHUTDOWN"

// ==================== TASK ÖNCELİKLERİ (FreeRTOS) ====================
#define TASK_PRIORITY_SAFETY      3
#define TASK_PRIORITY_MOTOR       2
#define TASK_PRIORITY_UART        2
#define TASK_PRIORITY_JOYSTICK    2
#define TASK_PRIORITY_LIDAR       1

// ==================== TASK STACK BOYUTLARI (byte) ====================
#define TASK_STACK_SAFETY      2048
#define TASK_STACK_MOTOR        4096
#define TASK_STACK_UART         4096
#define TASK_STACK_JOYSTICK     4096
#define TASK_STACK_LIDAR        2048

#endif