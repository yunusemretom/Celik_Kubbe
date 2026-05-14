const fs = require('fs');
const path = require('path');

const CONFIG_FILE = path.join(__dirname, 'yki_config.json');

const DEFAULT_CONFIG = {
  rpi: {
    ip: '192.168.1.100',
    tcpPort: 5000,
    udpPort: 5001,
  },
  video: {
    rtspUrl: 'rtsp://192.168.1.100:8554/camera',
    protocol: 'rtsp',
    bitrate: 800,
    fps: 30,
    resolution: '1280x720',
  },
  server: {
    httpPort: 3000,
    wsPort: 3000,
    videoWsPort: 8081,
  },
  vehicle: {
    name: 'Çelik Kubbe',
    teamName: 'Pars Takımı',
    systemId: 1,
  },
};

class Config {
  constructor() {
    this.data = this.load();
  }

  load() {
    try {
      if (fs.existsSync(CONFIG_FILE)) {
        const raw = fs.readFileSync(CONFIG_FILE, 'utf8');
        const saved = JSON.parse(raw);
        // Deep merge
        return {
          ...DEFAULT_CONFIG,
          ...saved,
          rpi: { ...DEFAULT_CONFIG.rpi, ...(saved.rpi || {}) },
          video: { ...DEFAULT_CONFIG.video, ...(saved.video || {}) },
          server: { ...DEFAULT_CONFIG.server, ...(saved.server || {}) },
          vehicle: { ...DEFAULT_CONFIG.vehicle, ...(saved.vehicle || {}) },
        };
      }
    } catch (e) {
      console.error('[Config] Load error:', e.message);
    }
    return JSON.parse(JSON.stringify(DEFAULT_CONFIG));
  }

  save() {
    try {
      fs.writeFileSync(CONFIG_FILE, JSON.stringify(this.data, null, 2));
      return true;
    } catch (e) {
      console.error('[Config] Save error:', e.message);
      return false;
    }
  }

  get(key) {
    return key ? this.data[key] : this.data;
  }

  set(section, values) {
    this.data[section] = { ...this.data[section], ...values };
    return this.save();
  }

  update(newConfig) {
    Object.keys(newConfig).forEach((section) => {
      if (this.data[section]) {
        this.data[section] = { ...this.data[section], ...newConfig[section] };
      } else {
        this.data[section] = newConfig[section];
      }
    });
    return this.save();
  }
}

module.exports = new Config();
