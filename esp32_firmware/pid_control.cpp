#include "pid_control.h"
#include "encoder.h"
#include "uart_protocol.h"   // sendErr(), ERR_AZ_LIMIT/ERR_EL_LIMIT icin

#define DEGREES_PER_STEP        0.1125f

#define MAX_STEP_FREQ_HZ        8000.0f
#define MIN_STEP_FREQ_HZ        20.0f

#define LEDC_RESOLUTION_BITS    8
#define LEDC_DUTY_50_PERCENT    128

#define INTEGRAL_LIMIT               50.0f
#define VELOCITY_OUTPUT_LIMIT_DEG_S  200.0f
#define DEAD_BAND_DEG                 0.03f

// Hiz modunda "durdu" sayilan esik (derece/saniye)
#define VELOCITY_STOPPED_DEG_S        1.0f

static AxisControlState azState;
static AxisControlState elevState;

struct AxisGains {
    float kp;
    float ki;
    float kd;
};
static AxisGains azGains   = { PID_KP, PID_KI, PID_KD };
static AxisGains elevGains = { PID_KP, PID_KI, PID_KD };

static bool estopped = true;
static float currentVelocityLimitDegS = VELOCITY_OUTPUT_LIMIT_DEG_S;
static PidControlMode controlMode = PID_MODE_POSITION;

// Son pid_setTargetAngles() cagrisinda hangi eksen(ler) kirpildi (clamp).
static bool azClampedFlag   = false;
static bool elevClampedFlag = false;


static void resetAxisState(AxisControlState &axis, float initialAngleDeg) {
    axis.currentAngleDeg    = initialAngleDeg;
    axis.targetAngleDeg     = initialAngleDeg;
    axis.integral           = 0.0f;
    axis.previousError      = 0.0f;
    axis.lastUpdateMicros   = micros();
    axis.commandedStepFreqHz = 0.0f;
    axis.movingPositive     = true;

    axis.velocityCmdDegS    = 0.0f;
    axis.velocityActualDegS = 0.0f;
    axis.estimatedAngleDeg  = 0.0f;
}


void pid_init() {
    pinMode(AZ_DIR_PIN, OUTPUT);
    pinMode(ELEV_DIR_PIN, OUTPUT);
    digitalWrite(AZ_DIR_PIN, HIGH);
    digitalWrite(ELEV_DIR_PIN, HIGH);
    pinMode(AZ_EN_PIN, OUTPUT);
    pinMode(ELEV_EN_PIN, OUTPUT);
    digitalWrite(AZ_EN_PIN, LOW);
    digitalWrite(ELEV_EN_PIN, LOW);

    ledcAttach(AZ_STEP_PIN, MIN_STEP_FREQ_HZ, LEDC_RESOLUTION_BITS);
    ledcAttach(ELEV_STEP_PIN, MIN_STEP_FREQ_HZ, LEDC_RESOLUTION_BITS);
    ledcWrite(AZ_STEP_PIN, 0);
    ledcWrite(ELEV_STEP_PIN, 0);

    float startAz   = encoder_getAzimuthDeg();
    float startElev = encoder_getElevationDeg();

    resetAxisState(azState, startAz);
    resetAxisState(elevState, startElev);

    azGains   = { PID_KP, PID_KI, PID_KD };
    elevGains = { PID_KP, PID_KI, PID_KD };

    azClampedFlag = false;
    elevClampedFlag = false;

    controlMode = PID_MODE_POSITION;
    estopped = false;
}


// ====================================================================
// KONTROL MODU
// ====================================================================
void pid_setControlMode(PidControlMode mode) {
    if (mode == controlMode) return;

    // Mod degisiminde motoru durdur: iki mod arasinda hiz/hedef durumu
    // tasinirsa taret ani sicrama yapar.
    ledcWrite(AZ_STEP_PIN, 0);
    ledcWrite(ELEV_STEP_PIN, 0);

    azState.velocityCmdDegS    = 0.0f;
    azState.velocityActualDegS = 0.0f;
    azState.commandedStepFreqHz = 0.0f;
    elevState.velocityCmdDegS    = 0.0f;
    elevState.velocityActualDegS = 0.0f;
    elevState.commandedStepFreqHz = 0.0f;

    azState.integral = 0.0f;   azState.previousError = 0.0f;
    elevState.integral = 0.0f; elevState.previousError = 0.0f;
    azState.lastUpdateMicros = micros();
    elevState.lastUpdateMicros = micros();

    if (mode == PID_MODE_POSITION) {
        // Kapali cevrime donerken hedefi mevcut konuma esitle, yoksa
        // eski hedefe dogru aniden kosar.
        azState.targetAngleDeg   = encoder_getAzimuthDeg();
        elevState.targetAngleDeg = encoder_getElevationDeg();
    } else {
        azState.targetAngleDeg   = azState.estimatedAngleDeg;
        elevState.targetAngleDeg = elevState.estimatedAngleDeg;
    }

    controlMode = mode;
    LOG_INFO("Mod: %s", mode == PID_MODE_VELOCITY ? "HIZ" : "POZISYON");
}

PidControlMode pid_getControlMode() {
    return controlMode;
}


void pid_setVelocityCommand(float azDegS, float elevDegS) {
    if (azDegS >  currentVelocityLimitDegS) azDegS =  currentVelocityLimitDegS;
    if (azDegS < -currentVelocityLimitDegS) azDegS = -currentVelocityLimitDegS;
    if (elevDegS >  currentVelocityLimitDegS) elevDegS =  currentVelocityLimitDegS;
    if (elevDegS < -currentVelocityLimitDegS) elevDegS = -currentVelocityLimitDegS;

    azState.velocityCmdDegS   = azDegS;
    elevState.velocityCmdDegS = elevDegS;
}


void pid_zeroPositionEstimate() {
    azState.estimatedAngleDeg   = 0.0f;
    elevState.estimatedAngleDeg = 0.0f;
    azState.currentAngleDeg     = 0.0f;
    elevState.currentAngleDeg   = 0.0f;
    LOG_INFO("Pozisyon tahmini sifirlandi (0/0)");
}

void pid_setTargetAngles(float azimuthDeg, float elevationDeg) {
    // Hiz modunda joystick tek efendidir; CMD_AIM burada yok sayilir.
    if (controlMode == PID_MODE_VELOCITY) return;

    float requestedAz = azimuthDeg;
    float requestedEl = elevationDeg;

    azClampedFlag = false;
    elevClampedFlag = false;

    if (azimuthDeg < AZIMUTH_MIN_DEG) { azimuthDeg = AZIMUTH_MIN_DEG; azClampedFlag = true; }
    if (azimuthDeg > AZIMUTH_MAX_DEG) { azimuthDeg = AZIMUTH_MAX_DEG; azClampedFlag = true; }
    if (elevationDeg < ELEVATION_MIN_DEG) { elevationDeg = ELEVATION_MIN_DEG; elevClampedFlag = true; }
    if (elevationDeg > ELEVATION_MAX_DEG) { elevationDeg = ELEVATION_MAX_DEG; elevClampedFlag = true; }

    azState.targetAngleDeg   = azimuthDeg;
    elevState.targetAngleDeg = elevationDeg;

    if (azClampedFlag) {
        sendErr(ERR_AZ_LIMIT, (uint16_t)(int16_t)(requestedAz * 10.0f));
    }
    if (elevClampedFlag) {
        sendErr(ERR_EL_LIMIT, (uint16_t)(int16_t)(requestedEl * 10.0f));
    }
}


// ---------- ORTAK: hesaplanan hizi step pinine uygula ----------
static void applyStepOutput(AxisControlState &axis, int stepPin, int dirPin,
                            float velocityDegPerSec) {
    axis.movingPositive = (velocityDegPerSec >= 0.0f);
    digitalWrite(dirPin, axis.movingPositive ? HIGH : LOW);

    float stepFreqHz = fabs(velocityDegPerSec) / DEGREES_PER_STEP;
    if (stepFreqHz > MAX_STEP_FREQ_HZ) stepFreqHz = MAX_STEP_FREQ_HZ;

    if (stepFreqHz < MIN_STEP_FREQ_HZ) {
        axis.commandedStepFreqHz = 0.0f;
        ledcWrite(stepPin, 0);
    } else {
        axis.commandedStepFreqHz = stepFreqHz;
        ledcChangeFrequency(stepPin, (uint32_t)stepFreqHz, LEDC_RESOLUTION_BITS);
        ledcWrite(stepPin, LEDC_DUTY_50_PERCENT);
    }
}


// ====================================================================
// KAPALI CEVRIM (POZISYON) - encoder geri beslemeli, degistirilmedi
// ====================================================================
static void updateAxis(AxisControlState &axis, int stepPin, int dirPin,
                        const AxisGains &gains,
                        float (*readEncoderDeg)()) {
    unsigned long now = micros();
    float dt = (now - axis.lastUpdateMicros) / 1000000.0f;
    if (dt <= 0.0f || dt > 0.5f) dt = 0.001f;
    axis.lastUpdateMicros = now;

    axis.currentAngleDeg = readEncoderDeg();

    float error = axis.targetAngleDeg - axis.currentAngleDeg;

    if (fabs(error) < DEAD_BAND_DEG) {
        axis.integral = 0.0f;
        axis.previousError = 0.0f;
        axis.commandedStepFreqHz = 0.0f;
        ledcWrite(stepPin, 0);
        return;
    }

    axis.integral += error * dt;
    if (axis.integral > INTEGRAL_LIMIT) axis.integral = INTEGRAL_LIMIT;
    if (axis.integral < -INTEGRAL_LIMIT) axis.integral = -INTEGRAL_LIMIT;

    float derivative = (error - axis.previousError) / dt;
    axis.previousError = error;

    float velocityDegPerSec = (gains.kp * error) + (gains.ki * axis.integral) + (gains.kd * derivative);

    if (velocityDegPerSec > currentVelocityLimitDegS)  velocityDegPerSec = currentVelocityLimitDegS;
    if (velocityDegPerSec < -currentVelocityLimitDegS) velocityDegPerSec = -currentVelocityLimitDegS;

    applyStepOutput(axis, stepPin, dirPin, velocityDegPerSec);
}


// ====================================================================
// ACIK CEVRIM (HIZ) - joystick / encoder yokken
//
// Eski joystick_motor.ino'daki rampaGuncelle() mantiginin ayni gorevi
// yapan hali. Farklari:
//   - adim/sn yerine derece/sn ile calisir (protokolle ayni birim)
//   - step palslerini bit-bang degil LEDC uretir (pid ile ayni cikis
//     katmani, pin cakismasi yok)
//   - pozisyon tahmini tutulur, boylece ELEVATION_MIN/MAX ve
//     NOFIRE_ZONE kontrolleri encoder olmadan da calisir
// ====================================================================
static void updateAxisVelocity(AxisControlState &axis, int stepPin, int dirPin,
                                float minDeg, float maxDeg) {
    unsigned long now = micros();
    float dt = (now - axis.lastUpdateMicros) / 1000000.0f;
    if (dt <= 0.0f || dt > 0.5f) dt = 0.001f;
    axis.lastUpdateMicros = now;

    float cmd = axis.velocityCmdDegS;

    // --- HAREKET LIMITI: limite dayandiysa o yone gitmeyi kes ---
    if (cmd > 0.0f && axis.estimatedAngleDeg >= maxDeg) cmd = 0.0f;
    if (cmd < 0.0f && axis.estimatedAngleDeg <= minDeg) cmd = 0.0f;

    // --- Yon degisimi: once sifira in, sonra ters yone cik ---
    // Duran bir step motoru dogrudan ters yone surmek adim kacirtir.
    bool tersYone = (cmd != 0.0f && axis.velocityActualDegS != 0.0f &&
                     ((cmd > 0.0f) != (axis.velocityActualDegS > 0.0f)));
    if (tersYone) cmd = 0.0f;

    // --- Rampa: yavaslarken daha sert ivme (tus birakilinca kaymasin) ---
    float ivme = (fabs(cmd) >= fabs(axis.velocityActualDegS))
                    ? VEL_ACCEL_DEG_S2 : VEL_DECEL_DEG_S2;

    float fark = cmd - axis.velocityActualDegS;
    float adim = ivme * dt;

    if (fark >  adim)      axis.velocityActualDegS += adim;
    else if (fark < -adim) axis.velocityActualDegS -= adim;
    else                   axis.velocityActualDegS = cmd;

    if (fabs(axis.velocityActualDegS) < 0.05f) axis.velocityActualDegS = 0.0f;

    // --- Pozisyon tahmini (komut edilen hizin integrali) ---
    // NOT: bu gercek olculmus aci DEGILDIR. Kacan adimlar birikir.
    // Encoder takilirsa PID_MODE_POSITION'a gecin.
    axis.estimatedAngleDeg += axis.velocityActualDegS * dt;
    if (axis.estimatedAngleDeg > maxDeg) axis.estimatedAngleDeg = maxDeg;
    if (axis.estimatedAngleDeg < minDeg) axis.estimatedAngleDeg = minDeg;

    axis.currentAngleDeg = axis.estimatedAngleDeg;
    axis.targetAngleDeg  = axis.estimatedAngleDeg;   // telemetri tutarli kalsin

    applyStepOutput(axis, stepPin, dirPin, axis.velocityActualDegS);
}


void pid_update() {
    if (estopped) {
        return;
    }

    if (controlMode == PID_MODE_VELOCITY) {
        updateAxisVelocity(azState,   AZ_STEP_PIN,   AZ_DIR_PIN,
                           AZIMUTH_MIN_DEG,   AZIMUTH_MAX_DEG);
        updateAxisVelocity(elevState, ELEV_STEP_PIN, ELEV_DIR_PIN,
                           ELEVATION_MIN_DEG, ELEVATION_MAX_DEG);
        return;
    }

    updateAxis(azState, AZ_STEP_PIN, AZ_DIR_PIN, azGains, encoder_getAzimuthDeg);
    updateAxis(elevState, ELEV_STEP_PIN, ELEV_DIR_PIN, elevGains, encoder_getElevationDeg);
}


float pid_getCurrentAzimuthDeg()   { return azState.currentAngleDeg; }
float pid_getCurrentElevationDeg() { return elevState.currentAngleDeg; }
float pid_getTargetAzimuthDeg()    { return azState.targetAngleDeg; }
float pid_getTargetElevationDeg()  { return elevState.targetAngleDeg; }


bool pid_isAtTarget(float toleranceDeg) {
    if (controlMode == PID_MODE_VELOCITY) {
        // Hiz modunda "kilitli" = taret duruyor demektir.
        return (fabs(azState.velocityActualDegS)   < VELOCITY_STOPPED_DEG_S) &&
               (fabs(elevState.velocityActualDegS) < VELOCITY_STOPPED_DEG_S);
    }
    bool azOk   = fabs(azState.targetAngleDeg - azState.currentAngleDeg) <= toleranceDeg;
    bool elevOk = fabs(elevState.targetAngleDeg - elevState.currentAngleDeg) <= toleranceDeg;
    return azOk && elevOk;
}

bool pid_wasAzimuthClamped()   { return azClampedFlag; }
bool pid_wasElevationClamped() { return elevClampedFlag; }


float pid_getCommandedStepFreqHz(AxisId axis) {
    return (axis == AXIS_AZIMUTH) ? azState.commandedStepFreqHz : elevState.commandedStepFreqHz;
}

float pid_getVelocityDegS(AxisId axis) {
    return (axis == AXIS_AZIMUTH) ? azState.velocityActualDegS : elevState.velocityActualDegS;
}


void pid_emergencyStop() {
    estopped = true;
    ledcWrite(AZ_STEP_PIN, 0);
    ledcWrite(ELEV_STEP_PIN, 0);

    digitalWrite(AZ_EN_PIN, HIGH);
    azState.commandedStepFreqHz = 0.0f;
    azState.velocityCmdDegS     = 0.0f;
    azState.velocityActualDegS  = 0.0f;

    digitalWrite(ELEV_EN_PIN, HIGH);
    elevState.commandedStepFreqHz = 0.0f;
    elevState.velocityCmdDegS     = 0.0f;
    elevState.velocityActualDegS  = 0.0f;
}

bool pid_isEmergencyStopped() {
    return estopped;
}

void pid_resumeAfterEstop() {
    digitalWrite(AZ_EN_PIN, LOW);
    digitalWrite(ELEV_EN_PIN, LOW);

    azState.integral = 0.0f;
    azState.previousError = 0.0f;
    azState.lastUpdateMicros = micros();
    azState.velocityCmdDegS = 0.0f;
    azState.velocityActualDegS = 0.0f;

    elevState.integral = 0.0f;
    elevState.previousError = 0.0f;
    elevState.lastUpdateMicros = micros();
    elevState.velocityCmdDegS = 0.0f;
    elevState.velocityActualDegS = 0.0f;

    // Kapali cevrimde eski hedefe kosmasin: hedefi mevcut konuma esitle.
    if (controlMode == PID_MODE_POSITION) {
        azState.targetAngleDeg   = encoder_getAzimuthDeg();
        elevState.targetAngleDeg = encoder_getElevationDeg();
    }

    estopped = false;
}


void pid_setGains(AxisId axis, float kp, float ki, float kd) {
    AxisGains newGains = { kp, ki, kd };
    if (axis == AXIS_AZIMUTH) {
        azGains = newGains;
    } else {
        elevGains = newGains;
    }
}

void pid_setVelocityLimitDegS(float limitDegS) {
    if (limitDegS <= 0.0f) return;   // gecersiz deger - guvenlik icin yok say
    currentVelocityLimitDegS = limitDegS;
}

void pid_resetVelocityLimitDegS() {
    currentVelocityLimitDegS = VELOCITY_OUTPUT_LIMIT_DEG_S;
}