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

// Progress controls
const progressControls = document.getElementById("progress-controls");
const cancelBtn = document.getElementById("cancel-btn");

// Ebook checkbox + segment type radios + confirm elements
const segmentOption = document.getElementById("segment-option");
const ebookCheckbox = document.getElementById("ebook-checkbox");
const segmentTypeOptions = document.getElementById("segment-type-options");
const autoSegmentRadio = document.getElementById("auto-segment-radio");
const manualSegmentRadio = document.getElementById("manual-segment-radio");
const manualSegmentRadioLabel = document.getElementById("manual-segment-radio-label");

// Manual segment elements
const manualSegmentSection = document.getElementById("manual-segment-section");
const manualSegmentSubtitle = document.getElementById("manual-segment-subtitle");
const manualSegmentRows = document.getElementById("manual-segment-rows");
const addRowBtn = document.getElementById("add-row-btn");
const manualSubmitBtn = document.getElementById("manual-submit-btn");
const manualBackBtn = document.getElementById("manual-back-btn");
const switchToManualBtn = document.getElementById("switch-to-manual-btn");

const confirmSection = document.getElementById("confirm-section");
const confirmFilename = document.getElementById("confirm-filename");
const confirmEstimate = document.getElementById("confirm-estimate");
const confirmConvertBtn = document.getElementById("confirm-convert-btn");
const confirmBackBtn = document.getElementById("confirm-back-btn");

// Chapter elements
const chaptersSection = document.getElementById("chapters-section");
const chaptersBookTitle = document.getElementById("chapters-book-title");
const chaptersCount = document.getElementById("chapters-count");
const chaptersDetectionNote = document.getElementById("chapters-detection-note");
const chaptersOverallProgress = document.getElementById("chapters-overall-progress");
const chaptersOverallBar = document.getElementById("chapters-overall-bar");
const chaptersOverallText = document.getElementById("chapters-overall-text");
const chaptersList = document.getElementById("chapters-list");
const convertAllBtn = document.getElementById("convert-all-btn");
const chaptersBackBtn = document.getElementById("chapters-back-btn");

// Auth elements
const authSection = document.getElementById("auth-section");
const userInfo = document.getElementById("user-info");
const userAvatar = document.getElementById("user-avatar");
const userName = document.getElementById("user-name");
const userBadge = document.getElementById("user-badge");
const signOutBtn = document.getElementById("sign-out-btn");
const authButtons = document.getElementById("auth-buttons");
const signInBtn = document.getElementById("sign-in-btn");
const signUpBtn = document.getElementById("sign-up-btn");
const tierNote = document.getElementById("tier-note");
const premiumUpgradeLink = document.getElementById("premium-upgrade-link");

let selectedFile = null;
let testAudio = null;
let clerk = null;
let currentUser = null;
let clerkConfig = null;

// Chapter state
let currentBookId = null;
let chapterJobs = {};  // {chapterIndex: {jobId, status, eventSource}}

// Manual segment state
let currentPageCount = null;
let currentFileForManual = null;

// Active conversion state (for cancel)
let activeJobId = null;
let activeEventSource = null;
let isConvertingAll = false;

// Initialize Clerk authentication
async function initClerk() {
    console.log("Initializing Clerk...");
    try {
        // Fetch config from backend
        const res = await fetch("/api/config");
        clerkConfig = await res.json();
        console.log("Clerk config received:", clerkConfig);

        if (!clerkConfig.clerkPublishableKey) {
            console.warn("Clerk not configured, auth features disabled");
            showAuthButtons();
            return;
        }

        const pubKey = clerkConfig.clerkPublishableKey;
        console.log("Publishable key:", pubKey);

        // Load Clerk SDK with data attribute to prevent auto-init error
        console.log("Loading Clerk SDK script...");

        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/@clerk/clerk-js@4/dist/clerk.browser.js';
        script.setAttribute('data-clerk-publishable-key', pubKey);
        script.async = true;
        script.crossOrigin = 'anonymous';

        // Wait for script to load
        await new Promise((resolve, reject) => {
            script.onload = () => {
                console.log("Clerk script loaded");
                resolve();
            };
            script.onerror = reject;
            document.head.appendChild(script);
        });

        // Wait for window.Clerk to be available
        console.log("Waiting for window.Clerk...");
        let attempts = 0;
        while (!window.Clerk && attempts < 100) {
            await new Promise(resolve => setTimeout(resolve, 50));
            attempts++;
        }

        if (!window.Clerk) {
            throw new Error("Clerk SDK did not initialize");
        }

        console.log("window.Clerk available:", window.Clerk);

        // Clerk should auto-initialize with the data-clerk-publishable-key attribute
        // Just wait a moment for it to finish
        await new Promise(resolve => setTimeout(resolve, 500));

        clerk = window.Clerk;
        console.log("Clerk instance:", clerk);

        // Wait for Clerk to be fully ready
        console.log("Waiting for Clerk components to be ready...");

        // Load the Clerk instance to initialize components
        await clerk.load();

        console.log("Clerk fully loaded and ready!");

        // Check initial auth state
        if (clerk.user) {
            console.log("User already signed in:", clerk.user);
            currentUser = clerk.user;
            showUserInfo();
        } else {
            console.log("No user signed in");
            showAuthButtons();
        }

    } catch (err) {
        console.error("Failed to initialize Clerk:", err);
        console.error("Error details:", err.message);
        if (err.stack) console.error("Stack:", err.stack);
        showAuthButtons();
    }
}

function updateAuthState() {
    if (clerk && clerk.user) {
        currentUser = clerk.user;
        showUserInfo();
    } else {
        currentUser = null;
        showAuthButtons();
    }
}

function showUserInfo() {
    if (!currentUser) return;

    // Get user details
    const firstName = currentUser.firstName || "";
    const lastName = currentUser.lastName || "";
    const email = currentUser.primaryEmailAddress?.emailAddress || "";
    const displayName = firstName || email.split("@")[0] || "User";

    // Get first letter for avatar
    const initial = (firstName || email)[0].toUpperCase();

    // Check premium status
    const isPremium = currentUser.publicMetadata?.isPremium === true;

    // Update UI
    userAvatar.textContent = initial;
    userName.textContent = displayName;

    if (isPremium) {
        userBadge.classList.remove("hidden");
        tierNote.innerHTML = 'Premium — unlimited pages!';
        premiumUpgradeLink.classList.add("hidden");
    } else {
        userBadge.classList.add("hidden");
        tierNote.innerHTML = `Free version — upload up to ${clerkConfig.freeTierLimit} pages at a time. <span id="premium-upgrade-link" class="premium-link">Get Premium for unlimited pages!</span>`;
        const newLink = document.getElementById("premium-upgrade-link");
        newLink.classList.remove("hidden");
        newLink.addEventListener("click", showSignUp);
    }

    userInfo.classList.remove("hidden");
    authButtons.classList.add("hidden");
}

function showAuthButtons() {
    userInfo.classList.add("hidden");
    authButtons.classList.remove("hidden");

    // Update tier note
    if (clerkConfig) {
        tierNote.innerHTML = `Free version — upload up to ${clerkConfig.freeTierLimit} pages at a time. <span id="premium-upgrade-link" class="premium-link">Get Premium for unlimited pages!</span>`;
        const newLink = document.getElementById("premium-upgrade-link");
        newLink.classList.remove("hidden");
        newLink.addEventListener("click", showSignUp);
    }
}

async function showSignIn() {
    console.log("showSignIn called, clerk:", clerk);
    if (!clerk) {
        console.error("Clerk not initialized!");
        return;
    }
    try {
        console.log("Opening sign in modal...");
        clerk.openSignIn();
    } catch (err) {
        console.error("Sign in error:", err);
    }
}

function showPremiumModal() {
    // Create modal overlay
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';

    // Create modal content
    overlay.innerHTML = `
        <div class="modal-content">
            <div class="modal-icon">✨</div>
            <h2 class="modal-title">Thanks for Your Interest in Narrio Pro!</h2>
            <p class="modal-message">
                Premium is coming soon with exciting features including unlimited page uploading,
                ebook chapter audio categorization and downloads. Stay tuned for updates!
            </p>
            <button class="modal-close-btn" onclick="this.closest('.modal-overlay').remove()">
                Got It!
            </button>
        </div>
    `;

    // Close on overlay click
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
            overlay.remove();
        }
    });

    document.body.appendChild(overlay);
}

async function showSignUp() {
    // Show premium coming soon modal instead of Clerk signup
    showPremiumModal();
}

async function signOut() {
    if (!clerk) return;
    try {
        await clerk.signOut();
        window.location.reload();
    } catch (err) {
        console.error("Sign out error:", err);
    }
}

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
    if (!["pdf", "epub", "docx"].includes(ext)) {
        showError("Only PDF, EPUB, and Word (.docx) files are supported.");
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

    // Show ebook checkbox for PDF/EPUB only (not DOCX)
    if (supportsChapters(file.name)) {
        segmentOption.classList.remove("hidden");
        ebookCheckbox.checked = false;
        segmentTypeOptions.classList.add("hidden");
        autoSegmentRadio.checked = true;

        // Manual segment only available for PDF (EPUBs have no page numbers)
        if (ext === "epub") {
            manualSegmentRadioLabel.classList.add("hidden");
        } else {
            manualSegmentRadioLabel.classList.remove("hidden");
        }
    } else {
        segmentOption.classList.add("hidden");
        ebookCheckbox.checked = false;
        segmentTypeOptions.classList.add("hidden");
    }
}

clearFile.addEventListener("click", () => {
    selectedFile = null;
    fileInput.value = "";
    fileInfo.classList.add("hidden");
    segmentOption.classList.add("hidden");
    ebookCheckbox.checked = false;
    segmentTypeOptions.classList.add("hidden");
    autoSegmentRadio.checked = true;
    dropZone.classList.remove("hidden");
    convertBtn.disabled = true;
});

// Ebook checkbox toggles radio options
ebookCheckbox.addEventListener("change", () => {
    if (ebookCheckbox.checked) {
        segmentTypeOptions.classList.remove("hidden");
    } else {
        segmentTypeOptions.classList.add("hidden");
    }
});

// Helper: check if current user is premium
function isPremiumUser() {
    return currentUser && currentUser.publicMetadata?.isPremium === true;
}

// Helper: check if file type supports chapter detection
function supportsChapters(filename) {
    const ext = filename.split(".").pop().toLowerCase();
    return ext === "pdf" || ext === "epub";
}

// Helper: get auth headers with fresh token
async function getAuthHeaders() {
    const headers = {};
    if (clerk && clerk.session) {
        const token = await clerk.session.getToken();
        if (token) {
            headers["Authorization"] = `Bearer ${token}`;
        }
    }
    return headers;
}

// Convert button — routes based on ebook checkbox and radio state
convertBtn.addEventListener("click", async () => {
    if (!selectedFile) return;

    if (ebookCheckbox.checked) {
        // Ebook mode — premium only
        if (!isPremiumUser()) {
            showPremiumModal();
            return;
        }

        if (manualSegmentRadio.checked) {
            await prepareManualSegment();
        } else {
            await analyzeBook();
        }
    } else {
        // No segmentation — estimate and confirm flow
        await estimateAndConfirm();
    }
});

// --- Estimate and confirm flow ---

async function estimateAndConfirm() {
    uploadSection.classList.add("hidden");
    progressSection.classList.remove("hidden");
    progressBar.style.width = "0%";
    progressText.textContent = "Estimating conversion time...";

    const formData = new FormData();
    formData.append("file", selectedFile);

    try {
        const headers = await getAuthHeaders();

        const res = await fetch("/api/estimate", {
            method: "POST",
            body: formData,
            headers: headers,
        });
        const data = await res.json();

        progressSection.classList.add("hidden");

        if (data.error) {
            if (data.requiresPremium && !currentUser) {
                showError(data.error + " Sign in to get Premium access!");
            } else {
                showError(data.error);
            }
            return;
        }

        // Format estimates
        const audioMin = data.estimated_audio_minutes;
        const procMin = data.estimated_processing_minutes;

        let audioStr;
        if (audioMin >= 60) {
            const h = Math.floor(audioMin / 60);
            const m = Math.round(audioMin % 60);
            audioStr = m > 0 ? `~${h}h ${m}m` : `~${h}h`;
        } else {
            audioStr = `~${Math.round(audioMin)} min`;
        }

        let procStr;
        if (procMin >= 60) {
            const h = Math.floor(procMin / 60);
            const m = Math.round(procMin % 60);
            procStr = m > 0 ? `~${h}h ${m}m` : `~${h}h`;
        } else if (procMin < 1) {
            procStr = "<1 min";
        } else {
            procStr = `~${Math.round(procMin)} min`;
        }

        confirmFilename.textContent = selectedFile.name;
        confirmEstimate.innerHTML =
            `Estimated audio length: <strong>${audioStr}</strong><br>` +
            `Estimated conversion time: <strong>${procStr}</strong>`;

        confirmSection.classList.remove("hidden");
    } catch (err) {
        progressSection.classList.add("hidden");
        showError("Failed to estimate conversion. Please try again.");
    }
}

// Confirm section buttons
confirmConvertBtn.addEventListener("click", async () => {
    confirmSection.classList.add("hidden");
    await startSingleConversion();
});

confirmBackBtn.addEventListener("click", () => {
    confirmSection.classList.add("hidden");
    uploadSection.classList.remove("hidden");
});

// --- Single file conversion (existing free-tier flow) ---

async function startSingleConversion() {
    uploadSection.classList.add("hidden");
    progressSection.classList.remove("hidden");
    progressBar.style.width = "0%";
    progressText.textContent = "Uploading...";

    const formData = new FormData();
    formData.append("file", selectedFile);
    formData.append("voice", voiceSelect.value);
    formData.append("rate", speedSelect.value);

    try {
        const headers = await getAuthHeaders();

        const res = await fetch("/api/convert", {
            method: "POST",
            body: formData,
            headers: headers
        });
        const data = await res.json();

        if (data.error) {
            if (data.requiresPremium && !currentUser) {
                showError(data.error + " Sign in to get Premium access!");
            } else if (data.requiresPremium && currentUser) {
                showError(data.error);
            } else {
                showError(data.error);
            }
            return;
        }

        listenProgress(data.job_id);
    } catch (err) {
        showError("Upload failed. Please try again.");
    }
}

async function listenProgress(jobId) {
    // Get a fresh token for the SSE connection
    let token = null;
    if (clerk && clerk.session) {
        token = await clerk.session.getToken();
    }

    const url = token ? `/api/progress/${jobId}?token=${encodeURIComponent(token)}` : `/api/progress/${jobId}`;
    const source = new EventSource(url);

    // Track active conversion for cancel
    activeJobId = jobId;
    activeEventSource = source;
    progressControls.classList.remove("hidden");
    cancelBtn.disabled = false;
    cancelBtn.textContent = "Cancel Conversion";

    source.onmessage = (event) => {
        const data = JSON.parse(event.data);

        const pct = Math.round(data.progress);
        progressBar.style.width = pct + "%";
        progressText.textContent = `${data.message} (${pct}%)`;

        if (data.status === "completed") {
            source.close();
            activeJobId = null;
            activeEventSource = null;
            progressControls.classList.add("hidden");
            showDone(jobId);
        } else if (data.status === "cancelled") {
            source.close();
            activeJobId = null;
            activeEventSource = null;
            progressControls.classList.add("hidden");
            showError("Conversion was cancelled.");
        } else if (data.status === "error") {
            source.close();
            activeJobId = null;
            activeEventSource = null;
            progressControls.classList.add("hidden");
            showError(data.message);
        }
    };

    source.onerror = () => {
        source.close();
        activeJobId = null;
        activeEventSource = null;
        progressControls.classList.add("hidden");
        showError("Lost connection to server. Please try again.");
    };
}

// Cancel button handler
cancelBtn.addEventListener("click", async () => {
    if (!activeJobId) return;

    cancelBtn.disabled = true;
    cancelBtn.textContent = "Cancelling...";

    try {
        const headers = await getAuthHeaders();

        await fetch(`/api/cancel/${activeJobId}`, {
            method: "POST",
            headers: headers,
        });
        // The SSE stream will receive the "cancelled" status and handle cleanup
    } catch (err) {
        console.error("Cancel request failed:", err);
        // Even if cancel request fails, the SSE stream will handle it
    }
});

function showDone(jobId) {
    progressSection.classList.add("hidden");
    doneSection.classList.remove("hidden");

    // Set base download URL (token will be fetched fresh on click)
    downloadBtn.href = `/api/download/${jobId}`;
    downloadBtn.dataset.jobId = jobId;
}

// Intercept download click to attach a fresh token (Clerk tokens expire in ~60s)
downloadBtn.addEventListener("click", async (e) => {
    if (clerk && clerk.session) {
        e.preventDefault();
        const freshToken = await clerk.session.getToken();
        const jobId = downloadBtn.dataset.jobId;
        const url = freshToken
            ? `/api/download/${jobId}?token=${encodeURIComponent(freshToken)}`
            : `/api/download/${jobId}`;
        window.location.href = url;
    }
});

// --- Chapter-based conversion (premium flow) ---

async function analyzeBook() {
    uploadSection.classList.add("hidden");
    progressSection.classList.remove("hidden");
    progressBar.style.width = "0%";
    progressText.textContent = "Analyzing chapters...";

    const formData = new FormData();
    formData.append("file", selectedFile);
    formData.append("voice", voiceSelect.value);
    formData.append("rate", speedSelect.value);

    try {
        const headers = await getAuthHeaders();

        const res = await fetch("/api/analyze", {
            method: "POST",
            body: formData,
            headers: headers,
        });

        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            showError(data.error || `Server error (${res.status})`);
            return;
        }

        const data = await res.json();

        if (data.error) {
            showError(data.error);
            return;
        }

        progressSection.classList.add("hidden");
        showChapterList(data);
    } catch (err) {
        console.error("analyzeBook error:", err);
        showError("Failed to analyze book. Please try again.");
    }
}

function showChapterList(bookData) {
    currentBookId = bookData.book_id;
    chapterJobs = {};

    // Set header — show full title without file extension
    const bookTitle = bookData.filename.replace(/\.[^.]+$/, "");
    chaptersBookTitle.textContent = bookTitle;
    chaptersCount.textContent = `${bookData.chapter_count} chapter${bookData.chapter_count !== 1 ? "s" : ""} detected`;

    // Show detection note for auto-sections
    if (bookData.detection_method === "auto_sections") {
        chaptersDetectionNote.textContent = "Chapters were auto-detected by page range — these may not match the book's actual chapters.";
        chaptersDetectionNote.classList.remove("hidden");
    } else {
        chaptersDetectionNote.classList.add("hidden");
    }

    // Render chapter cards
    chaptersList.innerHTML = "";
    bookData.chapters.forEach((ch) => {
        const card = document.createElement("div");
        card.className = "chapter-card";
        card.id = `chapter-card-${ch.index}`;

        const pageInfo = ch.page_start ? ` · Pages ${ch.page_start}–${ch.page_end}` : "";
        const duration = ch.estimated_minutes < 1 ? "<1 min" : `~${Math.round(ch.estimated_minutes)} min`;

        const badge = ch.chapter_label
            ? `<div class="chapter-number">${escapeHtml(ch.chapter_label)}</div>`
            : '';

        card.innerHTML = `
            ${badge}
            <div class="chapter-info">
                <div class="chapter-title" title="${escapeHtml(ch.title)}">${escapeHtml(ch.title)}</div>
                <div class="chapter-meta">${ch.word_count.toLocaleString()} words · ${duration}${pageInfo}</div>
            </div>
            <div class="chapter-action" id="chapter-action-${ch.index}">
                <button class="btn-chapter-convert" onclick="convertSingleChapter(${ch.index})">Convert</button>
            </div>
        `;

        chaptersList.appendChild(card);
    });

    // Show convert all button (reset state)
    isConvertingAll = false;
    convertAllBtn.disabled = false;
    convertAllBtn.textContent = "Convert All Chapters";
    convertAllBtn.classList.remove("btn-cancel");
    convertAllBtn.classList.add("btn-primary");

    // Hide overall progress
    chaptersOverallProgress.classList.add("hidden");

    // Show "switch to manual" button only for PDF files
    const ext = selectedFile ? selectedFile.name.split(".").pop().toLowerCase() : "";
    if (ext === "pdf") {
        switchToManualBtn.classList.remove("hidden");
    } else {
        switchToManualBtn.classList.add("hidden");
    }

    // Show section
    chaptersSection.classList.remove("hidden");
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

async function convertSingleChapter(index) {
    // Disable the convert button for this chapter
    const actionDiv = document.getElementById(`chapter-action-${index}`);
    actionDiv.innerHTML = `
        <div class="chapter-progress"><div class="chapter-progress-bar" id="chapter-bar-${index}" style="width: 0%"></div></div>
        <div class="chapter-action-row">
            <span class="chapter-status-text" id="chapter-status-${index}">Starting...</span>
            <button class="btn-chapter-cancel" id="chapter-cancel-${index}" onclick="cancelChapter(${index})" title="Cancel">&times;</button>
        </div>
    `;

    try {
        const headers = await getAuthHeaders();
        headers["Content-Type"] = "application/json";

        const res = await fetch("/api/convert-chapter", {
            method: "POST",
            body: JSON.stringify({ book_id: currentBookId, chapter_index: index }),
            headers: headers,
        });
        const data = await res.json();

        if (data.error) {
            actionDiv.innerHTML = `<div class="chapter-error-text">Error</div>`;
            return;
        }

        chapterJobs[index] = { jobId: data.job_id, status: data.status || "processing" };
        listenChapterProgress(index, data.job_id);
    } catch (err) {
        actionDiv.innerHTML = `<div class="chapter-error-text">Failed</div>`;
    }
}

async function convertAllChapters() {
    isConvertingAll = true;
    convertAllBtn.disabled = false;
    convertAllBtn.textContent = "Cancel All Conversions";
    convertAllBtn.classList.remove("btn-primary");
    convertAllBtn.classList.add("btn-cancel");

    // Show overall progress
    chaptersOverallProgress.classList.remove("hidden");
    chaptersOverallBar.style.width = "0%";
    chaptersOverallText.textContent = "Starting all chapters...";

    try {
        const headers = await getAuthHeaders();
        headers["Content-Type"] = "application/json";

        const res = await fetch("/api/convert-all-chapters", {
            method: "POST",
            body: JSON.stringify({ book_id: currentBookId }),
            headers: headers,
        });
        const data = await res.json();

        if (data.error) {
            chaptersOverallText.textContent = data.error;
            isConvertingAll = false;
            convertAllBtn.disabled = false;
            convertAllBtn.textContent = "Convert All Chapters";
            convertAllBtn.classList.remove("btn-cancel");
            convertAllBtn.classList.add("btn-primary");
            return;
        }

        // Start SSE listeners for each chapter
        data.chapters.forEach((ch) => {
            const actionDiv = document.getElementById(`chapter-action-${ch.chapter_index}`);
            if (ch.status === "completed") {
                // Already done
                chapterJobs[ch.chapter_index] = { jobId: ch.job_id, status: "completed" };
                showChapterDownload(ch.chapter_index, ch.job_id);
            } else if (ch.job_id) {
                chapterJobs[ch.chapter_index] = { jobId: ch.job_id, status: "processing" };
                actionDiv.innerHTML = `
                    <div class="chapter-progress"><div class="chapter-progress-bar" id="chapter-bar-${ch.chapter_index}" style="width: 0%"></div></div>
                    <div class="chapter-action-row">
                        <span class="chapter-status-text" id="chapter-status-${ch.chapter_index}">Queued...</span>
                        <button class="btn-chapter-cancel" id="chapter-cancel-${ch.chapter_index}" onclick="cancelChapter(${ch.chapter_index})" title="Cancel">&times;</button>
                    </div>
                `;
                listenChapterProgress(ch.chapter_index, ch.job_id);
            } else {
                actionDiv.innerHTML = `<div class="chapter-error-text">Error</div>`;
                chapterJobs[ch.chapter_index] = { jobId: null, status: "error" };
            }
        });

        updateOverallProgress();
    } catch (err) {
        chaptersOverallText.textContent = "Failed to start conversions.";
        isConvertingAll = false;
        convertAllBtn.disabled = false;
        convertAllBtn.textContent = "Convert All Chapters";
        convertAllBtn.classList.remove("btn-cancel");
        convertAllBtn.classList.add("btn-primary");
    }
}

async function cancelChapter(index) {
    const job = chapterJobs[index];
    if (!job || !job.jobId) return;

    const chapterCancelBtn = document.getElementById(`chapter-cancel-${index}`);
    if (chapterCancelBtn) {
        chapterCancelBtn.disabled = true;
        chapterCancelBtn.textContent = "...";
    }

    // Close the SSE connection immediately
    if (job.eventSource) {
        job.eventSource.close();
        job.eventSource = null;
    }

    try {
        const headers = await getAuthHeaders();
        await fetch(`/api/cancel/${job.jobId}`, {
            method: "POST",
            headers: headers,
        });
    } catch (err) {
        console.error("Chapter cancel failed:", err);
    }

    // Update UI immediately
    job.status = "cancelled";
    const actionDiv = document.getElementById(`chapter-action-${index}`);
    if (actionDiv) {
        actionDiv.innerHTML = `<div class="chapter-cancelled-text">Cancelled</div>`;
    }
    updateOverallProgress();
}

async function cancelAllChapters() {
    convertAllBtn.disabled = true;
    convertAllBtn.textContent = "Cancelling...";

    // 1. Close all SSE connections immediately
    const keys = Object.keys(chapterJobs);
    keys.forEach(k => {
        if (chapterJobs[k].eventSource) {
            chapterJobs[k].eventSource.close();
            chapterJobs[k].eventSource = null;
        }
    });

    // 2. Tell the server to cancel all jobs for this book in one request
    try {
        const headers = await getAuthHeaders();
        await fetch(`/api/cancel-book/${currentBookId}`, {
            method: "POST",
            headers: headers,
        });
    } catch (err) {
        console.error("cancelAllChapters error:", err);
    }

    // 3. Update UI immediately — mark all non-completed chapters as cancelled
    keys.forEach(k => {
        if (chapterJobs[k].status === "processing") {
            chapterJobs[k].status = "cancelled";
            const actionDiv = document.getElementById(`chapter-action-${k}`);
            if (actionDiv) {
                actionDiv.innerHTML = `<div class="chapter-cancelled-text">Cancelled</div>`;
            }
        }
    });

    updateOverallProgress();
}

async function listenChapterProgress(index, jobId) {
    let token = null;
    if (clerk && clerk.session) {
        token = await clerk.session.getToken();
    }

    const url = token
        ? `/api/progress/${jobId}?token=${encodeURIComponent(token)}`
        : `/api/progress/${jobId}`;
    const source = new EventSource(url);

    // Store the EventSource so cancelAllChapters can close it
    if (chapterJobs[index]) {
        chapterJobs[index].eventSource = source;
    }

    source.onmessage = (event) => {
        const data = JSON.parse(event.data);

        const bar = document.getElementById(`chapter-bar-${index}`);
        const statusEl = document.getElementById(`chapter-status-${index}`);

        if (bar) bar.style.width = Math.round(data.progress) + "%";
        if (statusEl) statusEl.textContent = `${Math.round(data.progress)}%`;

        if (data.status === "completed") {
            source.close();
            chapterJobs[index].status = "completed";
            showChapterDownload(index, jobId);
            updateOverallProgress();
        } else if (data.status === "cancelled") {
            source.close();
            chapterJobs[index].status = "cancelled";
            const actionDiv = document.getElementById(`chapter-action-${index}`);
            if (actionDiv) {
                actionDiv.innerHTML = `<div class="chapter-cancelled-text">Cancelled</div>`;
            }
            updateOverallProgress();
        } else if (data.status === "error") {
            source.close();
            chapterJobs[index].status = "error";
            const actionDiv = document.getElementById(`chapter-action-${index}`);
            if (actionDiv) {
                actionDiv.innerHTML = `<div class="chapter-error-text" title="${escapeHtml(data.message)}">Error</div>`;
            }
            updateOverallProgress();
        }
    };

    source.onerror = () => {
        source.close();
        chapterJobs[index].status = "error";
        const actionDiv = document.getElementById(`chapter-action-${index}`);
        if (actionDiv) {
            actionDiv.innerHTML = `<div class="chapter-error-text">Connection lost</div>`;
        }
        updateOverallProgress();
    };
}

function showChapterDownload(index, jobId) {
    const actionDiv = document.getElementById(`chapter-action-${index}`);
    if (!actionDiv) return;

    actionDiv.innerHTML = `<a class="btn-chapter-download" href="#" onclick="downloadChapter(event, '${jobId}')">Download</a>`;
}

async function downloadChapter(e, jobId) {
    e.preventDefault();
    let url = `/api/download/${jobId}`;
    if (clerk && clerk.session) {
        const freshToken = await clerk.session.getToken();
        if (freshToken) {
            url += `?token=${encodeURIComponent(freshToken)}`;
        }
    }
    window.location.href = url;
}

function updateOverallProgress() {
    const keys = Object.keys(chapterJobs);
    if (keys.length === 0) return;

    const completed = keys.filter(k => chapterJobs[k].status === "completed").length;
    const errors = keys.filter(k => chapterJobs[k].status === "error").length;
    const cancelled = keys.filter(k => chapterJobs[k].status === "cancelled").length;
    const finished = completed + errors + cancelled;
    const total = keys.length;
    const pct = Math.round((completed / total) * 100);

    chaptersOverallBar.style.width = pct + "%";

    if (finished >= total) {
        const issues = errors + cancelled;
        if (issues > 0) {
            chaptersOverallText.textContent = `Done! ${completed} of ${total} converted (${errors ? errors + " failed" : ""}${errors && cancelled ? ", " : ""}${cancelled ? cancelled + " cancelled" : ""})`;
        } else {
            chaptersOverallText.textContent = `All ${total} chapters converted!`;
        }
        isConvertingAll = false;
        convertAllBtn.disabled = false;
        convertAllBtn.textContent = "Convert All Chapters";
        convertAllBtn.classList.remove("btn-cancel");
        convertAllBtn.classList.add("btn-primary");
    } else {
        chaptersOverallText.textContent = `Converting... ${completed} of ${total} chapters done`;
    }
}

// Bind convert all button (toggles between convert and cancel)
if (convertAllBtn) convertAllBtn.addEventListener("click", () => {
    if (isConvertingAll) {
        cancelAllChapters();
    } else {
        convertAllChapters();
    }
});

// Back button — return to upload
if (chaptersBackBtn) chaptersBackBtn.addEventListener("click", () => {
    resetUI();
});

// --- Manual Segment Flow ---

async function prepareManualSegment() {
    uploadSection.classList.add("hidden");
    progressSection.classList.remove("hidden");
    progressBar.style.width = "0%";
    progressText.textContent = "Getting page count...";

    const formData = new FormData();
    formData.append("file", selectedFile);

    try {
        const headers = await getAuthHeaders();

        const res = await fetch("/api/estimate", {
            method: "POST",
            body: formData,
            headers: headers,
        });
        const data = await res.json();

        progressSection.classList.add("hidden");

        if (data.error) {
            showError(data.error);
            return;
        }

        currentPageCount = data.page_count || 0;
        currentFileForManual = selectedFile;
        showManualSegmentForm();
    } catch (err) {
        progressSection.classList.add("hidden");
        showError("Failed to get page count. Please try again.");
    }
}

function showManualSegmentForm() {
    manualSegmentSubtitle.textContent = currentPageCount
        ? `This PDF has ${currentPageCount} pages. Define your chapter ranges below.`
        : "Define your chapter ranges below.";

    manualSegmentRows.innerHTML = "";
    // Start with 3 blank rows
    for (let i = 0; i < 3; i++) {
        addManualRow();
    }

    manualSegmentSection.classList.remove("hidden");
}

function addManualRow() {
    const row = document.createElement("div");
    row.className = "manual-segment-row";

    const maxPage = currentPageCount || 9999;

    row.innerHTML = `
        <input type="text" class="segment-name-input" placeholder="Chapter name" maxlength="100">
        <input type="number" class="segment-page-input" placeholder="Start" min="1" max="${maxPage}">
        <input type="number" class="segment-page-input" placeholder="End" min="1" max="${maxPage}">
        <button type="button" class="btn-remove-row" title="Remove row">&times;</button>
    `;

    row.querySelector(".btn-remove-row").addEventListener("click", () => {
        row.remove();
    });

    manualSegmentRows.appendChild(row);
}

addRowBtn.addEventListener("click", addManualRow);

manualSubmitBtn.addEventListener("click", async () => {
    const rows = manualSegmentRows.querySelectorAll(".manual-segment-row");
    if (rows.length === 0) {
        showError("Please add at least one chapter row.");
        return;
    }

    const segments = [];
    const maxPage = currentPageCount || 9999;

    for (let i = 0; i < rows.length; i++) {
        const inputs = rows[i].querySelectorAll("input");
        const name = inputs[0].value.trim();
        const startPage = parseInt(inputs[1].value, 10);
        const endPage = parseInt(inputs[2].value, 10);

        if (!name || isNaN(startPage) || isNaN(endPage)) {
            showError(`Row ${i + 1}: All fields are required.`);
            return;
        }

        if (startPage < 1 || endPage < 1) {
            showError(`Row ${i + 1}: Page numbers must be at least 1.`);
            return;
        }

        if (currentPageCount && (startPage > currentPageCount || endPage > currentPageCount)) {
            showError(`Row ${i + 1}: Page numbers cannot exceed ${currentPageCount}.`);
            return;
        }

        if (startPage > endPage) {
            showError(`Row ${i + 1}: Start page cannot be greater than end page.`);
            return;
        }

        segments.push({ name, start_page: startPage, end_page: endPage });
    }

    // Check for overlapping ranges
    const sorted = [...segments].sort((a, b) => a.start_page - b.start_page);
    for (let i = 1; i < sorted.length; i++) {
        if (sorted[i].start_page <= sorted[i - 1].end_page) {
            showError(`Overlapping page ranges: "${sorted[i - 1].name}" and "${sorted[i].name}".`);
            return;
        }
    }

    // Submit to backend
    manualSegmentSection.classList.add("hidden");
    progressSection.classList.remove("hidden");
    progressBar.style.width = "0%";
    progressText.textContent = "Creating segments...";

    const formData = new FormData();
    formData.append("file", currentFileForManual || selectedFile);
    formData.append("voice", voiceSelect.value);
    formData.append("rate", speedSelect.value);
    formData.append("segments", JSON.stringify(segments));

    try {
        const headers = await getAuthHeaders();

        const res = await fetch("/api/analyze", {
            method: "POST",
            body: formData,
            headers: headers,
        });

        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            showError(data.error || `Server error (${res.status})`);
            return;
        }

        const data = await res.json();

        if (data.error) {
            showError(data.error);
            return;
        }

        progressSection.classList.add("hidden");
        showChapterList(data);
    } catch (err) {
        console.error("Manual segment submit error:", err);
        showError("Failed to create segments. Please try again.");
    }
});

manualBackBtn.addEventListener("click", () => {
    manualSegmentSection.classList.add("hidden");
    uploadSection.classList.remove("hidden");
});

// Switch from auto results to manual segment
switchToManualBtn.addEventListener("click", async () => {
    chaptersSection.classList.add("hidden");

    // If we already have a page count, go straight to the form
    if (currentPageCount) {
        showManualSegmentForm();
        return;
    }

    // Otherwise, call estimate to get page count
    progressSection.classList.remove("hidden");
    progressBar.style.width = "0%";
    progressText.textContent = "Getting page count...";

    const formData = new FormData();
    formData.append("file", selectedFile);

    try {
        const headers = await getAuthHeaders();

        const res = await fetch("/api/estimate", {
            method: "POST",
            body: formData,
            headers: headers,
        });
        const data = await res.json();

        progressSection.classList.add("hidden");

        if (data.error) {
            showError(data.error);
            return;
        }

        currentPageCount = data.page_count || 0;
        currentFileForManual = selectedFile;
        showManualSegmentForm();
    } catch (err) {
        progressSection.classList.add("hidden");
        showError("Failed to get page count. Please try again.");
    }
});


function showError(message) {
    uploadSection.classList.add("hidden");
    progressSection.classList.add("hidden");
    doneSection.classList.add("hidden");
    confirmSection.classList.add("hidden");
    if (chaptersSection) chaptersSection.classList.add("hidden");
    manualSegmentSection.classList.add("hidden");
    errorSection.classList.remove("hidden");
    errorText.textContent = message;
}

function resetUI() {
    selectedFile = null;
    fileInput.value = "";
    fileInfo.classList.add("hidden");
    segmentOption.classList.add("hidden");
    ebookCheckbox.checked = false;
    segmentTypeOptions.classList.add("hidden");
    autoSegmentRadio.checked = true;
    dropZone.classList.remove("hidden");
    convertBtn.disabled = true;
    errorSection.classList.add("hidden");
    doneSection.classList.add("hidden");
    progressSection.classList.add("hidden");
    confirmSection.classList.add("hidden");
    if (chaptersSection) chaptersSection.classList.add("hidden");
    manualSegmentSection.classList.add("hidden");
    uploadSection.classList.remove("hidden");

    // Reset chapter state
    currentBookId = null;
    chapterJobs = {};

    // Reset manual segment state
    currentPageCount = null;
    currentFileForManual = null;

    // Reset active conversion state
    if (activeEventSource) {
        activeEventSource.close();
    }
    activeJobId = null;
    activeEventSource = null;
    isConvertingAll = false;
    progressControls.classList.add("hidden");
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
        // Get auth token if signed in
        const headers = {};

        if (clerk && clerk.session) {
            const token = await clerk.session.getToken();
            if (token) {
                headers["Authorization"] = `Bearer ${token}`;
            }
        }

        const res = await fetch("/api/test-voice", {
            method: "POST",
            body: formData,
            headers: headers
        });
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

// Event listeners for auth
signInBtn.addEventListener("click", showSignIn);
signUpBtn.addEventListener("click", showSignUp);
signOutBtn.addEventListener("click", signOut);

// Init
loadVoices();
initClerk();
