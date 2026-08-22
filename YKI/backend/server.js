const express = require('express');
const WebSocket = require('ws');
const http = require('http');
const path = require('path');

const config = require('./config');
const TelemetryBridge = require('./telemetryBridge');
const CommandBridge = require('./commandBridge');
const VideoRelay = require('./videoRelay');
const videoDevices = require('./videoDevices');
// Adres duzeltici tarayici ile ORTAK dosyadan gelir: iki taraf ayni kurallari
// uygulasin diye tek kaynak.
const { normalizeStreamUrl } = require('../frontend/js/streamUrl');

// ─── Express ───────────────────────────────────────────────────────────────────
const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, '../frontend')));

// ─── API ───────────────────────────────────────────────────────────────────────
// Not: bu rotalar aşağıdaki catch-all'dan ÖNCE tanımlanmalı, yoksa istek
// index.html ile cevaplanır ve arayüzde JSON ayrıştırma hatası olur.

/**
 * Sistemdeki V4L2 kameralarını listeler.
 * Yalnızca GÖRÜNTÜ VEREN düğümler döner: UVC kameralar her biri için ikinci
 * bir metadata düğümü (/dev/videoN+1) açar ve o düğüm kare vermez. Eskiden
 * ikisi de listelendiği için aynı isimden iki seçenek çıkıyor, metadata
 * düğümü seçildiğinde kamera sessizce açılmıyordu.
 */
app.get('/api/devices/video', (_, res) => {
  try {
    res.json({ devices: videoDevices.listCaptureDevices() });
  } catch (e) {
    res.status(500).json({ devices: [], error: e.message });
  }
});

/**
 * MJPEG vekil (proxy) ucu.
 *
 * NEDEN GEREKLI: tarayıcı uzak bir MJPEG kaynağını doğrudan çekerken kaynak
 * sunucu CORS başlığı göndermiyorsa ya da yalnızca sunucunun bulunduğu ağdan
 * erişilebiliyorsa görüntü gelmez. Burada akışı YKI sunucusu çeker ve aynı
 * origin üzerinden tarayıcıya aktarır; CORS ve erişim sorunları ortadan kalkar.
 *
 * Kullanım: /api/video/mjpeg?url=http%3A%2F%2F10.25.64.85%3A8090%2Fstream
 */
app.get('/api/video/mjpeg', (req, res) => {
  let hedef;
  try {
    hedef = new URL(normalizeStreamUrl(req.query.url || ''));
  } catch (e) {
    res.status(400).type('text').send('Geçersiz URL');
    return;
  }
  if (hedef.protocol !== 'http:' && hedef.protocol !== 'https:') {
    res.status(400).type('text').send('Yalnızca http/https desteklenir');
    return;
  }

  const istemci = hedef.protocol === 'https:' ? require('https') : require('http');
  const istek = istemci.get(hedef, (kaynak) => {
    if (kaynak.statusCode !== 200) {
      res.status(502).type('text').send(`Kaynak HTTP ${kaynak.statusCode} döndü`);
      kaynak.resume();
      return;
    }
    // Content-Type sınır (boundary) bilgisini içerir, aynen aktarılmalı.
    res.writeHead(200, {
      'Content-Type': kaynak.headers['content-type'] || 'multipart/x-mixed-replace',
      'Cache-Control': 'no-cache, private',
      'Access-Control-Allow-Origin': '*',
      Connection: 'close',
    });
    kaynak.pipe(res);
    res.on('close', () => kaynak.destroy());
  });

  istek.on('error', (err) => {
    console.error('[Video] MJPEG vekil hatası:', err.message);
    if (!res.headersSent) res.status(502).type('text').send(`Kaynağa ulaşılamadı: ${err.message}`);
  });
  istek.setTimeout(8000, () => istek.destroy(new Error('bağlantı zaman aşımı')));
});

app.get('*', (_, res) => res.sendFile(path.join(__dirname, '../frontend/index.html')));

// ─── HTTP + WS Sunucu ──────────────────────────────────────────────────────────
const { httpPort } = config.get('server');
const PORT = httpPort || 3000;
const server = http.createServer(app);
const wss = new WebSocket.Server({ server });

const frontendClients = new Set();

function broadcast(data) {
  const msg = JSON.stringify(data);
  frontendClients.forEach((ws) => {
    if (ws.readyState === WebSocket.OPEN) {
      try { ws.send(msg); } catch (_) {}
    }
  });
}

// ─── Köprüler ─────────────────────────────────────────────────────────────────
const telemetry = new TelemetryBridge(config);
const commandBridge = new CommandBridge(config);
const videoRelay = new VideoRelay(config);

// Telemetri olayları
telemetry.on('data', (data) => broadcast({ type: 'telemetry', data }));
telemetry.on('connected', (ip) => {
  console.log(`[Server] Telemetri bağlandı: ${ip}`);
  broadcast({ type: 'telemetry_status', connected: true, ip });
});
telemetry.on('disconnected', () => {
  broadcast({ type: 'telemetry_status', connected: false });
});

// Komut olayları
commandBridge.on('connected', () => broadcast({ type: 'command_status', connected: true }));
commandBridge.on('disconnected', () => broadcast({ type: 'command_status', connected: false }));
commandBridge.on('error', (msg) => broadcast({ type: 'command_status', connected: false, error: msg }));
commandBridge.on('response', (res) => broadcast({ type: 'command_response', data: res }));

// Video olayları
videoRelay.on('error', (msg) => broadcast({ type: 'video_error', error: msg }));
// Kaynak değiştirildi ama yayın devam ediyor (ör. kayıtlı cihaz bulunamadı):
// hata değil, kullanıcıyı bilgilendirme.
videoRelay.on('warning', (msg) => broadcast({ type: 'video_warning', warning: msg }));
// Yayın kendiliğinden düşerse arayüz "sinyal yok"a dönsün
videoRelay.on('stopped', () => broadcast({ type: 'video_status', streaming: false }));

// ─── WebSocket Mesaj İşleyici ─────────────────────────────────────────────────
wss.on('connection', (ws) => {
  frontendClients.add(ws);
  console.log(`[WS] İstemci bağlandı. Toplam: ${frontendClients.size}`);

  // İlk bağlantıda mevcut durumu gönder
  ws.send(JSON.stringify({
    type: 'init',
    config: config.get(),
    telemetryStatus: telemetry.getStatus(),
    commandStatus: commandBridge.getStatus(),
    videoStatus: videoRelay.getStatus(),
  }));

  ws.on('message', (raw) => {
    try {
      handleMessage(ws, JSON.parse(raw.toString()));
    } catch (e) {
      console.error('[WS] Mesaj hatası:', e.message);
    }
  });

  ws.on('close', () => {
    frontendClients.delete(ws);
    console.log(`[WS] İstemci ayrıldı. Toplam: ${frontendClients.size}`);
  });

  ws.on('error', () => frontendClients.delete(ws));
});

function handleMessage(ws, msg) {
  switch (msg.type) {
    case 'command':
      const result = commandBridge.sendCommand(msg.cmd, msg.params || {});
      ws.send(JSON.stringify({ type: 'command_ack', ...result, cmd: msg.cmd }));
      break;

    case 'video_start':
      videoRelay.startStream({
        source: msg.source || 'rtsp',
        url: msg.url || msg.rtspUrl || config.get('video').rtspUrl,
        device: msg.device || config.get('video').device,
      });
      broadcast({ type: 'video_status', ...videoRelay.getStatus() });
      break;

    case 'video_stop':
      videoRelay.stopStream();
      break;

    case 'video_status':
      ws.send(JSON.stringify({ type: 'video_status', ...videoRelay.getStatus() }));
      break;

    case 'settings_update':
      const saved = config.update(msg.settings);
      ws.send(JSON.stringify({ type: 'settings_saved', success: saved }));
      if (saved) {
        broadcast({ type: 'config_updated', config: config.get() });
        // Yalnızca RPi ayarları değiştiyse köprüleri yeniden kur. Kamera
        // kaynağı uygulanırken telemetri bağlantısı boşuna kopmasın.
        if (msg.settings && msg.settings.rpi) {
          telemetry.restart();
          commandBridge.disconnect();
          setTimeout(() => commandBridge.connect(), 1000);
        }
      }
      break;

    case 'settings_get':
      ws.send(JSON.stringify({ type: 'config', config: config.get() }));
      break;

    case 'ping':
      ws.send(JSON.stringify({ type: 'pong', timestamp: Date.now() }));
      break;

    default:
      console.warn('[WS] Bilinmeyen mesaj tipi:', msg.type);
  }
}

// ─── Başlat ───────────────────────────────────────────────────────────────────
telemetry.start();
commandBridge.connect();
videoRelay.startServer();

server.listen(PORT, () => {
  console.log('');
  console.log('╔══════════════════════════════════════════════════╗');
  console.log('║     YKI — Yer Kontrol İstasyonu  v1.0.0         ║');
  console.log('╠══════════════════════════════════════════════════╣');
  console.log(`║  Web Arayüzü : http://localhost:${PORT}            ║`);
  console.log(`║  Video WS    : ws://localhost:${config.get('server').videoWsPort}          ║`);
  console.log(`║  Telemetri   : UDP :${config.get('rpi').udpPort}                     ║`);
  console.log(`║  Komut       : TCP → ${config.get('rpi').ip}:${config.get('rpi').tcpPort}     ║`);
  console.log('╚══════════════════════════════════════════════════╝');
  console.log('');
});

// Temiz kapanış
process.on('SIGINT', () => {
  console.log('\n[Server] Kapatılıyor...');
  telemetry.stop();
  commandBridge.disconnect();
  videoRelay.stopStream();
  process.exit(0);
});
