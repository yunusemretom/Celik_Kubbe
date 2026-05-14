/**
 * Ayarlar sayfası — Kamera kaynağı + bağlantı ayarları
 */
class SettingsPage {
  constructor() {
    this._bindCameraSource();
    this._bindSave();
    this._bindApplyCamera();
    this._bindEvents();
  }

  // ── Camera Source ─────────────────────────────────────────
  _bindCameraSource() {
    document.getElementById('cfg-camera-source').addEventListener('change', (e) => {
      this._updateCameraUI(e.target.value);
    });

    document.getElementById('btn-enumerate-devices').addEventListener('click', () => {
      this._enumerateDevices();
    });

    // Live URL parse for RTSP
    document.getElementById('cfg-rtsp-url-cam').addEventListener('input', (e) => {
      this._parseRtspUrl(e.target.value);
    });
  }

  _updateCameraUI(source) {
    document.getElementById('camera-webcam-section').style.display = source === 'webcam' ? '' : 'none';
    document.getElementById('camera-rtsp-section').classList.toggle('hidden', source !== 'rtsp');
    document.getElementById('camera-mjpeg-section').classList.toggle('hidden', source !== 'mjpeg');
  }

  async _enumerateDevices() {
    try {
      // İzin iste
      await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      const devices = await navigator.mediaDevices.enumerateDevices();
      const cameras = devices.filter((d) => d.kind === 'videoinput');

      const sel = document.getElementById('cfg-webcam-device');
      sel.innerHTML = '<option value="">Varsayılan Kamera</option>' +
        cameras.map((c, i) =>
          `<option value="${c.deviceId}">${c.label || 'Kamera ' + (i + 1)}</option>`
        ).join('');

      window.showToast(`${cameras.length} kamera bulundu`, 'success');
    } catch (e) {
      window.showToast('Kamera izni reddedildi veya kamera bulunamadı', 'error');
    }
  }

  _parseRtspUrl(url) {
    const box = document.getElementById('rtsp-parse-box');
    if (!url) { box.innerHTML = ''; return; }
    try {
      const u = new URL(url);
      box.innerHTML = `
        <div class="url-info-row"><span class="url-info-key">Protokol</span><span class="url-info-val">${u.protocol}</span></div>
        <div class="url-info-row"><span class="url-info-key">IP Adresi</span><span class="url-info-val">${u.hostname}</span></div>
        <div class="url-info-row"><span class="url-info-key">Port</span><span class="url-info-val">${u.port || '554 (varsayılan)'}</span></div>
        <div class="url-info-row"><span class="url-info-key">Yol</span><span class="url-info-val">${u.pathname}</span></div>
      `;
    } catch (_) {
      box.innerHTML = '<div class="url-info-row"><span class="url-info-key" style="color:var(--danger)">Geçersiz URL</span></div>';
    }
  }

  _bindApplyCamera() {
    document.getElementById('btn-apply-camera').addEventListener('click', () => {
      const source = document.getElementById('cfg-camera-source').value;
      const opts = {};

      if (source === 'webcam') {
        opts.deviceId = document.getElementById('cfg-webcam-device').value;
      } else if (source === 'rtsp') {
        opts.rtspUrl = document.getElementById('cfg-rtsp-url-cam').value;
        if (!opts.rtspUrl) { window.showToast('RTSP URL giriniz', 'warning'); return; }
        // Update backend config too
        ykiWS.send({ type: 'settings_update', settings: { video: { rtspUrl: opts.rtspUrl } } });
      } else if (source === 'mjpeg') {
        opts.mjpegUrl = document.getElementById('cfg-mjpeg-url').value;
        if (!opts.mjpegUrl) { window.showToast('MJPEG URL giriniz', 'warning'); return; }
      }

      // Apply to dashboard
      if (window.dashboard) {
        window.dashboard.stopCamera();
        window.dashboard.currentSource = source;
        if (source === 'webcam') window.dashboard.currentDeviceId = opts.deviceId;
        if (source === 'mjpeg') window.dashboard._mjpegUrl = opts.mjpegUrl;
        if (source === 'rtsp' && opts.rtspUrl) {
          // Update backend RTSP URL first then start
          setTimeout(() => window.dashboard.startCamera(), 800);
        } else {
          window.dashboard.startCamera();
        }
        window.showToast('Kamera kaynağı değiştirildi: ' + source.toUpperCase(), 'success');
      }
    });
  }

  // ── Connection Settings ───────────────────────────────────
  _bindSave() {
    document.getElementById('btn-save-settings').addEventListener('click', () => this.save());
  }

  _bindEvents() {
    ykiWS.on('init', (msg) => this.populate(msg.config));
    ykiWS.on('config_updated', (msg) => this.populate(msg.config));

    ykiWS.on('settings_saved', (msg) => {
      if (msg.success) window.showToast('Ayarlar kaydedildi ✓', 'success');
      else window.showToast('Ayarlar kaydedilemedi!', 'error');
    });

    ykiWS.on('telemetry_status', (msg) => {
      const badge = document.getElementById('badge-telemetry');
      badge.textContent = msg.connected ? `Bağlı (${msg.ip || ''})` : 'Bağlı Değil';
      badge.className = 'conn-badge ' + (msg.connected ? 'connected' : 'disconnected');
    });

    ykiWS.on('command_status', (msg) => {
      const badge = document.getElementById('badge-command');
      badge.textContent = msg.connected ? 'Bağlı' : 'Bağlı Değil';
      badge.className = 'conn-badge ' + (msg.connected ? 'connected' : 'disconnected');
    });
  }

  populate(cfg) {
    if (!cfg) return;
    if (cfg.rpi) {
      this._val('cfg-rpi-ip', cfg.rpi.ip);
      this._val('cfg-tcp-port', cfg.rpi.tcpPort);
      this._val('cfg-udp-port', cfg.rpi.udpPort);
    }
    if (cfg.video) {
      this._val('cfg-rtsp-url', cfg.video.rtspUrl);
      this._val('cfg-rtsp-url-cam', cfg.video.rtspUrl);
      this._val('cfg-resolution', cfg.video.resolution);
      this._val('cfg-fps', cfg.video.fps);
      this._val('cfg-bitrate', cfg.video.bitrate);
    }
    if (cfg.vehicle) {
      this._val('cfg-vehicle-name', cfg.vehicle.name);
      this._val('cfg-team-name', cfg.vehicle.teamName);
    }
    if (cfg.server) {
      document.getElementById('srv-http-port').textContent = cfg.server.httpPort || 3000;
      document.getElementById('srv-video-port').textContent = cfg.server.videoWsPort || 8081;
    }
  }

  _val(id, val) {
    const el = document.getElementById(id);
    if (el && val !== undefined && val !== null) el.value = val;
  }

  _read(id) {
    const el = document.getElementById(id);
    return el ? el.value : null;
  }

  save() {
    const settings = {
      rpi: {
        ip: this._read('cfg-rpi-ip'),
        tcpPort: parseInt(this._read('cfg-tcp-port')) || 5000,
        udpPort: parseInt(this._read('cfg-udp-port')) || 5001,
      },
      video: {
        rtspUrl: this._read('cfg-rtsp-url'),
        resolution: this._read('cfg-resolution'),
        fps: parseInt(this._read('cfg-fps')) || 30,
        bitrate: parseInt(this._read('cfg-bitrate')) || 800,
      },
      vehicle: {
        name: this._read('cfg-vehicle-name'),
        teamName: this._read('cfg-team-name'),
      },
    };
    ykiWS.send({ type: 'settings_update', settings });
  }
}

window.settingsPage = null;
