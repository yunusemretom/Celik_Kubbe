// Tarayicidaki sanal joystick'ten WS ile gelen komutu, ESP32'ye DOGRUDAN
// UDP ile iletir.
//
// DEGISIKLIK: paket artik 4 alanli -> "pitch,yaw,fire,arm\n"
// ESP32 tarafinda joystick.cpp bu bicimi bekliyor. 3 alanli eski bicimi de
// kabul ediyor ama o durumda arm=0 varsayip ATES ETMIYOR.

const dgram = require('dgram');
const config = require('./config');

const sock = dgram.createSocket('udp4');

// Karti/agi bogmamak icin gonderimi sinirla (Hz).
const MAX_SEND_HZ = 50;
const MIN_INTERVAL_MS = 1000 / MAX_SEND_HZ;

let sonGonderimMs = 0;
let sonPaket = null;

sock.on('error', (err) => {
  console.error('[joystickBridge] UDP soket hatasi:', err.message);
});

/**
 * @param {{pitch:number, yaw:number, fire?:number, arm?:number}} data
 */
function sendJoystick(data) {
  const paket = {
    pitch: clamp(Number(data.pitch) || 0, -1, 1),
    yaw: clamp(Number(data.yaw) || 0, -1, 1),
    fire: clamp(Number(data.fire) || 0, 0, 1),
    arm: clamp(Number(data.arm) || 0, 0, 1),
  };

  const simdi = Date.now();
  if (simdi - sonGonderimMs < MIN_INTERVAL_MS) {
    sonPaket = paket;   // en son degeri kaybetmemek icin sakla
    return;
  }
  gercektenGonder(paket);
}

function gercektenGonder(paket) {
  const { host, udpPort } = config.get('esp32');
  const satir =
    `${paket.pitch.toFixed(3)},${paket.yaw.toFixed(3)},` +
    `${paket.fire.toFixed(0)},${paket.arm.toFixed(0)}\n`;

  sock.send(Buffer.from(satir), udpPort, host, (err) => {
    if (err) console.error('[joystickBridge] gonderim hatasi:', err.message);
  });
  sonGonderimMs = Date.now();
  sonPaket = null;
}

// Throttle yuzunden bekleyen son paketi gonder.
setInterval(() => {
  if (sonPaket) gercektenGonder(sonPaket);
}, MIN_INTERVAL_MS);

// Tarayici baglantisi koptugunda / kapanista cagirilir.
// ARM ve FIRE'i da sifirlar - ESP32'nin watchdog'una birakma.
function sendStop() {
  sonPaket = null;
  gercektenGonder({ pitch: 0, yaw: 0, fire: 0, arm: 0 });
}

function clamp(v, min, max) {
  return Math.max(min, Math.min(max, v));
}

module.exports = { sendJoystick, sendStop };