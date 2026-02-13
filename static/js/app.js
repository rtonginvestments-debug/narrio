const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");
const fileInfo = document.getElementById("file-info");
const fileName = document.getElementById("file-name");
const clearFile = document.getElementById("clear-file");
const voiceSelect = document.getElementById("voice-select");
const speedSelect = document.getElementById("speed-select");
const convertBtn = document.getElementById("convert-btn");
const uploadSection = document.getElementById("upload-section");
const progressSection = document.getElementById("progress-section");
const progressBar = document.getElementById("progress-bar");
const progressText = document.getElementById("progress-text");
const doneSection = document.getElementById("done-section");
const downloadBtn = document.getElementById("download-btn");
const resetBtn = document.getElementById("reset-btn");
const errorSection = document.getElementById("error-section");
const errorText = document.getElementById("error-text");
const errorResetBtn = document.getElementById("error-reset-btn");
const testVoiceBtn = document.getElementById("test-voice-btn");

let selectedFile = null;
let testAudio = null;

// Load voices on startup
async function loadVoices() {
    try {
        const res = await fetch("/api/voices");
        const voices = await res.json();

        if (voices.error) throw new Error(voices.error);

        voiceSelect.innerHTML = "";
        voices.forEach((v) => {
            const opt = document.createElement("option");
            opt.value = v.name;
            // Clean up friendly name: remove "Microsoft", split camelCase
            const cleanName = v.friendly_name.replace(/^Microsoft\s+/i, "").replace(/([a-z])([A-Z])/g, "$1 $2");
            opt.textContent = `${cleanName} (${v.gender})`;
            if (v.name === "en-US-AriaNeural") opt.selected = true;
            voiceSelect.appendChild(opt);
        });
    } catch (err) {
        voiceSelect.innerHTML = '<option value="en-US-AriaNeural">Aria (Default)</option>';
        console.error("Failed to load voices:", err);
    }
}

// Drag and drop
dropZone.addEventListener("click", () => fileInput.click());

dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
});

dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("dragover");
});

dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
        handleFile(e.dataTransfer.files[0]);
    }
});

fileInput.addEventListener("change", () => {
    if (fileInput.files.length > 0) {
        handleFile(fileInput.files[0]);
    }
});

function handleFile(file) {
    const ext = file.name.split(".").pop().toLowerCase();
    if (!["pdf", "epub"].includes(ext)) {
        showError("Only PDF and EPUB files are supported.");
        return;
    }
    if (file.size > 50 * 1024 * 1024) {
        showError("File is too large. Maximum size is 50 MB.");
        return;
    }
    selectedFile = file;
    fileName.textContent = file.name;
    fileInfo.classList.remove("hidden");
    dropZone.classList.add("hidden");
    convertBtn.disabled = false;
}

clearFile.addEventListener("click", () => {
    selectedFile = null;
    fileInput.value = "";
    fileInfo.classList.add("hidden");
    dropZone.classList.remove("hidden");
    convertBtn.disabled = true;
});

// Convert
convertBtn.addEventListener("click", async () => {
    if (!selectedFile) return;

    uploadSection.classList.add("hidden");
    progressSection.classList.remove("hidden");
    progressBar.style.width = "0%";
    progressText.textContent = "Uploading...";

    const formData = new FormData();
    formData.append("file", selectedFile);
    formData.append("voice", voiceSelect.value);
    formData.append("rate", speedSelect.value);

    try {
        const res = await fetch("/api/convert", { method: "POST", body: formData });
        const data = await res.json();

        if (data.error) {
            showError(data.error);
            return;
        }

        listenProgress(data.job_id);
    } catch (err) {
        showError("Upload failed. Please try again.");
    }
});

function listenProgress(jobId) {
    const source = new EventSource(`/api/progress/${jobId}`);

    source.onmessage = (event) => {
        const data = JSON.parse(event.data);

        const pct = Math.round(data.progress);
        progressBar.style.width = pct + "%";
        progressText.textContent = `${data.message} (${pct}%)`;

        if (data.status === "completed") {
            source.close();
            showDone(jobId);
        } else if (data.status === "error") {
            source.close();
            showError(data.message);
        }
    };

    source.onerror = () => {
        source.close();
        showError("Lost connection to server. Please try again.");
    };
}

function showDone(jobId) {
    progressSection.classList.add("hidden");
    doneSection.classList.remove("hidden");
    downloadBtn.href = `/api/download/${jobId}`;
}

function showError(message) {
    uploadSection.classList.add("hidden");
    progressSection.classList.add("hidden");
    doneSection.classList.add("hidden");
    errorSection.classList.remove("hidden");
    errorText.textContent = message;
}

function resetUI() {
    selectedFile = null;
    fileInput.value = "";
    fileInfo.classList.add("hidden");
    dropZone.classList.remove("hidden");
    convertBtn.disabled = true;
    errorSection.classList.add("hidden");
    doneSection.classList.add("hidden");
    progressSection.classList.add("hidden");
    uploadSection.classList.remove("hidden");
}

resetBtn.addEventListener("click", resetUI);
errorResetBtn.addEventListener("click", resetUI);

// Test voice
testVoiceBtn.addEventListener("click", async () => {
    if (testVoiceBtn.disabled) return;

    // Stop any currently playing test audio
    if (testAudio) {
        testAudio.pause();
        testAudio = null;
    }

    const originalText = testVoiceBtn.textContent;
    testVoiceBtn.textContent = "Generating...";
    testVoiceBtn.disabled = true;

    const formData = new FormData();
    formData.append("voice", voiceSelect.value);

    try {
        const res = await fetch("/api/test-voice", { method: "POST", body: formData });
        if (!res.ok) {
            const data = await res.json();
            throw new Error(data.error || "Failed to generate test audio.");
        }

        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        testAudio = new Audio(url);
        testAudio.play();

        testVoiceBtn.textContent = "Playing...";

        testAudio.addEventListener("ended", () => {
            URL.revokeObjectURL(url);
            testAudio = null;
            testVoiceBtn.textContent = originalText;
            testVoiceBtn.disabled = false;
        });
    } catch (err) {
        console.error("Voice test failed:", err);
        testVoiceBtn.textContent = originalText;
        testVoiceBtn.disabled = false;
    }
});

// Init
loadVoices();
