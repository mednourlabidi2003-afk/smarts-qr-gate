const elements = {
  statusPill: document.getElementById("gateStatusPill"),
  barrierArm: document.getElementById("barrierArm"),
  gateStateTitle: document.getElementById("gateStateTitle"),
  gateReason: document.getElementById("gateReason"),
  scannerVideo: document.getElementById("scannerVideo"),
  scannerStatus: document.getElementById("scannerStatus"),
  startScanner: document.getElementById("startScanner"),
  stopScanner: document.getElementById("stopScanner"),
};

const scannerState = {
  detector: null,
  stream: null,
  timer: null,
  isRunning: false,
  isSubmitting: false,
  canvas: document.createElement("canvas"),
  context: null,
};

const reasonCopy = {
  "Waiting for QR ticket scan.": "Closed while waiting for a QR ticket.",
  invalid_ticket_format: "Closed because the QR ticket format is invalid.",
  ticket_not_found: "Closed because the ticket was not found.",
  spot_mismatch: "Closed because the reserved spot does not match.",
  plate_mismatch: "Closed because the vehicle plate does not match.",
  booking_not_started: "Closed because the booking has not started yet.",
  booking_expired: "Closed because the booking has expired.",
  valid_booking: "Opened because the QR ticket is valid.",
  manual_override: "Opened manually by the operator.",
  manual_close: "Closed by the operator.",
  auto_close: "Closed automatically after the vehicle passed.",
};

function setScannerStatus(message) {
  elements.scannerStatus.textContent = message;
}

function describeGate(status) {
  if (status.reason && reasonCopy[status.reason]) {
    return reasonCopy[status.reason];
  }

  if (status.gate_status === "OPEN") {
    return "Opened after successful QR validation.";
  }

  return "Closed while waiting for a valid QR ticket.";
}

function updateStatus(status) {
  const isOpen = status.gate_status === "OPEN";
  elements.statusPill.textContent = status.gate_status;
  elements.statusPill.className = `status-pill ${isOpen ? "open" : "closed"}`;
  elements.barrierArm.classList.toggle("open", isOpen);
  elements.gateStateTitle.textContent = isOpen ? "Gate open" : "Gate closed";
  elements.gateReason.textContent = describeGate(status);
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

async function refreshStatus() {
  updateStatus(await requestJSON("/api/gate/status"));
}

function connectWebSocket() {
  const socket = new WebSocket(window.SMARTS_CONFIG.wsUrl);

  socket.addEventListener("message", (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === "snapshot") {
        updateStatus(payload.status);
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
    setScannerStatus("Camera is live, but the QR code is not readable yet.");
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
      video: {
        facingMode: { ideal: "environment" },
        width: { ideal: 1280 },
        height: { ideal: 720 },
      },
    });

    elements.scannerVideo.srcObject = scannerState.stream;
    await elements.scannerVideo.play();
    scannerState.isRunning = true;
    setScannerStatus(`Scanner active using ${getDecoderModeLabel()}.`);
    scanLoop();
  } catch (error) {
    console.error("Unable to start scanner", error);
    await stopScanner({ silent: true });
    setScannerStatus(`Unable to start camera: ${error.message}`);
  }
}

async function runAction(action, failureMessage) {
  try {
    await action();
  } catch (error) {
    console.error(error);
    setScannerStatus(`${failureMessage}: ${error.message}`);
  }
}

elements.startScanner.addEventListener("click", () => runAction(startScanner, "Scanner start failed"));
elements.stopScanner.addEventListener("click", () => runAction(() => stopScanner(), "Scanner stop failed"));

window.addEventListener("beforeunload", () => {
  stopScanner({ silent: true }).catch(() => undefined);
});

refreshStatus().catch((error) => console.error(error));
connectWebSocket();
