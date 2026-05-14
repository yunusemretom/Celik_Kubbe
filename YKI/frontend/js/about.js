// Hakkında sayfası — statik içerik, ek JS gerekmez
// İleride dinamik sürüm bilgisi vs. eklenebilir
class AboutPage {
  constructor() {
    // Versiyon ve build tarihi
    const buildDate = new Date().toLocaleDateString('tr-TR');
    const el = document.querySelector('.about-version');
    if (el) el.textContent = `v1.0.0 — TEKNOFEST 2026`;
  }
}

window.aboutPage = null;
