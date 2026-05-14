/**
 * YKI Ana Uygulama
 * Sayfa yönetimi, status bar, toast bildirimleri, WS olayları
 */

// ─── Toast ────────────────────────────────────────────────────────────────────
window.showToast = function (message, type = 'info', duration = 3500) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  const icons = { success: '✓', error: '✗', warning: '⚠', info: 'ℹ' };
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${icons[type] || 'ℹ'}</span><span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 350);
  }, duration);
};

// ─── Saat ─────────────────────────────────────────────────────────────────────
function updateClock() {
  const now = new Date();
  const t = now.toLocaleTimeString('tr-TR', { hour12: false });
  document.getElementById('clock').textContent = t;
}
setInterval(updateClock, 1000);
updateClock();

// ─── Sayfa Yöneticisi ─────────────────────────────────────────────────────────
const pages = ['dashboard', 'telemetry', 'settings', 'about'];
let currentPage = 'dashboard';

function navigateTo(pageId) {
  if (!pages.includes(pageId)) return;
  currentPage = pageId;

  pages.forEach((p) => {
    document.getElementById(`page-${p}`).classList.toggle('active', p === pageId);
    document.getElementById(`tab-${p}`)?.classList.toggle('active', p === pageId);
  });
}

document.querySelectorAll('.nav-tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    const page = tab.dataset.page;
    if (page) navigateTo(page);
  });
});

// ─── Status Bar ───────────────────────────────────────────────────────────────
function setVehicleStatus(connected, mode) {
  const dot = document.getElementById('dot-vehicle');
  const label = document.getElementById('label-vehicle');
  if (connected) {
    dot.className = 'status-dot connected';
    label.textContent = 'BAĞLI';
  } else {
    dot.className = 'status-dot disconnected';
    label.textContent = 'BAĞLI DEĞİL';
  }
}

function updateStatusBar(data) {
  if (!data) return;
  if (data.battery !== undefined)
    document.getElementById('label-battery').textContent = `${Math.round(data.battery)}%`;
  if (data.altitude !== undefined)
    document.getElementById('label-altitude').textContent = `${data.altitude.toFixed(1)} m`;
  if (data.speed !== undefined)
    document.getElementById('label-speed').textContent = `${data.speed.toFixed(1)} m/s`;
  if (data.mode !== undefined) {
    const el = document.getElementById('label-mode');
    el.textContent = data.mode;
    const pill = document.getElementById('mode-pill');
    pill.style.color = data.mode === 'TRACKING' ? 'var(--success)' : 'var(--warning)';
    pill.style.borderColor = data.mode === 'TRACKING' ? 'var(--success)' : 'var(--warning)';
  }
}

// ─── WebSocket Olayları ───────────────────────────────────────────────────────
ykiWS.on('connected', () => {
  console.log('[App] YKI bağlandı');
  showToast('Sunucuya bağlandı', 'success');
});

ykiWS.on('disconnected', () => {
  setVehicleStatus(false);
  showToast('Sunucu bağlantısı kesildi, yeniden bağlanılıyor...', 'warning', 5000);
});

ykiWS.on('telemetry_status', (msg) => {
  setVehicleStatus(msg.connected);
  if (msg.connected) showToast(`Telemetri bağlandı (${msg.ip || 'RPi5'})`, 'success');
  else showToast('Telemetri bağlantısı kesildi', 'warning');
});

// TCP komut hatası sadece bir kez bildirim gösterir
let _cmdErrShown = false;

ykiWS.on('command_status', (msg) => {
  if (msg.connected) {
    _cmdErrShown = false;
    showToast('Komut kanalı bağlandı (TCP)', 'success');
  } else if (msg.error && !_cmdErrShown) {
    _cmdErrShown = true;
    // EHOSTUNREACH = RPi5 ulaşılamaz, normal durum
    const isUnreachable = msg.error.includes('EHOSTUNREACH') || msg.error.includes('ECONNREFUSED');
    if (isUnreachable) {
      showToast('RPi5 bağlı değil — komut kanalı yeniden deneniyor...', 'warning', 5000);
    } else {
      showToast(`Komut kanalı hatası: ${msg.error}`, 'error');
    }
  }
});

ykiWS.on('telemetry', (msg) => {
  updateStatusBar(msg.data);
  setVehicleStatus(true, msg.data?.mode);
});

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Sayfaları başlat
  window.dashboard = new Dashboard();
  window.telemetryPage = new TelemetryPage();
  window.settingsPage = new SettingsPage();
  window.aboutPage = new AboutPage();

  // WebSocket bağlantısını kur
  ykiWS.connect();

  // Varsayılan sayfa
  navigateTo('dashboard');

  console.log('%c YKI — Yer Kontrol İstasyonu v1.0.0 ', 'background:#00c8ff;color:#000;font-weight:bold;padding:4px 8px;');
  console.log('%c TEKNOFEST Çelik Kubbe | Pars Takımı ', 'background:#1e2328;color:#00c8ff;padding:4px 8px;');
});
