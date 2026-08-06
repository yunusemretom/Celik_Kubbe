#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>

#define AZ_ENCODER_I2C_ADDR    0x36   // AS5600, Wire (hat 1) - yaty eksen
#define ELEV_ENCODER_I2C_ADDR  0x36   // AS5600, Wire1 (hat 2) - dikey açı
#define AZ_STEP_PIN      4
#define AZ_DIR_PIN       5
#define AZ_EN_PIN        6
#define ELEV_STEP_PIN    7
#define ELEV_DIR_PIN     8
#define ELEV_EN_PIN      9

//Değişecek
#define AZ_I2C_SDA_PIN     35   
#define AZ_I2C_SCL_PIN     36   
#define ELEV_I2C_SDA_PIN   37   
#define ELEV_I2C_SCL_PIN   38   

// ==================== UART - RPi HABERLEŞME PINLERI ====================
#define RPI_UART_RX_PIN     16
#define RPI_UART_TX_PIN     17
#define RPI_UART_BAUD       115200  //saniyede gönderilen bit veri

// ==================== UART - LiDAR (TF03-180) PINLERI ====================
#define LIDAR_UART_RX_PIN   18
#define LIDAR_UART_TX_PIN   19
#define LIDAR_UART_BAUD     115200

// ==================== MOTOR SÜRÜCÜ (MKS Servo42C) PINLERI ====================
#define MOTOR_I2C_SDA_PIN   21 
#define MOTOR_I2C_SCL_PIN   22 

// ==================== MOSFET ÇIKIŞ PINLERI ====================
#define MOSFET1_LASER_PIN      25   // Lazer
#define MOSFET2_FEED_MOTOR_PIN 26   // Mühimmat besleme motoru
#define MOSFET3_BEACON_PIN     27   // İkaz kulesi uyarı lambası
#define MOSFET4_SOLENOID_PIN   32   // Ateşleme valf (solenoid)

// ==================== E-STOP PINI ====================
#define ESTOP_PIN           33      // NC (Normalde Kapalı) buton, harici kesme (interrupt) için kullanılacak

// ==================== ELEKTRIKSEL SABITLER ====================
#define BATTERY_NOMINAL_VOLTAGE   14.8f   // 4S LiPo nominal voltaj
#define BATTERY_FULL_VOLTAGE      16.8f   // 4S LiPo tam şarj voltaj

// ==================== PID KATSAYILARI (Azimuth ve Elevasyon için ayrı ayrı ayarlanacak) ====================
#define PID_KP              1.0f
#define PID_KI              0.0f
#define PID_KD              0.1f

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
#define RANGE_UAV_MAX_M        15.0f

// ==================== MÜHIMMAT SINIRI ====================
#define MAX_AMMO_COUNT       100     // Yazılımsal mühimmat sınırı (magazin kapasitesine göre ayarlanacak)

// ==================== ENCODER ====================
#define ENCODER_RESOLUTION_BITS   12
#define ENCODER_MAX_VALUE     4096   // 2^12

// ==================== SISTEM MODLARI ====================
enum SystemMode {
  MANUAL,                // Aşama-1: Operatör joystick kontrolü
  AUTONOMOUS_SWARM,       // Aşama-2: Otonom sürü tespiti/imhası
  AUTONOMOUS_LAYERED      // Aşama-3: Dost/düşman ayrımı + otonom angajman
};

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
#define TASK_PRIORITY_LIDAR       1

// ==================== TASK STACK BOYUTLARI (byte) ====================
#define TASK_STACK_SAFETY      2048
#define TASK_STACK_MOTOR        4096
#define TASK_STACK_UART         4096
#define TASK_STACK_LIDAR        2048

#endif // CONFIG_H