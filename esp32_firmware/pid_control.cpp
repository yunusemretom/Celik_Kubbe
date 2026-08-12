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

    estopped = false;
}


void pid_setTargetAngles(float azimuthDeg, float elevationDeg) {
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


void pid_update() {
    if (estopped) {
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
    bool azOk   = fabs(azState.targetAngleDeg - azState.currentAngleDeg) <= toleranceDeg;
    bool elevOk = fabs(elevState.targetAngleDeg - elevState.currentAngleDeg) <= toleranceDeg;
    return azOk && elevOk;
}

bool pid_wasAzimuthClamped()   { return azClampedFlag; }
bool pid_wasElevationClamped() { return elevClampedFlag; }


float pid_getCommandedStepFreqHz(AxisId axis) {
    return (axis == AXIS_AZIMUTH) ? azState.commandedStepFreqHz : elevState.commandedStepFreqHz;
}


void pid_emergencyStop() {
    estopped = true;
    ledcWrite(AZ_STEP_PIN, 0);
    ledcWrite(ELEV_STEP_PIN, 0);
    digitalWrite(AZ_EN_PIN, HIGH);
    azState.commandedStepFreqHz = 0.0f;
    digitalWrite(ELEV_EN_PIN, HIGH);
    elevState.commandedStepFreqHz = 0.0f;
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

    elevState.integral = 0.0f;
    elevState.previousError = 0.0f;
    elevState.lastUpdateMicros = micros();

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