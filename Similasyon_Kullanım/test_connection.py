#!/usr/bin/env python3
"""
Kopru dogrulama testi - sadece standart kutuphane kullanir (OpenCV gerekmez).

Unity'ye baglanir, birkac kare alir, telemetriyi dogrular ve tarete kisa bir
hareket komutu gonderip acinin gercekten degistigini olcer.

Kullanim:
    python3 test_connection.py
"""

from __future__ import annotations

import json
import socket
import struct
import sys
import time

HOST, PORT = "127.0.0.1", 8765
MSG_FRAME, MSG_COMMAND = 0x01, 0x10
HEADER = struct.Struct(">BI")


class Reader:
    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.buf = bytearray()

    def exactly(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("Unity baglantiyi kapatti")
            self.buf.extend(chunk)
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def frame(self):
        type_, length = HEADER.unpack(self.exactly(HEADER.size))
        body = self.exactly(length)
        if type_ != MSG_FRAME:
            raise ValueError(f"beklenmeyen mesaj tipi 0x{type_:02x}")
        json_len = int.from_bytes(body[:2], "big")
        telemetry = json.loads(body[2 : 2 + json_len].decode("utf-8"))
        jpeg = body[2 + json_len :]
        return telemetry, jpeg


def send(sock: socket.socket, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    sock.sendall(HEADER.pack(MSG_COMMAND, len(body)) + body)


def main() -> int:
    print(f"[1/4] Baglaniliyor {HOST}:{PORT} ...")
    try:
        sock = socket.create_connection((HOST, PORT), timeout=10)
    except OSError as e:
        print(f"  BASARISIZ: {e}")
        print("  Unity'de SteelDomeSim sahnesinin Play modunda oldugundan emin olun.")
        return 1
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print("  Baglanti kuruldu.")

    reader = Reader(sock)

    print("[2/4] Kare akisi kontrol ediliyor ...")
    start = time.monotonic()
    sizes = []
    telemetry = {}
    for i in range(20):
        telemetry, jpeg = reader.frame()
        sizes.append(len(jpeg))
        if i == 0:
            magic_ok = jpeg[:2] == b"\xff\xd8" and jpeg[-2:] == b"\xff\xd9"
            print(f"  Ilk kare: {len(jpeg)} bayt, gecerli JPEG: {magic_ok}")
            print(f"  Cozunurluk: {telemetry.get('w')}x{telemetry.get('h')}  "
                  f"dikey FOV: {telemetry.get('vfov')} derece")
    elapsed = time.monotonic() - start
    print(f"  20 kare {elapsed:.2f} sn'de alindi -> {20 / elapsed:.1f} fps")
    print(f"  Ortalama kare boyutu: {sum(sizes) // len(sizes)} bayt")

    print("[3/4] Hareket komutu testi (yaw saga 1 sn) ...")
    yaw_before = telemetry.get("yaw", 0.0)
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        send(sock, {"mode": "rate", "yaw": 1.0, "pitch": 0.0})
        telemetry, _ = reader.frame()
    send(sock, {"mode": "stop"})
    for _ in range(5):
        telemetry, _ = reader.frame()
    yaw_after = telemetry.get("yaw", 0.0)
    delta = yaw_after - yaw_before
    print(f"  Yaw: {yaw_before:.2f} -> {yaw_after:.2f} derece  (degisim {delta:+.2f})")
    moved = abs(delta) > 5.0
    print(f"  Taret hareket etti: {moved}")

    print("[4/4] Mutlak aci komutu testi (yaw=-45, pitch=15) ...")
    send(sock, {"mode": "angle", "yaw": -45.0, "pitch": 15.0})
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        telemetry, _ = reader.frame()
    yaw_err = abs(telemetry.get("yaw", 0.0) - (-45.0))
    pitch_err = abs(telemetry.get("pitch", 0.0) - 15.0)
    print(f"  Ulasilan: yaw {telemetry.get('yaw'):.2f}  pitch {telemetry.get('pitch'):.2f}")
    print(f"  Sapma   : yaw {yaw_err:.2f}  pitch {pitch_err:.2f} derece")
    accurate = yaw_err < 1.0 and pitch_err < 1.0

    send(sock, {"mode": "stop"})
    sock.close()

    ok = moved and accurate
    print("\nSONUC:", "TUM TESTLER BASARILI" if ok else "BAZI TESTLER BASARISIZ")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
