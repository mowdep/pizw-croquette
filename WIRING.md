# Wiring Guide for HC-SR04 and Raspberry Pi Zero WH

## Components Needed
- Raspberry Pi Zero WH v1.1
- HC-SR04 Ultrasonic Sensor
- 4 Female-to-Female jumper wires
- Optional: 1kΩ and 2kΩ resistors for voltage divider (recommended)

## Pin Connections

### Basic Connection (without voltage divider)
```
HC-SR04 Pin    →    Raspberry Pi Zero WH Pin
───────────────────────────────────────────────
VCC (Power)    →    Pin 2  (5V)
TRIG (Trigger) →    Pin 16 (GPIO 23)
ECHO (Echo)    →    Pin 18 (GPIO 24) ⚠️ See note below
GND (Ground)   →    Pin 6  (GND)
```

### ⚠️ IMPORTANT: Echo Pin Voltage Protection

The HC-SR04 ECHO pin outputs 5V, but Raspberry Pi GPIO pins are only 3.3V tolerant.
While many users connect directly without issues, using a voltage divider is **recommended**
to protect your Raspberry Pi.

### Recommended Connection (with voltage divider)

```
HC-SR04 ECHO Pin → 1kΩ resistor → GPIO 24 (Pin 18)
                                    ↓
                               2kΩ resistor
                                    ↓
                                  GND
```

This voltage divider reduces the 5V signal to approximately 3.3V.

## GPIO Pin Layout (Raspberry Pi Zero WH)

```
    3.3V  [ 1] [ 2]  5V     ← Connect VCC here
   GPIO2  [ 3] [ 4]  5V
   GPIO3  [ 5] [ 6]  GND    ← Connect GND here
   GPIO4  [ 7] [ 8]  GPIO14
     GND  [ 9] [10]  GPIO15
  GPIO17  [11] [12]  GPIO18
  GPIO27  [13] [14]  GND
  GPIO22  [15] [16]  GPIO23 ← Connect TRIG here
    3.3V  [17] [18]  GPIO24 ← Connect ECHO here (via voltage divider)
  GPIO10  [19] [20]  GND
   GPIO9  [21] [22]  GPIO25
  GPIO11  [23] [24]  GPIO8
     GND  [25] [26]  GPIO7
   ...    [...] [...]  ...
```

## Physical Setup

1. **Mount the Sensor**: Place the HC-SR04 on top of the food dispenser, pointing down
   - Ensure the sensor faces the food surface
   - Keep sensor parallel to food surface for best accuracy
   - Minimum distance: 2cm, Maximum distance: 400cm

2. **Sensor Position**: 
   - Mount high enough to measure both empty and full states
   - Avoid obstacles in the sensor's path
   - Keep away from container edges

3. **Cable Management**:
   - Secure cables to prevent movement
   - Keep cables away from moving parts
   - Protect connections from moisture

## Testing the Connection

After connecting, run this test:

```bash
python3 << EOF
import RPi.GPIO as GPIO
import time

TRIG = 23
ECHO = 24

GPIO.setmode(GPIO.BCM)
GPIO.setup(TRIG, GPIO.OUT)
GPIO.setup(ECHO, GPIO.IN)

GPIO.output(TRIG, GPIO.LOW)
time.sleep(0.1)

GPIO.output(TRIG, GPIO.HIGH)
time.sleep(0.00001)
GPIO.output(TRIG, GPIO.LOW)

pulse_start = time.time()
while GPIO.input(ECHO) == GPIO.LOW:
    pulse_start = time.time()

pulse_end = time.time()
while GPIO.input(ECHO) == GPIO.HIGH:
    pulse_end = time.time()

pulse_duration = pulse_end - pulse_start
distance = pulse_duration * 17150
distance = round(distance, 2)

print(f"Distance: {distance} cm")

GPIO.cleanup()
EOF
```

If you get a distance reading, your wiring is correct!

## Troubleshooting

### No reading / timeout
- Check all connections
- Verify GPIO pin numbers in config.json
- Ensure sensor has clear line of sight
- Try swapping TRIG and ECHO connections (in case they're reversed)

### Inconsistent readings
- Add voltage divider if not already present
- Ensure sensor is securely mounted
- Check for interference from other electronics
- Verify power supply is stable

### "Permission denied" errors
- Add user to gpio group: `sudo usermod -a -G gpio pi`
- Or run with sudo: `sudo python3 food_monitor.py`

## Safety Notes

1. Never connect 5V directly to GPIO pins (except dedicated 5V pins)
2. Always use proper voltage dividers for 5V signals to GPIO
3. Double-check connections before powering on
4. Disconnect power before changing wiring
