/**
 * SolarGuard AI - Main Dashboard Controller
 * Handles REST API communication, live UI state synchronization,
 * hardware control, reference management, and log streaming.
 */

const STATE = {
  isPolling: true,
  pollIntervalMs: 1500,
  cleanThreshold: 22.0,
  heavyThreshold: 48.0,
  autoScrollLogs: true,
  lastLogCount: 0
};

// Initialize Dashboard on load
document.addEventListener('DOMContentLoaded', () => {
  initUIEventListeners();
  fetchInitialConfig();
  fetchCameraDevices();
  fetchNetworkDiagnostics();
  fetchReferenceImage();
  fetchStats();
  fetchLogs();
  startStatusPolling();
});

/**
 * Attaches event listeners to buttons, toggles, and modals
 */
function initUIEventListeners() {
  // Camera & Monitoring Controls
  const btnStartMon = document.getElementById('btnStartMonitoring');
  const btnStopMon = document.getElementById('btnStopMonitoring');
  const btnSingleScan = document.getElementById('btnSingleScan');
  const btnStartCam = document.getElementById('btnStartCamera');
  const btnStopCam = document.getElementById('btnStopCamera');
  const camSelect = document.getElementById('cameraDeviceSelect');

  if (btnStartMon) btnStartMon.addEventListener('click', startMonitoring);
  if (btnStopMon) btnStopMon.addEventListener('click', stopMonitoring);
  if (btnSingleScan) btnSingleScan.addEventListener('click', triggerSingleScan);
  if (btnStartCam) btnStartCam.addEventListener('click', () => startCamera());
  if (btnStopCam) btnStopCam.addEventListener('click', stopCamera);
  if (camSelect) camSelect.addEventListener('change', onCameraSelected);

  // Mobile IP Webcam Controls
  const btnToggleMobileCam = document.getElementById('btnToggleMobileCamPanel');
  const btnCloseMobileCam = document.getElementById('btnCloseMobileCamPanel');
  const btnConnectIpCam = document.getElementById('btnConnectIpCam');
  const btnTestIpCam = document.getElementById('btnTestIpCam');
  const btnToggleTorch = document.getElementById('btnToggleTorch');
  const btnFlipCamera = document.getElementById('btnFlipCamera');
  const btnTriggerFocus = document.getElementById('btnTriggerFocus');
  const inputMobileIp = document.getElementById('inputMobileIpUrl');

  if (btnToggleMobileCam) btnToggleMobileCam.addEventListener('click', toggleMobileCamPanel);
  if (btnCloseMobileCam) btnCloseMobileCam.addEventListener('click', () => {
    const p = document.getElementById('mobileCamPanel');
    if (p) p.style.display = 'none';
  });
  if (btnConnectIpCam) btnConnectIpCam.addEventListener('click', connectIpWebcam);
  if (btnTestIpCam) btnTestIpCam.addEventListener('click', testIpWebcam);
  const btnAutoDetect = document.getElementById('btnAutoDetectIpCam');
  const btnUseGateway = document.getElementById('btnUseGatewayIp');
  if (btnAutoDetect) btnAutoDetect.addEventListener('click', autoDetectIpWebcam);
  if (btnUseGateway) btnUseGateway.addEventListener('click', useGatewayIp);
  if (btnToggleTorch) btnToggleTorch.addEventListener('click', () => controlIpWebcam('torch_toggle'));
  if (btnFlipCamera) btnFlipCamera.addEventListener('click', () => controlIpWebcam('camera_flip'));
  if (btnTriggerFocus) btnTriggerFocus.addEventListener('click', () => controlIpWebcam('focus'));

  const savedIpUrl = localStorage.getItem('solarguard_ip_webcam_url');
  if (savedIpUrl && inputMobileIp) {
    inputMobileIp.value = savedIpUrl.replace(/\/video\/?$/i, '');
  }
  const btnEspConnect = document.getElementById('btnEspConnect');
  const btnTestRedOn = document.getElementById('btnTestRedOn');
  const btnTestRedOff = document.getElementById('btnTestRedOff');
  const btnTestGreenOn = document.getElementById('btnTestGreenOn');
  const btnTestGreenOff = document.getElementById('btnTestGreenOff');
  const btnTestServoWipe = document.getElementById('btnTestServoWipe');
  const btnTestServoZero = document.getElementById('btnTestServoZero');
  const btnTestServo180 = document.getElementById('btnTestServo180');
  const autoModeToggle = document.getElementById('autoModeToggle');

  if (btnEspConnect) btnEspConnect.addEventListener('click', connectEsp32);
  if (btnTestRedOn) btnTestRedOn.addEventListener('click', () => testEspLed('red', true));
  if (btnTestRedOff) btnTestRedOff.addEventListener('click', () => testEspLed('red', false));
  if (btnTestGreenOn) btnTestGreenOn.addEventListener('click', () => testEspLed('green', true));
  if (btnTestGreenOff) btnTestGreenOff.addEventListener('click', () => testEspLed('green', false));
  if (btnTestServoWipe) btnTestServoWipe.addEventListener('click', () => testEspServo(null, 'wipe'));
  if (btnTestServoZero) btnTestServoZero.addEventListener('click', () => testEspServo(0, null));
  if (btnTestServo180) btnTestServo180.addEventListener('click', () => testEspServo(180, null));
  if (autoModeToggle) autoModeToggle.addEventListener('change', onAutoModeToggled);

  // Reference Controls
  const btnCaptureRef = document.getElementById('btnCaptureReference');
  const refFileInput = document.getElementById('refFileInput');
  if (btnCaptureRef) btnCaptureRef.addEventListener('click', captureCleanReference);
  if (refFileInput) refFileInput.addEventListener('change', uploadReferenceFile);

  // Simulation Controls
  const simToggle = document.getElementById('simToggle');
  const simDustSlider = document.getElementById('simDustSlider');
  const simDustVal = document.getElementById('simDustVal');
  if (simToggle) simToggle.addEventListener('change', toggleSimulation);
  if (simDustSlider) {
    simDustSlider.addEventListener('input', (e) => {
      if (simDustVal) simDustVal.textContent = e.target.value + '%';
    });
    simDustSlider.addEventListener('change', (e) => {
      setSimulatedDust(e.target.value);
    });
  }

  // Calibration Modal
  const btnOpenSettings = document.getElementById('btnOpenSettings');
  const btnCloseSettings = document.getElementById('btnCloseSettings');
  const btnSaveSettings = document.getElementById('btnSaveSettings');
  const modalSettings = document.getElementById('modalSettings');

  if (btnOpenSettings) btnOpenSettings.addEventListener('click', () => {
    modalSettings.classList.add('active');
  });
  if (btnCloseSettings) btnCloseSettings.addEventListener('click', () => {
    modalSettings.classList.remove('active');
  });
  if (btnSaveSettings) btnSaveSettings.addEventListener('click', saveThresholdSettings);
  const btnTrainModel = document.getElementById('btnTrainModel');
  if (btnTrainModel) btnTrainModel.addEventListener('click', triggerModelTraining);

  // Export CSV & Logs
  const btnExportCsv = document.getElementById('btnExportCsv');
  const btnClearLogs = document.getElementById('btnClearLogs');
  const chkAutoScroll = document.getElementById('chkAutoScroll');
  if (btnExportCsv) btnExportCsv.addEventListener('click', exportHistoryCsv);
  if (btnClearLogs) btnClearLogs.addEventListener('click', () => {
    const term = document.getElementById('logTerminal');
    if (term) term.innerHTML = '<div class="log-entry"><span class="log-msg">Logs cleared.</span></div>';
  });
  if (chkAutoScroll) chkAutoScroll.addEventListener('change', (e) => {
    STATE.autoScrollLogs = e.target.checked;
  });
}

/**
 * Periodic status polling loop (runs every 1.5s)
 */
function startStatusPolling() {
  setInterval(async () => {
    if (!STATE.isPolling) return;
    try {
      const resp = await fetch('/api/status');
      if (resp.ok) {
        const data = await resp.json();
        updateDashboardUI(data);
      }
    } catch (e) {
      console.warn("Polling error:", e);
    }
  }, STATE.pollIntervalMs);

  // Poll stats and charts every 4 seconds
  setInterval(fetchStats, 4000);

  // Poll system logs every 3 seconds
  setInterval(fetchLogs, 3000);
}

/**
 * Updates all DOM elements with fresh telemetry from /api/status
 */
function updateDashboardUI(data) {
  if (!data || !data.success) return;

  const mon = data.monitoring || {};
  const cam = data.camera || {};
  const esp = data.esp32 || {};
  const det = data.latest_detection || {};

  // 1. Top Header Indicators
  const topCameraStatus = document.getElementById('topCameraStatus');
  const topEspStatus = document.getElementById('topEspStatus');
  const topModeStatus = document.getElementById('topModeStatus');

  if (topCameraStatus) {
    if (cam.is_running) {
      topCameraStatus.innerHTML = `<span class="pulse-dot online"></span> Camera Active (${cam.fps} FPS)`;
    } else {
      topCameraStatus.innerHTML = `<span class="pulse-dot"></span> Camera Idle`;
    }
  }

  if (topEspStatus) {
    if (esp.is_connected) {
      topEspStatus.innerHTML = `<span class="pulse-dot clean"></span> ESP32 Online (${esp.latency_ms || 0}ms)`;
    } else {
      topEspStatus.innerHTML = `<span class="pulse-dot dusty"></span> ESP32 Offline`;
    }
  }

  if (topModeStatus) {
    topModeStatus.textContent = mon.auto_mode ? 'Mode: AUTO' : 'Mode: MANUAL';
  }

  // 2. KPI Cards
  const kpiCondition = document.getElementById('kpiCondition');
  const kpiSoiling = document.getElementById('kpiSoiling');
  const kpiConfidence = document.getElementById('kpiConfidence');
  const kpiScans = document.getElementById('kpiScans');
  const kpiUptime = document.getElementById('kpiUptime');

  const status = det.status || 'CLEAN';
  const soiling = det.soiling_index !== undefined ? Number(det.soiling_index).toFixed(1) : '0.0';
  const confidence = det.confidence !== undefined ? Number(det.confidence).toFixed(0) : '0';

  if (kpiCondition) {
    let cls = 'clean';
    let text = 'PANEL CLEAN';
    if (status === 'MODERATELY DUSTY') {
      cls = 'moderate';
      text = 'MODERATELY DUSTY';
    } else if (status === 'HEAVILY DUSTY') {
      cls = 'heavy';
      text = 'DUST DETECTED (HEAVY)';
    }
    kpiCondition.innerHTML = `<span class="badge-condition ${cls}">${text}</span>`;
  }

  if (kpiSoiling) kpiSoiling.textContent = `${soiling}%`;
  if (kpiConfidence) kpiConfidence.textContent = `${confidence}%`;
  if (kpiScans) kpiScans.textContent = mon.total_scans || 0;
  if (kpiUptime) kpiUptime.textContent = formatUptime(mon.uptime_seconds || 0);

  // 3. ESP32 Hardware Status Card
  const espStatusBadge = document.getElementById('espStatusBadge');
  const espIpDisplay = document.getElementById('espIpDisplay');
  const espLatencyDisplay = document.getElementById('espLatencyDisplay');
  const ledRedBulb = document.getElementById('ledRedBulb');
  const ledGreenBulb = document.getElementById('ledGreenBulb');

  if (espStatusBadge) {
    if (esp.is_connected) {
      espStatusBadge.className = 'status-pill';
      espStatusBadge.innerHTML = '<span class="pulse-dot clean"></span> CONNECTED';
    } else {
      espStatusBadge.className = 'status-pill';
      espStatusBadge.innerHTML = '<span class="pulse-dot dusty"></span> DISCONNECTED';
    }
  }

  if (espIpDisplay) espIpDisplay.textContent = esp.ip || '---';
  if (espLatencyDisplay) {
    espLatencyDisplay.textContent = esp.is_connected && esp.latency_ms !== null ? `${esp.latency_ms} ms` : 'N/A';
  }

  // Update Visual LED Bulbs
  const currentLeds = esp.current_leds || {};
  if (ledRedBulb) {
    if (currentLeds.red) {
      ledRedBulb.classList.add('red-on');
    } else {
      ledRedBulb.classList.remove('red-on');
    }
  }

  if (ledGreenBulb) {
    if (currentLeds.green) {
      ledGreenBulb.classList.add('green-on');
    } else {
      ledGreenBulb.classList.remove('green-on');
    }
  }

  // Update Servo Wiper Badge (GPIO 18)
  const servoAngleBadge = document.getElementById('servoAngleBadge');
  if (servoAngleBadge && esp.servo) {
    const sAngle = esp.servo.angle !== undefined ? esp.servo.angle : 0;
    const sState = esp.servo.wiper_state || 'IDLE_0';
    if (sAngle > 0 || sState.includes('180') || sState.includes('HOLDING')) {
      servoAngleBadge.className = 'status-pill status-dusty';
      servoAngleBadge.textContent = `${sAngle}° (Wiping / 3s Delay)`;
    } else {
      servoAngleBadge.className = 'status-pill status-clean';
      servoAngleBadge.textContent = '0° (Idle / Clean)';
    }
  }

  // 4. Update Simulation Banner State
  const simBanner = document.getElementById('simBanner');
  if (simBanner) {
    simBanner.style.display = cam.simulation_mode ? 'flex' : 'none';
  }

  // 5. Update Vision Camera & Mobile IP Webcam status indicators
  const sideCamIndicator = document.getElementById('sideCamIndicator');
  const mobileCamBadge = document.getElementById('mobileCamBadge');
  const mobileCamControls = document.getElementById('mobileCamControls');
  const mobileCamActiveUrl = document.getElementById('mobileCamActiveUrl');
  const lblTorchText = document.getElementById('lblTorchText');
  const lblCameraFacing = document.getElementById('lblCameraFacing');
  const inputMobileIpUrl = document.getElementById('inputMobileIpUrl');

  if (cam.is_ip_camera && cam.is_running && !cam.simulation_mode) {
    if (sideCamIndicator) {
      sideCamIndicator.innerHTML = '<span style="color:var(--teal-primary);">📱 Mobile IP Cam</span>';
    }
    if (mobileCamBadge) {
      mobileCamBadge.innerHTML = '<span class="pulse-dot clean" style="display:inline-block; margin-right:4px;"></span> Active';
      mobileCamBadge.style.color = 'var(--emerald-clean)';
      mobileCamBadge.style.background = 'rgba(16, 185, 129, 0.15)';
      mobileCamBadge.style.borderColor = 'rgba(16, 185, 129, 0.4)';
    }
    if (mobileCamControls) mobileCamControls.style.display = 'flex';
    if (mobileCamActiveUrl) mobileCamActiveUrl.textContent = cam.ip_camera_url || cam.camera_source || '';
    if (lblTorchText) lblTorchText.textContent = cam.torch_active ? 'Torch OFF' : 'Torch ON';
    if (lblCameraFacing) lblCameraFacing.textContent = (cam.camera_facing === 'front') ? 'Switch Rear Cam' : 'Switch Front Cam';
  } else {
    if (sideCamIndicator) {
      sideCamIndicator.innerHTML = cam.simulation_mode
        ? '<span style="color:var(--amber-moderate);">Virtual Test Gen</span>'
        : '<span style="color:var(--teal-primary);">USB Video Cam</span>';
    }
    if (mobileCamBadge) {
      mobileCamBadge.textContent = 'Not Connected';
      mobileCamBadge.style.color = 'var(--text-dim)';
      mobileCamBadge.style.background = 'rgba(100, 116, 139, 0.2)';
      mobileCamBadge.style.borderColor = 'var(--border-color)';
    }
    if (mobileCamControls) mobileCamControls.style.display = 'none';
  }

  // Auto pre-fill input if empty and backend has saved IP URL
  if (inputMobileIpUrl && !inputMobileIpUrl.value && cam.ip_camera_url) {
    inputMobileIpUrl.value = cam.ip_camera_url.replace(/\/video\/?$/i, '');
  }
}

/**
 * Fetches analytics statistics from /api/detection/stats and feeds Chart.js
 */
async function fetchStats() {
  try {
    const resp = await fetch('/api/detection/stats');
    if (resp.ok) {
      const data = await resp.json();
      if (data.success && data.stats) {
        if (typeof updateChartsWithStats === 'function') {
          updateChartsWithStats(data.stats);
        }
      }
    }
  } catch (e) {
    console.warn("Failed to fetch stats:", e);
  }
}

/**
 * Fetches recent system logs and streams them to the log terminal
 */
async function fetchLogs() {
  try {
    const resp = await fetch('/api/logs?limit=40');
    if (resp.ok) {
      const data = await resp.json();
      if (data.success && data.logs) {
        renderLogs(data.logs);
      }
    }
  } catch (e) {
    console.warn("Failed to fetch logs:", e);
  }
}

function renderLogs(logs) {
  const terminal = document.getElementById('logTerminal');
  if (!terminal || !logs || logs.length === 0) return;

  // Reverse so newest at bottom
  const sorted = [...logs].reverse();
  let html = '';

  sorted.forEach(l => {
    const d = new Date(l.timestamp);
    const timeStr = d.toLocaleTimeString([], { hour12: false });
    html += `
      <div class="log-entry">
        <span class="log-time">[${timeStr}]</span>
        <span class="log-level-${l.level}">[${l.level}]</span>
        <span class="log-comp">[${l.component}]</span>
        <span class="log-msg">${escapeHtml(l.message)}</span>
      </div>
    `;
  });

  terminal.innerHTML = html;
  if (STATE.autoScrollLogs) {
    terminal.scrollTop = terminal.scrollHeight;
  }
}

function refreshVideoStream() {
  const liveFeed = document.getElementById('liveVideoFeed');
  if (liveFeed) {
    liveFeed.src = '/video_feed?t=' + Date.now();
  }
}

/**
 * Camera Actions
 */
async function startCamera(camIndex = null) {
  try {
    const payload = camIndex !== null ? { camera_index: camIndex } : {};
    const resp = await fetch('/api/camera/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await resp.json();
    showToast(data.message || 'Camera started');
    refreshVideoStream();
  } catch (e) {
    showToast('Failed to start camera', true);
  }
}

async function stopCamera() {
  try {
    const resp = await fetch('/api/camera/stop', { method: 'POST' });
    const data = await resp.json();
    showToast(data.message || 'Camera stopped');
    refreshVideoStream();
  } catch (e) {
    showToast('Failed to stop camera', true);
  }
}

function toggleMobileCamPanel() {
  const panel = document.getElementById('mobileCamPanel');
  if (!panel) return;
  const isOpening = panel.style.display === 'none' || !panel.style.display;
  panel.style.display = isOpening ? 'block' : 'none';
  if (isOpening) {
    fetchNetworkDiagnostics();
    const input = document.getElementById('inputMobileIpUrl');
    if (input) input.focus();
  }
}

async function fetchNetworkDiagnostics() {
  try {
    const resp = await fetch('/api/camera/ip-webcam/diagnostics');
    if (!resp.ok) return;
    const data = await resp.json();
    if (data.success && data.diagnostics) {
      const diag = data.diagnostics;
      const bannerSsid = document.getElementById('bannerSsid');
      const btnUseGateway = document.getElementById('btnUseGatewayIp');
      if (bannerSsid) {
        bannerSsid.textContent = diag.wifi_ssid || 'Local Wi-Fi';
      }
      if (btnUseGateway && diag.suggested_url) {
        btnUseGateway.textContent = `Use ${diag.gateway_ip || 'Hotspot'}:8080`;
        btnUseGateway.setAttribute('data-url', diag.suggested_url);
      }
    }
  } catch (e) {
    console.warn("Network diagnostics fetch failed:", e);
  }
}

function useGatewayIp() {
  const btn = document.getElementById('btnUseGatewayIp');
  const input = document.getElementById('inputMobileIpUrl');
  if (!input) return;
  const rawUrl = btn ? (btn.getAttribute('data-url') || 'http://10.89.28.44:8080') : 'http://10.89.28.44:8080';
  const url = rawUrl.replace(/\/video\/?$/i, '');
  input.value = url;
  showToast(`Pasted ${url} - Tap 'Connect Phone'`);
}

async function autoDetectIpWebcam() {
  const btn = document.getElementById('btnAutoDetectIpCam');
  const input = document.getElementById('inputMobileIpUrl');
  const errBox = document.getElementById('mobileCamErrorBox');
  const originalHtml = btn ? btn.innerHTML : '';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '🔍 Scanning...';
  }
  showToast('Scanning network for Android IP Webcam...');
  try {
    const resp = await fetch('/api/camera/ip-webcam/discover');
    const data = await resp.json();
    if (data.success && data.found && data.cameras && data.cameras.length > 0) {
      const cam = data.cameras[0];
      const rawUrl = cam.url || `http://${cam.host || cam.ip}:${cam.port || 8080}`;
      const streamUrl = rawUrl.replace(/\/video\/?$/i, '');
      if (input) input.value = streamUrl;
      if (errBox) errBox.style.display = 'none';
      showToast(`🎯 Found camera at ${cam.host || cam.ip}:${cam.port || 8080}! Connecting...`);
      await connectIpWebcam();
    } else {
      if (errBox) {
        errBox.style.display = 'block';
        const msgSpan = document.getElementById('mobileCamErrorMsg');
        if (msgSpan) msgSpan.textContent = 'Auto-detect found no IP Webcam broadcasting';
      }
      showToast('No active IP Webcam found. Ensure "Start server" is tapped in IP Webcam app.', true);
    }
  } catch (e) {
    showToast(`Discovery failed: ${e.message}`, true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalHtml;
    }
  }
}

async function fetchCameraDevices() {
  const select = document.getElementById('cameraDeviceSelect');
  if (!select) return;

  try {
    const resp = await fetch('/api/camera/devices');
    if (resp.ok) {
      const data = await resp.json();
      if (data.devices && data.devices.length > 0) {
        const currentVal = select.value;
        select.innerHTML = '';
        data.devices.forEach(d => {
          const opt = document.createElement('option');
          opt.value = d.index;
          opt.textContent = `${d.name} (${d.status})`;
          select.appendChild(opt);
        });
        if (currentVal) {
          select.value = currentVal;
        }
      }
    }
  } catch (e) {
    console.warn("Failed scanning cameras:", e);
  }
}

async function onCameraSelected(e) {
  const val = e.target.value;
  try {
    if (val === 'ip_webcam') {
      const panel = document.getElementById('mobileCamPanel');
      if (panel) panel.style.display = 'block';
    }
    const resp = await fetch('/api/camera/select', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ camera_source: val, camera_index: val })
    });
    const data = await resp.json();
    if (data.success) {
      showToast(`Camera switched to: ${val === 'ip_webcam' ? 'Mobile IP Webcam' : val}`);
      refreshVideoStream();
    } else {
      showToast(data.error || 'Error switching camera', true);
    }
  } catch (e) {
    showToast('Error switching camera', true);
  }
}

async function connectIpWebcam() {
  const input = document.getElementById('inputMobileIpUrl');
  const errBox = document.getElementById('mobileCamErrorBox');
  const errMsg = document.getElementById('mobileCamErrorMsg');
  const rawTarget = input ? input.value.trim() : '';
  const target = rawTarget.replace(/\/video\/?$/i, '');
  if (input && input.value !== target) {
    input.value = target;
  }

  if (!target) {
    showToast('Please enter your mobile phone IP address or URL', true);
    if (input) input.focus();
    return;
  }

  showToast('Connecting to Mobile IP Webcam...');
  try {
    const resp = await fetch('/api/camera/ip-webcam/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: target })
    });
    const data = await resp.json();
    if (data.success) {
      if (errBox) errBox.style.display = 'none';
      const cleanUrl = (data.url || target).replace(/\/video\/?$/i, '');
      localStorage.setItem('solarguard_ip_webcam_url', cleanUrl);
      if (input) input.value = cleanUrl;
      showToast(data.message || 'Connected to Mobile IP Webcam!');
      await fetchCameraDevices();
      const select = document.getElementById('cameraDeviceSelect');
      if (select) select.value = 'ip_webcam';
      refreshVideoStream();
    } else {
      if (errBox) {
        errBox.style.display = 'block';
        if (errMsg) errMsg.textContent = data.message || data.error || 'Connection failed';
      }
      showToast(data.error || data.message || 'Connection failed', true);
    }
  } catch (e) {
    if (errBox) {
      errBox.style.display = 'block';
      if (errMsg) errMsg.textContent = `Error: ${e.message}`;
    }
    showToast(`Failed connecting to mobile phone: ${e.message}`, true);
  }
}

async function testIpWebcam() {
  const input = document.getElementById('inputMobileIpUrl');
  const errBox = document.getElementById('mobileCamErrorBox');
  const errMsg = document.getElementById('mobileCamErrorMsg');
  const rawTarget = input ? input.value.trim() : '';
  const target = rawTarget.replace(/\/video\/?$/i, '');
  if (input && input.value !== target) {
    input.value = target;
  }

  showToast('Testing connection to mobile IP Webcam...');
  try {
    const resp = await fetch('/api/camera/ip-webcam/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: target })
    });
    const data = await resp.json();
    if (data.success) {
      if (errBox) errBox.style.display = 'none';
      const ms = data.details && data.details.latency_ms;
      const battery = data.details && data.details.battery;
      let msg = `✅ Phone reachable (${ms ? ms + 'ms' : 'OK'})`;
      if (battery !== undefined) msg += ` - Battery: ${battery}%`;
      showToast(msg);
    } else {
      if (errBox) {
        errBox.style.display = 'block';
        if (errMsg) errMsg.textContent = data.message || 'Phone unreachable on network';
      }
      showToast(data.message || 'Phone unreachable on network', true);
    }
  } catch (e) {
    if (errBox) {
      errBox.style.display = 'block';
      if (errMsg) errMsg.textContent = `Ping error: ${e.message}`;
    }
    showToast(`Test failed: ${e.message}`, true);
  }
}

async function controlIpWebcam(action) {
  try {
    const resp = await fetch('/api/camera/ip-webcam/control', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: action })
    });
    const data = await resp.json();
    if (data.success) {
      showToast(data.message);
      const lblTorch = document.getElementById('lblTorchText');
      if (lblTorch && data.torch_active !== undefined) {
        lblTorch.textContent = data.torch_active ? 'Torch OFF' : 'Torch ON';
      }
      const lblFacing = document.getElementById('lblCameraFacing');
      if (lblFacing && data.camera_facing) {
        lblFacing.textContent = (data.camera_facing === 'front') ? 'Switch Rear Cam' : 'Switch Front Cam';
      }
    } else {
      showToast(data.error || 'Control command failed', true);
    }
  } catch (e) {
    showToast('Failed to send mobile command', true);
  }
}

/**
 * Monitoring Controls
 */
async function startMonitoring() {
  try {
    const resp = await fetch('/api/detection/start', { method: 'POST' });
    const data = await resp.json();
    showToast(data.message || 'Continuous monitoring active');
  } catch (e) {
    showToast('Failed starting monitoring', true);
  }
}

async function stopMonitoring() {
  try {
    const resp = await fetch('/api/detection/stop', { method: 'POST' });
    const data = await resp.json();
    showToast(data.message || 'Monitoring stopped');
  } catch (e) {
    showToast('Failed stopping monitoring', true);
  }
}

async function triggerSingleScan() {
  try {
    showToast('Executing one-shot scan...');
    const resp = await fetch('/api/detection/scan', { method: 'POST' });
    const data = await resp.json();
    if (data.success && data.result) {
      showToast(`Scan complete: ${data.result.status} (${data.result.soiling_index}%)`);
      fetchStats();
      fetchHistoryTable();
    }
  } catch (e) {
    showToast('Scan execution failed', true);
  }
}

/**
 * ESP32 Wi-Fi Node Controls
 */
async function connectEsp32() {
  const ipInput = document.getElementById('espIpInput');
  if (!ipInput || !ipInput.value.trim()) {
    showToast('Please enter an ESP32 IP address', true);
    return;
  }

  const ip = ipInput.value.trim();
  showToast(`Pinging ESP32 at ${ip}...`);

  try {
    const resp = await fetch('/api/esp32/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ip })
    });
    const data = await resp.json();
    if (data.success) {
      showToast(`Connected to ESP32! Latency: ${data.latency_ms} ms`);
    } else {
      showToast(`ESP32 Connection Failed: ${data.message || 'Offline'}`, true);
    }
  } catch (e) {
    showToast('ESP32 ping failed: Network error', true);
  }
}

async function testEspLed(led, state) {
  try {
    const resp = await fetch('/api/esp32/test-led', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ led, state })
    });
    const data = await resp.json();
    if (data.success) {
      showToast(data.message);
    } else {
      showToast(`LED command failed: ${data.message || 'ESP32 offline'}`, true);
    }
  } catch (e) {
    showToast('Failed to send LED test command', true);
  }
}

async function testEspServo(angle, action) {
  try {
    const payload = {};
    if (angle !== null && angle !== undefined) payload.angle = angle;
    if (action) payload.action = action;
    const resp = await fetch('/api/esp32/test-servo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await resp.json();
    if (data.success) {
      showToast(data.message);
    } else {
      showToast(`Servo command failed: ${data.message || data.error || 'ESP32 offline'}`, true);
    }
  } catch (e) {
    showToast('Failed to send servo command', true);
  }
}

async function onAutoModeToggled(e) {
  const enabled = e.target.checked;
  try {
    await fetch('/api/settings/auto-mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled })
    });
    showToast(`ESP32 Auto Sync: ${enabled ? 'ENABLED' : 'DISABLED'}`);
  } catch (e) {
    showToast('Failed to update Auto Mode', true);
  }
}

/**
 * Clean Reference Image Management
 */
async function captureCleanReference() {
  try {
    showToast('Capturing clean solar panel reference...');
    const resp = await fetch('/api/reference/capture', { method: 'POST' });
    const data = await resp.json();
    if (data.success) {
      showToast('Clean reference captured and stored!');
      if (data.reference_base64) {
        const img = document.getElementById('referencePreviewImg');
        if (img) img.src = data.reference_base64;
      }
    } else {
      showToast(`Capture failed: ${data.error}`, true);
    }
  } catch (e) {
    showToast('Reference capture failed', true);
  }
}

async function uploadReferenceFile(e) {
  const file = e.target.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append('file', file);

  try {
    showToast('Uploading custom reference image...');
    const resp = await fetch('/api/reference/upload', {
      method: 'POST',
      body: formData
    });
    const data = await resp.json();
    if (data.success) {
      showToast('New clean reference image saved!');
      if (data.reference_base64) {
        const img = document.getElementById('referencePreviewImg');
        if (img) img.src = data.reference_base64;
      }
    } else {
      showToast(`Upload failed: ${data.error}`, true);
    }
  } catch (err) {
    showToast('File upload failed', true);
  }
}

async function fetchReferenceImage() {
  try {
    const resp = await fetch('/api/reference/view');
    if (resp.ok) {
      const data = await resp.json();
      if (data.success && data.reference_base64) {
        const img = document.getElementById('referencePreviewImg');
        if (img) img.src = data.reference_base64;
      }
    }
  } catch (e) {
    console.warn("Could not load reference preview:", e);
  }
}

/**
 * Simulation Mode Controls (Test Mode without Hardware)
 */
async function toggleSimulation(e) {
  const enabled = e.target.checked;
  try {
    const resp = await fetch('/api/simulation/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled })
    });
    const data = await resp.json();
    showToast(`Simulation Mode: ${data.simulation_mode ? 'ON' : 'OFF'}`);
  } catch (e) {
    showToast('Simulation toggle failed', true);
  }
}

async function setSimulatedDust(level) {
  try {
    await fetch('/api/simulation/dust-level', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ level: parseFloat(level) })
    });
  } catch (e) {
    console.warn("Failed to set simulated dust:", e);
  }
}

/**
 * Settings & Calibration Modal
 */
async function fetchInitialConfig() {
  try {
    const resp = await fetch('/api/settings');
    if (resp.ok) {
      const data = await resp.json();
      if (data.thresholds) {
        STATE.cleanThreshold = data.thresholds.clean;
        STATE.heavyThreshold = data.thresholds.heavy;

        const inClean = document.getElementById('settingCleanThreshold');
        const inHeavy = document.getElementById('settingHeavyThreshold');
        if (inClean) inClean.value = data.thresholds.clean;
        if (inHeavy) inHeavy.value = data.thresholds.heavy;
      }
      if (data.esp32_ip) {
        const ipIn = document.getElementById('espIpInput');
        if (ipIn) ipIn.value = data.esp32_ip;
      }
    }
  } catch (e) {
    console.warn("Failed fetching settings:", e);
  }
  fetchModelStatus();
  fetchHistoryTable();
}

async function saveThresholdSettings() {
  const inClean = document.getElementById('settingCleanThreshold');
  const inHeavy = document.getElementById('settingHeavyThreshold');
  const modalSettings = document.getElementById('modalSettings');

  if (!inClean || !inHeavy) return;

  const clean = parseFloat(inClean.value);
  const heavy = parseFloat(inHeavy.value);

  try {
    const resp = await fetch('/api/settings/threshold', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ clean, heavy })
    });
    const data = await resp.json();
    if (data.success) {
      STATE.cleanThreshold = clean;
      STATE.heavyThreshold = heavy;
      showToast('Thresholds updated and saved!');
      if (modalSettings) modalSettings.classList.remove('active');
    } else {
      showToast(`Error: ${data.error}`, true);
    }
  } catch (e) {
    showToast('Failed saving thresholds', true);
  }
}

/**
 * Model Training & Dataset Calibration
 */
async function fetchModelStatus() {
  try {
    const resp = await fetch('/api/model/status');
    if (resp.ok) {
      const data = await resp.json();
      if (data.success && data.model) {
        updateModelStatusUI(data.model);
      }
    }
  } catch (e) {
    console.warn("Failed fetching model status:", e);
  }
}

function updateModelStatusUI(model) {
  const badge = document.getElementById('modelAccuracyBadge');
  const datasetName = document.getElementById('modelDatasetName');
  const sampleCount = document.getElementById('modelSampleCount');

  if (badge) {
    badge.textContent = `${model.accuracy}% Accuracy`;
  }
  if (datasetName) {
    datasetName.textContent = `${model.dataset_name} (${(model.clean_samples || 0) + (model.dirty_samples || 0)} samples)`;
  }
  if (sampleCount) {
    sampleCount.textContent = `${model.clean_samples || 0} Clean, ${model.dirty_samples || 0} Dirty`;
  }
}

async function triggerModelTraining() {
  const btn = document.getElementById('btnTrainModel');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span style="display:inline-block; width:12px; height:12px; border:2px solid #ccc; border-top-color:var(--teal-primary); border-radius:50%; animation:spin 1s linear infinite; margin-right:6px;"></span> Calibrating Model...`;
  }
  showToast('Running computer vision training on dataset...');
  try {
    const resp = await fetch('/api/model/train', { method: 'POST' });
    const data = await resp.json();
    if (data.success) {
      showToast(`Training complete! Accuracy: ${data.accuracy}%, F1: ${data.f1_score}%`);
      fetchModelStatus();
      loadReferencePreview();
    } else {
      showToast(data.error || 'Model training failed', true);
    }
  } catch (e) {
    showToast(`Training error: ${e.message}`, true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="23 4 23 10 17 10"></polyline>
          <polyline points="1 20 1 14 7 14"></polyline>
          <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
        </svg>
        Re-Train & Calibrate Model
      `;
    }
  }
}

/**
 * History Table Rendering & CSV Export
 */
async function fetchHistoryTable() {
  const tbody = document.getElementById('historyTableBody');
  if (!tbody) return;

  try {
    const resp = await fetch('/api/detection/history?limit=15');
    if (resp.ok) {
      const data = await resp.json();
      if (data.success && data.history) {
        if (data.history.length === 0) {
          tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#64748b;">No detection events recorded yet.</td></tr>';
          return;
        }

        let html = '';
        data.history.forEach(row => {
          const d = new Date(row.timestamp);
          const timeStr = d.toLocaleTimeString([], { hour12: false });
          let badgeCls = 'clean';
          if (row.status === 'MODERATELY DUSTY') badgeCls = 'moderate';
          if (row.status === 'HEAVILY DUSTY') badgeCls = 'heavy';

          html += `
            <tr>
              <td>#${row.id}</td>
              <td>${timeStr}</td>
              <td><span class="badge-condition ${badgeCls}">${row.status}</span></td>
              <td style="font-family:var(--font-mono); font-weight:600;">${row.soiling_index}%</td>
              <td>${row.confidence}%</td>
              <td style="font-family:var(--font-mono); font-size:11px;">${escapeHtml(row.esp32_command_sent || 'NONE')}</td>
            </tr>
          `;
        });
        tbody.innerHTML = html;
      }
    }
  } catch (e) {
    console.warn("History fetch error:", e);
  }
}

async function exportHistoryCsv() {
  try {
    const resp = await fetch('/api/detection/history?limit=500');
    if (!resp.ok) return;
    const data = await resp.json();
    if (!data.history || data.history.length === 0) {
      showToast('No history available to export', true);
      return;
    }

    const headers = ['ID', 'Timestamp', 'Status', 'Soiling_Index', 'Confidence', 'SSIM', 'Texture_Loss', 'ESP32_Status', 'Command_Sent'];
    let csv = headers.join(',') + '\n';

    data.history.forEach(r => {
      const line = [
        r.id,
        `"${r.timestamp}"`,
        `"${r.status}"`,
        r.soiling_index,
        r.confidence,
        r.metric_ssim,
        r.metric_texture,
        `"${r.esp32_status}"`,
        `"${r.esp32_command_sent}"`
      ];
      csv += line.join(',') + '\n';
    });

    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', `solarguard_detection_history_${Date.now()}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast('Exported CSV successfully!');
  } catch (e) {
    showToast('Failed to export CSV', true);
  }
}

/**
 * Toast Notification Utility
 */
function showToast(message, isError = false) {
  let toastContainer = document.getElementById('solarguardToastContainer');
  if (!toastContainer) {
    toastContainer = document.createElement('div');
    toastContainer.id = 'solarguardToastContainer';
    toastContainer.style.position = 'fixed';
    toastContainer.style.bottom = '20px';
    toastContainer.style.right = '20px';
    toastContainer.style.zIndex = '9999';
    toastContainer.style.display = 'flex';
    toastContainer.style.flexDirection = 'column';
    toastContainer.style.gap = '8px';
    document.body.appendChild(toastContainer);
  }

  const toast = document.createElement('div');
  toast.style.padding = '10px 16px';
  toast.style.borderRadius = '8px';
  toast.style.fontSize = '13px';
  toast.style.fontWeight = '500';
  toast.style.color = '#fff';
  toast.style.backgroundColor = isError ? '#991b1b' : '#065f46';
  toast.style.border = isError ? '1px solid #ef4444' : '1px solid #10b981';
  toast.style.boxShadow = '0 4px 12px rgba(0,0,0,0.4)';
  toast.style.transition = 'opacity 0.3s ease';
  toast.textContent = message;

  toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 3200);
}

/**
 * Helpers
 */
function formatUptime(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

function escapeHtml(text) {
  if (!text) return '';
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
