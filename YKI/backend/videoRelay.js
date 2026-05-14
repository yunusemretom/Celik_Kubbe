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

  startStream(rtspUrl) {
    if (this.streaming) this.stopStream();

    const cfg = this.config.get('video');
    const [width, height] = (cfg.resolution || '1280x720').split('x');
    this.currentUrl = rtspUrl || cfg.rtspUrl;

    console.log(`[Video] Stream başlatılıyor: ${this.currentUrl}`);

    const args = [
      '-loglevel', 'warning',
      '-rtsp_transport', 'tcp',
      '-i', this.currentUrl,
      '-f', 'mpeg1video',
      '-b:v', `${cfg.bitrate || 800}k`,
      '-r', String(cfg.fps || 30),
      '-vf', `scale=${width}:${height}`,
      '-q:v', '5',
      'pipe:1',
    ];

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

    this.ffmpegProcess.stderr.on('data', (data) => {
      const msg = data.toString();
      if (msg.includes('Error') || msg.includes('error')) {
        console.error('[Video] FFmpeg:', msg.trim());
      }
    });

    this.ffmpegProcess.on('close', (code) => {
      console.log(`[Video] FFmpeg kapandı (kod: ${code})`);
      this.streaming = false;
      this.ffmpegProcess = null;
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
    this._broadcastStatus();
    console.log('[Video] Stream durduruldu');
  }

  _broadcastStatus() {
    const msg = JSON.stringify({
      type: 'stream_status',
      streaming: this.streaming,
      url: this.currentUrl,
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
    };
  }
}

module.exports = VideoRelay;
