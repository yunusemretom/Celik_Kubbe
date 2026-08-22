const { spawn } = require('child_process');
const WebSocket = require('ws');
const EventEmitter = require('events');
const videoDevices = require('./videoDevices');

class VideoRelay extends EventEmitter {
  constructor(config) {
    super();
    this.config = config;
    this.ffmpegProcess = null;
    this.wsServer = null;
    this.clients = new Set();
    this.streaming = false;
    this.frameCount = 0;
    this.startTime = null;
    this.currentUrl = null;
    this.currentSource = null;
    this.lastError = null;
    this._esnekMod = false;   // cozunurluk dayatmadan yeniden deneme
    this._sonOpts = null;
  }

  startServer() {
    const { videoWsPort } = this.config.get('server');

    this.wsServer = new WebSocket.Server({ port: videoWsPort });

    this.wsServer.on('connection', (ws) => {
      this.clients.add(ws);
      console.log(`[Video] İstemci bağlandı. Toplam: ${this.clients.size}`);

      // Yeni istemciye mevcut durumu gönder
      ws.send(JSON.stringify({
        type: 'stream_status',
        streaming: this.streaming,
        url: this.currentUrl,
      }));

      ws.on('close', () => {
        this.clients.delete(ws);
        console.log(`[Video] İstemci ayrıldı. Toplam: ${this.clients.size}`);
      });

      ws.on('error', () => { this.clients.delete(ws); });
    });

    console.log(`[Video] WebSocket sunucu port ${videoWsPort} hazır`);
  }

  /**
   * Girdiye göre FFmpeg giriş argümanlarını kurar.
   * opts: { source: 'rtsp'|'device'|'mjpeg', url, device }
   */
  _inputArgs(opts, cfg, width, height) {
    const fps = String(cfg.fps || 30);

    if (opts.source === 'device') {
      let dev = opts.device || cfg.device || '/dev/video0';

      // Kaydedilmiş cihaz artık yoksa ya da metadata düğümüyse (kare vermez)
      // gerçek bir kameraya geç. Kamera numaraları takma sırasına göre
      // kaydığı için yki_config.json'daki yol her açılışta doğru olmayabilir.
      if (!videoDevices.isCaptureDevice(dev)) {
        const yedek = videoDevices.pickFallback(dev);
        if (yedek) {
          console.warn(`[Video] ${dev} görüntü veren bir cihaz değil -> ${yedek} kullanılıyor`);
          this.emit('warning', `${dev} bulunamadı, ${yedek} kullanılıyor`);
          dev = yedek;
        } else {
          console.error('[Video] Sistemde hiç kamera bulunamadı');
          this.emit('error', 'Sistemde kamera bulunamadı (/dev/video* yok)');
        }
      }

      this.currentUrl = dev;

      // İkinci denemede çözünürlük/fps dayatmayı bırakırız: kamera istenen
      // kipi desteklemiyorsa ffmpeg "Invalid argument" ile kapanır, oysa
      // sürücünün kendi varsayılanıyla sorunsuz açılır.
      if (this._esnekMod) {
        return ['-f', 'v4l2', '-i', this.currentUrl];
      }
      return [
        '-f', 'v4l2',
        '-framerate', fps,
        '-video_size', `${width}x${height}`,
        '-i', this.currentUrl,
      ];
    }

    if (opts.source === 'mjpeg') {
      // Tarayıcı MJPEG'i doğrudan da çizebilir; bu yol yalnızca kaynağa
      // yalnızca sunucunun erişebildiği durumlar için.
      this.currentUrl = opts.url || cfg.mjpegUrl;
      return ['-f', 'mjpeg', '-i', this.currentUrl];
    }

    this.currentUrl = opts.url || cfg.rtspUrl;
    return ['-rtsp_transport', 'tcp', '-i', this.currentUrl];
  }

  /**
   * Yayını başlatır.
   * Eski kullanım (`startStream(rtspUrl)`) çalışmaya devam eder.
   */
  startStream(opts) {
    if (this.streaming) this.stopStream();

    if (typeof opts === 'string' || !opts) opts = { source: 'rtsp', url: opts };

    const cfg = this.config.get('video');
    const [width, height] = (cfg.resolution || '1280x720').split('x');
    this.currentSource = opts.source || 'rtsp';
    this._sonOpts = opts;          // başarısız olursa yeniden denemek için
    // Esnek mod YALNIZCA içeriden yapılan tekrar denemede açık olmalı. Aksi
    // halde bir kez devreye girdikten sonra açık kalır ve sonraki normal
    // başlatmalarda da çözünürlük ayarı sessizce yok sayılırdı.
    this._esnekMod = !!opts._retry;

    const args = [
      '-loglevel', 'warning',
      ...this._inputArgs(opts, cfg, width, height),
      '-f', 'mpeg1video',
      '-b:v', `${cfg.bitrate || 800}k`,
      '-r', String(cfg.fps || 30),
      '-vf', `scale=${width}:${height}`,
      '-q:v', '5',
      'pipe:1',
    ];

    console.log(`[Video] Stream başlatılıyor (${this.currentSource}): ${this.currentUrl}`);

    this.ffmpegProcess = spawn('ffmpeg', args);
    this.startTime = Date.now();
    this.frameCount = 0;
    this.streaming = true;

    this.ffmpegProcess.stdout.on('data', (data) => {
      this.frameCount++;
      this.clients.forEach((client) => {
        if (client.readyState === WebSocket.OPEN) {
          try { client.send(data, { binary: true }); } catch (_) {}
        }
      });
    });

    this.lastError = null;
    this.ffmpegProcess.stderr.on('data', (data) => {
      const msg = data.toString().trim();
      if (!msg) return;
      // Kaynak açılamadığında hata son satırda gelir; arayüze taşımak için
      // saklıyoruz - aksi halde kamera sessizce açılmıyor gibi görünüyor.
      this.lastError = msg.split('\n').pop();
      if (/error|Invalid|No such|busy|refused|denied|timed out/i.test(msg)) {
        console.error('[Video] FFmpeg:', msg);
      }
    });

    this.ffmpegProcess.on('close', (code) => {
      console.log(`[Video] FFmpeg kapandı (kod: ${code})`);
      const failed = this.streaming && code !== 0 && this.frameCount === 0;
      this.streaming = false;
      this.ffmpegProcess = null;

      // Kamera istenen çözünürlük/fps'i desteklemiyorsa ffmpeg hiç kare
      // üretmeden kapanır. Bir kez de sürücünün kendi varsayılanıyla dene;
      // çoğu USB kamera 1280x720@30 veremez ama 640x480 verir.
      if (failed && this.currentSource === 'device' && !this._esnekMod
          && this._bicimHatasi(this.lastError)) {
        console.warn('[Video] Çözünürlük/fps kabul edilmedi, kameranın kendi '
          + 'varsayılanıyla yeniden deneniyor');
        const tekrar = { ...this._sonOpts, device: this.currentUrl, _retry: true };
        setTimeout(() => this.startStream(tekrar), 300);
        return;
      }

      if (failed) {
        this.emit('error', `Kaynak açılamadı (${this.currentUrl}): `
          + (this.lastError || `ffmpeg kod ${code}`) + this._ipucu(this.lastError));
      }
      this.emit('stopped');
      this._broadcastStatus();
    });

    this.ffmpegProcess.on('error', (err) => {
      if (err.code === 'ENOENT') {
        console.error('[Video] FFmpeg bulunamadı! Lütfen ffmpeg kurun: sudo apt install ffmpeg');
        this.emit('error', 'FFmpeg kurulu değil');
      } else {
        console.error('[Video] FFmpeg hatası:', err.message);
        this.emit('error', err.message);
      }
      this.streaming = false;
      this._broadcastStatus();
    });

    this._broadcastStatus();
  }

  /** ffmpeg hatası "bu kip desteklenmiyor" anlamına mı geliyor? */
  _bicimHatasi(msg) {
    if (!msg) return true;    // sebep belli değilse esnek modu bir kez dene
    return /Invalid argument|Inappropriate ioctl|not support|Cannot find|pixel format|framerate|video_size/i
      .test(msg);
  }

  /** Kullanıcıya ne yapması gerektiğini söyleyen kısa ek. */
  _ipucu(msg) {
    if (!msg) return '';
    if (/busy/i.test(msg)) {
      return ' — kamerayı başka bir uygulama kullanıyor '
        + '(otonom_takip.py, tarayıcı sekmesi veya önceki bir ffmpeg). '
        + 'Kontrol: fuser -v ' + this.currentUrl;
    }
    if (/No such file|not found/i.test(msg)) {
      return ' — kamera takılı değil ya da yol değişmiş. '
        + 'Ayarlar > Kamera listesinden yeniden seçin.';
    }
    if (/Permission denied/i.test(msg)) {
      return ' — kullanıcı "video" grubunda değil: sudo usermod -aG video $USER';
    }
    return '';
  }

  stopStream() {
    if (this.ffmpegProcess) {
      this.ffmpegProcess.kill('SIGTERM');
      this.ffmpegProcess = null;
    }
    this.streaming = false;
    this.startTime = null;
    this.frameCount = 0;
    this.currentUrl = null;
    this.currentSource = null;
    this._broadcastStatus();
    console.log('[Video] Stream durduruldu');
  }

  _broadcastStatus() {
    const msg = JSON.stringify({
      type: 'stream_status',
      streaming: this.streaming,
      url: this.currentUrl,
      source: this.currentSource,
    });
    this.clients.forEach((client) => {
      if (client.readyState === WebSocket.OPEN) {
        try { client.send(msg); } catch (_) {}
      }
    });
  }

  getStatus() {
    const elapsed = this.startTime ? (Date.now() - this.startTime) / 1000 : 0;
    return {
      streaming: this.streaming,
      clients: this.clients.size,
      frameCount: this.frameCount,
      fps: elapsed > 0 ? Math.round(this.frameCount / elapsed) : 0,
      url: this.currentUrl,
      source: this.currentSource,
      lastError: this.lastError || null,
    };
  }
}

module.exports = VideoRelay;
