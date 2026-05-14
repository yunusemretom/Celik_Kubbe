/**
 * Telemetri sayfası — Chart.js grafikleri ve ham veri tablosu
 */
class TelemetryPage {
  constructor() {
    this.charts = {};
    this.MAX_POINTS = 60; // son 60 veri noktası
    this.history = [];
    this.csvData = [];
    this._initCharts();
    this._bindEvents();

    document.getElementById('btn-clear-charts').addEventListener('click', () => this.clearAll());
    document.getElementById('btn-export-csv').addEventListener('click', () => this.exportCSV());
  }

  _chartDefaults() {
    return {
      type: 'line',
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        plugins: { legend: { display: false } },
        scales: {
          x: {
            display: false,
          },
          y: {
            grid: { color: 'rgba(255,255,255,0.05)' },
            ticks: { color: '#8e949a', font: { size: 10 } },
          },
        },
        elements: {
          point: { radius: 0 },
          line: { borderWidth: 2, tension: 0.3 },
        },
      },
    };
  }

  _makeDataset(color) {
    return {
      data: [],
      borderColor: color,
      backgroundColor: color.replace(')', ', 0.08)').replace('rgb', 'rgba'),
      fill: true,
    };
  }

  _initCharts() {
    Chart.defaults.color = '#8e949a';

    const configs = [
      { id: 'chart-battery', color: 'rgb(0, 230, 118)', yLabel: '%', min: 0, max: 100 },
      { id: 'chart-altitude', color: 'rgb(0, 200, 255)', yLabel: 'm' },
      { id: 'chart-speed', color: 'rgb(255, 171, 0)', yLabel: 'm/s', min: 0 },
      { id: 'chart-rssi', color: 'rgb(186, 104, 200)', yLabel: 'dBm' },
    ];

    configs.forEach(({ id, color, min, max }) => {
      const cfg = this._chartDefaults();
      cfg.data = { labels: [], datasets: [this._makeDataset(color)] };
      if (min !== undefined) cfg.options.scales.y.min = min;
      if (max !== undefined) cfg.options.scales.y.max = max;
      const ctx = document.getElementById(id).getContext('2d');
      this.charts[id] = new Chart(ctx, cfg);
    });
  }

  _push(chartId, value) {
    const chart = this.charts[chartId];
    if (!chart || value === undefined || value === null) return;
    const label = new Date().toLocaleTimeString('tr-TR', { hour12: false });
    chart.data.labels.push(label);
    chart.data.datasets[0].data.push(value);
    if (chart.data.labels.length > this.MAX_POINTS) {
      chart.data.labels.shift();
      chart.data.datasets[0].data.shift();
    }
    chart.update('none');
  }

  update(data) {
    if (!data) return;

    const battery = data.battery ?? data.battery_pct ?? null;
    const altitude = data.altitude ?? data.alt ?? null;
    const speed = data.speed ?? data.groundspeed ?? null;
    const rssi = data.rssi ?? data.signal ?? null;

    this._push('chart-battery', battery);
    this._push('chart-altitude', altitude);
    this._push('chart-speed', speed);
    this._push('chart-rssi', rssi);

    // Live labels
    if (battery !== null) document.getElementById('live-battery').textContent = `${battery.toFixed(0)}%`;
    if (altitude !== null) document.getElementById('live-altitude').textContent = `${altitude.toFixed(1)} m`;
    if (speed !== null) document.getElementById('live-speed').textContent = `${speed.toFixed(1)} m/s`;
    if (rssi !== null) document.getElementById('live-rssi').textContent = `${rssi.toFixed(0)} dBm`;

    // Raw table
    this._addTableRow(data);

    // CSV buffer
    this.csvData.push({
      time: new Date().toISOString(),
      battery, altitude, speed, rssi,
      lat: data.gps?.lat, lon: data.gps?.lon,
      mode: data.mode,
    });
  }

  _addTableRow(data) {
    const table = document.getElementById('tele-table');
    const placeholder = table.querySelector('.tele-placeholder');
    if (placeholder) placeholder.remove();

    const time = new Date().toLocaleTimeString('tr-TR', { hour12: false });

    // Basit key-value satırları
    const interestingKeys = ['battery', 'altitude', 'speed', 'mode', 'rssi', 'tracking'];
    interestingKeys.forEach((key) => {
      if (data[key] === undefined) return;
      const row = document.createElement('div');
      row.className = 'tele-row';
      row.innerHTML = `
        <span class="tele-time">${time}</span>
        <span class="tele-key">${key}</span>
        <span class="tele-val">${JSON.stringify(data[key])}</span>`;
      table.insertBefore(row, table.firstChild);
    });

    // Max 100 satır tut
    while (table.children.length > 100) table.removeChild(table.lastChild);
  }

  clearAll() {
    Object.values(this.charts).forEach((c) => {
      c.data.labels = [];
      c.data.datasets[0].data = [];
      c.update();
    });
    document.getElementById('tele-table').innerHTML = '<div class="tele-placeholder">Telemetri verisi bekleniyor...</div>';
    this.csvData = [];
    document.getElementById('live-battery').textContent = '--%';
    document.getElementById('live-altitude').textContent = '-- m';
    document.getElementById('live-speed').textContent = '-- m/s';
    document.getElementById('live-rssi').textContent = '-- dBm';
    window.showToast('Veriler temizlendi', 'info');
  }

  exportCSV() {
    if (this.csvData.length === 0) {
      window.showToast('Dışa aktarılacak veri yok', 'warning');
      return;
    }
    const headers = Object.keys(this.csvData[0]).join(',');
    const rows = this.csvData.map((r) => Object.values(r).join(','));
    const content = [headers, ...rows].join('\n');
    const blob = new Blob([content], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `yki_telemetri_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    window.showToast('CSV indirildi', 'success');
  }

  _bindEvents() {
    ykiWS.on('telemetry', (msg) => this.update(msg.data));
  }
}

window.telemetryPage = null;
