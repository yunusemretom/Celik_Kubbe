const net = require('net');
const EventEmitter = require('events');

class CommandBridge extends EventEmitter {
  constructor(config) {
    super();
    this.config = config;
    this.client = null;
    this.connected = false;
    this.reconnectTimer = null;
    this.commandQueue = [];
    this.buffer = '';
  }

  connect() {
    const { ip, tcpPort } = this.config.get('rpi');
    console.log(`[Command] ${ip}:${tcpPort} adresine bağlanılıyor...`);

    if (this.client) {
      this.client.destroy();
      this.client = null;
    }

    this.client = new net.Socket();
    this.client.setTimeout(10000);

    this.client.connect(tcpPort, ip, () => {
      console.log(`[Command] RPi5'e bağlandı: ${ip}:${tcpPort}`);
      this.connected = true;
      if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
      this.emit('connected');

      // Kuyrukta bekleyen komutları gönder
      while (this.commandQueue.length > 0) {
        this._send(this.commandQueue.shift());
      }
    });

    this.client.on('data', (data) => {
      this.buffer += data.toString();
      const lines = this.buffer.split('\n');
      this.buffer = lines.pop(); // Son tamamlanmamış satırı sakla
      lines.forEach((line) => {
        if (!line.trim()) return;
        try {
          const response = JSON.parse(line);
          this.emit('response', response);
        } catch (e) {
          console.error('[Command] Parse hatası:', e.message);
        }
      });
    });

    this.client.on('timeout', () => {
      console.warn('[Command] Bağlantı zaman aşımı');
      this.client.destroy();
    });

    this.client.on('close', () => {
      console.log('[Command] Bağlantı kapandı');
      this.connected = false;
      this.client = null;
      this.emit('disconnected');
      this._scheduleReconnect();
    });

    this.client.on('error', (err) => {
      console.error('[Command] Hata:', err.message);
      this.emit('error', err.message);
    });
  }

  _scheduleReconnect() {
    if (this.reconnectTimer) return;
    console.log('[Command] 5 saniye sonra yeniden bağlanılacak...');
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, 5000);
  }

  _send(data) {
    if (!this.client || !this.connected) return false;
    try {
      this.client.write(JSON.stringify(data) + '\n');
      return true;
    } catch (e) {
      console.error('[Command] Gönderme hatası:', e.message);
      return false;
    }
  }

  sendCommand(cmd, params = {}) {
    const command = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      cmd,
      params,
      timestamp: Date.now(),
    };

    if (!this.connected) {
      console.log('[Command] Bağlı değil, komut kuyruğa alındı:', cmd);
      this.commandQueue.push(command);
      return { queued: true, id: command.id };
    }

    const sent = this._send(command);
    return { sent, id: command.id };
  }

  disconnect() {
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
    if (this.client) { this.client.destroy(); this.client = null; }
    this.connected = false;
  }

  getStatus() {
    return {
      connected: this.connected,
      queuedCommands: this.commandQueue.length,
    };
  }
}

module.exports = CommandBridge;
