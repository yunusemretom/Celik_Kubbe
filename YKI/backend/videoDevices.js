/**
 * V4L2 kamera kesfi.
 *
 * NEDEN AYRI BIR MODUL: /dev/video* dugumlerini duz listelemek yanlis sonuc
 * verir. UVC kameralar (butun USB webcam'ler) HER BIRI ICIN IKI dugum acar:
 *
 *   /dev/video2  index=0  -> goruntu (capture)      <- kullanilacak olan
 *   /dev/video3  index=1  -> metadata               <- goruntu VERMEZ
 *
 * Ikisinin de adi ayni oldugu icin ("C270 HD WEBCAM") arayuzde iki ayni
 * secenek gorunur; kullanici metadata dugumunu secerse ffmpeg kareyi alamaz
 * ve kamera "hic acilmiyor" gibi gorunur. Asagidaki filtre bunu onler.
 */

const fs = require('fs');

const SYS = '/sys/class/video4linux';

function oku(yol, varsayilan = '') {
  try {
    return fs.readFileSync(yol, 'utf8').trim();
  } catch (_) {
    return varsayilan;
  }
}

/**
 * Yalnizca goruntu veren (capture) dugumleri dondurur.
 * @returns {Array<{path,name,usb,bus,node}>}
 */
function listCaptureDevices() {
  let nodes;
  try {
    nodes = fs.readdirSync('/dev').filter((f) => /^video\d+$/.test(f));
  } catch (_) {
    return [];
  }

  nodes.sort((a, b) => parseInt(a.slice(5), 10) - parseInt(b.slice(5), 10));

  const devices = [];
  for (const node of nodes) {
    // index=0 goruntu dugumu, index>0 metadata/ikincil dugum.
    const index = parseInt(oku(`${SYS}/${node}/index`, '0'), 10);
    if (index !== 0) continue;

    const name = oku(`${SYS}/${node}/name`, 'Bilinmeyen cihaz');

    // Fiziksel yol: hangi kameranin USB'ye takili oldugunu buradan anliyoruz.
    let bus = '';
    try {
      bus = fs.realpathSync(`${SYS}/${node}/device`);
    } catch (_) {}
    // Not: dizustu bilgisayarlarin DAHILI kamerasi da USB veriyolundadir,
    // bu yuzden 'usb' harici kamera demek degildir - yalnizca bilgidir.
    const usb = /\/usb\d+\//.test(bus);

    devices.push({
      path: `/dev/${node}`,
      node,
      name,
      usb,
      bus: bus ? bus.replace(/^.*\/(usb\d+\/.*)$/, '$1') : '',
      // Ayni model iki kez takiliysa yol tek ayirt edici bilgidir.
      label: `${name} - /dev/${node}`,
    });
  }
  return devices;
}

/** Verilen yol gercekten goruntu veren bir dugum mu? */
function isCaptureDevice(devicePath) {
  return listCaptureDevices().some((d) => d.path === devicePath);
}

/** Bir dugumun sysfs USB yolu (ayni fiziksel kamerayi tanimak icin). */
function busOf(devicePath) {
  const node = devicePath.replace('/dev/', '');
  try {
    return fs.realpathSync(`${SYS}/${node}/device`);
  } catch (_) {
    return '';
  }
}

/**
 * Yapilandirilmis cihaz artik yoksa (kamera cikarilmis, numara kaymis) ya da
 * goruntu vermeyen bir dugumse makul bir yedek secer.
 *
 * Once AYNI FIZIKSEL KAMERANIN goruntu dugumu aranir: kullanici listeden
 * /dev/video3'u sectiyse aslinda o kamerayi istiyordur, /dev/video2 onun
 * goruntu dugumudur. Ancak o da yoksa ilk kameraya dusulur.
 */
function pickFallback(preferred) {
  const devices = listCaptureDevices();
  if (!devices.length) return null;
  if (preferred && devices.some((d) => d.path === preferred)) return preferred;

  if (preferred) {
    const bus = busOf(preferred);
    if (bus) {
      const kardes = devices.find((d) => busOf(d.path) === bus);
      if (kardes) return kardes.path;
    }
  }
  return devices[0].path;
}

module.exports = { listCaptureDevices, isCaptureDevice, pickFallback };
