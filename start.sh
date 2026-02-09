#!/bin/bash
# Quick start script for Food Level Monitor

echo "================================"
echo "Food Level Monitor - Quick Start"
echo "================================"
echo ""

# Check if running on Raspberry Pi
if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    echo "⚠️  Warning: This doesn't appear to be a Raspberry Pi"
    echo "   The GPIO functionality may not work."
    echo ""
fi

# Check if config.json exists
if [ ! -f "config.json" ]; then
    echo "📝 Creating config.json from example..."
    cp config.example.json config.json
    echo "✅ config.json created"
    echo ""
    echo "⚙️  Please edit config.json with your settings:"
    echo "   - MQTT broker address (if using)"
    echo "   - Telegram bot token and chat ID (if using)"
    echo "   - GPIO pins (if different from default)"
    echo ""
    read -p "Press Enter to continue or Ctrl+C to exit and edit config.json..."
fi

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed"
    exit 1
fi

# Check if pip is installed
if ! command -v pip3 &> /dev/null; then
    echo "📦 Installing pip3..."
    sudo apt-get update
    sudo apt-get install -y python3-pip
fi

# Check if RPi.GPIO is installed
if ! python3 -c "import RPi.GPIO" 2>/dev/null; then
    echo "📦 Installing RPi.GPIO..."
    sudo apt-get install -y python3-rpi.gpio
fi

# Install requirements
echo "📦 Installing Python dependencies..."
pip3 install -r requirements.txt --quiet

echo ""
echo "✅ Setup complete!"
echo ""
echo "🚀 Starting Food Level Monitor..."
echo "   Access the web interface at: http://$(hostname -I | awk '{print $1}'):5000"
echo ""
echo "Press Ctrl+C to stop the application"
echo ""

# Run the application
python3 food_monitor.py
