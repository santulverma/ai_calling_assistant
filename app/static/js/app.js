// Real-Time AI Calling Agent Frontend Controller

document.addEventListener("DOMContentLoaded", () => {
    initTabs();
    initDialer();
    initBrowserMicCall();
    initDashboardWebSocket();
    initDataTables();
});

// --- Tab Switching Logic ---
function initTabs() {
    const navButtons = document.querySelectorAll(".nav-btn");
    const tabContents = document.querySelectorAll(".tab-content");

    navButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            const targetTab = btn.getAttribute("data-tab");
            navButtons.forEach(b => b.classList.remove("active"));
            tabContents.forEach(tc => tc.classList.remove("active"));

            btn.classList.add("active");
            const activeContent = document.getElementById(`tab-${targetTab}`);
            if (activeContent) {
                activeContent.classList.add("active");
            }

            if (targetTab === "calls") loadCallLogs();
            if (targetTab === "leads") loadLeads();
            if (targetTab === "appointments") loadAppointments();
        });
    });
}

// --- Outbound Dialer Submission ---
function initDialer() {
    const form = document.getElementById("dialForm");
    const btnDial = document.getElementById("btnDial");
    const statusAlert = document.getElementById("dialStatusAlert");

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        
        const phone = document.getElementById("phoneNumber").value.trim();
        const name = document.getElementById("prospectName").value.trim();
        const company = document.getElementById("companyName").value.trim();
        const email = document.getElementById("prospectEmail").value.trim();
        const provider = document.getElementById("telephonyProvider")?.value || "exotel";

        if (!phone) return;

        btnDial.disabled = true;
        btnDial.innerHTML = `<span class="btn-icon">⏳</span><span>Connecting via ${provider.toUpperCase()}...</span>`;
        statusAlert.className = "dial-status-alert hidden";

        try {
            const res = await fetch("/api/calls/dial", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    phone_number: phone,
                    name: name,
                    company: company,
                    email: email,
                    provider: provider
                })
            });

            const data = await res.json();
            if (res.ok) {
                if (data.call_response?.status === "error") {
                    statusAlert.className = "dial-status-alert error";
                    let errMsg = data.call_response?.error || data.call_response?.message || "Unknown error";
                    try {
                        const parsed = JSON.parse(errMsg);
                        if (parsed.errors && parsed.errors.length > 0) {
                            errMsg = parsed.errors.map(e => e.detail || e.title).join(", ");
                        }
                    } catch (e) {}
                    statusAlert.textContent = `${data.provider?.toUpperCase()} Error: ${errMsg}`;
                    updateCallState("Call Failed", false);
                    return;
                }
                statusAlert.className = "dial-status-alert success";
                statusAlert.textContent = `Call dispatched via ${data.provider?.toUpperCase()}! Call ID: ${data.call_response?.call_control_id || 'Active'}. Waiting for answer...`;
                updateCallState("Calling / Ringing...", true);
                activatePipelineStep("node-plivo");
            } else {
                statusAlert.className = "dial-status-alert error";
                statusAlert.textContent = `Error initiating call: ${data.detail || JSON.stringify(data)}`;
            }
        } catch (err) {
            statusAlert.className = "dial-status-alert error";
            statusAlert.textContent = `Network error: ${err.message}`;
        } finally {
            btnDial.disabled = false;
            btnDial.innerHTML = `<span class="btn-icon">⚡</span><span>Dial Phone via Carrier</span>`;
        }
    });
}

// --- In-Browser Microphone Real-Time Calling (100% Free Live Testing) ---
let browserWs = null;
let micStream = null;
let micAudioCtx = null;
let micProcessor = null;
let micSource = null;
let micGain = null;
let speakerAudioCtx = null;
let activeAudioSources = [];
let isBrowserCalling = false;
let isStartingCall = false;
let nextSpeakerPlayTime = 0;
let isAgentSpeakingLocally = false;

function initBrowserMicCall() {
    const btn = document.getElementById("btnBrowserMicCall");
    if (!btn) return;

    btn.addEventListener("click", async (e) => {
        e.preventDefault();
        if (isStartingCall) return;
        if (!isBrowserCalling) {
            await startBrowserCall();
        } else {
            stopBrowserCall();
        }
    });
}

async function startBrowserCall() {
    const btn = document.getElementById("btnBrowserMicCall");
    const statusAlert = document.getElementById("dialStatusAlert");
    const name = document.getElementById("prospectName")?.value.trim() || "Santul";
    const company = document.getElementById("companyName")?.value.trim() || "ApexGrowth";

    isStartingCall = true;
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span class="btn-icon">⏳</span><span>Requesting Mic...</span>`;
    }
    if (statusAlert) {
        statusAlert.className = "dial-status-alert";
        statusAlert.textContent = "Requesting microphone permission...";
    }

    try {
        // 1. Validate secure context / getUserMedia support
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            throw new Error("Microphone API not available. If accessing remotely, please ensure you use HTTPS or http://localhost:8000.");
        }

        // 2. Initialize Web Audio contexts right inside the user gesture
        const AudioCtxClass = window.AudioContext || window.webkitAudioContext;
        if (!micAudioCtx || micAudioCtx.state === "closed") {
            micAudioCtx = new AudioCtxClass();
        }
        if (micAudioCtx.state === "suspended") {
            await micAudioCtx.resume();
        }

        if (!speakerAudioCtx || speakerAudioCtx.state === "closed") {
            speakerAudioCtx = new AudioCtxClass();
        }
        if (speakerAudioCtx.state === "suspended") {
            await speakerAudioCtx.resume();
        }

        // 3. Request user microphone (clean constraints without hardcoded sampleRate)
        micStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true
            }
        });

        if (statusAlert) {
            statusAlert.textContent = "Connecting to AI Voice Engine...";
        }

        // 4. Open WebSocket to /ws/browser
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${protocol}//${window.location.host}/ws/browser?lead_name=${encodeURIComponent(name)}&company=${encodeURIComponent(company)}`;
        browserWs = new WebSocket(wsUrl);

        browserWs.onopen = () => {
            isBrowserCalling = true;
            isStartingCall = false;
            if (btn) {
                btn.disabled = false;
                btn.classList.add("calling");
                btn.innerHTML = `<span class="btn-icon">🛑</span><span>End Browser Call</span>`;
            }
            if (statusAlert) {
                statusAlert.className = "dial-status-alert success";
                statusAlert.textContent = "Live browser call connected! AI is speaking the greeting; reply into your microphone.";
            }
            updateCallState("Browser Call Connected (Live)", true);
            setupMicAudioProcessing();
        };

        browserWs.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                if (msg.type === "audio" && msg.audio) {
                    playIncomingAudio(msg.audio, msg.format || "mulaw");
                } else if (msg.type === "clear_audio") {
                    stopAllActiveAudio();
                }
            } catch (e) {
                console.error("Error processing browser audio msg:", e);
            }
        };

        browserWs.onclose = () => {
            stopBrowserCall();
        };

        browserWs.onerror = (err) => {
            console.error("Browser call WS error:", err);
            stopBrowserCall();
        };

    } catch (err) {
        console.error("Could not start browser call:", err);
        if (statusAlert) {
            statusAlert.className = "dial-status-alert error";
            statusAlert.textContent = "Microphone Error: " + (err.message || err.name);
        } else {
            alert("Could not access microphone: " + (err.message || err.name));
        }
        isStartingCall = false;
        stopBrowserCall();
    }
}

function setupMicAudioProcessing() {
    if (!micAudioCtx || !micStream) return;

    micSource = micAudioCtx.createMediaStreamSource(micStream);
    micProcessor = micAudioCtx.createScriptProcessor(4096, 1, 1);

    // MUTE gain node: connect processor to a 0-gain node so user mic is NEVER played out of speakers!
    micGain = micAudioCtx.createGain();
    micGain.gain.value = 0;
    micSource.connect(micProcessor);
    micProcessor.connect(micGain);
    micGain.connect(micAudioCtx.destination);

    const inputSampleRate = micAudioCtx.sampleRate;

    micProcessor.onaudioprocess = (e) => {
        if (!isBrowserCalling || !browserWs || browserWs.readyState !== WebSocket.OPEN) return;

        const inputData = e.inputBuffer.getChannelData(0);

        // Echo Guard: While agent is speaking, ignore faint acoustic bleed unless user speaks clearly to barge in
        if (isAgentSpeakingLocally) {
            let sum = 0;
            for (let i = 0; i < inputData.length; i++) {
                sum += inputData[i] * inputData[i];
            }
            const rms = Math.sqrt(sum / inputData.length);
            if (rms < 0.02) {
                return; // Suppress faint speaker echo
            }
        }

        // Downsample input from hardware sample rate (e.g. 48000/44100) to 16000Hz for Sarvam STT
        const resampled = downsampleTo16k(inputData, inputSampleRate);

        const pcm16 = new Int16Array(resampled.length);
        for (let i = 0; i < resampled.length; i++) {
            let s = Math.max(-1, Math.min(1, resampled[i]));
            pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }

        const b64 = arrayBufferToBase64(pcm16.buffer);
        browserWs.send(JSON.stringify({ type: "audio", audio: b64 }));
    };
}

function downsampleTo16k(buffer, inputSampleRate) {
    if (inputSampleRate === 16000) return buffer;
    const ratio = inputSampleRate / 16000;
    const newLength = Math.round(buffer.length / ratio);
    const result = new Float32Array(newLength);
    let offsetResult = 0;
    let offsetBuffer = 0;
    while (offsetResult < result.length) {
        const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
        let accum = 0, count = 0;
        for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
            accum += buffer[i];
            count++;
        }
        result[offsetResult] = count > 0 ? accum / count : 0;
        offsetResult++;
        offsetBuffer = nextOffsetBuffer;
    }
    return result;
}

function playIncomingAudio(b64Audio, format = "mulaw") {
    if (!speakerAudioCtx || speakerAudioCtx.state === "closed") {
        speakerAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (speakerAudioCtx.state === "suspended") {
        speakerAudioCtx.resume();
    }

    const binaryString = window.atob(b64Audio);
    const len = binaryString.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
        bytes[i] = binaryString.charCodeAt(i);
    }

    let pcmSamples;
    let srcRate = 8000;

    if (format === "mulaw") {
        pcmSamples = decodeMulawToPcm(bytes);
        srcRate = 8000;
    } else {
        pcmSamples = new Int16Array(bytes.buffer);
        srcRate = 16000;
    }

    // Upsample directly to speakerAudioCtx.sampleRate (e.g. 44100 / 48000) so createBuffer is 100% supported on all browsers
    const targetRate = speakerAudioCtx.sampleRate;
    const floatSamples = resampleFloat(pcmSamples, srcRate, targetRate);

    const audioBuffer = speakerAudioCtx.createBuffer(1, floatSamples.length, targetRate);
    audioBuffer.getChannelData(0).set(floatSamples);

    const source = speakerAudioCtx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(speakerAudioCtx.destination);

    // Audio Playback Queue: Schedule seamlessly after current chunk so sentences NEVER play simultaneously!
    const currentTime = speakerAudioCtx.currentTime;
    if (nextSpeakerPlayTime < currentTime) {
        nextSpeakerPlayTime = currentTime + 0.02; // Small 20ms onset
    }
    source.start(nextSpeakerPlayTime);
    nextSpeakerPlayTime += audioBuffer.duration;

    isAgentSpeakingLocally = true;
    activeAudioSources.push(source);

    source.onended = () => {
        const idx = activeAudioSources.indexOf(source);
        if (idx !== -1) activeAudioSources.splice(idx, 1);
        if (activeAudioSources.length === 0) {
            isAgentSpeakingLocally = false;
        }
    };
}

function resampleFloat(int16Samples, fromRate, toRate) {
    if (fromRate === toRate) {
        const out = new Float32Array(int16Samples.length);
        for (let i = 0; i < int16Samples.length; i++) out[i] = int16Samples[i] / 32768.0;
        return out;
    }
    const ratio = toRate / fromRate;
    const outLength = Math.round(int16Samples.length * ratio);
    const output = new Float32Array(outLength);
    for (let i = 0; i < outLength; i++) {
        const srcPos = i / ratio;
        const srcIdx = Math.floor(srcPos);
        const frac = srcPos - srcIdx;
        const s1 = int16Samples[srcIdx] || 0;
        const s2 = int16Samples[Math.min(srcIdx + 1, int16Samples.length - 1)] || 0;
        output[i] = (s1 + frac * (s2 - s1)) / 32768.0;
    }
    return output;
}

function decodeMulawToPcm(mulawBytes) {
    const pcm = new Int16Array(mulawBytes.length);
    for (let i = 0; i < mulawBytes.length; i++) {
        let byte = ~mulawBytes[i] & 0xFF;
        let sign = byte & 0x80;
        let exponent = (byte >> 4) & 0x07;
        let mantissa = byte & 0x0F;
        let sample = (mantissa << 3) + 0x84;
        sample <<= exponent;
        sample -= 0x84;
        pcm[i] = sign === 0 ? -sample : sample;
    }
    return pcm;
}

function stopAllActiveAudio() {
    activeAudioSources.forEach(src => {
        try { src.stop(); } catch (e) {}
    });
    activeAudioSources = [];
    nextSpeakerPlayTime = 0;
    isAgentSpeakingLocally = false;
}

function stopBrowserCall() {
    isBrowserCalling = false;
    isStartingCall = false;
    stopAllActiveAudio();

    if (micProcessor) {
        try {
            micProcessor.disconnect();
            micProcessor.onaudioprocess = null;
        } catch(e) {}
        micProcessor = null;
    }
    if (micSource) {
        try { micSource.disconnect(); } catch(e) {}
        micSource = null;
    }
    if (micGain) {
        try { micGain.disconnect(); } catch(e) {}
        micGain = null;
    }
    if (micStream) {
        micStream.getTracks().forEach(track => track.stop());
        micStream = null;
    }
    if (micAudioCtx) {
        try { micAudioCtx.close(); } catch(e) {}
        micAudioCtx = null;
    }
    if (browserWs) {
        try {
            if (browserWs.readyState === WebSocket.OPEN) {
                browserWs.send(JSON.stringify({ type: "stop" }));
            }
            browserWs.close();
        } catch(e) {}
        browserWs = null;
    }

    const btn = document.getElementById("btnBrowserMicCall");
    if (btn) {
        btn.disabled = false;
        btn.classList.remove("calling");
        btn.innerHTML = `<span class="btn-icon">🎙️</span><span>Talk Live with Computer Mic</span>`;
    }
    updateCallState("Standby / Idle", false);
}

function arrayBufferToBase64(buffer) {
    let binary = '';
    const bytes = new Uint8Array(buffer);
    const len = bytes.byteLength;
    for (let i = 0; i < len; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return window.btoa(binary);
}

// --- Real-Time WebSocket for Live Transcripts & Pipeline Visualization ---
let dashboardWs = null;

function initDashboardWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/dashboard`;

    try {
        dashboardWs = new WebSocket(wsUrl);

        dashboardWs.onopen = () => {
            console.log("Connected to dashboard live WebSocket feed.");
            setInterval(() => {
                if (dashboardWs && dashboardWs.readyState === WebSocket.OPEN) {
                    dashboardWs.send("ping");
                }
            }, 25000);
        };

        dashboardWs.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                handleLiveUpdate(msg);
            } catch (err) {
                console.error("Could not parse dashboard WS message:", err);
            }
        };

        dashboardWs.onclose = () => {
            console.log("Dashboard WS disconnected. Reconnecting in 3s...");
            setTimeout(initDashboardWebSocket, 3000);
        };
    } catch (e) {
        console.warn("WebSocket init error:", e);
    }
}

function handleLiveUpdate(msg) {
    if (msg.type === "transcript") {
        updateCallState("In-Progress (Connected)", true);
        appendTranscriptBubble(msg.speaker, msg.text, msg.timestamp);

        if (msg.speaker === "callee") {
            activatePipelineStep("node-caller");
            setTimeout(() => activatePipelineStep("node-stt"), 300);
            setTimeout(() => activatePipelineStep("node-gemini"), 600);
        } else if (msg.speaker === "agent") {
            activatePipelineStep("node-tts");
            setTimeout(() => activatePipelineStep("node-plivo"), 300);
            setTimeout(() => activatePipelineStep("node-caller"), 600);
        }
    }
}

function appendTranscriptBubble(speaker, text, timestamp) {
    const feed = document.getElementById("liveTranscriptFeed");
    const placeholder = feed.querySelector(".empty-feed-placeholder");
    if (placeholder) placeholder.remove();

    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${speaker}`;

    const timeStr = timestamp ? new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : "";
    const speakerLabel = speaker === "agent" ? "Riya (AI)" : "Customer";

    bubble.innerHTML = `
        <div class="bubble-meta">
            <strong>${speakerLabel}</strong>
            <span>${timeStr}</span>
        </div>
        <div class="bubble-text">${escapeHtml(text)}</div>
    `;

    feed.appendChild(bubble);
    feed.scrollTop = feed.scrollHeight;
}

function updateCallState(label, isActive) {
    const pill = document.getElementById("liveCallStatePill");
    const stateLabel = document.getElementById("callStateLabel");
    if (!pill || !stateLabel) return;
    stateLabel.textContent = label;
    if (isActive) {
        pill.classList.add("active");
    } else {
        pill.classList.remove("active");
    }
}

function activatePipelineStep(nodeId) {
    const node = document.getElementById(nodeId);
    if (!node) return;
    node.classList.add("active");
    setTimeout(() => {
        node.classList.remove("active");
    }, 1500);
}

// --- Data Tables (Calls, Leads, Appointments) ---
function initDataTables() {
    document.getElementById("btnRefreshCalls")?.addEventListener("click", loadCallLogs);
    document.getElementById("btnRefreshAppts")?.addEventListener("click", loadAppointments);

    document.getElementById("btnCloseModal")?.addEventListener("click", () => {
        document.getElementById("transcriptModal").classList.add("hidden");
    });
}

async function loadCallLogs() {
    const tbody = document.getElementById("callLogsTableBody");
    try {
        const res = await fetch("/api/calls/logs");
        const calls = await res.json();
        if (calls.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="loading-cell">No calls logged yet. Initiate your first call!</td></tr>`;
            return;
        }

        tbody.innerHTML = calls.map(c => `
            <tr>
                <td>#${c.id}</td>
                <td><strong>${escapeHtml(c.phone_number)}</strong></td>
                <td><span class="status-val badge-${c.status === 'completed' ? 'plivo' : 'gemini'}">${escapeHtml(c.status)}</span></td>
                <td>${c.duration}s</td>
                <td>${c.qualification || 'Pending'}</td>
                <td>${c.created_at || 'Just now'}</td>
                <td>
                    <button class="btn-secondary" onclick="viewTranscript(${c.id})">View Transcript</button>
                </td>
            </tr>
        `).join("");
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="7" class="loading-cell error">Failed to load calls: ${e.message}</td></tr>`;
    }
}

async function loadLeads() {
    const tbody = document.getElementById("leadsTableBody");
    try {
        const res = await fetch("/api/leads");
        const leads = await res.json();
        if (leads.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="loading-cell">No leads yet.</td></tr>`;
            return;
        }

        tbody.innerHTML = leads.map(l => `
            <tr>
                <td><strong>${escapeHtml(l.name)}</strong></td>
                <td>${escapeHtml(l.phone)}</td>
                <td>${escapeHtml(l.company || '-')}</td>
                <td><span class="status-val badge-plivo">${escapeHtml(l.status)}</span></td>
                <td>${escapeHtml(l.notes || '-')}</td>
                <td>
                    <button class="btn-secondary" onclick="quickDial('${l.phone}', '${escapeHtml(l.name)}')">Call</button>
                </td>
            </tr>
        `).join("");
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="6" class="loading-cell error">Failed to load leads: ${e.message}</td></tr>`;
    }
}

async function loadAppointments() {
    const tbody = document.getElementById("appointmentsTableBody");
    try {
        const res = await fetch("/api/appointments");
        const appts = await res.json();
        if (appts.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="loading-cell">No audits booked yet. Once a lead agrees on the phone, the AI will automatically book it!</td></tr>`;
            return;
        }

        tbody.innerHTML = appts.map(a => `
            <tr>
                <td><strong>${escapeHtml(a.customer_name)}</strong></td>
                <td>${escapeHtml(a.customer_phone)}</td>
                <td>${escapeHtml(a.customer_email || '-')}</td>
                <td><strong style="color: var(--accent-cyan);">${escapeHtml(a.slot_time)}</strong></td>
                <td>${escapeHtml(a.notes || '-')}</td>
                <td>${a.created_at}</td>
            </tr>
        `).join("");
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="6" class="loading-cell error">Failed to load audits: ${e.message}</td></tr>`;
    }
}

window.viewTranscript = async function(callId) {
    const modal = document.getElementById("transcriptModal");
    const content = document.getElementById("modalTranscriptContent");
    modal.classList.remove("hidden");
    content.innerHTML = "Loading conversation...";

    try {
        const res = await fetch(`/api/calls/${callId}/transcript`);
        const messages = await res.json();
        if (messages.length === 0) {
            content.innerHTML = "<p>No messages recorded for this call.</p>";
            return;
        }

        content.innerHTML = messages.map(m => `
            <div class="chat-bubble ${m.speaker}" style="max-width: 100%;">
                <div class="bubble-meta">
                    <strong>${m.speaker === 'agent' ? 'AI Agent' : 'Customer'}</strong>
                    <span>${m.timestamp || ''}</span>
                </div>
                <div class="bubble-text">${escapeHtml(m.text)}</div>
            </div>
        `).join("");
    } catch (err) {
        content.innerHTML = `<p class="error">Error loading transcript: ${err.message}</p>`;
    }
};

window.quickDial = function(phone, name) {
    document.querySelector('.nav-btn[data-tab="dialer"]').click();
    document.getElementById("phoneNumber").value = phone;
    if (name) document.getElementById("prospectName").value = name;
};

function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
