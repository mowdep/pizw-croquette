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
from flask import Flask, render_template, jsonify, request
import paho.mqtt.client as mqtt
from datetime import datetime

# Configuration
CONFIG_FILE = 'config.json'
CALIBRATION_FILE = 'calibration.json'

class FoodLevelMonitor:
    def __init__(self, config_file=CONFIG_FILE):
        """Initialize the food level monitor"""
        self.config = self.load_config(config_file)
        self.calibration = self.load_calibration()
        self.current_level = 0
        self.current_distance = 0
        self.mqtt_client = None
        self.telegram_bot = None
        self.last_notification_time = 0
        
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
            time.sleep(0.1)
            
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
        try:
            from telegram import Bot
            self.telegram_bot = Bot(token=self.config['telegram']['bot_token'])
            print("Telegram bot initialized")
        except Exception as e:
            print(f"Error setting up Telegram: {e}")
            self.telegram_bot = None
    
    def send_telegram_notification(self, message):
        """Send notification via Telegram"""
        if self.telegram_bot:
            try:
                import asyncio
                asyncio.run(self.telegram_bot.send_message(
                    chat_id=self.config['telegram']['chat_id'],
                    text=message
                ))
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
