# Çelik Kubbe - Nesne Tespiti (Object Detection)

Bu dizin, Pars Takımı Çelik Kubbe İHA sistemi için hedef tespiti ve takibi amacıyla yazılmış YOLO tabanlı derin öğrenme kodlarını barındırır.

## Dosyalar

* **`train.py`**: Modele yeni veri setleri (örneğin hava savunma nesneleri, rakip İHA'lar vb.) vererek model eğitimi yapmak için kullanılır.
* **`export_tensorrt.py`**: Eğitilmiş `.pt` modelini Jetson veya benzeri NVIDIA GPU kullanan cihazlarda yüksek performans ile çalıştırmak için `.engine` (TensorRT) formatına dönüştürür.
* **`realtime_detect.py`**: Bir video kaynağından (Webcam, USB Kamera, RTSP Yayın veya Video Dosyası) görüntüleri alarak gerçek zamanlı nesne tespiti yapan çıkarım (inference) kodudur.

## Kurulum ve Gereksinimler

Sistemin çalışması için aşağıdaki paketlerin Python ortamınızda yüklü olması gerekmektedir:

```bash
pip install ultralytics opencv-python
```

Eğer modeli TensorRT formatında dışa aktaracaksanız sisteminizde uygun NVIDIA sürücüleri, CUDA ve TensorRT kurulu olmalıdır.
