/*
 ==============================================================================
  PROJECT: SolarGuard AI - Intelligent Solar Panel Dust Detection System
  FIRMWARE: solarguard_esp32.ino
  TARGET: ESP32 DevKit V1 / NodeMCU-32S
  
  HARDWARE CONFIGURATION:
   - Red LED:   GPIO 25 (with 220-ohm resistor in series) -> Dust Alert
   - Green LED: GPIO 26 (with 220-ohm resistor in series) -> Panel Clean
   - GND:       Common Ground
   
  COMMUNICATION PROTOCOL:
   - HTTP REST WebServer on Port 80
   
  ENDPOINTS:
   - GET  /health      -> Link ping & heartbeat
   - GET  /status      -> Device state & LED statuses
   - POST /led/on      -> Dust Detected: RED ON, GREEN OFF
   - POST /led/off     -> Panel Clean:   GREEN ON, RED OFF
   - POST /led/manual  -> Manual test control
   
  CORS SUPPORT:
   - Access-Control-Allow-Origin: * enabled for cross-origin dashboard requests.
 ==============================================================================
*/

#include <WiFi.h>
#include <WebServer.h>

// ==============================================================================
// 1. WI-FI CREDENTIALS (CHANGE THESE TO MATCH YOUR LOCAL WI-FI NETWORK)
// ==============================================================================
const char* WIFI_SSID     = "amey";
const char* WIFI_PASSWORD = "ameyjadhav1";

// ==============================================================================
// 2. PIN DEFINITIONS
// ==============================================================================
const int PIN_RED_LED   = 25;  // Dust Detection Alert LED
const int PIN_GREEN_LED = 26;  // Panel Clean Status LED

// LED State Tracking
volatile bool redLedState   = false;
volatile bool greenLedState = true;   // Default initial state: Clean (Green ON)

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

void performSelfTest() {
  Serial.println("[SolarGuard] Running hardware LED diagnostic self-test...");
  for (int i = 0; i < 3; i++) {
    digitalWrite(PIN_RED_LED, HIGH);
    digitalWrite(PIN_GREEN_LED, LOW);
    delay(150);
    digitalWrite(PIN_RED_LED, LOW);
    digitalWrite(PIN_GREEN_LED, HIGH);
    delay(150);
  }
  // Initialize safe default: Green ON (Clean), Red OFF
  redLedState = false;
  greenLedState = true;
  applyLedStates();
  Serial.println("[SolarGuard] Self-test complete: System in safe state (GREEN ON).");
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
  char buffer[180];
  snprintf(buffer, sizeof(buffer),
    "{\"status\":\"ok\",\"device\":\"SolarGuard-ESP32\",\"uptime_ms\":%lu,\"rssi\":%d,\"free_heap\":%u}",
    millis(), WiFi.RSSI(), ESP.getFreeHeap()
  );
  server.send(200, "application/json", buffer);
}

// GET /status
void handleStatus() {
  setCorsHeaders();
  char buffer[220];
  snprintf(buffer, sizeof(buffer),
    "{\"status\":\"ok\",\"device\":\"SolarGuard-ESP32\",\"ip\":\"%s\",\"red_led\":%d,\"green_led\":%d,\"panel_state\":\"%s\",\"uptime_s\":%lu}",
    WiFi.localIP().toString().c_str(),
    redLedState ? 1 : 0,
    greenLedState ? 1 : 0,
    redLedState ? "DUSTY" : "CLEAN",
    millis() / 1000
  );
  server.send(200, "application/json", buffer);
}

// POST or GET /led/on -> DUST DETECTED (Turn RED ON, GREEN OFF)
void handleLedOn() {
  setCorsHeaders();
  redLedState   = true;
  greenLedState = false;
  applyLedStates();

  Serial.println("[ALERT] DUST DETECTED! Action: RED LED = ON, GREEN LED = OFF");

  char buffer[160];
  snprintf(buffer, sizeof(buffer),
    "{\"status\":\"ok\",\"action\":\"dust_alert\",\"panel_state\":\"DUSTY\",\"red_led\":1,\"green_led\":0}"
  );
  server.send(200, "application/json", buffer);
}

// POST or GET /led/off -> PANEL CLEAN (Turn GREEN ON, RED OFF)
void handleLedOff() {
  setCorsHeaders();
  redLedState   = false;
  greenLedState = true;
  applyLedStates();

  Serial.println("[STATUS] PANEL CLEAN! Action: GREEN LED = ON, RED LED = OFF");

  char buffer[160];
  snprintf(buffer, sizeof(buffer),
    "{\"status\":\"ok\",\"action\":\"panel_clean\",\"panel_state\":\"CLEAN\",\"red_led\":0,\"green_led\":1}"
  );
  server.send(200, "application/json", buffer);
}

// POST /led/manual -> Direct pin testing
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
  Serial.println("==============================================");

  // Initialize GPIO Pins
  pinMode(PIN_RED_LED, OUTPUT);
  pinMode(PIN_GREEN_LED, OUTPUT);

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
  server.on("/health",     HTTP_GET,     handleHealth);
  server.on("/status",     HTTP_GET,     handleStatus);
  server.on("/led/on",     HTTP_POST,    handleLedOn);
  server.on("/led/on",     HTTP_GET,     handleLedOn);   // Also accept GET for quick browser test
  server.on("/led/off",    HTTP_POST,    handleLedOff);
  server.on("/led/off",    HTTP_GET,     handleLedOff);  // Also accept GET for quick browser test
  server.on("/led/manual", HTTP_POST,    handleLedManual);
  server.on("/led/manual", HTTP_GET,     handleLedManual);

  // CORS Preflight Handlers
  server.on("/health",     HTTP_OPTIONS, handleOptions);
  server.on("/status",     HTTP_OPTIONS, handleOptions);
  server.on("/led/on",     HTTP_OPTIONS, handleOptions);
  server.on("/led/off",    HTTP_OPTIONS, handleOptions);
  server.on("/led/manual", HTTP_OPTIONS, handleOptions);

  server.onNotFound(handleNotFound);

  // Start HTTP Web Server
  server.begin();
  Serial.println("[HTTP] REST Server listening on port 80.");
}

// ==============================================================================
// MAIN LOOP
// ==============================================================================
void loop() {
  // Handle incoming HTTP client requests
  server.handleClient();

  // Periodic Wi-Fi reconnection check
  unsigned long now = millis();
  if (now - lastWifiCheck > WIFI_CHECK_INTERVAL) {
    lastWifiCheck = now;
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("[Wi-Fi] Connection dropped! Attempting auto-reconnection...");
      WiFi.reconnect();
    }
  }
}
