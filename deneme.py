import pygame, serial, time

ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=0)  # Windows'ta 'COM3'
time.sleep(2)   # Arduino resetini bekle

pygame.init(); pygame.joystick.init()
js = pygame.joystick.Joystick(0); js.init()

DEADZONE = 0.10
son_gonderim = (None, None)

try:
    while True:
        pygame.event.pump()

        e1 = js.get_axis(0)          # sol çubuk yatay
        e2 = -js.get_axis(1)         # sol çubuk dikey (yukarı = pozitif olsun)

        e1 = 0.0 if abs(e1) < DEADZONE else e1
        e2 = 0.0 if abs(e2) < DEADZONE else e2

        paket = (round(e1, 2), round(e2, 2))
        if paket != son_gonderim:                    # sadece değişince gönder
            ser.write(f"{paket[0]:.2f},{paket[1]:.2f}\n".encode())
            son_gonderim = paket

        time.sleep(0.02)             # 50 Hz yeterli

except KeyboardInterrupt:
    ser.write(b"0.00,0.00\n")        # çıkarken motorları durdur
    ser.close()