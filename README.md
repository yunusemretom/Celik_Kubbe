# Çelik Kubbe

A two-axis tracking turret for the TEKNOFEST air defense competition, spanning
the whole stack: a browser-based ground control station, a YOLO target detection
pipeline, and ESP32-S3 firmware that owns motion control and the firing
interlocks.

Built by team Pars.

![demo](docs/demo.gif)

## Tech stack

![Node.js](https://img.shields.io/badge/Node.js-Backend-339933?logo=nodedotjs&logoColor=white)
![WebSocket](https://img.shields.io/badge/WebSocket-Realtime-010101?logo=socketdotio&logoColor=white)
![JavaScript](https://img.shields.io/badge/JavaScript-Frontend-F7DF1E?logo=javascript&logoColor=black)
![Python](https://img.shields.io/badge/Python-Detection-3776AB?logo=python&logoColor=white)
![YOLO](https://img.shields.io/badge/YOLO-Ultralytics-00FFFF)
![TensorRT](https://img.shields.io/badge/TensorRT-Inference-76B900?logo=nvidia&logoColor=white)
![ESP32](https://img.shields.io/badge/ESP32--S3-FreeRTOS-E7352C?logo=espressif&logoColor=white)
![Raspberry Pi](https://img.shields.io/badge/Raspberry_Pi_5-SBC-A22846?logo=raspberrypi&logoColor=white)
![FFmpeg](https://img.shields.io/badge/FFmpeg-Video_Relay-007808?logo=ffmpeg&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-blue)

## Quick start

The ground control station runs on its own and can be driven by the bundled
telemetry simulator, so you do not need the hardware to try it.

```bash
# 1. Clone
git clone https://github.com/yunusemretom/Celik_Kubbe.git
cd Celik_Kubbe

# 2. Ground control station
cd YKI/backend
npm install
npm start
```

Open `http://localhost:3000`. In a second terminal, feed it synthetic telemetry:

```bash
python YKI/telemetry_sim.py
```

Node.js, npm and FFmpeg are required; FFmpeg only for the RTSP camera mode.

Detection and firmware are built separately:

```bash
# Detection pipeline
cd Object_detection
pip install -r requirements.txt
export ROBOFLOW_API_KEY=your_key_here   # only needed for dataset download

# ESP32-S3 firmware: open esp32_firmware/esp32_firmware.ino in Arduino IDE
# Board: ESP32S3 Dev Module, USB CDC On Boot: Enabled
```

## How it works

Three computers with three different jobs, chosen by what each is good at.

```
[Browser / operator]
      | WebSocket :3000
[Ground station, Node.js]
      | TCP :5000   commands out
      | UDP :5001   telemetry in
      | WS  :8081   FFmpeg RTSP relay
[Raspberry Pi 5, vehicle computer]
      | USB serial, binary framing
[ESP32-S3, motion and safety]
```

Repository layout follows that split: `YKI/` is the ground station,
`Object_detection/` is the vision pipeline, `esp32_firmware/` and
`control_code/` are the embedded side.

### Why the transports are different

The ground station uses three transports on purpose, not by accident.

- **Telemetry over UDP.** Arrives once per second and is only useful fresh. A
  retransmitted one-second-old attitude reading is worse than a dropped one, so
  there is no reason to pay for reliability.
- **Commands over TCP,** with an application-level acknowledgement on top. Every
  command carries an `id`, and the vehicle answers `{"ack": id, "status": "ok"}`.
  Arming a turret is not a fire-and-forget operation.
- **Video over a separate WebSocket,** relayed by FFmpeg into jsmpeg. Keeping it
  off the telemetry socket means a stalled video decode cannot delay attitude
  updates.

### The problem the firmware exists to solve

The turret has two ways to be commanded: an operator joystick, and automatic aim
commands from the Pi. My first firmware let both drive the motors, and the
result was the classic "two masters" failure. The joystick and the position
controller fought each other, and the turret oscillated.

The fix is that mode ownership is exclusive and lives in one place:

| Mode | Input | Encoder | Control law |
|---|---|---|---|
| `MANUAL` | joystick | unused | open-loop velocity |
| everything else | `CMD_AIM` from Pi | AS5600 | closed-loop position |

One function, `applyModeToController()`, is the only thing that switches this. A
single owner per mode is less clever than blending the two inputs, and it is the
reason the turret stopped shaking.

### Safety is one gate, not scattered checks

`safety.cpp` is deliberately the only code in the system authorized to actuate
the trigger. Every fire request passes one gate that checks arm state, emergency
stop, remaining ammunition, no-fire zone bounds, range validity, target lock and
the minimum interval between shots. `config.h` is validated at compile time with
`#error` directives, so a build with a missing no-fire-zone constant does not
produce a binary at all.

The actuator behind the gate changed during the project, from a solenoid valve to
a servo pulling the trigger mechanically. The gate did not change. That is the
point of putting it in one place: swapping the bottom layer touched one function
call.

### Framing over USB serial

The Pi-to-ESP32 link is a binary protocol rather than JSON, because the aim
command runs far faster than telemetry and the parsing cost showed up.

```
0xAA 0x55 | msg_id | len | payload (<=32 B) | CRC-16/CCITT-FALSE
```

Bit 7 of `msg_id` marks direction, which makes a mis-wired loopback obvious
instead of silently plausible. Aim commands carry a sequence byte, and the
firmware counts gaps over a one-second window; sustained loss trips a
communication-lost freeze rather than letting the turret coast on a stale
setpoint. Debug logging shares the same framing as a `LOG_MSG` type, so firmware
logs surface in the web interface instead of needing a serial monitor.

Firmware runs as four FreeRTOS tasks pinned across both cores, so a blocking
LiDAR read cannot stall the control loop.

## Known limitations

- Tuned for one physical build. Pin map, PID gains and no-fire zone limits in
  `config.h` are specific to that turret.
- Detection was trained on a small competition dataset and does not generalize
  to other targets or lighting.
- The ground station has no authentication. It assumes an isolated competition
  network and should not be exposed.
- Telemetry at one hertz is too slow for smooth instrument display, so the
  interface interpolates between packets.
- The joystick can arrive over WiFi/UDP, which is the least reliable path in the
  system and is not recommended outside bench testing.
- No recorded flight or engagement logs are committed, so results cannot be
  reproduced from this repository alone.

## Roadmap

- Raise the telemetry rate and drop the interface interpolation.
- Move detection fully onto TensorRT on the Pi and measure end-to-end latency
  from frame to aim command.
- Add authentication and TLS to the ground station.
- Replay tooling so recorded engagements can be re-run against new controller
  gains offline.

## License

MIT. See [LICENSE](LICENSE).

Turkish documentation is preserved in [README.tr.md](README.tr.md), and the
subsystems have their own notes under `YKI/`, `esp32_firmware/` and
`control_code/`.
