/*
 ==============================================================================
  PROJECT: SolarGuard AI - Intelligent Solar Panel Dust Detection System
  FIRMWARE: solarguard_esp32.ino
  TARGET: ESP32 DevKit V1 / NodeMCU-32S
  
  HARDWARE CONFIGURATION:
   - Servo Motor: GPIO 18 (PWM Signal / Orange or Yellow wire)
                  VCC -> 5V / VIN (use external 5V supply if high-torque servo)
                  GND -> Common Ground (GND)
   - Red LED:     GPIO 25 (with 220-ohm resistor in series) -> Dust Alert
   - Green LED:   GPIO 26 (with 220-ohm resistor in series) -> Panel Clean
   - GND:         Common Ground
   
  REQUIRED ARDUINO LIBRARY:
   - "ESP32Servo" by Kevin Harrington
   - Installation: In Arduino IDE, navigate to:
     Sketch -> Include Library -> Manage Libraries...
     Search for "ESP32Servo" and click Install.
     
  SYSTEM LOGIC:
   - DIRT >= 70%: Triggers the servo motor on GPIO 18 to start rotating from
                  0° (0%) to 180° (180%), holds at 180° for 3 seconds delay,
                  then returns from 180° back to 0°. If dirt remains >= 70%,
                  the cleaning cycle repeats after a 3s pause.
                  RED LED is turned ON, GREEN LED is turned OFF.
   - DIRT < 70%:  Servo motor stays firmly at 0° (0% home position).
                  GREEN LED is turned ON, RED LED is turned OFF.

  COMMUNICATION PROTOCOL:
   - HTTP REST WebServer on Port 80
   
  ENDPOINTS:
   - GET  /health       -> Link ping & heartbeat
   - GET  /status       -> Device state, LED statuses, dirt %, and servo angle
   - POST /dirt         -> Accepts dirt % (e.g. ?dirt=75.5 or JSON {"dirt":75.5})
                           Evaluates >= 70% threshold and controls LEDs & servo
   - POST /led/on       -> Dust Detected alert (accepts optional ?dirt=XX.X)
   - POST /led/off      -> Panel Clean status (accepts optional ?dirt=XX.X)
   - POST /servo        -> Direct servo control (?angle=0..180 or ?action=wipe)
   - POST /led/manual   -> Manual LED test control
   
  CORS SUPPORT:
   - Access-Control-Allow-Origin: * enabled for cross-origin dashboard requests.
 ==============================================================================
*/

#include <WiFi.h>
#include <WebServer.h>
#include <ESP32Servo.h>

// ==============================================================================
// 1. WI-FI CREDENTIALS (CHANGE THESE TO MATCH YOUR LOCAL WI-FI NETWORK)
// ==============================================================================
const char* WIFI_SSID     = "amey";
const char* WIFI_PASSWORD = "ameyjadhav1";

// ==============================================================================
// 2. PIN DEFINITIONS & THRESHOLD CONSTANTS
// ==============================================================================
const int PIN_SERVO     = 18;  // Servo Motor Signal Pin (GPIO 18)
const int PIN_RED_LED   = 25;  // Dust Detection Alert LED (GPIO 25)
const int PIN_GREEN_LED = 26;  // Panel Clean Status LED (GPIO 26)

// Dust detection threshold for triggering servo wiper (70.0%)
const float DIRT_SERVO_THRESHOLD = 70.0;

// Delay duration at 180 degrees (3 seconds = 3000 ms)
const unsigned long SERVO_DELAY_MS = 3000;

// ==============================================================================
// 3. HARDWARE & STATE OBJECTS
// ==============================================================================
Servo wiperServo;

// LED State Tracking
volatile bool redLedState   = false;
volatile bool greenLedState = true;   // Default initial state: Clean (Green ON)

// Dirt and Servo State Tracking
volatile float currentDirtPercentage = 0.0;
volatile int currentServoAngle       = 0;   // 0 degrees = 0% home position

// Non-blocking Wiper State Machine
enum WiperState {
  WIPER_IDLE_0,       // Resting at 0° (dirt < 70% or standby)
  WIPER_HOLDING_180,  // Reached 180°, holding for 3-second delay
  WIPER_HOLDING_0     // Returned to 0°, pausing before next wipe if still dirty
};

volatile WiperState wiperState = WIPER_IDLE_0;
unsigned long wiperTimer = 0;
volatile bool manualWipeTriggered = false;

// Web Server instance on standard HTTP port 80
WebServer server(80);

// Watchdog timer for Wi-Fi auto-reconnection
unsigned long lastWifiCheck = 0;
const unsigned long WIFI_CHECK_INTERVAL = 10000; // 10 seconds

// ==============================================================================
// HELPER FUNCTIONS
// ==============================================================================
void setCorsHeaders() {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
}

void applyLedStates() {
  digitalWrite(PIN_RED_LED, redLedState ? HIGH : LOW);
  digitalWrite(PIN_GREEN_LED, greenLedState ? HIGH : LOW);
}

// Commands the servo safely to an angle between 0 and 180 degrees
void setServoAngle(int angle) {
  angle = constrain(angle, 0, 180);
  if (wiperServo.attached()) {
    wiperServo.write(angle);
  }
  currentServoAngle = angle;
}

// Initiates the 0° -> 180° wipe cycle with 3-second delay
void startWiperCycle() {
  Serial.printf("[SERVO] Initiating wiper cycle: Rotating from 0 deg to 180 deg (3s delay)...\n");
  setServoAngle(180);
  wiperState = WIPER_HOLDING_180;
  wiperTimer = millis();
}

// Resets the wiper servo immediately to 0 degrees
void stopWiperToZero() {
  setServoAngle(0);
  wiperState = WIPER_IDLE_0;
  manualWipeTriggered = false;
  Serial.println("[SERVO] Servo stopped and held at 0 deg (Home position).");
}

// Hardware diagnostic self-test runs on boot
void performSelfTest() {
  Serial.println("[SolarGuard] Running hardware self-test (LEDs + Servo Pin 18)...");
  
  // LED blink sequence
  for (int i = 0; i < 3; i++) {
    digitalWrite(PIN_RED_LED, HIGH);
    digitalWrite(PIN_GREEN_LED, LOW);
    delay(150);
    digitalWrite(PIN_RED_LED, LOW);
    digitalWrite(PIN_GREEN_LED, HIGH);
    delay(150);
  }

  // Servo brief functional check (0° -> 45° -> 0°)
  setServoAngle(0);
  delay(300);
  setServoAngle(45);
  delay(300);
  setServoAngle(0);
  delay(200);

  // Initialize safe default: Green ON (Clean), Red OFF, Servo at 0%
  redLedState   = false;
  greenLedState = true;
  currentDirtPercentage = 0.0;
  applyLedStates();
  stopWiperToZero();

  Serial.println("[SolarGuard] Self-test complete: System in safe state (GREEN ON, SERVO AT 0 DEG).");
}

// Non-blocking servo wiper state machine executed inside loop()
void updateServoStateMachine() {
  unsigned long now = millis();

  // If dirt is below 70% and not in manual test, ensure servo stays at 0%
  if (currentDirtPercentage < DIRT_SERVO_THRESHOLD && !manualWipeTriggered) {
    if (wiperState != WIPER_IDLE_0 || currentServoAngle != 0) {
      stopWiperToZero();
    }
    return;
  }

  switch (wiperState) {
    case WIPER_IDLE_0:
      // If dirt >= 70% or manual wipe requested, trigger the wipe
      if (currentDirtPercentage >= DIRT_SERVO_THRESHOLD || manualWipeTriggered) {
        startWiperCycle();
      }
      break;

    case WIPER_HOLDING_180:
      // Holding at 180° for 3 seconds delay
      if (now - wiperTimer >= SERVO_DELAY_MS) {
        Serial.println("[SERVO] 3-second delay at 180 deg complete. Returning to 0 deg...");
        setServoAngle(0);
        wiperState = WIPER_HOLDING_0;
        wiperTimer = now;
      }
      break;

    case WIPER_HOLDING_0:
      // Holding at 0° for 3 seconds before next sweep if still dirty
      if (now - wiperTimer >= SERVO_DELAY_MS) {
        manualWipeTriggered = false; // Manual one-shot wipe finished
        if (currentDirtPercentage >= DIRT_SERVO_THRESHOLD) {
          Serial.printf("[SERVO] Dirt is still %.1f%% (>= 70%%). Repeating wiper cycle!\n", currentDirtPercentage);
          startWiperCycle();
        } else {
          Serial.printf("[SERVO] Dirt is %.1f%% (< 70%%). Wiper resting at 0 deg.\n", currentDirtPercentage);
          wiperState = WIPER_IDLE_0;
          setServoAngle(0);
        }
      }
      break;
  }
}

// ==============================================================================
// HTTP ENDPOINT HANDLERS
// ==============================================================================

// OPTIONS pre-flight handler for CORS
void handleOptions() {
  setCorsHeaders();
  server.send(204);
}

// GET /health
void handleHealth() {
  setCorsHeaders();
  char buffer[200];
  snprintf(buffer, sizeof(buffer),
    "{\"status\":\"ok\",\"device\":\"SolarGuard-ESP32\",\"uptime_ms\":%lu,\"rssi\":%d,\"free_heap\":%u,\"servo_pin\":%d}",
    millis(), WiFi.RSSI(), ESP.getFreeHeap(), PIN_SERVO
  );
  server.send(200, "application/json", buffer);
}

// GET /status
void handleStatus() {
  setCorsHeaders();
  const char* wiperStateStr = (wiperState == WIPER_IDLE_0) ? "IDLE_0" :
                              (wiperState == WIPER_HOLDING_180) ? "HOLDING_180" : "HOLDING_0";

  char buffer[320];
  snprintf(buffer, sizeof(buffer),
    "{\"status\":\"ok\",\"device\":\"SolarGuard-ESP32\",\"ip\":\"%s\","
    "\"red_led\":%d,\"green_led\":%d,\"panel_state\":\"%s\","
    "\"dirt_percentage\":%.1f,\"dirt_threshold\":%.1f,"
    "\"servo_pin\":%d,\"servo_angle\":%d,\"wiper_state\":\"%s\","
    "\"uptime_s\":%lu}",
    WiFi.localIP().toString().c_str(),
    redLedState ? 1 : 0,
    greenLedState ? 1 : 0,
    (currentDirtPercentage >= DIRT_SERVO_THRESHOLD || redLedState) ? "DUSTY" : "CLEAN",
    currentDirtPercentage,
    DIRT_SERVO_THRESHOLD,
    PIN_SERVO,
    currentServoAngle,
    wiperStateStr,
    millis() / 1000
  );
  server.send(200, "application/json", buffer);
}

// Helper to extract dirt percentage from query string or JSON body
float parseDirtParam() {
  float dirtVal = -1.0;

  // 1. Query parameters (?dirt=75.5 or ?percentage=75.5)
  if (server.hasArg("dirt")) {
    dirtVal = server.arg("dirt").toFloat();
  } else if (server.hasArg("percentage")) {
    dirtVal = server.arg("percentage").toFloat();
  } else if (server.hasArg("soiling")) {
    dirtVal = server.arg("soiling").toFloat();
  }

  // 2. JSON body parsing fallback
  String body = server.arg("plain");
  if (dirtVal < 0.0 && body.length() > 0) {
    int idx = body.indexOf("\"dirt\":");
    if (idx == -1) idx = body.indexOf("\"dirt_percentage\":");
    if (idx == -1) idx = body.indexOf("\"percentage\":");
    if (idx == -1) idx = body.indexOf("\"soiling_index\":");
    if (idx != -1) {
      int colonIdx = body.indexOf(':', idx);
      if (colonIdx != -1) {
        dirtVal = body.substring(colonIdx + 1).toFloat();
      }
    }
  }

  return dirtVal;
}

// POST or GET /dirt -> Core endpoint for dirt percentage evaluation
void handleDirt() {
  setCorsHeaders();
  float dirt = parseDirtParam();

  if (dirt >= 0.0) {
    currentDirtPercentage = constrain(dirt, 0.0f, 100.0f);
  }

  bool isAbove70 = (currentDirtPercentage >= DIRT_SERVO_THRESHOLD);

  if (isAbove70) {
    // Dirt >= 70%: Red LED ON, Green LED OFF, Trigger Servo Wiper
    redLedState   = true;
    greenLedState = false;
    applyLedStates();
    if (wiperState == WIPER_IDLE_0) {
      startWiperCycle();
    }
    Serial.printf("[ALERT] DIRT DETECTED: %.1f%% (>= %.1f%%). Red LED ON, Servo Wiper Triggered!\n",
                  currentDirtPercentage, DIRT_SERVO_THRESHOLD);
  } else {
    // Dirt < 70%: Green LED ON, Red LED OFF, Servo stays at 0%
    redLedState   = false;
    greenLedState = true;
    applyLedStates();
    stopWiperToZero();
    Serial.printf("[STATUS] DIRT LEVEL: %.1f%% (< %.1f%%). Green LED ON, Servo staying at 0%%.\n",
                  currentDirtPercentage, DIRT_SERVO_THRESHOLD);
  }

  char buffer[240];
  snprintf(buffer, sizeof(buffer),
    "{\"status\":\"ok\",\"dirt_percentage\":%.1f,\"dirt_threshold\":%.1f,"
    "\"servo_pin\":%d,\"servo_angle\":%d,\"wiper_triggered\":%s,\"red_led\":%d,\"green_led\":%d}",
    currentDirtPercentage, DIRT_SERVO_THRESHOLD,
    PIN_SERVO, currentServoAngle,
    isAbove70 ? "true" : "false",
    redLedState ? 1 : 0, greenLedState ? 1 : 0
  );
  server.send(200, "application/json", buffer);
}

// POST or GET /led/on -> DUST DETECTED (Turn RED ON, GREEN OFF, check dirt % for servo)
void handleLedOn() {
  setCorsHeaders();
  float dirt = parseDirtParam();
  if (dirt >= 0.0) {
    currentDirtPercentage = constrain(dirt, 0.0f, 100.0f);
  } else {
    // If not explicitly provided, assume above threshold for alert
    currentDirtPercentage = 100.0;
  }

  redLedState   = true;
  greenLedState = false;
  applyLedStates();

  bool isAbove70 = (currentDirtPercentage >= DIRT_SERVO_THRESHOLD);
  if (isAbove70) {
    startWiperCycle();
    Serial.printf("[ALERT] DUST DETECTED (%.1f%% >= 70%%)! Action: RED ON, GREEN OFF, SERVO WIPING!\n",
                  currentDirtPercentage);
  } else {
    stopWiperToZero();
    Serial.printf("[ALERT] Dust Alert with Dirt %.1f%% (< 70%%). RED ON, GREEN OFF, Servo at 0 deg.\n",
                  currentDirtPercentage);
  }

  char buffer[240];
  snprintf(buffer, sizeof(buffer),
    "{\"status\":\"ok\",\"action\":\"dust_alert\",\"panel_state\":\"DUSTY\","
    "\"dirt_percentage\":%.1f,\"servo_pin\":%d,\"servo_angle\":%d,\"wiper_active\":%s,"
    "\"red_led\":1,\"green_led\":0}",
    currentDirtPercentage, PIN_SERVO, currentServoAngle,
    isAbove70 ? "true" : "false"
  );
  server.send(200, "application/json", buffer);
}

// POST or GET /led/off -> PANEL CLEAN (Turn GREEN ON, RED OFF, Servo stays at 0%)
void handleLedOff() {
  setCorsHeaders();
  float dirt = parseDirtParam();
  if (dirt >= 0.0) {
    currentDirtPercentage = constrain(dirt, 0.0f, 100.0f);
  } else {
    currentDirtPercentage = 0.0; // Default clean
  }

  redLedState   = false;
  greenLedState = true;
  applyLedStates();
  stopWiperToZero();

  Serial.printf("[STATUS] PANEL CLEAN (%.1f%% < 70%%)! Action: GREEN ON, RED OFF, SERVO AT 0 DEG.\n",
                currentDirtPercentage);

  char buffer[220];
  snprintf(buffer, sizeof(buffer),
    "{\"status\":\"ok\",\"action\":\"panel_clean\",\"panel_state\":\"CLEAN\","
    "\"dirt_percentage\":%.1f,\"servo_pin\":%d,\"servo_angle\":0,\"wiper_active\":false,"
    "\"red_led\":0,\"green_led\":1}",
    currentDirtPercentage, PIN_SERVO
  );
  server.send(200, "application/json", buffer);
}

// POST or GET /servo -> Direct servo testing and manual wiping control
void handleServo() {
  setCorsHeaders();
  String body = server.arg("plain");

  // Check for angle parameter (?angle=180 or JSON {"angle":180})
  int targetAngle = -1;
  if (server.hasArg("angle")) {
    targetAngle = server.arg("angle").toInt();
  } else if (body.indexOf("\"angle\":") != -1) {
    int idx = body.indexOf("\"angle\":");
    targetAngle = body.substring(idx + 8).toInt();
  }

  // Check for action parameter (?action=wipe or JSON {"action":"wipe"})
  bool doWipe = false;
  if (server.hasArg("action") && server.arg("action") == "wipe") {
    doWipe = true;
  } else if (body.indexOf("\"wipe\"") != -1) {
    doWipe = true;
  }

  if (doWipe) {
    manualWipeTriggered = true;
    startWiperCycle();
    Serial.println("[MANUAL] Servo manual wipe initiated (0 -> 180 with 3s delay -> 0).");
  } else if (targetAngle >= 0) {
    manualWipeTriggered = false;
    setServoAngle(targetAngle);
    wiperState = WIPER_IDLE_0;
    Serial.printf("[MANUAL] Servo directly commanded to %d degrees on Pin %d.\n", targetAngle, PIN_SERVO);
  }

  char buffer[220];
  snprintf(buffer, sizeof(buffer),
    "{\"status\":\"ok\",\"servo_pin\":%d,\"servo_angle\":%d,\"manual_wipe\":%s,\"dirt_percentage\":%.1f}",
    PIN_SERVO, currentServoAngle,
    doWipe ? "true" : "false",
    currentDirtPercentage
  );
  server.send(200, "application/json", buffer);
}

// POST or GET /led/manual -> Direct pin testing
void handleLedManual() {
  setCorsHeaders();
  String body = server.arg("plain");

  // Query parameters fallback (?red=1&green=0)
  if (server.hasArg("red")) {
    redLedState = (server.arg("red").toInt() == 1);
  }
  if (server.hasArg("green")) {
    greenLedState = (server.arg("green").toInt() == 1);
  }

  // Parse simple JSON: {"led":"red","state":1} or {"led":"green","state":0}
  if (body.length() > 0) {
    if (body.indexOf("\"red\"") != -1) {
      redLedState = (body.indexOf("\"state\":1") != -1 || body.indexOf("\"state\": 1") != -1);
    }
    if (body.indexOf("\"green\"") != -1) {
      greenLedState = (body.indexOf("\"state\":1") != -1 || body.indexOf("\"state\": 1") != -1);
    }
  }

  applyLedStates();
  Serial.printf("[MANUAL] Red LED: %d, Green LED: %d\n", redLedState, greenLedState);

  char buffer[180];
  snprintf(buffer, sizeof(buffer),
    "{\"status\":\"ok\",\"mode\":\"manual\",\"red_led\":%d,\"green_led\":%d}",
    redLedState ? 1 : 0, greenLedState ? 1 : 0
  );
  server.send(200, "application/json", buffer);
}

// 404 Handler
void handleNotFound() {
  setCorsHeaders();
  server.send(404, "application/json", "{\"status\":\"error\",\"message\":\"Endpoint not found\"}");
}

// ==============================================================================
// SETUP
// ==============================================================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("\n==============================================");
  Serial.println("  SOLARGUARD AI - ESP32 WI-FI NODE FIRMWARE  ");
  Serial.println("  PIN 18: SERVO WIPER (0-180 DEG, 3S DELAY)   ");
  Serial.println("  PIN 25: RED DUST ALERT LED                  ");
  Serial.println("  PIN 26: GREEN PANEL CLEAN LED               ");
  Serial.println("==============================================");

  // Initialize GPIO Pins
  pinMode(PIN_RED_LED, OUTPUT);
  pinMode(PIN_GREEN_LED, OUTPUT);

  // Initialize Servo on Pin 18 using ESP32Servo
  // Allocate timers for ESP32 PWM
  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);
  ESP32PWM::allocateTimer(2);
  ESP32PWM::allocateTimer(3);

  wiperServo.setPeriodHertz(50); // Standard 50Hz RC servo
  wiperServo.attach(PIN_SERVO, 500, 2400); // 500us to 2400us pulse widths
  setServoAngle(0); // Initialize at safe 0% (0 degrees) home position

  // Hardware self-test
  performSelfTest();

  // Connect to Wi-Fi
  Serial.printf("[Wi-Fi] Connecting to SSID: %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 25) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[Wi-Fi] Connection Established Successfully!");
    Serial.printf("[Wi-Fi] Assigned IP Address: %s\n", WiFi.localIP().toString().c_str());
    Serial.printf("[Wi-Fi] Subnet Mask:         %s\n", WiFi.subnetMask().toString().c_str());
    Serial.printf("[Wi-Fi] Gateway:             %s\n", WiFi.gatewayIP().toString().c_str());
    Serial.printf("[Wi-Fi] Signal Strength:     %d dBm\n", WiFi.RSSI());
    Serial.println("----------------------------------------------");
    Serial.println("Enter this IP address into the SolarGuard Dashboard: ");
    Serial.printf(">>>  %s  <<<\n", WiFi.localIP().toString().c_str());
    Serial.println("----------------------------------------------");
  } else {
    Serial.println("\n[Wi-Fi] Warning: Could not connect to Wi-Fi. Will auto-retry in loop.");
  }

  // Register REST API Route Handlers
  server.on("/health",       HTTP_GET,     handleHealth);
  server.on("/status",       HTTP_GET,     handleStatus);
  server.on("/dirt",         HTTP_POST,    handleDirt);
  server.on("/dirt",         HTTP_GET,     handleDirt);
  server.on("/servo",        HTTP_POST,    handleServo);
  server.on("/servo",        HTTP_GET,     handleServo);
  server.on("/servo/manual", HTTP_POST,    handleServo);
  server.on("/servo/manual", HTTP_GET,     handleServo);
  server.on("/led/on",       HTTP_POST,    handleLedOn);
  server.on("/led/on",       HTTP_GET,     handleLedOn);
  server.on("/led/off",      HTTP_POST,    handleLedOff);
  server.on("/led/off",      HTTP_GET,     handleLedOff);
  server.on("/led/manual",   HTTP_POST,    handleLedManual);
  server.on("/led/manual",   HTTP_GET,     handleLedManual);

  // CORS Preflight Handlers
  server.on("/health",       HTTP_OPTIONS, handleOptions);
  server.on("/status",       HTTP_OPTIONS, handleOptions);
  server.on("/dirt",         HTTP_OPTIONS, handleOptions);
  server.on("/servo",        HTTP_OPTIONS, handleOptions);
  server.on("/servo/manual", HTTP_OPTIONS, handleOptions);
  server.on("/led/on",       HTTP_OPTIONS, handleOptions);
  server.on("/led/off",      HTTP_OPTIONS, handleOptions);
  server.on("/led/manual",   HTTP_OPTIONS, handleOptions);

  server.onNotFound(handleNotFound);

  // Start HTTP Web Server
  server.begin();
  Serial.println("[HTTP] REST Server listening on port 80.");
}

// ==============================================================================
// MAIN LOOP
// ==============================================================================
void loop() {
  // 1. Handle incoming HTTP client requests
  server.handleClient();

  // 2. Non-blocking Servo Wiper state machine (handles 3s delay & 0-180-0 rotation)
  updateServoStateMachine();

  // 3. Periodic Wi-Fi reconnection watchdog
  unsigned long now = millis();
  if (now - lastWifiCheck > WIFI_CHECK_INTERVAL) {
    lastWifiCheck = now;
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("[Wi-Fi] Connection dropped! Attempting auto-reconnection...");
      WiFi.reconnect();
    }
  }
}
