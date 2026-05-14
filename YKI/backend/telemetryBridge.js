const dgram = require('dgram');
const EventEmitter = require('events');

class TelemetryBridge extends EventEmitter {
  constructor(config) {
    super();
    this.config = config;
    this.socket = null;
    this.lastTelemetry = null;
    this.connected = false;
    this.packetCount = 0;
    this.lostPackets = 0;
    this.lastSeq = -1;
    this.timeoutTimer = null;
  }

  start() {
    const { udpPort } = this.config.get('rpi');
    this.socket = dgram.createSocket('udp4');

    this.socket.on('message', (msg, rinfo) => {
      try {
        const data = JSON.parse(msg.toString());
        this.packetCount++;

        // Paket kayıp tespiti
        if (data.seq !== undefined && this.lastSeq !== -1) {
          const diff = data.seq - this.lastSeq - 1;
          if (diff > 0) this.lostPackets += diff;
        }
        if (data.seq !== undefined) this.lastSeq = data.seq;

        this.lastTelemetry = {
          ...data,
          _meta: {
            receivedAt: Date.now(),
            fromIp: rinfo.address,
            packetCount: this.packetCount,
            lostPackets: this.lostPackets,
          },
        };

        if (!this.connected) {
          this.connected = true;
          this.emit('connected', rinfo.address);
          console.log(`[Telemetry] Bağlantı: ${rinfo.address}`);
        }

        this.emit('data', this.lastTelemetry);
      } catch (e) {
        console.error('[Telemetry] Parse hatası:', e.message);
      }
    });

    this.socket.on('error', (err) => {
      console.error('[Telemetry] Socket hatası:', err.message);
      this.emit('error', err.message);
    });

    this.socket.bind(udpPort, '0.0.0.0', () => {
      console.log(`[Telemetry] UDP port ${udpPort} dinleniyor`);
    });

    // 3 saniye veri gelmezse bağlantı koptu say
    this.timeoutTimer = setInterval(() => {
      if (this.lastTelemetry && this.connected) {
        const age = Date.now() - this.lastTelemetry._meta.receivedAt;
        if (age > 3000) {
          this.connected = false;
          this.emit('disconnected');
          console.log('[Telemetry] Bağlantı zaman aşımı');
        }
      }
    }, 1000);
  }

  restart() {
    this.stop();
    setTimeout(() => this.start(), 500);
  }

  stop() {
    if (this.timeoutTimer) { clearInterval(this.timeoutTimer); this.timeoutTimer = null; }
    if (this.socket) { this.socket.close(); this.socket = null; }
    this.connected = false;
    this.lastTelemetry = null;
  }

  getStatus() {
    return {
      connected: this.connected,
      lastData: this.lastTelemetry,
      packetCount: this.packetCount,
      lostPackets: this.lostPackets,
    };
  }
}

module.exports = TelemetryBridge;
