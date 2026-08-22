/**
 * joystick.js
 * -----------
 * Dashboard'daki sanal joystick. Mouse/dokunmatik ile suruklenir, merkeze
 * gore normalize edilmis (pitch, yaw) uretir ve mevcut `window.ykiWS`
 * baglantisi uzerinden backend'e gonderir.
 *
 * DEGISIKLIK (ESP32 entegrasyonu):
 *   - Paket artik 4 alanli: { pitch, yaw, fire, arm }
 *   - ARM (emniyet mandali) ayri bir toggle. ARM kapaliyken ESP32
 *     ates etmez. Onceki surumde firmware ARM'i kosulsuz aciyordu.
 *   - ARM acikken sayfadan cikilirsa / sekme gizlenirse ARM otomatik duser.
 */

(function () {
  'use strict';

  const GONDERIM_HZ = 25;
  const OLU_BOLGE = 0.08;

  let sürükleniyor = false;
  let pitch = 0; // -1..1, yukari = +1
  let yaw = 0; // -1..1, sag = +1
  let fireBasili = false;
  let armAcik = false;

  function kur() {
    const taban = document.getElementById('joystick-taban');
    const topuz = document.getElementById('joystick-topuz');
    const fireBtn = document.getElementById('joystick-fire');
    const armBtn = document.getElementById('joystick-arm');
    const okuDeger = document.getElementById('joystick-oku');

    if (!taban || !topuz) {
      console.warn('[joystick] joystick-taban/joystick-topuz bulunamadi.');
      return;
    }

    function merkezeAl() {
      topuz.style.left = '50%';
      topuz.style.top = '50%';
      pitch = 0;
      yaw = 0;
      guncelleGosterge(okuDeger);
    }

    function noktadanEksenlereCevir(clientX, clientY) {
      const kutu = taban.getBoundingClientRect();
      const r = kutu.width / 2;
      let dx = clientX - (kutu.left + r);
      let dy = clientY - (kutu.top + r);

      const mesafe = Math.min(Math.hypot(dx, dy), r);
      const aci = Math.atan2(dy, dx);
      dx = Math.cos(aci) * mesafe;
      dy = Math.sin(aci) * mesafe;

      topuz.style.left = `calc(50% + ${dx}px)`;
      topuz.style.top = `calc(50% + ${dy}px)`;

      let yeniYaw = dx / r;
      let yeniPitch = -dy / r; // ekranda asagi=pozitif, biz yukari=+pitch istiyoruz

      if (Math.abs(yeniYaw) < OLU_BOLGE) yeniYaw = 0;
      if (Math.abs(yeniPitch) < OLU_BOLGE) yeniPitch = 0;

      yaw = clampBirim(yeniYaw);
      pitch = clampBirim(yeniPitch);
      guncelleGosterge(okuDeger);
    }

    function baslat(e) {
      sürükleniyor = true;
      tasi(e);
    }
    function tasi(e) {
      if (!sürükleniyor) return;
      const nokta = e.touches ? e.touches[0] : e;
      noktadanEksenlereCevir(nokta.clientX, nokta.clientY);
    }
    function birak() {
      if (!sürükleniyor) return;
      sürükleniyor = false;
      merkezeAl();
    }

    topuz.addEventListener('pointerdown', baslat);
    window.addEventListener('pointermove', tasi);
    window.addEventListener('pointerup', birak);
    topuz.addEventListener('touchstart', baslat, { passive: true });
    window.addEventListener('touchmove', tasi, { passive: true });
    window.addEventListener('touchend', birak);

    // ─── ARM (emniyet mandali) ───────────────────────────────────────
    function armGuncelle() {
      if (!armBtn) return;
      armBtn.classList.toggle('armed', armAcik);
      armBtn.textContent = armAcik ? 'ARM: ACIK' : 'ARM: KAPALI';
      guncelleGosterge(okuDeger);
    }

    function armKapat() {
      if (!armAcik) return;
      armAcik = false;
      armGuncelle();
      if (typeof window.showToast === 'function') {
        window.showToast('ARM kapatildi', 'info');
      }
    }

    if (armBtn) {
      armBtn.addEventListener('click', () => {
        armAcik = !armAcik;
        armGuncelle();
        if (typeof window.showToast === 'function') {
          window.showToast(
            armAcik ? 'ARM ACIK - sistem ates edebilir' : 'ARM kapatildi',
            armAcik ? 'warning' : 'info'
          );
        }
      });
      armGuncelle();
    }

    // ─── FIRE ────────────────────────────────────────────────────────
    if (fireBtn) {
      const basildi = () => {
        fireBasili = true;
        fireBtn.classList.add('active');
        guncelleGosterge(okuDeger);
      };
      const birakildi = () => {
        fireBasili = false;
        fireBtn.classList.remove('active');
        guncelleGosterge(okuDeger);
      };
      fireBtn.addEventListener('pointerdown', basildi);
      fireBtn.addEventListener('pointerup', birakildi);
      fireBtn.addEventListener('pointerleave', birakildi);
      fireBtn.addEventListener('touchstart', basildi, { passive: true });
      fireBtn.addEventListener('touchend', birakildi);

      // Klavye: Space = ates
      window.addEventListener('keydown', (e) => {
        if (e.code === 'Space' && !e.repeat) {
          e.preventDefault();
          basildi();
        }
        // Escape = acil: ARM kapat, tetigi birak, eksenleri sifirla
        if (e.code === 'Escape') {
          birakildi();
          armKapat();
          pitch = yaw = 0;
          merkezeAl();
        }
      });
      window.addEventListener('keyup', (e) => {
        if (e.code === 'Space') {
          e.preventDefault();
          birakildi();
        }
      });
    }

    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        pitch = yaw = 0;
        fireBasili = false;
        armKapat();     // sekme arkaya gecerse silahli kalma
      }
    });

    window.addEventListener('blur', () => {
      fireBasili = false;
    });

    merkezeAl();
  }

  function clampBirim(v) {
    return Math.max(-1, Math.min(1, v));
  }

  function guncelleGosterge(el) {
    if (el) {
      el.textContent =
        `pitch ${pitch.toFixed(2)}  yaw ${yaw.toFixed(2)}  ` +
        `fire ${fireBasili ? 1 : 0}  arm ${armAcik ? 1 : 0}`;
    }
  }

  function gonderimDongusuBaslat() {
    setInterval(() => {
      if (typeof ykiWS !== 'undefined') {
        ykiWS.send({
          type: 'joystick',
          pitch,
          yaw,
          fire: fireBasili ? 1 : 0,
          arm: armAcik ? 1 : 0,
        });
      }
    }, 1000 / GONDERIM_HZ);
  }

  document.addEventListener('DOMContentLoaded', () => {
    kur();
    gonderimDongusuBaslat();
  });

  window.addEventListener('beforeunload', () => {
    if (typeof ykiWS !== 'undefined') {
      ykiWS.send({ type: 'joystick', pitch: 0, yaw: 0, fire: 0, arm: 0 });
    }
  });
})();