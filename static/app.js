const elements = {
  statusPill: document.getElementById("gateStatusPill"),
  barrierArm: document.getElementById("barrierArm"),
  accessBanner: document.getElementById("accessBanner"),
  lastTicket: document.getElementById("lastTicket"),
  paymentStatus: document.getElementById("paymentStatus"),
  spotChip: document.getElementById("spotChip"),
  userName: document.getElementById("userName"),
  lastTimestamp: document.getElementById("lastTimestamp"),
  lastQrPayload: document.getElementById("lastQrPayload"),
  metricTotal: document.getElementById("metricTotal"),
  metricGranted: document.getElementById("metricGranted"),
  metricDenied: document.getElementById("metricDenied"),
  metricManual: document.getElementById("metricManual"),
  logTableBody: document.getElementById("logTableBody"),
  scannerVideo: document.getElementById("scannerVideo"),
  scannerStatus: document.getElementById("scannerStatus"),
  cameraSelect: document.getElementById("cameraSelect"),
  startScanner: document.getElementById("startScanner"),
  stopScanner: document.getElementById("stopScanner"),
  simulateValid: document.getElementById("simulateValid"),
  simulateUnpaid: document.getElementById("simulateUnpaid"),
  simulateExpired: document.getElementById("simulateExpired"),
  openGateManual: document.getElementById("openGateManual"),
  closeGateManual: document.getElementById("closeGateManual"),
  clearLog: document.getElementById("clearLog"),
  manualTicket: document.getElementById("manualTicket"),
  submitCustomTicket: document.getElementById("submitCustomTicket"),
};

const scannerState = {
  detector: null,
  stream: null,
  timer: null,
  isRunning: false,
  isSubmitting: false,
  canvas: document.createElement("canvas"),
  context: null,
  devices: [],
};

function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function titleize(value) {
  return String(value || "-")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function badgeClass(value) {
  const text = String(value || "").toLowerCase();
  if (text.includes("granted") || text.includes("opened")) return "granted";
  if (text.includes("denied") || text.includes("closed")) return "denied";
  return "manual";
}

function setScannerStatus(message) {
  elements.scannerStatus.textContent = message;
}

function populateCameraOptions(devices) {
  elements.cameraSelect.innerHTML = "";

  if (!devices.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No camera detected";
    elements.cameraSelect.appendChild(option);
    elements.cameraSelect.disabled = true;
    return;
  }

  elements.cameraSelect.disabled = false;
  devices.forEach((device, index) => {
    const option = document.createElement("option");
    option.value = device.deviceId;
    option.textContent = device.label || `Camera ${index + 1}`;
    elements.cameraSelect.appendChild(option);
  });
}

async function refreshCameraList() {
  if (!navigator.mediaDevices?.enumerateDevices) {
    populateCameraOptions([]);
    return;
  }

  const devices = await navigator.mediaDevices.enumerateDevices();
  scannerState.devices = devices.filter((device) => device.kind === "videoinput");
  populateCameraOptions(scannerState.devices);
}

function getSelectedDeviceId() {
  return elements.cameraSelect.value || scannerState.devices[0]?.deviceId || "";
}

function getVideoConstraints() {
  const deviceId = getSelectedDeviceId();
  if (deviceId) {
    return {
      deviceId: { exact: deviceId },
      width: { ideal: 1280 },
      height: { ideal: 720 },
    };
  }

  return {
    width: { ideal: 1280 },
    height: { ideal: 720 },
  };
}

function updateStatus(status) {
  const isOpen = status.gate_status === "OPEN";
  elements.statusPill.textContent = status.gate_status;
  elements.statusPill.className = `status-pill ${isOpen ? "open" : "closed"}`;
  elements.barrierArm.classList.toggle("open", isOpen);

  elements.lastTicket.textContent = status.last_ticket_code || "-";
  elements.lastQrPayload.textContent = status.last_qr_payload || "-";
  elements.paymentStatus.textContent = status.payment_status || "-";
  elements.spotChip.textContent = `Spot ${status.spot_number || "-"}`;
  elements.userName.textContent = status.user_name || "-";
  elements.lastTimestamp.textContent = formatTime(status.timestamp);

  const stats = status.stats || {};
  elements.metricTotal.textContent = stats.total_events ?? 0;
  elements.metricGranted.textContent = stats.granted_count ?? 0;
  elements.metricDenied.textContent = stats.denied_count ?? 0;
  elements.metricManual.textContent = stats.manual_actions ?? 0;

  const reasonText = status.reason ? ` - ${titleize(status.reason)}` : "";
  elements.accessBanner.textContent = `${status.validation_result}${reasonText}`.trim();
  elements.accessBanner.className = "access-banner neutral";

  if (status.validation_result === "ACCESS GRANTED") {
    elements.accessBanner.classList.add("granted");
  } else if (status.validation_result === "ACCESS DENIED") {
    elements.accessBanner.classList.add("denied");
  } else if (status.validation_result === "MANUAL OPEN") {
    elements.accessBanner.classList.add("manual");
  } else {
    elements.accessBanner.classList.add("neutral");
  }
}

function renderLogs(logs) {
  elements.logTableBody.innerHTML = "";

  if (!logs.length) {
    const row = document.createElement("tr");
    row.className = "empty-row";
    row.innerHTML = `<td colspan="5">No access events recorded yet.</td>`;
    elements.logTableBody.appendChild(row);
    return;
  }

  for (const entry of logs) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${formatTime(entry.timestamp)}</td>
      <td class="mono">${entry.ticket_code || "-"}</td>
      <td><span class="result-tag ${badgeClass(entry.result)}">${titleize(entry.result)}</span></td>
      <td><span class="result-tag ${badgeClass(entry.gate_action)}">${titleize(entry.gate_action)}</span></td>
      <td>${titleize(entry.reason)}</td>
    `;
    elements.logTableBody.appendChild(row);
  }
}

async function requestJSON(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || `${response.status} ${response.statusText}`);
  }
  if (response.status === 204) return null;
  return response.json();
}

async function refreshSnapshot() {
  const [status, logs] = await Promise.all([
    requestJSON("/api/gate/status"),
    requestJSON("/api/access-log"),
  ]);
  updateStatus(status);
  renderLogs(logs);
}

function connectWebSocket() {
  const socket = new WebSocket(window.SMARTS_CONFIG.wsUrl);

  socket.addEventListener("message", (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === "snapshot") {
        updateStatus(payload.status);
        renderLogs(payload.logs || []);
      }
    } catch (error) {
      console.error("Failed to parse WebSocket payload", error);
    }
  });

  socket.addEventListener("close", () => {
    window.setTimeout(connectWebSocket, 1500);
  });

  return socket;
}

async function validateTicket(payload) {
  return requestJSON("/api/validate-ticket", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

async function openGate() {
  await requestJSON("/api/gate/open", {
    method: "POST",
    body: JSON.stringify({ reason: "manual_override" }),
  });
}

async function closeGate() {
  await requestJSON("/api/gate/close", {
    method: "POST",
    body: JSON.stringify({ reason: "manual_close" }),
  });
}

async function clearLog() {
  await requestJSON("/api/access-log/clear", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

async function stopScanner({ silent = false } = {}) {
  scannerState.isRunning = false;

  if (scannerState.timer) {
    window.clearTimeout(scannerState.timer);
    scannerState.timer = null;
  }

  if (scannerState.stream) {
    for (const track of scannerState.stream.getTracks()) {
      track.stop();
    }
    scannerState.stream = null;
  }

  elements.scannerVideo.pause();
  elements.scannerVideo.srcObject = null;

  if (!silent) {
    setScannerStatus("Scanner stopped.");
  }
}

function decodeWithJsQr() {
  const video = elements.scannerVideo;
  if (!video.videoWidth || !video.videoHeight || typeof window.jsQR !== "function") {
    return null;
  }

  scannerState.canvas.width = video.videoWidth;
  scannerState.canvas.height = video.videoHeight;
  scannerState.context = scannerState.context || scannerState.canvas.getContext("2d", { willReadFrequently: true });

  if (!scannerState.context) {
    return null;
  }

  scannerState.context.drawImage(video, 0, 0, scannerState.canvas.width, scannerState.canvas.height);
  const imageData = scannerState.context.getImageData(0, 0, scannerState.canvas.width, scannerState.canvas.height);
  const result = window.jsQR(imageData.data, imageData.width, imageData.height, {
    inversionAttempts: "dontInvert",
  });

  return result?.data || null;
}

async function decodeQrPayload() {
  if (scannerState.detector) {
    const codes = await scannerState.detector.detect(elements.scannerVideo);
    const qrCode = codes.find((code) => code.rawValue && code.rawValue.trim());
    return qrCode?.rawValue?.trim() || null;
  }

  return decodeWithJsQr();
}

async function scanLoop() {
  if (!scannerState.isRunning || !scannerState.stream) {
    return;
  }

  try {
    const rawValue = await decodeQrPayload();

    if (rawValue && !scannerState.isSubmitting) {
      scannerState.isSubmitting = true;
      elements.lastQrPayload.textContent = rawValue;
      setScannerStatus("QR detected. Validating ticket...");

      try {
        await validateTicket({ qr_data: rawValue });
        await stopScanner({ silent: true });
        setScannerStatus("QR detected and validation sent.");
      } catch (error) {
        setScannerStatus(`Validation failed: ${error.message}`);
      } finally {
        scannerState.isSubmitting = false;
      }
      return;
    }
  } catch (error) {
    console.error("QR scan failed", error);
    setScannerStatus("Camera is live, but the frame could not be decoded yet.");
  }

  scannerState.timer = window.setTimeout(scanLoop, 180);
}

function getDecoderModeLabel() {
  if (scannerState.detector) {
    return "BarcodeDetector";
  }
  if (typeof window.jsQR === "function") {
    return "jsQR";
  }
  return "none";
}

async function startScanner() {
  if (!navigator.mediaDevices?.getUserMedia) {
    setScannerStatus("Camera access is not available in this browser.");
    return;
  }

  if (scannerState.isRunning) {
    return;
  }

  if ("BarcodeDetector" in window) {
    scannerState.detector = new window.BarcodeDetector({ formats: ["qr_code"] });
  } else {
    scannerState.detector = null;
  }

  if (!scannerState.detector && typeof window.jsQR !== "function") {
    setScannerStatus("QR decoding is not available in this browser.");
    return;
  }

  try {
    scannerState.stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: getVideoConstraints(),
    });

    elements.scannerVideo.srcObject = scannerState.stream;
    await elements.scannerVideo.play();
    scannerState.isRunning = true;
    await refreshCameraList();
    setScannerStatus(`Scanner active on your computer camera using ${getDecoderModeLabel()}.`);
    scanLoop();
  } catch (error) {
    console.error("Unable to start scanner", error);
    await stopScanner({ silent: true });
    setScannerStatus(`Unable to start camera: ${error.message}`);
  }
}

async function handleCameraChange() {
  if (!scannerState.isRunning) {
    return;
  }

  await stopScanner({ silent: true });
  await startScanner();
}

async function runAction(action, failureMessage) {
  try {
    await action();
  } catch (error) {
    console.error(error);
    setScannerStatus(failureMessage ? `${failureMessage}: ${error.message}` : error.message);
  }
}

elements.simulateValid.addEventListener("click", () => runAction(
  () => validateTicket({ ticket_code: elements.simulateValid.dataset.ticket }),
  "Valid ticket simulation failed",
));

elements.simulateUnpaid.addEventListener("click", () => runAction(
  () => validateTicket({ ticket_code: elements.simulateUnpaid.dataset.ticket }),
  "Upcoming ticket simulation failed",
));

elements.simulateExpired.addEventListener("click", () => runAction(
  () => validateTicket({ ticket_code: elements.simulateExpired.dataset.ticket }),
  "Expired ticket simulation failed",
));

elements.openGateManual.addEventListener("click", () => runAction(openGate, "Manual open failed"));
elements.closeGateManual.addEventListener("click", () => runAction(closeGate, "Manual close failed"));
elements.clearLog.addEventListener("click", () => runAction(clearLog, "Log clear failed"));
elements.startScanner.addEventListener("click", () => runAction(startScanner, "Scanner start failed"));
elements.stopScanner.addEventListener("click", () => runAction(() => stopScanner(), "Scanner stop failed"));
elements.cameraSelect.addEventListener("change", () => runAction(handleCameraChange, "Camera switch failed"));

elements.submitCustomTicket.addEventListener("click", () => runAction(async () => {
  const value = elements.manualTicket.value.trim();
  if (!value) {
    setScannerStatus("Enter a ticket code or QR payload first.");
    return;
  }
  await validateTicket({ qr_data: value });
  elements.manualTicket.value = "";
}, "Manual validation failed"));

elements.manualTicket.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") {
    return;
  }

  event.preventDefault();
  elements.submitCustomTicket.click();
});

window.addEventListener("beforeunload", () => {
  stopScanner({ silent: true }).catch(() => undefined);
});

refreshSnapshot().catch((error) => console.error(error));
refreshCameraList().catch((error) => console.error("Unable to list cameras", error));
connectWebSocket();
