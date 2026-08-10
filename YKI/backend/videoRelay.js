const { spawn } = require('child_process');
const WebSocket = require('ws');
const EventEmitter = require('events');

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
      // V4L2 kamera: çözünürlük/fps sürücüden istenir, ffmpeg dönüştürmez.
      this.currentUrl = opts.device || cfg.device || '/dev/video0';
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
      if (failed) {
        this.emit('error', `Kaynak açılamadı (${this.currentUrl}): `
          + (this.lastError || `ffmpeg kod ${code}`));
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
