/**
 * Dashboard — Kamera görüntüsü (Webcam/RTSP/MJPEG) + Uçuş Enstrümanları
 */

// ═══════════════════════════════════════════════════════════════
// AttitudeIndicator — Yapay Ufuk Canvas Çizici
// ═══════════════════════════════════════════════════════════════
class AttitudeIndicator {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas.getContext('2d');
    this.roll = 0;
    this.pitch = 0;
    this.draw();
  }

  update(roll, pitch) {
    this.roll = roll || 0;
    this.pitch = pitch || 0;
    this.draw();
  }

  draw() {
    const c = this.canvas;
    const ctx = this.ctx;
    const w = c.width, h = c.height;
    const cx = w / 2, cy = h / 2;
    const r = cx - 3;
    const rollRad = (this.roll * Math.PI) / 180;
    const pitchPx = (this.pitch / 90) * r;

    ctx.clearRect(0, 0, w, h);

    // ── Clip to circle ──
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.clip();

    // ── Sky + Ground (rotated for roll, shifted for pitch) ──
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(rollRad);

    // Sky
    ctx.fillStyle = '#1565C0';
    ctx.fillRect(-w, -h * 2 - pitchPx, w * 2, h * 2);
    // Ground
    ctx.fillStyle = '#6D4C41';
    ctx.fillRect(-w, -pitchPx, w * 2, h * 2);

    // Horizon line
    ctx.strokeStyle = 'rgba(255,255,255,0.9)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(-w, -pitchPx);
    ctx.lineTo(w, -pitchPx);
    ctx.stroke();

    // Pitch ladder lines
    for (let deg = -30; deg <= 30; deg += 10) {
      if (deg === 0) continue;
      const y = -pitchPx - (deg / 90) * r;
      const lw = Math.abs(deg) % 20 === 0 ? r * 0.45 : r * 0.28;
      ctx.strokeStyle = 'rgba(255,255,255,0.85)';
      ctx.lineWidth = deg % 20 === 0 ? 1.5 : 1;
      ctx.beginPath();
      ctx.moveTo(-lw / 2, y);
      ctx.lineTo(lw / 2, y);
      ctx.stroke();
      // Pitch label
      ctx.fillStyle = 'rgba(255,255,255,0.8)';
      ctx.font = `bold 9px "Share Tech Mono", monospace`;
      ctx.textAlign = 'left';
      ctx.fillText(`${Math.abs(deg)}`, lw / 2 + 4, y + 3.5);
      ctx.textAlign = 'right';
      ctx.fillText(`${Math.abs(deg)}`, -lw / 2 - 4, y + 3.5);
    }

    ctx.restore();

    // ── Roll arc & tick marks (fixed, not pitched) ──
    ctx.save();
    ctx.translate(cx, cy);
    ctx.strokeStyle = 'rgba(255,255,255,0.7)';
    ctx.lineWidth = 1;

    [10, 20, 30, 45, 60].forEach((a) => {
      [-a, a].forEach((angle) => {
        const rad = ((angle - 90) * Math.PI) / 180;
        const inner = r - (Math.abs(angle) % 30 === 0 ? 10 : 6);
        ctx.beginPath();
        ctx.moveTo(Math.cos(rad) * inner, Math.sin(rad) * inner);
        ctx.lineTo(Math.cos(rad) * r, Math.sin(rad) * r);
        ctx.stroke();
      });
    });

    // Roll triangle indicator (rotates with roll)
    ctx.save();
    ctx.rotate(rollRad);
    ctx.fillStyle = '#fff';
    ctx.beginPath();
    ctx.moveTo(0, -(r - 2));
    ctx.lineTo(-5, -(r - 12));
    ctx.lineTo(5, -(r - 12));
    ctx.closePath();
    ctx.fill();
    ctx.restore();

    ctx.restore();

    // ── Fixed aircraft symbol ──
    ctx.save();
    ctx.translate(cx, cy);
    ctx.strokeStyle = '#FFD600';
    ctx.lineWidth = 2.5;
    ctx.lineCap = 'round';
    // Left wing
    ctx.beginPath(); ctx.moveTo(-r * 0.48, 0); ctx.lineTo(-10, 0); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(-10, 0); ctx.lineTo(-10, 5); ctx.stroke();
    // Right wing
    ctx.beginPath(); ctx.moveTo(r * 0.48, 0); ctx.lineTo(10, 0); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(10, 0); ctx.lineTo(10, 5); ctx.stroke();
    // Center dot
    ctx.fillStyle = '#FFD600';
    ctx.beginPath(); ctx.arc(0, 0, 3, 0, Math.PI * 2); ctx.fill();
    ctx.restore();

    // ── Slip indicator (ball) at bottom ──
    ctx.save();
    ctx.translate(cx, cy);
    ctx.strokeStyle = 'rgba(255,255,255,0.4)';
    ctx.lineWidth = 1;
    const ballY = r - 14;
    const ballR = 5;
    const slipX = -Math.sin(rollRad) * 8;
    ctx.fillStyle = '#1a1c1e';
    ctx.beginPath(); ctx.arc(0, ballY, 14, 0, Math.PI * 2); ctx.fill();
    ctx.stroke();
    ctx.fillStyle = '#fff';
    ctx.beginPath(); ctx.arc(slipX, ballY, ballR, 0, Math.PI * 2); ctx.fill();
    ctx.restore();

    ctx.restore(); // clip

    // ── Outer ring ──
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.strokeStyle = '#3c4249';
    ctx.lineWidth = 3;
    ctx.stroke();
  }
}

// ═══════════════════════════════════════════════════════════════
// CompassIndicator — Pusula Canvas Çizici
// ═══════════════════════════════════════════════════════════════
class CompassIndicator {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas.getContext('2d');
    this.heading = 0;
    this.draw();
  }

  update(heading) {
    this.heading = ((heading || 0) + 360) % 360;
    this.draw();
  }

  draw() {
    const c = this.canvas;
    const ctx = this.ctx;
    const w = c.width, h = c.height;
    const cx = w / 2, cy = h / 2;
    const r = cx - 3;

    ctx.clearRect(0, 0, w, h);

    // Background
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = '#0d1117';
    ctx.fill();
    ctx.clip();

    // Rose rotate
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate((-this.heading * Math.PI) / 180);

    // Major ticks every 10°, labels every 30°
    const cardinals = { 0: 'N', 90: 'E', 180: 'S', 270: 'W', 45: 'NE', 135: 'SE', 225: 'SW', 315: 'NW' };

    for (let deg = 0; deg < 360; deg += 10) {
      const rad = (deg * Math.PI) / 180 - Math.PI / 2;
      const isMajor = deg % 30 === 0;
      const tickLen = isMajor ? 12 : 6;
      const innerR = r - tickLen;

      ctx.strokeStyle = isMajor ? 'rgba(255,255,255,0.8)' : 'rgba(255,255,255,0.3)';
      ctx.lineWidth = isMajor ? 1.5 : 1;
      ctx.beginPath();
      ctx.moveTo(Math.cos(rad) * innerR, Math.sin(rad) * innerR);
      ctx.lineTo(Math.cos(rad) * r, Math.sin(rad) * r);
      ctx.stroke();

      if (cardinals[deg] !== undefined) {
        const labelR = r - 20;
        ctx.fillStyle = deg === 0 ? '#f44336' : 'rgba(255,255,255,0.85)';
        ctx.font = `bold ${deg % 90 === 0 ? 12 : 9}px "Share Tech Mono", monospace`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(cardinals[deg], Math.cos(rad) * labelR, Math.sin(rad) * labelR);
      }
    }

    ctx.restore();

    // Fixed triangle pointer (top = current heading)
    ctx.save();
    ctx.translate(cx, cy);
    ctx.fillStyle = '#f44336';
    ctx.beginPath();
    ctx.moveTo(0, -(r - 2));
    ctx.lineTo(-5, -(r - 14));
    ctx.lineTo(5, -(r - 14));
    ctx.closePath();
    ctx.fill();

    // Center circle
    ctx.fillStyle = '#1e2328';
    ctx.beginPath(); ctx.arc(0, 0, 22, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = '#3c4249';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Heading text
    ctx.fillStyle = '#00c8ff';
    ctx.font = `bold 13px "Share Tech Mono", monospace`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(String(Math.round(this.heading)).padStart(3, '0') + '°', 0, 0);

    ctx.restore();
    ctx.restore(); // clip

    // Outer ring
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.strokeStyle = '#3c4249';
    ctx.lineWidth = 3;
    ctx.stroke();
  }
}

// ═══════════════════════════════════════════════════════════════
// Dashboard — Ana Sınıf
// ═══════════════════════════════════════════════════════════════
class Dashboard {
  constructor() {
    this.canvas = document.getElementById('video-canvas');
    this.webcamVideo = document.getElementById('webcam-video');
    this.player = null;
    this.webcamStream = null;
    this.currentSource = 'webcam'; // webcam | device | rtsp | mjpeg
    this.currentDeviceId = '';     // tarayıcı webcam'i (getUserMedia deviceId)
    this.videoDevice = '/dev/video0'; // sunucu tarafı V4L2 cihazı
    this.videoWsPort = 8081;
    this.streaming = false;
    this._mjpegUrl = '';
    this._rtspUrl = '';
    this._mjpegErrors = 0;

    // Instruments
    this.ai = new AttitudeIndicator('ai-canvas');
    this.compass = new CompassIndicator('compass-canvas');
    this._instrumentsVisible = false;
    this._animFrame = null;

    this._bindUI();
    this._bindEvents();
    this._setupModePanel();
  }

  _bindUI() {
    document.getElementById('btn-start-stream').addEventListener('click', () => this.startCamera());
    document.getElementById('btn-toggle-stream').addEventListener('click', () => this.stopCamera());

    document.getElementById('btn-instruments').addEventListener('click', () => this.toggleInstruments());
    document.getElementById('btn-close-instruments').addEventListener('click', () => this.toggleInstruments(false));

    document.getElementById('btn-fullscreen').addEventListener('click', () => {
      const el = document.getElementById('page-dashboard');
      if (!document.fullscreenElement) el.requestFullscreen().catch(() => {});
      else document.exitFullscreen();
    });
  }

  _setupModePanel() {
  const modeSelect = document.getElementById('cfg-op-mode');
  if (!modeSelect) return;

  const modeCard = modeSelect.closest('.settings-card');
  if (!modeCard) return;

  modeCard.id = 'mode-panel';
  modeCard.classList.add('instrument-panel', 'hidden');

  const oldTitle = modeCard.querySelector('.settings-card-title');
  if (oldTitle) oldTitle.remove();

  const header = document.createElement('div');
  header.className = 'inst-panel-header';
  header.innerHTML = `<span>OPERASYON MODU</span><button id="btn-close-mode-panel">✕</button>`;
  modeCard.insertBefore(header, modeCard.firstChild);

  const sidePanelStack = document.getElementById('side-panel-stack')
    || document.querySelector('.camera-container');
  sidePanelStack.appendChild(modeCard);

  const controls = document.querySelector('.camera-controls');
  const modeBtn = document.createElement('button');
  modeBtn.id = 'btn-mode-panel';
  modeBtn.className = 'cam-btn';
  modeBtn.innerHTML = `<svg viewBox="0 0 20 20" width="14"><circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="2" fill="none"/><path d="M10 5v5l3 3" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg> Mod`;
  controls.appendChild(modeBtn);

  modeBtn.addEventListener('click', () => modeCard.classList.toggle('hidden'));
  header.querySelector('#btn-close-mode-panel')
    .addEventListener('click', () => modeCard.classList.add('hidden'));
}

  _bindEvents() {
    ykiWS.on('init', (msg) => {
      if (msg.config?.server?.videoWsPort) this.videoWsPort = msg.config.server.videoWsPort;
      this.applyConfig(msg.config);
    });

    ykiWS.on('config_updated', (msg) => this.applyConfig(msg.config));

    ykiWS.on('video_status', (msg) => {
      if (msg.streaming) this._onStreamStarted(msg.source || this.currentSource);
      else if (this._usesBackend()) this._onStreamStopped();
    });

    ykiWS.on('video_error', (msg) => {
      window.showToast('Video hatası: ' + msg.error, 'error');
      this._onStreamStopped();
    });

    // Yayın sürüyor ama sunucu kaynağı değiştirmek zorunda kaldı (kayıtlı
    // kamera bulunamadı vb.). Yayını durdurmaz, yalnızca haber verir.
    ykiWS.on('video_warning', (msg) => {
      window.showToast('Kamera: ' + msg.warning, 'warning');
    });

    ykiWS.on('telemetry', (msg) => {
      this._updateOverlay(msg.data);
      this._updateInstruments(msg.data);
    });

    ykiWS.on('latency', (msg) => {
      document.getElementById('info-latency').textContent = `${msg.ms} ms`;
    });
  }

  // ── Camera Control ─────────────────────────────────────────
  /** Sunucudan gelen ayarları uygular; sayfa açılışında kaynak buradan gelir. */
  applyConfig(cfg) {
    const v = cfg?.video;
    if (!v) return;
    if (v.source) this.currentSource = v.source;
    if (v.mjpegUrl) this._mjpegUrl = v.mjpegUrl;
    if (v.rtspUrl) this._rtspUrl = v.rtspUrl;
    if (v.device) this.videoDevice = v.device;
  }

  /** Kaynak sunucu tarafında FFmpeg ile mi açılıyor? */
  _usesBackend() {
    return this.currentSource === 'rtsp' || this.currentSource === 'device';
  }

  setCameraSource(source, opts = {}) {
    this.currentSource = source;
    if (opts.deviceId !== undefined) this.currentDeviceId = opts.deviceId;
    if (opts.device !== undefined) this.videoDevice = opts.device;
    if (opts.mjpegUrl !== undefined) this._mjpegUrl = opts.mjpegUrl;
    if (opts.rtspUrl !== undefined) this._rtspUrl = opts.rtspUrl;
  }

  async startCamera() {
    this.stopCamera();
    switch (this.currentSource) {
      case 'webcam':  await this._startWebcam(); break;
      case 'device':  this._startBackendStream('device'); break;
      case 'rtsp':    this._startBackendStream('rtsp'); break;
      case 'mjpeg':   this._startMJPEG(this._mjpegUrl); break;
      default:
        window.showToast('Bilinmeyen kamera kaynağı: ' + this.currentSource, 'error');
    }
  }

  stopCamera() {
    // Sunucudaki FFmpeg de dursun, aksi halde kaynak meşgul kalıyor
    if (this._usesBackend() && this.streaming) ykiWS.send({ type: 'video_stop' });
    // Webcam
    if (this.webcamStream) {
      this.webcamStream.getTracks().forEach((t) => t.stop());
      this.webcamStream = null;
    }
    this.webcamVideo.srcObject = null;
    // JSMpeg
    if (this.player) { this.player.destroy(); this.player = null; }
    // MJPEG img
    if (this._mjpegImg) { this._mjpegImg.src = ''; this._mjpegImg = null; }
    this.canvas.getContext('2d').clearRect(0, 0, this.canvas.width, this.canvas.height);
    this._onStreamStopped();
  }

  async _startWebcam() {
    if (!navigator.mediaDevices?.getUserMedia) {
      // Tarayıcı getUserMedia'yı yalnızca güvenli kaynakta verir: localhost ya
      // da https. YKI'ye ağ üzerinden IP ile girildiğinde web kamera açılmaz.
      window.showToast(
        'Web kamera yalnızca localhost veya HTTPS üzerinden açılabilir. '
        + 'Ağ üzerinden bağlıysanız V4L2 / MJPEG kaynağını kullanın.', 'error');
      return;
    }
    try {
      const constraints = {
        video: this.currentDeviceId ? { deviceId: { exact: this.currentDeviceId } } : true,
        audio: false,
      };
      this.webcamStream = await navigator.mediaDevices.getUserMedia(constraints);
      this.webcamVideo.srcObject = this.webcamStream;
      this.webcamVideo.classList.remove('hidden');
      this.canvas.classList.add('hidden');
      this._onStreamStarted('webcam');
      window.showToast('Web kamera başlatıldı', 'success');
    } catch (e) {
      window.showToast('Kamera erişimi reddedildi: ' + e.message, 'error');
    }
  }

  /** RTSP ve V4L2: kaynağı sunucudaki FFmpeg açar, kareler WS ile gelir. */
  _startBackendStream(source) {
    ykiWS.send({
      type: 'video_start',
      source,
      url: this._rtspUrl,
      device: this.videoDevice,
    });
    this.webcamVideo.classList.add('hidden');
    this.canvas.classList.remove('hidden');

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.hostname}:${this.videoWsPort}`;

    this.player = new JSMpeg.Player(wsUrl, {
      canvas: this.canvas,
      autoplay: true,
      audio: false,
    });
    const what = source === 'device' ? this.videoDevice : this._rtspUrl;
    window.showToast(`Yayın başlatılıyor: ${what}`, 'info');
  }

  _startMJPEG(url, opts = {}) {
    if (!url) { window.showToast('MJPEG URL giriniz', 'error'); return; }

    // Adresi düzelt: eksik şema, sondaki nokta, boşluk. Bunlar sessiz
    // başarısızlığın en sık sebebi ("10.25.64.85." çözümlenemez).
    // Vekil adresi ("/api/video/mjpeg?...") zaten aynı origin'de ve göreli;
    // ona dokunulmaz, yoksa başına http:// eklenip bozulur.
    if (!url.startsWith('/')) {
      const { url: temiz, duzeltmeler } = window.normalizeStreamUrlDetay(url, {
        defaultPath: '/stream',
      });
      if (duzeltmeler.length) {
        window.showToast(`Adres düzeltildi (${duzeltmeler.join(', ')}): ${temiz}`, 'info');
      }
      url = temiz;
    }

    this._mjpegUrl = url;
    this._mjpegErrors = 0;
    this._mjpegVekil = !!opts.vekil;
    this.webcamVideo.classList.add('hidden');
    this.canvas.classList.remove('hidden');

    // Draw MJPEG img to canvas
    const img = new Image();
    // DİKKAT: burada crossOrigin='anonymous' KULLANILMAZ. Kaynak sunucu
    // Access-Control-Allow-Origin göndermiyorsa (çoğu MJPEG sunucusu
    // göndermez) tarayıcı görüntüyü hiç yüklemez ve hata bile göstermez.
    // Canvas'tan piksel okumadığımız için (getImageData/toDataURL yok)
    // "kirlenmiş canvas" bizim için sorun değil.
    this._mjpegImg = img;

    let drawn = 0;
    let fpsStart = performance.now();

    const drawFrame = () => {
      if (!this._mjpegImg) return;
      const ctx = this.canvas.getContext('2d');
      if (img.complete && img.naturalWidth) {
        this.canvas.width = img.naturalWidth;
        this.canvas.height = img.naturalHeight;
        ctx.drawImage(img, 0, 0);
        drawn++;
      }
      const dt = performance.now() - fpsStart;
      if (dt >= 1000) {
        document.getElementById('info-fps').textContent = Math.round((drawn * 1000) / dt);
        drawn = 0;
        fpsStart = performance.now();
      }
      this._animFrame = requestAnimationFrame(drawFrame);
    };

    img.onload = () => {
      this._mjpegErrors = 0;
      this._onStreamStarted('mjpeg');
      drawFrame();
    };
    img.onerror = () => {
      // Kaynak henüz ayakta olmayabilir; birkaç kez dene, sonra vazgeç.
      // (Eskiden sonsuza kadar sessizce denerdi: kamera "hiç açılmıyor" görünürdü.)
      if (this._mjpegImg !== img) return;
      this._mjpegErrors++;

      // 4 denemeden sonra sunucu üzerinden gitmeyi dene. Tarayıcı kaynağa
      // erişemiyor olabilir (CORS engeli, farklı ağ, karışık içerik); YKI
      // sunucusu erişebiliyorsa yayın oradan aktarılır.
      if (this._mjpegErrors === 4 && !this._mjpegVekil) {
        const vekilUrl = `/api/video/mjpeg?url=${encodeURIComponent(url)}`;
        window.showToast('Doğrudan bağlanılamadı, sunucu üzerinden deneniyor...', 'warning');
        this.stopCamera();
        this._startMJPEG(vekilUrl, { vekil: true });
        return;
      }

      if (this._mjpegErrors === 5) {
        window.showToast(`MJPEG kaynağına ulaşılamıyor: ${url}`, 'error');
      }
      if (this._mjpegErrors > 20) {
        window.showToast('MJPEG bağlantısı kurulamadı, durduruldu', 'error');
        this.stopCamera();
        return;
      }
      setTimeout(() => {
        if (this._mjpegImg === img) img.src = url + (url.includes('?') ? '&' : '?') + Date.now();
      }, 500);
    };
    img.src = url;
    window.showToast('MJPEG stream bağlanıyor...', 'info');
  }

  _onStreamStarted(type) {
    this.streaming = true;
    document.getElementById('no-signal-overlay').classList.add('hidden');
    const btn = document.getElementById('btn-toggle-stream');
    btn.classList.remove('hidden');
    btn.innerHTML = `<svg viewBox="0 0 20 20" width="14"><rect x="3" y="4" width="5" height="12" rx="1" fill="currentColor"/><rect x="12" y="4" width="5" height="12" rx="1" fill="currentColor"/></svg> Durdur`;
  }

  _onStreamStopped() {
    this.streaming = false;
    if (this._animFrame) { cancelAnimationFrame(this._animFrame); this._animFrame = null; }
    this.webcamVideo.classList.add('hidden');
    this.canvas.classList.remove('hidden');
    document.getElementById('no-signal-overlay').classList.remove('hidden');
    document.getElementById('btn-toggle-stream').classList.add('hidden');
    document.getElementById('info-fps').textContent = '--';
  }

  // ── Instruments ────────────────────────────────────────────
  toggleInstruments(show) {
    const panel = document.getElementById('instrument-panel');
    this._instrumentsVisible = show !== undefined ? show : !this._instrumentsVisible;
    panel.classList.toggle('hidden', !this._instrumentsVisible);
  }

  _updateInstruments(data) {
    if (!this._instrumentsVisible) return;
    const pitch = data.pitch ?? 0;
    const roll = data.roll ?? 0;
    const yaw = data.yaw ?? data.heading ?? 0;

    this.ai.update(roll, pitch);
    this.compass.update(yaw);

    document.getElementById('inst-pitch').textContent = `${pitch.toFixed(1)}°`;
    document.getElementById('inst-roll').textContent = `${roll.toFixed(1)}°`;
    document.getElementById('inst-hdg').textContent = `${String(Math.round(((yaw % 360) + 360) % 360)).padStart(3, '0')}°`;
    document.getElementById('inst-yaw').textContent = `${yaw.toFixed(1)}°`;
  }

  // ── Overlay ────────────────────────────────────────────────
  _updateOverlay(data) {
    if (data.gps) {
      document.getElementById('info-lat').textContent =
        data.gps.lat !== undefined ? data.gps.lat.toFixed(6) : '--.------';
      document.getElementById('info-lon').textContent =
        data.gps.lon !== undefined ? data.gps.lon.toFixed(6) : '--.------';
    }
    if (data.tracking !== undefined) {
      document.getElementById('tracking-badge').classList.toggle('hidden', !data.tracking);
    }
  }
}

window.dashboard = null;