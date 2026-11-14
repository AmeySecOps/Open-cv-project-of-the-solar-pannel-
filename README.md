# SolarGuard AI – Intelligent Solar Panel Dust Detection and Automatic Alert System

![SolarGuard AI System](https://img.shields.io/badge/System-SolarGuard%20AI-06d6a0?style=for-the-badge)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge)
![OpenCV](https://img.shields.io/badge/Computer%20Vision-OpenCV%205.0-red?style=for-the-badge)
![ESP32](https://img.shields.io/badge/Hardware-ESP32%20DevKit-orange?style=for-the-badge)
![Flask](https://img.shields.io/badge/Framework-Flask%20REST-lightgrey?style=for-the-badge)

**SolarGuard AI** is a production-grade, end-to-end industrial IoT and computer vision monitoring system designed to detect dust and soiling accumulation on photovoltaic (PV) solar panels. 

When soiling is detected, the Python OpenCV engine calculates a multi-metric visual soiling indicator ($0.0 - 100.0\%$), debounces the state transitions, transmits HTTP alert commands over Wi-Fi to an ESP32 microcontroller to turn **ON the RED Alert LED** (GPIO 25), and updates a dark-navy industrial web telemetry dashboard in real time. When the panel is clean, the system turns **ON the GREEN LED** (GPIO 26) and clears the alert.

---

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [Hardware Requirements & Pinout](#2-hardware-requirements--pinout)
3. [Software Technology Stack](#3-software-technology-stack)
4. [Computer Vision Dust Detection Engine](#4-computer-vision-dust-detection-engine)
5. [ESP32 Firmware Installation & Wi-Fi Setup](#5-esp32-firmware-installation--wi-fi-setup)
6. [Python Backend Installation & Setup](#6-python-backend-installation--setup)
7. [Running the Application (Windows Quick Start)](#7-running-the-application-windows-quick-start)
8. [Dashboard Walkthrough & Operations](#8-dashboard-walkthrough--operations)
9. [Automated Testing & Hardware Simulation Mode](#9-automated-testing--hardware-simulation-mode)
10. [REST API Documentation](#10-rest-api-documentation)
11. [Troubleshooting Guide](#11-troubleshooting-guide)

---

## 1. System Architecture

```
+------------------------------------------------------------------------------------+
|                                SOLARGUARD AI ARCHITECTURE                          |
+------------------------------------------------------------------------------------+

     +-----------------------+                +-------------------------+
     |   USB Video Webcam    |                |    Physical PV Panel    |
     | (Targeted at Solar PV)|                | (Clean vs Soiled State) |
     +-----------+-----------+                +------------+------------+
                 |                                         |
                 +-------------------+---------------------+
                                     |
                                     v
                 +-----------------------------------------+
                 |       Python OpenCV Vision Engine       |
                 | - Dual Color Spaces (Grayscale + HSV)   |
                 | - Illumination / Sunlight Normalization |
                 | - Structural Similarity Index (SSIM)    |
                 | - High-Frequency Laplacian Texture Loss |
                 | - Local Dynamic Range & Contrast Loss   |
                 | - Multi-metric Calibrated Soiling Score |
                 +-------------------+---------------------+
                                     |
                                     v
                 +-----------------------------------------+
                 |        Monitoring & Debounce Engine     |
                 | - N-Consecutive Frame State Filter      |
                 | - Transient Shadow Rejection Guard      |
                 | - Redundant Command Suppression Guard   |
                 +-------------------+---------------------+
                                     |
                   +-----------------+-----------------+
                   |                                   |
         Wi-Fi HTTP REST (Port 80)                     |
                   |                                   |
                   v                                   v
+------------------------------------+   +------------------------------------+
|        ESP32 DevKit Node           |   |     Flask Real-Time Dashboard      |
| - WebServer on Port 80             |   | - Live MJPEG Video Stream with HUD |
| - GPIO 25: RED LED (Dust Alert)    |   | - Chart.js Soiling Trends & Stats  |
| - GPIO 26: GREEN LED (Panel Clean) |   | - Real-time ESP32 Ping & Latency   |
| - Safe Hardware Failover           |   | - Clean Reference Capture & Upload |
+------------------------------------+   | - SQLite Telemetry Database        |
                                         +------------------------------------+
```

---

## 2. Hardware Requirements & Pinout

### Required Components:
1. **ESP32 DevKit Development Board** (ESP32-WROOM-32 or NodeMCU-32S).
2. **USB Webcam** connected to the computer host.
3. **Solar Panel** (test cell or full module mounted in a fixed position).
4. **Red LED** (Indicates DUST DETECTED).
5. **Green LED** (Indicates PANEL CLEAN).
6. **2x 220Ω Resistors** (current limiting for LEDs).
7. **Breadboard & Jumper Wires**.
8. **Wi-Fi Network** (2.4 GHz) accessible by both the computer and ESP32.

### Wiring Schematic:
| ESP32 Pin | Component | Series Resistor | Function |
| :--- | :--- | :--- | :--- |
| **GPIO 25** | Red LED Anode (+) | 220Ω | Dust Alert (HIGH = ON) |
| **GPIO 26** | Green LED Anode (+) | 220Ω | Clean Indicator (HIGH = ON) |
| **GND** | Both LED Cathodes (-) | Direct | Common Ground |

> **Note**: Standard ESP32 boards support only 2.4 GHz Wi-Fi networks. Ensure your router or hotspot broadcasts on 2.4 GHz.

---

## 3. Software Technology Stack

* **Backend**: Python 3.10+, OpenCV (`cv2`), NumPy, Flask, Requests, SQLite3, Threading.
* **Frontend**: Modern HTML5, Responsive Dark Navy CSS3, Vanilla JavaScript (ES6+), Chart.js 4.x.
* **Microcontroller**: ESP32 C++ (Arduino Core), `WiFi.h`, `WebServer.h`.
* **Testing**: Python `unittest` suite (includes hardware simulation mocks).

---

## 4. Computer Vision Dust Detection Engine

The detection engine in `backend/dust_detector.py` does **not** rely on naive brightness comparisons, which fail under changing outdoor daylight or shadows. Instead, it utilizes a multi-metric computer vision pipeline:

1. **Region of Interest (ROI) Isolation**: Focuses processing solely on the solar cell active area, excluding background clutter.
2. **Standardized Spatial Scaling**: Normalizes live frames and reference images to matching analysis dimensions ($480 \times 360$).
3. **Dual Color-Space Projection**: Converts to Grayscale and HSV simultaneously.
4. **Illumination Normalization**: Aligns baseline mean luminance between live and clean reference frames, preventing false alarms when daylight dims or clouds pass.
5. **Gaussian Spatial Filtering**: Minimizes sensor noise while preserving busbar geometry.
6. **Structural Similarity Index (SSIM)**: Compares structural correlation $1.0 - \text{SSIM}$.
7. **High-Frequency Texture & Edge Energy Loss**: Clean solar panels feature sharp wafer busbars and gridlines. Dust acts as an optical diffuser, causing high-frequency edge attenuation computed via Laplacian variance:
   $$\text{Texture Loss} = 1.0 - \frac{\text{Var}(\nabla^2 I_{live})}{\text{Var}(\nabla^2 I_{ref})}$$
8. **HSV Saturation Attenuation**: Clean crystalline cells display deep blue/black saturation. Airborne dust (silica/sand/dirt) forms a matte layer that lowers saturation.
9. **Visual Soiling Index ($0 - 100\%$)**: Weighted multi-factor score:
   $$S = 125 \times (0.40 \cdot D_{ssim} + 0.30 \cdot D_{texture} + 0.20 \cdot \Delta S + 0.10 \cdot D_{contrast})$$
10. **Temporal Smoothing**: Requires $N$ consecutive matching scans before triggering an ESP32 alert state change, preventing oscillation on borderline values.

---

## 5. ESP32 Firmware Installation & Wi-Fi Setup

1. Open the Arduino IDE.
2. Ensure the ESP32 board package is installed:
   * **File > Preferences > Additional Boards Manager URLs**:
     `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
   * Open **Tools > Board > Boards Manager**, search for `esp32`, and install.
3. Open `firmware/solarguard_esp32.ino`.
4. In lines 30-31, configure your Wi-Fi credentials:
   ```cpp
   const char* WIFI_SSID     = "YOUR_WIFI_SSID";
   const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
   ```
5. Connect your ESP32 via USB. Select your COM port under **Tools > Port** and board model **ESP32 Dev Module**.
6. Click **Upload**.
7. Open the **Serial Monitor** at **115200 baud**.
8. After booting, the ESP32 performs a diagnostic LED test and prints its assigned IP address:
   ```
   ==============================================
     SOLARGUARD AI - ESP32 WI-FI NODE FIRMWARE  
   ==============================================
   [Wi-Fi] Connection Established Successfully!
   [Wi-Fi] Assigned IP Address: 192.168.1.150
   ```
9. Note down this IP address.

---

## 6. Python Backend Installation & Setup

### Prerequisites
* Python 3.10 or higher installed.
* pip package manager.

### Step-by-Step Setup:
```bash
# 1. Open a terminal in the project directory
cd "d:\solar project opencv"

# 2. (Recommended) Create and activate a Python virtual environment
python -m venv .venv

# On Windows:
.venv\Scripts\activate

# On Linux/macOS:
source .venv/bin/activate

# 3. Install required dependencies
pip install -r requirements.txt
```

---

## 7. Running the Application (Windows Quick Start)

### Option A: One-Click Startup Script (Windows)
Double-click `start.bat` in the project root directory, or run from PowerShell/CMD:
```bat
start.bat
```
This script automatically checks Python, verifies dependencies, opens your default web browser to `http://localhost:5000`, and launches the monitoring server.

### Option B: Manual Command Line
```bash
python -m backend.app
```
Then navigate to: **`http://localhost:5000`** in your browser.

---

## 8. Dashboard Walkthrough & Operations

1. **ESP32 Connectivity**:
   * Locate the **ESP32 Wi-Fi Node Controller** card on the right column.
   * Enter your ESP32's IP address (e.g., `192.168.1.150`) into the input box and click **Ping / Connect**.
   * The status badge turns from `DISCONNECTED` (crimson) to `CONNECTED` (green) with real-time round-trip latency (e.g., `12 ms`).
   * Test LED hardware anytime using the **ON / OFF** buttons beneath the Red and Green LED visual indicators.
2. **Camera Management & Mobile Phone Support**:
   * **USB Webcam**: Select from camera index dropdown (0, 1, 2).
   * **Mobile Phone (Android IP Webcam - No DroidCam Required)**:
     * Install the free **IP Webcam** app (by Pavel Khlebovich) on your mobile phone from the Google Play Store.
     * Connect your phone and PC to the same Wi-Fi network (or computer connected to phone's Wi-Fi hotspot).
     * Open IP Webcam on your phone, scroll to the bottom, and tap **Start server**.
     * Note the IP address displayed on your phone screen (e.g., `http://192.168.1.100:8080`).
     * On the SolarGuard AI dashboard, click **Mobile IP Cam**, enter your phone IP or URL, and click **Connect Phone**.
     * Control phone camera features directly from the web dashboard:
       * 🔦 **Torch (Flashlight)**: Turn the phone's LED on/off for dimly lit panels.
       * 🔄 **Flip Camera**: Toggle between front-facing and rear cameras.
       * 🎯 **Autofocus**: Trigger phone autofocus.
   * **Virtual Test Generator**: Built-in synthetic solar panel with dynamic dust simulation if physical camera is detached.
3. **Capturing Clean Reference Image**:
   * Mount the camera facing your clean solar panel.
   * Click **Capture Current Frame** under the *Clean Reference Image* panel.
   * The reference image is immediately saved to `reference_images/clean_reference.jpg` and will persist across restarts.
4. **Automated Monitoring**:
   * Click **Start Monitoring**.
   * The system evaluates frames continuously.
   * When dust accumulates or simulated dust is applied:
     * Condition changes to **DUST DETECTED (HEAVY)**.
     * The Python backend dispatches an HTTP request to `http://<esp32-ip>/led/on`.
     * The ESP32 illuminates the **Red LED** and turns off the Green LED.
   * When cleaned:
     * Condition reverts to **PANEL CLEAN**.
     * Python dispatches `http://<esp32-ip>/led/off`.
     * The ESP32 illuminates the **Green LED** and turns off the Red LED.
5. **Threshold Calibration**:
   * Click **Calibration** in the top header.
   * Adjust the Clean Threshold (default 22%) and Heavily Dusty Threshold (default 48%) sliders.
   * Click **Save Calibration**.

---

## 9. Automated Testing & Hardware Simulation Mode

### Running the Test Suite
The project comes with a comprehensive test suite verifying the CV engine, illumination invariance, ESP32 controller, and REST APIs without requiring physical hardware:

```bash
python -m unittest discover tests
```

### Virtual Hardware Simulation Mode
If you do not have a webcam or ESP32 connected right now, SolarGuard AI includes an integrated **Virtual Test Generator**:
1. Open the dashboard at `http://localhost:5000`.
2. Notice the yellow **Virtual Test Mode** banner at the top of the screen.
3. Drag the **Simulated Dust Slider** from `0%` to `80%`.
4. Observe the live video feed: realistic dust particles and optical blur are blended onto the solar cell in real time.
5. The OpenCV detector analyzes the synthetic frame, calculates the soiling score, updates the trend chart, logs to SQLite, and commands the ESP32.

---

## 10. REST API Documentation

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/status` | Top-level system telemetry (camera, monitoring, ESP32, latest scan). |
| `GET` | `/video_feed` | Continuous MJPEG stream with OpenCV HUD telemetry. |
| `GET` | `/api/camera/devices` | Enumerate connected USB video capture hardware & Mobile IP Webcam. |
| `POST` | `/api/camera/start` | Start camera frame capture thread (supports USB index or stream URL). |
| `POST` | `/api/camera/stop` | Stop camera capture and release device. |
| `POST` | `/api/camera/select` | Select USB index, Virtual mode (-1), or Mobile IP Webcam URL. |
| `POST` | `/api/camera/ip-webcam/connect` | Connect to Android IP Webcam stream (`{"url":"..."}` or `{"ip":"...","port":8080}`). |
| `POST` | `/api/camera/ip-webcam/test` | Probe mobile IP Webcam connectivity & query battery level. |
| `POST` | `/api/camera/ip-webcam/control` | Control mobile phone hardware (`torch_toggle`, `camera_flip`, `focus`). |
| `POST` | `/api/reference/capture` | Capture and save current live frame as clean reference. |
| `POST` | `/api/reference/upload` | Upload a custom image file as clean reference. |
| `GET` | `/api/reference/view` | Fetch current reference image base64 or raw JPEG file. |
| `POST` | `/api/detection/start` | Start automated background continuous monitoring. |
| `POST` | `/api/detection/stop` | Stop continuous monitoring service. |
| `POST` | `/api/detection/scan` | Trigger an instantaneous one-shot scan. |
| `GET` | `/api/detection/latest` | Retrieve latest detection metrics and condition. |
| `GET` | `/api/detection/history` | Paginated SQLite history of scans. |
| `GET` | `/api/detection/stats` | Aggregated statistics for Chart.js analytics. |
| `GET` | `/api/esp32/status` | ESP32 connectivity, latency, and current LED states. |
| `POST` | `/api/esp32/connect` | Set target ESP32 IP address and test ping. |
| `POST` | `/api/esp32/test-led` | Manually command Red or Green LED (`{"led":"red","state":true}`). |
| `POST` | `/api/settings/threshold` | Update classification thresholds (`{"clean":22.0,"heavy":48.0}`). |
| `GET` | `/api/logs` | Real-time system activity logs. |

---

## 11. Troubleshooting Guide

### 1. Camera Not Opening / Mobile IP Webcam Connection
* **Mobile IP Webcam**:
  * Ensure both your phone and PC are connected to the **same Wi-Fi network** (or connect your PC to your phone's personal hotspot).
  * In the Android **IP Webcam** app, scroll down and verify **Start server** is running.
  * Test ping using the **Test Ping** button in the dashboard.
  * If the video stream pauses when the phone screen turns off, set the phone screen timeout to "Never" or keep IP Webcam in the foreground.
* **USB Webcams**:
  * Ensure other applications (Zoom, Teams, Windows Camera App) are not locking the device.
  * In the dashboard, switch between camera indices (0, 1, 2) in the dropdown.
* If no physical camera is available, toggle **Simulation Mode** in Calibration settings to use the built-in synthetic solar test generator.

### 2. ESP32 Connection Offline / Refused
* Verify both your computer and ESP32 are connected to the **same Wi-Fi network**.
* Check the Serial Monitor in Arduino IDE (115200 baud) to confirm the IP address.
* Make sure your router does not have "Client Isolation" or "Guest Mode" enabled, which blocks local device-to-device communication.
* Verify the Red LED is wired to GPIO 25 and Green LED to GPIO 26 with 220Ω series resistors to GND.

### 3. False Positives from Sunlight or Shadows
* SolarGuard AI includes an illumination normalization pre-processor. However, for best results, ensure the camera is mounted firmly and the Region of Interest (ROI) is positioned squarely on the active solar cells.
* Click **Capture Current Frame** when the panel is clean under typical ambient daylight to establish a fresh baseline.
* Fine-tune the thresholds in the **Calibration** modal if local dust characteristics differ.

---

## License & Credits
Developed for industrial solar installations, research labs, and IoT monitoring applications. Built with Python, OpenCV, and ESP32.
