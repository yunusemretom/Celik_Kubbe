#!/usr/bin/env python3
"""
YKI — Telemetri Simülatörü
RPi5'i simüle eder. UDP üzerinden JSON telemetri gönderir.

Kullanım: python3 telemetry_sim.py [hedef_ip] [port]
"""
import socket, json, time, math, sys

HOST = sys.argv[1] if len(sys.argv) > 1 else '127.0.0.1'
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 5001

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
seq = 0
t0 = time.time()

print(f"YKI Telemetri Simülatörü → {HOST}:{PORT}")
print("Ctrl+C ile durdurun...\n")

try:
    while True:
        t = time.time() - t0
        data = {
            "seq": seq,
            "timestamp": int(time.time() * 1000),
            # Batarya yavaşça düşüyor
            "battery": max(0, 100 - t * 0.05),
            # Sinüs dalgalarıyla değişen değerler
            "altitude": 100 + 40 * math.sin(t / 15),
            "speed": 12 + 5 * math.cos(t / 10),
            "rssi": -55 - 15 * abs(math.sin(t / 8)),
            # Uçuş açıları
            "pitch": 10 * math.sin(t / 5),
            "roll": 20 * math.sin(t / 7),
            "yaw": (t * 15) % 360,
            "heading": (t * 15) % 360,
            # Mod: her 15 saniyede değişiyor
            "mode": "TRACKING" if int(t / 15) % 2 == 0 else "IDLE",
            "tracking": int(t / 15) % 2 == 0,
            # GPS
            "gps": {
                "lat": 39.925533 + 0.0005 * math.sin(t / 20),
                "lon": 32.866287 + 0.0005 * math.cos(t / 20),
                "fix": True,
                "satellites": 12
            }
        }
        payload = json.dumps(data).encode()
        s.sendto(payload, (HOST, PORT))

        # Konsol çıktısı
        print(f"\rSeq:{seq:5d} | Bat:{data['battery']:.1f}% | Alt:{data['altitude']:.1f}m | "
              f"P:{data['pitch']:.1f}° R:{data['roll']:.1f}° H:{data['heading']:.0f}° | "
              f"Mode:{data['mode']}", end='', flush=True)

        seq += 1
        time.sleep(0.1)  # 10 Hz

except KeyboardInterrupt:
    print(f"\n\nDurduruldu. Toplam {seq} paket gönderildi.")
    s.close()
