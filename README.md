# pizw-croquette 🐱
Low food detector for my cats based on Raspberry Pi Zero WH and HC-SR04 Ultrasonic Sensor

## Features

- 📊 **Web Interface**: Beautiful, responsive web dashboard displaying food level percentage with visual progress bar
- 🔧 **Easy Calibration**: Simple web-based calibration for empty and full container measurements
- 📡 **MQTT Integration**: Publishes food level data to MQTT broker for Home Assistant integration
- 📱 **Telegram Notifications**: Sends alerts when food level is low (configurable threshold)
- 🔄 **Auto Refresh**: Real-time monitoring with automatic updates
- 🎯 **Accurate Measurements**: Uses HC-SR04 ultrasonic sensor (Kitronic compatible)

## Hardware Requirements

- Raspberry Pi Zero WH v1.1
- HC-SR04 Ultrasonic Sensor (Kitronic)
- Food dispenser/container
- Jumper wires

## Wiring Diagram

Connect the HC-SR04 sensor to the Raspberry Pi:

```
HC-SR04          Raspberry Pi Zero WH
VCC       --->   5V (Pin 2)
TRIG      --->   GPIO 23 (Pin 16)
ECHO      --->   GPIO 24 (Pin 18)
GND       --->   Ground (Pin 6)
```

**Important**: The ECHO pin outputs 5V, but Raspberry Pi GPIO pins are 3.3V tolerant. Consider using a voltage divider (1kΩ and 2kΩ resistors) to protect the Pi.

## Installation

1. **Clone the repository**:
   ```bash
   cd ~
   git clone https://github.com/mowdep/pizw-croquette.git
   cd pizw-croquette
   ```

2. **Install dependencies**:
   ```bash
   sudo apt-get update
   sudo apt-get install python3-pip python3-rpi.gpio
   pip3 install -r requirements.txt
   ```

3. **Create configuration file**:
   ```bash
   cp config.example.json config.json
   nano config.json
   ```

4. **Edit the configuration** (see Configuration section below)

5. **Test the application**:
   ```bash
   python3 food_monitor.py
   ```

6. **Access the web interface**:
   Open your browser and navigate to `http://<raspberry-pi-ip>:5000`

## Configuration

Edit `config.json` to customize your setup:

```json
{
  "sensor": {
    "trigger_pin": 23,        // GPIO pin for trigger
    "echo_pin": 24,           // GPIO pin for echo
    "measurement_interval": 60 // Seconds between measurements
  },
  "calibration": {
    "max_distance_cm": 30,    // Distance when empty (default)
    "min_distance_cm": 5      // Distance when full (default)
  },
  "mqtt": {
    "enabled": true,
    "broker": "localhost",    // MQTT broker address
    "port": 1883,
    "username": "",           // Optional
    "password": "",           // Optional
    "topic": "home/food_dispenser/level"
  },
  "telegram": {
    "enabled": false,
    "bot_token": "YOUR_BOT_TOKEN",
    "chat_id": "YOUR_CHAT_ID",
    "low_level_threshold": 20 // Percentage threshold for alerts
  },
  "web": {
    "host": "0.0.0.0",
    "port": 5000
  }
}
```

### MQTT Configuration

The application publishes JSON data to the configured MQTT topic:

```json
{
  "level": 85.5,
  "distance": 7.3,
  "timestamp": "2026-02-09T10:30:00"
}
```

### Home Assistant Integration

Add to your `configuration.yaml`:

```yaml
mqtt:
  sensor:
    - name: "Cat Food Level"
      state_topic: "home/food_dispenser/level"
      unit_of_measurement: "%"
      value_template: "{{ value_json.level }}"
      icon: mdi:food-drumstick
    
    - name: "Cat Food Distance"
      state_topic: "home/food_dispenser/level"
      unit_of_measurement: "cm"
      value_template: "{{ value_json.distance }}"
```

### Telegram Bot Setup

1. Create a bot using [@BotFather](https://t.me/botfather)
2. Get your bot token
3. Get your chat ID:
   - Send a message to your bot
   - Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
   - Find your chat ID in the response
4. Update `config.json` with your bot token and chat ID
5. Set `enabled: true` in the telegram section

## Running as a Service

To run the application automatically on boot:

1. **Copy the service file**:
   ```bash
   sudo cp food-monitor.service /etc/systemd/system/
   ```

2. **Edit the service file if needed** (adjust paths and user):
   ```bash
   sudo nano /etc/systemd/system/food-monitor.service
   ```

3. **Enable and start the service**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable food-monitor.service
   sudo systemctl start food-monitor.service
   ```

4. **Check status**:
   ```bash
   sudo systemctl status food-monitor.service
   ```

5. **View logs**:
   ```bash
   sudo journalctl -u food-monitor.service -f
   ```

## Usage

### Web Interface

1. Navigate to `http://<raspberry-pi-ip>:5000`
2. View the current food level percentage and distance
3. Click **Refresh** to manually update the reading
4. Click **Calibrate** to set up the sensor for your container

### Calibration Process

1. Click the **Calibrate** button
2. **Step 1**: Empty the food container completely, then click "Measure Empty"
3. **Step 2**: Fill the food container completely, then click "Measure Full"
4. Click **Save** to store the calibration

The system will now calculate food level percentage based on these measurements.

## Troubleshooting

### Sensor not reading properly
- Check wiring connections
- Verify GPIO pins in config.json
- Ensure sensor has clear line of sight
- Make sure there are no obstructions

### Web interface not accessible
- Check if service is running: `sudo systemctl status food-monitor.service`
- Verify firewall settings
- Try accessing locally: `curl http://localhost:5000`

### MQTT not connecting
- Verify broker address and credentials
- Check if mosquitto is running: `sudo systemctl status mosquitto`
- Test connection: `mosquitto_pub -h localhost -t test -m "hello"`

### Telegram notifications not working
- Verify bot token and chat ID
- Check internet connectivity
- Test bot manually using the Telegram API

## Files Structure

```
pizw-croquette/
├── food_monitor.py           # Main application
├── templates/
│   └── index.html           # Web interface
├── requirements.txt         # Python dependencies
├── config.example.json      # Example configuration
├── config.json             # Your configuration (gitignored)
├── calibration.json        # Calibration data (gitignored)
├── food-monitor.service    # Systemd service file
├── .gitignore
└── README.md
```

## Contributing

Feel free to open issues or submit pull requests for improvements!

## License

MIT License - Feel free to use and modify for your needs.

## Author

Created for monitoring cat food levels with love! 🐱💕
