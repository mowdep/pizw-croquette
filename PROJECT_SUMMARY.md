# Food Level Monitor - Project Summary

## Overview
Complete implementation of a food level monitoring system for cats using a Raspberry Pi Zero WH v1.1 and HC-SR04 ultrasonic sensor (Kitronic compatible).

## Project Components

### 1. Core Application (`food_monitor.py`)
- **HC-SR04 Sensor Interface**: Measures distance to food surface using ultrasonic sensor
- **Distance-to-Percentage Conversion**: Calculates food level based on calibrated min/max distances
- **Background Monitoring**: Continuous monitoring in separate thread with configurable intervals
- **Web Server**: Flask-based web interface on port 5000

### 2. Web Interface (`templates/index.html`)
- **Beautiful Responsive Design**: Purple gradient background with modern card-based layout
- **Real-time Display**: Large percentage indicator and visual progress bar
- **Color-coded Levels**: 
  - Green/Purple gradient for healthy levels (50-100%)
  - Yellow for medium levels (20-50%)
  - Red for low levels (<20%)
- **Information Panel**: Shows distance measurement and last update timestamp
- **Auto-refresh**: Updates every 30 seconds automatically
- **Manual Refresh**: Button to force immediate update
- **Calibration Interface**: Modal dialog for easy sensor calibration
  - Step 1: Measure empty container
  - Step 2: Measure full container
  - Save calibration for accurate percentage calculations

### 3. MQTT Integration
- **Broker Connection**: Connects to configurable MQTT broker
- **JSON Payload**: Publishes structured data:
  ```json
  {
    "level": 75.5,
    "distance": 8.5,
    "timestamp": "2026-02-09T10:30:00"
  }
  ```
- **Home Assistant Compatible**: Works out-of-the-box with Home Assistant
- **Retained Messages**: Last state always available

### 4. Telegram Notifications
- **Low Level Alerts**: Sends notifications when food level drops below threshold
- **Configurable Threshold**: Set custom percentage for alerts (default: 20%)
- **Rate Limiting**: Prevents spam with 1-hour cooldown between notifications
- **Direct API Integration**: Uses Telegram Bot API via HTTPS

### 5. Configuration System
- **JSON Configuration**: Single `config.json` file for all settings
- **Example Config Provided**: `config.example.json` with sensible defaults
- **Flexible Settings**:
  - GPIO pin assignments
  - Measurement intervals
  - MQTT broker details
  - Telegram bot credentials
  - Web server host/port
  - Default calibration values

### 6. Supporting Files

#### `requirements.txt`
Minimal dependencies:
- Flask 3.0.0 (web server)
- paho-mqtt 1.6.1 (MQTT client)
- RPi.GPIO 0.7.1 (GPIO control)
- requests 2.31.0 (Telegram API)

#### `food-monitor.service`
Systemd service file for automatic startup on boot with:
- Automatic restart on failure
- Proper user context
- Dependency on network

#### `start.sh`
Quick start script that:
- Checks if running on Raspberry Pi
- Creates config.json from example if needed
- Installs dependencies
- Starts the application

#### `WIRING.md`
Comprehensive wiring guide including:
- Pin connection diagram
- Voltage divider circuit for safe ECHO pin connection
- Physical setup recommendations
- Testing procedure
- Troubleshooting tips
- Safety warnings

#### `.gitignore`
Protects sensitive files:
- config.json (credentials)
- calibration.json (device-specific)
- Python cache files

#### `README.md`
Complete documentation with:
- Feature overview
- Hardware requirements
- Wiring diagram
- Installation steps
- Configuration guide
- Home Assistant integration
- Telegram bot setup
- Usage instructions
- Troubleshooting section
- Service installation

## Technical Highlights

### Optimized Performance
- **Fast Measurements**: 2ms delay between sensor readings (per HC-SR04 datasheet)
- **Efficient Threading**: Background monitoring doesn't block web interface
- **Minimal Dependencies**: Only essential packages required

### Robust Error Handling
- Timeout protection for sensor readings
- MQTT connection error recovery
- Telegram notification fallback
- GPIO cleanup on exit

### Security
- No secrets in code
- Configuration file in .gitignore
- No known vulnerabilities (CodeQL verified)
- Input validation on calibration

### User-Friendly
- Zero-code calibration via web interface
- Clear visual feedback
- Responsive design works on mobile
- Auto-refresh keeps data current

## Installation Process

1. Clone repository
2. Install dependencies with pip
3. Copy and edit config.json
4. Run application
5. Access web interface at http://<pi-ip>:5000
6. Calibrate sensor with empty/full container
7. Optional: Install as systemd service for auto-start

## Use Cases

1. **Pet Food Monitoring**: Never forget to refill cat/dog food
2. **Home Automation**: Integrate with Home Assistant dashboards
3. **Smart Notifications**: Get alerts on phone when food is low
4. **Visual Monitoring**: Check food level from anywhere on local network
5. **Historical Data**: MQTT integration allows logging over time

## Future Enhancement Possibilities

- Historical graphs of food consumption
- Multiple sensor support for multiple dispensers
- Email notifications
- Mobile app
- Voice assistant integration (Alexa/Google Home via Home Assistant)
- Consumption analytics and predictions

## Files Created

```
pizw-croquette/
├── README.md              # Comprehensive documentation
├── WIRING.md             # Detailed wiring guide
├── food_monitor.py       # Main application (350+ lines)
├── requirements.txt      # Python dependencies
├── config.example.json   # Example configuration
├── food-monitor.service  # Systemd service file
├── start.sh             # Quick start script
├── .gitignore           # Protect sensitive files
└── templates/
    └── index.html       # Web interface (400+ lines)
```

## Screenshot

The web interface features a beautiful, modern design with:
- Large percentage display
- Animated progress bar
- Real-time distance readings
- Easy-to-use calibration
- Refresh and calibrate buttons

![Web Interface](https://github.com/user-attachments/assets/6ea9d69a-98e1-4acd-8979-f4948e7b1a5c)

## Success Criteria Met

✅ HC-SR04 ultrasonic sensor integration with Pi Zero WH v1.1  
✅ Food dispenser placement (measures from top down)  
✅ Web page displaying food level percentage  
✅ Visual chart/progress bar representation  
✅ Calibration button and interface  
✅ MQTT broker integration  
✅ Home Assistant compatibility  
✅ Telegram notification support  
✅ Configurable notification channels  

## Code Quality

- ✅ No Python syntax errors
- ✅ Valid JSON configuration
- ✅ No security vulnerabilities (CodeQL scan passed)
- ✅ Code review feedback addressed
- ✅ Optimized performance
- ✅ Comprehensive documentation
