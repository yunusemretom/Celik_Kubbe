/**
 * Yayın adresi düzeltici — hem tarayıcı hem sunucu (node) tarafında kullanılır.
 *
 * Elle yazılan adreslerde sık yapılan hatalar sessiz başarısızlığa yol açar:
 *
 *   "10.25.64.85:8090/stream"    -> şema yok, tarayıcı göreli yol sanır
 *   "http://10.25.64.85.:8090/…" -> IP'nin sonundaki NOKTA. Bu artık geçerli bir
 *                                   IPv4 değildir, alan adı olarak çözümlenmeye
 *                                   çalışılır ve "Could not resolve host" alınır.
 *                                   Ekranda hiçbir hata görünmez, sadece görüntü
 *                                   gelmez.
 *   "http://10.25.64.85:8090"    -> yol yok; çoğu MJPEG sunucusu /stream ister
 *   sondaki/baştaki boşluk       -> kopyala-yapıştırdan gelir
 *
 * Döner: { url, duzeltmeler[] }  — duzeltmeler kullanıcıya gösterilebilir.
 */
(function (kok) {
  function normalizeStreamUrlDetay(ham, opts) {
    const varsayilanYol = (opts && opts.defaultPath) || '';
    const duzeltmeler = [];
    let s = String(ham == null ? '' : ham).trim();
    if (!s) return { url: '', duzeltmeler };

    if (/\s/.test(s)) {
      s = s.replace(/\s+/g, '');
      duzeltmeler.push('boşluklar silindi');
    }

    if (!/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(s)) {
      s = 'http://' + s;
      duzeltmeler.push('başına http:// eklendi');
    }

    let u;
    try {
      u = new URL(s);
    } catch (_) {
      return { url: s, duzeltmeler };   // ayrıştırılamadı: olduğu gibi bırak
    }

    // Sondaki nokta: "10.25.64.85." çözümlenemez. Alan adlarında da kök
    // noktası gereksizdir, güvenle atılabilir.
    if (u.hostname.length > 1 && u.hostname.endsWith('.')) {
      u.hostname = u.hostname.replace(/\.+$/, '');
      duzeltmeler.push('adresin sonundaki nokta kaldırıldı');
    }

    if (varsayilanYol && (u.pathname === '' || u.pathname === '/')) {
      u.pathname = varsayilanYol;
      duzeltmeler.push(`yol eklendi (${varsayilanYol})`);
    }

    return { url: u.toString(), duzeltmeler };
  }

  function normalizeStreamUrl(ham, opts) {
    return normalizeStreamUrlDetay(ham, opts).url;
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { normalizeStreamUrl, normalizeStreamUrlDetay };
  } else {
    kok.normalizeStreamUrl = normalizeStreamUrl;
    kok.normalizeStreamUrlDetay = normalizeStreamUrlDetay;
  }
})(typeof window !== 'undefined' ? window : globalThis);
