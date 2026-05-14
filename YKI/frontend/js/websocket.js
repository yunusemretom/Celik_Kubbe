/**
 * YKI WebSocket Manager
 * Backend ile tek bağlantı noktası. Event-based mimari.
 */
class YKIWebSocket extends EventTarget {
  constructor() {
    super();
    this.ws = null;
    this.connected = false;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 10;
    this.reconnectDelay = 2000;
    this.pingInterval = null;
    this.latency = 0;
    this._pingTs = 0;
  }

  connect() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${location.host}`;

    console.log(`[WS] Bağlanılıyor: ${url}`);
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      console.log('[WS] Bağlandı');
      this.connected = true;
      this.reconnectAttempts = 0;
      this.dispatch('connected');
      this._startPing();
    };

    this.ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        this._handleMessage(msg);
      } catch (e) {
        console.error('[WS] Parse hatası:', e);
      }
    };

    this.ws.onclose = () => {
      console.warn('[WS] Bağlantı kapandı');
      this.connected = false;
      this._stopPing();
      this.dispatch('disconnected');
      this._scheduleReconnect();
    };

    this.ws.onerror = (e) => {
      console.error('[WS] Hata:', e);
      this.dispatch('error', { message: 'WebSocket hatası' });
    };
  }

  _handleMessage(msg) {
    if (msg.type === 'pong') {
      this.latency = Date.now() - this._pingTs;
      this.dispatch('latency', { ms: this.latency });
      return;
    }
    this.dispatch(msg.type, msg);
  }

  _startPing() {
    this.pingInterval = setInterval(() => {
      if (this.connected) {
        this._pingTs = Date.now();
        this.send({ type: 'ping' });
      }
    }, 2000);
  }

  _stopPing() {
    if (this.pingInterval) { clearInterval(this.pingInterval); this.pingInterval = null; }
  }

  _scheduleReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('[WS] Maksimum yeniden bağlanma denemesi aşıldı');
      return;
    }
    const delay = Math.min(this.reconnectDelay * Math.pow(1.5, this.reconnectAttempts), 15000);
    this.reconnectAttempts++;
    console.log(`[WS] ${delay}ms sonra yeniden bağlanılacak (deneme ${this.reconnectAttempts})`);
    setTimeout(() => this.connect(), delay);
  }

  send(data) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
      return true;
    }
    return false;
  }

  dispatch(type, data = {}) {
    this.dispatchEvent(Object.assign(new Event(type), { detail: data }));
  }

  on(type, handler) {
    this.addEventListener(type, (e) => handler(e.detail || e));
  }
}

// Global instance
window.ykiWS = new YKIWebSocket();
