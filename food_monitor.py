#!/usr/bin/env python3
"""
Food Level Monitor
Monitors food level using HC-SR04 ultrasonic sensor on Raspberry Pi Zero WH
Features: Web interface, MQTT integration, Telegram notifications
"""

import RPi.GPIO as GPIO
import time
import json
import os
import threading
import base64
from flask import Flask, render_template, jsonify, request
import paho.mqtt.client as mqtt
from datetime import datetime
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2

# Configuration
CONFIG_FILE = 'config.json'
CALIBRATION_FILE = 'calibration.json'
CREDENTIALS_FILE = 'credentials.enc'
SALT_FILE = '.salt'

class CredentialManager:
    """Manages encrypted storage of sensitive credentials"""
    
    def __init__(self, salt_file=SALT_FILE, creds_file=CREDENTIALS_FILE):
        self.salt_file = salt_file
        self.creds_file = creds_file
        self._ensure_salt()
    
    def _ensure_salt(self):
        """Create salt file if it doesn't exist"""
        if not os.path.exists(self.salt_file):
            salt = os.urandom(16)
            with open(self.salt_file, 'wb') as f:
                f.write(salt)
            # Set restrictive permissions (owner read/write only)
            os.chmod(self.salt_file, 0o600)
    
    def _get_cipher(self):
        """Get Fernet cipher using device-specific key"""
        # Read salt
        with open(self.salt_file, 'rb') as f:
            salt = f.read()
        
        # Generate key from machine ID (or create one if not available)
        try:
            with open('/etc/machine-id', 'r') as f:
                machine_id = f.read().strip()
        except:
            # Fallback for non-Linux systems or if file doesn't exist
            machine_id = 'default-key-fallback-12345'
        
        # Derive encryption key
        kdf = PBKDF2(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(machine_id.encode()))
        return Fernet(key)
    
    def save_credentials(self, credentials):
        """Encrypt and save credentials"""
        cipher = self._get_cipher()
        encrypted = cipher.encrypt(json.dumps(credentials).encode())
        
        with open(self.creds_file, 'wb') as f:
            f.write(encrypted)
        
        # Set restrictive permissions
        os.chmod(self.creds_file, 0o600)
    
    def load_credentials(self):
        """Load and decrypt credentials"""
        if not os.path.exists(self.creds_file):
            return {}
        
        try:
            cipher = self._get_cipher()
            with open(self.creds_file, 'rb') as f:
                encrypted = f.read()
            
            decrypted = cipher.decrypt(encrypted)
            return json.loads(decrypted.decode())
        except Exception as e:
            print(f"Error loading credentials: {e}")
            return {}

class FoodLevelMonitor:
    def __init__(self, config_file=CONFIG_FILE):
        """Initialize the food level monitor"""
        self.config = self.load_config(config_file)
        self.calibration = self.load_calibration()
        self.credentials = CredentialManager()
        self.current_level = 0
        self.current_distance = 0
        self.mqtt_client = None
        self.last_notification_time = 0
        
        # Load credentials and merge with config
        self._load_credentials_into_config()
        
        # Setup GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.config['sensor']['trigger_pin'], GPIO.OUT)
        GPIO.setup(self.config['sensor']['echo_pin'], GPIO.IN)
        
        # Initialize MQTT if enabled
        if self.config['mqtt']['enabled']:
            self.setup_mqtt()
        
        # Initialize Telegram if enabled
        if self.config['telegram']['enabled']:
            self.setup_telegram()
    
    def _load_credentials_into_config(self):
        """Load encrypted credentials into config"""
        creds = self.credentials.load_credentials()
        
        # Merge MQTT credentials
        if 'mqtt' in creds:
            self.config['mqtt'].update(creds['mqtt'])
        
        # Merge Telegram credentials
        if 'telegram' in creds:
            self.config['telegram'].update(creds['telegram'])
    
    def save_config(self):
        """Save configuration to file (non-sensitive data only)"""
        # Create a copy without sensitive data
        safe_config = json.loads(json.dumps(self.config))
        safe_config['mqtt']['username'] = ''
        safe_config['mqtt']['password'] = ''
        safe_config['telegram']['bot_token'] = ''
        safe_config['telegram']['chat_id'] = ''
        
        with open(CONFIG_FILE, 'w') as f:
            json.dump(safe_config, f, indent=2)
    
    def save_credentials_to_store(self, mqtt_creds=None, telegram_creds=None):
        """Save credentials to encrypted storage"""
        creds = self.credentials.load_credentials()
        
        if mqtt_creds:
            creds['mqtt'] = mqtt_creds
            # Update runtime config
            self.config['mqtt'].update(mqtt_creds)
        
        if telegram_creds:
            creds['telegram'] = telegram_creds
            # Update runtime config
            self.config['telegram'].update(telegram_creds)
        
        self.credentials.save_credentials(creds)
    
    def load_config(self, config_file):
        """Load configuration from JSON file"""
        if not os.path.exists(config_file):
            # Use example config if config.json doesn't exist
            config_file = 'config.example.json'
        
        with open(config_file, 'r') as f:
            return json.load(f)
    
    def load_calibration(self):
        """Load calibration data"""
        if os.path.exists(CALIBRATION_FILE):
            with open(CALIBRATION_FILE, 'r') as f:
                return json.load(f)
        else:
            # Default calibration from config
            return {
                'max_distance_cm': self.config['calibration']['max_distance_cm'],
                'min_distance_cm': self.config['calibration']['min_distance_cm']
            }
    
    def save_calibration(self, min_distance, max_distance):
        """Save calibration data"""
        self.calibration = {
            'max_distance_cm': max_distance,
            'min_distance_cm': min_distance
        }
        with open(CALIBRATION_FILE, 'w') as f:
            json.dump(self.calibration, f, indent=2)
    
    def measure_distance(self):
        """Measure distance using HC-SR04 sensor"""
        try:
            # Ensure trigger is low
            GPIO.output(self.config['sensor']['trigger_pin'], GPIO.LOW)
            time.sleep(0.002)  # 2ms delay as per HC-SR04 datasheet
            
            # Send 10us pulse to trigger
            GPIO.output(self.config['sensor']['trigger_pin'], GPIO.HIGH)
            time.sleep(0.00001)
            GPIO.output(self.config['sensor']['trigger_pin'], GPIO.LOW)
            
            # Wait for echo
            pulse_start = time.time()
            timeout = pulse_start + 0.1  # 100ms timeout
            
            while GPIO.input(self.config['sensor']['echo_pin']) == GPIO.LOW:
                pulse_start = time.time()
                if pulse_start > timeout:
                    return None
            
            pulse_end = time.time()
            timeout = pulse_end + 0.1
            
            while GPIO.input(self.config['sensor']['echo_pin']) == GPIO.HIGH:
                pulse_end = time.time()
                if pulse_end > timeout:
                    return None
            
            # Calculate distance
            pulse_duration = pulse_end - pulse_start
            distance = pulse_duration * 17150  # Speed of sound = 34300 cm/s, divided by 2
            distance = round(distance, 2)
            
            return distance
        except Exception as e:
            print(f"Error measuring distance: {e}")
            return None
    
    def calculate_level_percentage(self, distance):
        """Calculate food level percentage based on calibration"""
        if distance is None:
            return 0
        
        max_dist = self.calibration['max_distance_cm']
        min_dist = self.calibration['min_distance_cm']
        
        # Invert: smaller distance = more food = higher percentage
        if distance <= min_dist:
            return 100
        elif distance >= max_dist:
            return 0
        else:
            percentage = 100 - ((distance - min_dist) / (max_dist - min_dist) * 100)
            return round(percentage, 1)
    
    def setup_mqtt(self):
        """Setup MQTT client"""
        try:
            self.mqtt_client = mqtt.Client()
            
            if self.config['mqtt']['username']:
                self.mqtt_client.username_pw_set(
                    self.config['mqtt']['username'],
                    self.config['mqtt']['password']
                )
            
            self.mqtt_client.connect(
                self.config['mqtt']['broker'],
                self.config['mqtt']['port'],
                60
            )
            self.mqtt_client.loop_start()
            print("MQTT client connected")
        except Exception as e:
            print(f"Error setting up MQTT: {e}")
            self.mqtt_client = None
    
    def publish_mqtt(self, level, distance):
        """Publish data to MQTT broker"""
        if self.mqtt_client:
            try:
                payload = {
                    'level': level,
                    'distance': distance,
                    'timestamp': datetime.now().isoformat()
                }
                self.mqtt_client.publish(
                    self.config['mqtt']['topic'],
                    json.dumps(payload),
                    retain=True
                )
            except Exception as e:
                print(f"Error publishing to MQTT: {e}")
    
    def setup_telegram(self):
        """Setup Telegram bot"""
        # Telegram notifications use direct API via requests
        # No initialization needed
        if self.config['telegram']['enabled'] and self.config['telegram']['bot_token']:
            print("Telegram notifications enabled")
        else:
            print("Telegram notifications disabled")
    
    def send_telegram_notification(self, message):
        """Send notification via Telegram"""
        if self.config['telegram']['enabled']:
            try:
                import requests
                url = f"https://api.telegram.org/bot{self.config['telegram']['bot_token']}/sendMessage"
                data = {
                    'chat_id': self.config['telegram']['chat_id'],
                    'text': message
                }
                requests.post(url, data=data, timeout=10)
            except Exception as e:
                print(f"Error sending Telegram notification: {e}")
    
    def check_and_notify(self, level):
        """Check if notification should be sent"""
        if not self.config['telegram']['enabled']:
            return
        
        threshold = self.config['telegram']['low_level_threshold']
        current_time = time.time()
        
        # Send notification if level is low and at least 1 hour has passed since last notification
        if level < threshold and (current_time - self.last_notification_time) > 3600:
            message = f"⚠️ Food level is low: {level}%\nPlease refill the dispenser."
            self.send_telegram_notification(message)
            self.last_notification_time = current_time
    
    def update_reading(self):
        """Take a reading and update current values"""
        distance = self.measure_distance()
        if distance is not None:
            self.current_distance = distance
            self.current_level = self.calculate_level_percentage(distance)
            
            # Publish to MQTT
            if self.config['mqtt']['enabled']:
                self.publish_mqtt(self.current_level, self.current_distance)
            
            # Check for notifications
            self.check_and_notify(self.current_level)
        
        return self.current_level, self.current_distance
    
    def cleanup(self):
        """Cleanup GPIO and connections"""
        GPIO.cleanup()
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

# Flask Web Application
app = Flask(__name__)
monitor = None

@app.route('/')
def index():
    """Serve the main web page"""
    return render_template('index.html')

@app.route('/api/level')
def get_level():
    """API endpoint to get current food level"""
    level, distance = monitor.update_reading()
    return jsonify({
        'level': level,
        'distance': distance,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/calibrate', methods=['POST'])
def calibrate():
    """API endpoint to calibrate sensor"""
    data = request.json
    action = data.get('action')
    
    if action == 'measure':
        # Take measurement for calibration
        distance = monitor.measure_distance()
        return jsonify({'distance': distance})
    
    elif action == 'save':
        # Save calibration values
        min_distance = data.get('min_distance')
        max_distance = data.get('max_distance')
        monitor.save_calibration(min_distance, max_distance)
        return jsonify({'success': True})
    
    return jsonify({'error': 'Invalid action'}), 400

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """API endpoint to get current settings (without sensitive data)"""
    settings = {
        'mqtt': {
            'enabled': monitor.config['mqtt']['enabled'],
            'broker': monitor.config['mqtt']['broker'],
            'port': monitor.config['mqtt']['port'],
            'username': monitor.config['mqtt']['username'],
            'topic': monitor.config['mqtt']['topic'],
            'has_password': bool(monitor.config['mqtt']['password'])
        },
        'telegram': {
            'enabled': monitor.config['telegram']['enabled'],
            'chat_id': monitor.config['telegram']['chat_id'],
            'low_level_threshold': monitor.config['telegram']['low_level_threshold'],
            'has_bot_token': bool(monitor.config['telegram']['bot_token'])
        },
        'sensor': monitor.config['sensor']
    }
    return jsonify(settings)

@app.route('/api/settings/mqtt', methods=['POST'])
def update_mqtt_settings():
    """API endpoint to update MQTT settings"""
    try:
        data = request.json
        
        # Update config
        monitor.config['mqtt']['enabled'] = data.get('enabled', False)
        monitor.config['mqtt']['broker'] = data.get('broker', 'localhost')
        monitor.config['mqtt']['port'] = int(data.get('port', 1883))
        monitor.config['mqtt']['topic'] = data.get('topic', 'home/food_dispenser/level')
        
        # Handle credentials separately
        mqtt_creds = {}
        if 'username' in data:
            mqtt_creds['username'] = data['username']
            monitor.config['mqtt']['username'] = data['username']
        if 'password' in data and data['password']:  # Only update if provided
            mqtt_creds['password'] = data['password']
            monitor.config['mqtt']['password'] = data['password']
        
        # Save credentials to encrypted storage
        if mqtt_creds:
            monitor.save_credentials_to_store(mqtt_creds=mqtt_creds)
        
        # Save non-sensitive config
        monitor.save_config()
        
        # Reconnect MQTT with new settings
        if monitor.mqtt_client:
            monitor.mqtt_client.loop_stop()
            monitor.mqtt_client.disconnect()
            monitor.mqtt_client = None
        
        if monitor.config['mqtt']['enabled']:
            monitor.setup_mqtt()
        
        return jsonify({'success': True, 'message': 'MQTT settings updated'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/settings/telegram', methods=['POST'])
def update_telegram_settings():
    """API endpoint to update Telegram settings"""
    try:
        data = request.json
        
        # Update config
        monitor.config['telegram']['enabled'] = data.get('enabled', False)
        monitor.config['telegram']['low_level_threshold'] = int(data.get('low_level_threshold', 20))
        
        # Handle credentials separately
        telegram_creds = {}
        if 'bot_token' in data and data['bot_token']:  # Only update if provided
            telegram_creds['bot_token'] = data['bot_token']
            monitor.config['telegram']['bot_token'] = data['bot_token']
        if 'chat_id' in data:
            telegram_creds['chat_id'] = data['chat_id']
            monitor.config['telegram']['chat_id'] = data['chat_id']
        
        # Save credentials to encrypted storage
        if telegram_creds:
            monitor.save_credentials_to_store(telegram_creds=telegram_creds)
        
        # Save non-sensitive config
        monitor.save_config()
        
        # Reinitialize Telegram with new settings
        if monitor.config['telegram']['enabled']:
            monitor.setup_telegram()
        
        return jsonify({'success': True, 'message': 'Telegram settings updated'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/settings/test/mqtt', methods=['POST'])
def test_mqtt():
    """Test MQTT connection"""
    try:
        data = request.json
        test_client = mqtt.Client()
        
        if data.get('username'):
            test_client.username_pw_set(data['username'], data.get('password', ''))
        
        test_client.connect(data['broker'], int(data['port']), 10)
        test_client.loop_start()
        time.sleep(1)
        test_client.loop_stop()
        test_client.disconnect()
        
        return jsonify({'success': True, 'message': 'MQTT connection successful'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/settings/test/telegram', methods=['POST'])
def test_telegram():
    """Test Telegram bot"""
    try:
        data = request.json
        import requests
        
        url = f"https://api.telegram.org/bot{data['bot_token']}/getMe"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            bot_info = response.json()
            if bot_info.get('ok'):
                return jsonify({
                    'success': True,
                    'message': f"Bot verified: @{bot_info['result']['username']}"
                })
        
        return jsonify({'success': False, 'error': 'Invalid bot token'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

def monitoring_loop():
    """Background thread for continuous monitoring"""
    while True:
        try:
            monitor.update_reading()
            time.sleep(monitor.config['sensor']['measurement_interval'])
        except Exception as e:
            print(f"Error in monitoring loop: {e}")
            time.sleep(5)

def main():
    """Main application entry point"""
    global monitor
    
    try:
        # Initialize monitor
        monitor = FoodLevelMonitor()
        
        # Start monitoring thread
        monitoring_thread = threading.Thread(target=monitoring_loop, daemon=True)
        monitoring_thread.start()
        
        # Start web server
        print(f"Starting web server on {monitor.config['web']['host']}:{monitor.config['web']['port']}")
        app.run(
            host=monitor.config['web']['host'],
            port=monitor.config['web']['port'],
            debug=False
        )
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        if monitor:
            monitor.cleanup()

if __name__ == '__main__':
    main()
