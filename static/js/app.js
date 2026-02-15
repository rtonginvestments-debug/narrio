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
const progressPrompt = document.getElementById("progress-prompt");

// Encouraging prompts at specific percentages
const progressPrompts = [
    [20, "Warming up my voice"],
    [40, "Cruising along"],
    [60, "Halfway-ish"],
    [80, "Home stretch"],
    [85, "Almost there"],
    [90, "Final polish"],
    [95, "Packing it up"],
    [98, "Sealing the MP3"],
    [99, "One last check"],
    [100, "Done! Download ready"]
];

function getProgressPrompt(pct) {
    let prompt = "";
    for (const [threshold, msg] of progressPrompts) {
        if (pct >= threshold) prompt = msg;
    }
    return prompt;
}

// Finalizing prompts — cycle at random 3–5s intervals once progress reaches 95%
const finalizingPrompts = [
    "Final checks",
    "Audio stitching",
    "Exporting MP3",
    "Polishing sound",
    "Nearly finished",
    "Preparing download",
    "Last touches"
];
let finalizingTimer = null;
let finalizingIndex = 0;
let lastFinalizingPct = 0;

function randomDelay() {
    return 3000 + Math.random() * 2000;
}

function showNextFinalizing() {
    const msg = finalizingPrompts[finalizingIndex % finalizingPrompts.length];
    progressPrompt.textContent = msg;
    progressPrompt.classList.add("visible");
    progressText.textContent = `${msg}... (${lastFinalizingPct}%)`;
    finalizingIndex++;
    finalizingTimer = setTimeout(showNextFinalizing, randomDelay());
}

function startFinalizingCycle() {
    if (finalizingTimer) return;
    finalizingIndex = 0;
    showNextFinalizing();
}

function stopFinalizingCycle() {
    if (finalizingTimer) {
        clearTimeout(finalizingTimer);
        finalizingTimer = null;
        finalizingIndex = 0;
    }
}

function startChapterCycle(index, statusEl, pct) {
    if (chapterJobs[index].finalizingTimer) return;
    let chIdx = 0;
    function next() {
        const msg = finalizingPrompts[chIdx % finalizingPrompts.length];
        if (statusEl) statusEl.textContent = `${pct}% — ${msg}`;
        chIdx++;
        chapterJobs[index].finalizingTimer = setTimeout(next, randomDelay());
    }
    next();
}

function stopChapterCycle(idx) {
    if (chapterJobs[idx] && chapterJobs[idx].finalizingTimer) {
        clearTimeout(chapterJobs[idx].finalizingTimer);
        chapterJobs[idx].finalizingTimer = null;
    }
}

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

// EPUB segment state
let currentWordCount = null;
let currentEstimatedAudioMinutes = null;

// EPUB segment elements
const epubSegmentSection = document.getElementById("epub-segment-section");
const segMethodAudio = document.getElementById("seg-method-audio");
const segMethodPages = document.getElementById("seg-method-pages");
const suboptionAudio = document.getElementById("suboption-audio");
const suboptionPages = document.getElementById("suboption-pages");
const segAudioMinutes = document.getElementById("seg-audio-minutes");
const segPageCount = document.getElementById("seg-page-count");
const epubSegmentSubmitBtn = document.getElementById("epub-segment-submit-btn");
const epubSegmentBackBtn = document.getElementById("epub-segment-back-btn");
const segMethodRanges = document.getElementById("seg-method-ranges");
const segMethodRangesLabel = document.getElementById("seg-method-ranges-label");
const autoSegmentTitle = document.getElementById("auto-segment-title");

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

        // Listen for auth state changes (e.g. after sign-up during trial flow)
        clerk.addListener(({ user }) => {
            if (user) {
                currentUser = user;
                showUserInfo();
                if (sessionStorage.getItem("pendingTrialFlow")) {
                    sessionStorage.removeItem("pendingTrialFlow");
                    showPremiumTrialPage();
                }
            } else {
                currentUser = null;
                showAuthButtons();
            }
        });

        // Check initial auth state
        if (clerk.user) {
            console.log("User already signed in:", clerk.user);
            currentUser = clerk.user;
            showUserInfo();

            // Check if we need to show trial page after a sign-up redirect
            if (sessionStorage.getItem("pendingTrialFlow")) {
                sessionStorage.removeItem("pendingTrialFlow");
                showPremiumTrialPage();
            }
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
            <div class="modal-icon">&#9889;</div>
            <h2 class="modal-title">Upgrade to Narrio Pro</h2>
            <ul class="modal-features">
                <li>Upload files with unlimited page counts</li>
                <li>Auto-segment ebooks into chapters</li>
                <li>Customize audio segments by length or page count</li>
                <li>Download individual chapter MP3s</li>
                <li>More advanced features coming soon</li>
            </ul>
            <p class="modal-pricing">All for just <strong>$2.49/mo</strong></p>
            <button class="modal-cta-btn" id="modal-start-trial-btn">
                Start Free 3-Day Trial
            </button>
            <button class="modal-close-link" onclick="this.closest('.modal-overlay').remove()">
                Maybe later
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

    // Bind trial button
    document.getElementById("modal-start-trial-btn").addEventListener("click", () => {
        overlay.remove();
        startTrialFlow();
    });
}

function showEbookPremiumModal() {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';

    overlay.innerHTML = `
        <div class="modal-content">
            <div class="modal-icon">&#127911;</div>
            <h2 class="modal-title">Chapter Segmentation is a Premium Feature</h2>
            <p class="modal-message">
                Splitting your audiobooks into chapters or sections is available exclusively
                to Narrio Pro members. Upgrade to unlock this feature, enjoy unlimited page
                uploads, and access other advanced tools.
            </p>
            <p class="modal-pricing">All for just <strong>$2.49/mo</strong></p>
            <button class="modal-cta-btn" id="modal-ebook-trial-btn">
                Start Free 3-Day Trial
            </button>
            <button class="modal-close-link" onclick="this.closest('.modal-overlay').remove()">
                Maybe later
            </button>
        </div>
    `;

    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.remove();
    });

    document.body.appendChild(overlay);

    document.getElementById("modal-ebook-trial-btn").addEventListener("click", () => {
        overlay.remove();
        startTrialFlow();
    });
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

// --- Premium Trial Flow ---

const premiumTrialSection = document.getElementById("premium-trial-section");
const activateTrialBtn = document.getElementById("activate-trial-btn");
const trialBackBtn = document.getElementById("trial-back-btn");

function startTrialFlow() {
    if (!clerk) {
        console.error("Clerk not initialized");
        return;
    }

    // If user is already signed in, go straight to the features page
    if (clerk.user) {
        showPremiumTrialPage();
        return;
    }

    // Persist flag so it survives page reloads after Clerk sign-up
    sessionStorage.setItem("pendingTrialFlow", "1");
    clerk.openSignUp();
}

function showPremiumTrialPage() {
    // Hide all other sections
    uploadSection.classList.add("hidden");
    progressSection.classList.add("hidden");
    doneSection.classList.add("hidden");
    confirmSection.classList.add("hidden");
    if (chaptersSection) chaptersSection.classList.add("hidden");
    manualSegmentSection.classList.add("hidden");
    epubSegmentSection.classList.add("hidden");
    errorSection.classList.add("hidden");

    premiumTrialSection.classList.remove("hidden");
}

function showTrialWelcomeModal() {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';

    overlay.innerHTML = `
        <div class="modal-content">
            <div class="modal-icon">&#127881;</div>
            <h2 class="modal-title">Congratulations!</h2>
            <p class="modal-message">
                You've been upgraded to <strong>Narrio Pro</strong>! You have
                <strong>3 days</strong> to enjoy unlimited access to all premium features:
            </p>
            <ul class="modal-features">
                <li>Unlimited page caps per document</li>
                <li>Auto chapter segmentation</li>
                <li>Manual segmentation by audio length or pages</li>
                <li>Individual chapter MP3 downloads</li>
            </ul>
            <p class="modal-pricing">
                Enroll in Premium for only <strong>$2.49/mo</strong>!<br>
                <span style="font-size: 0.85rem;">Additional advanced features upcoming weekly!</span>
            </p>
            <button class="modal-cta-btn" id="trial-welcome-close-btn">
                Start Exploring
            </button>
        </div>
    `;

    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
            overlay.remove();
            window.location.reload();
        }
    });

    document.body.appendChild(overlay);

    document.getElementById("trial-welcome-close-btn").addEventListener("click", () => {
        overlay.remove();
        window.location.reload();
    });
}

activateTrialBtn.addEventListener("click", async () => {
    activateTrialBtn.disabled = true;
    activateTrialBtn.textContent = "Activating...";

    try {
        const headers = await getAuthHeaders();
        headers["Content-Type"] = "application/json";

        const res = await fetch("/api/start-trial", {
            method: "POST",
            headers: headers,
        });
        const data = await res.json();

        if (data.error) {
            premiumTrialSection.classList.add("hidden");
            showError(data.error);
            activateTrialBtn.disabled = false;
            activateTrialBtn.textContent = "Start 3-Day Trial (No Payment Needed)";
            return;
        }

        // Success — show welcome modal, then reload
        showTrialWelcomeModal();
    } catch (err) {
        console.error("Trial activation error:", err);
        activateTrialBtn.textContent = "Something went wrong. Try again.";
        setTimeout(() => {
            activateTrialBtn.disabled = false;
            activateTrialBtn.textContent = "Start 3-Day Trial (No Payment Needed)";
        }, 3000);
    }
});

trialBackBtn.addEventListener("click", () => {
    premiumTrialSection.classList.add("hidden");
    uploadSection.classList.remove("hidden");
});

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
    if (file.size > 150 * 1024 * 1024) {
        showError("File is too large. Maximum size is 150 MB.");
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

        manualSegmentRadioLabel.classList.remove("hidden");
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
            showEbookPremiumModal();
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
    progressPrompt.textContent = "";
    progressPrompt.classList.remove("visible");

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
            showError(data.error, data.requiresPremium);
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
    progressPrompt.textContent = "";
    progressPrompt.classList.remove("visible");

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
            showError(data.error, data.requiresPremium);
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
        lastFinalizingPct = pct;
        progressBar.style.width = pct + "%";

        if (pct >= 95 && data.status === "processing") {
            startFinalizingCycle();
        } else {
            stopFinalizingCycle();
            progressText.textContent = `${data.message} (${pct}%)`;
            const prompt = getProgressPrompt(pct);
            if (prompt) {
                progressPrompt.textContent = prompt;
                progressPrompt.classList.add("visible");
            }
        }

        if (data.status === "completed") {
            stopFinalizingCycle();
            source.close();
            activeJobId = null;
            activeEventSource = null;
            progressControls.classList.add("hidden");
            showDone(jobId);
        } else if (data.status === "cancelled") {
            stopFinalizingCycle();
            source.close();
            activeJobId = null;
            activeEventSource = null;
            progressControls.classList.add("hidden");
            showError("Conversion was cancelled.");
        } else if (data.status === "error") {
            stopFinalizingCycle();
            source.close();
            activeJobId = null;
            activeEventSource = null;
            progressControls.classList.add("hidden");
            showError(data.message);
        }
    };

    source.onerror = () => {
        stopFinalizingCycle();
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
    progressPrompt.textContent = "";
    progressPrompt.classList.remove("visible");

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
    const ext = selectedFile ? selectedFile.name.split(".").pop().toLowerCase() : "";
    const isEpubManual = ext === "epub" && bookData.detection_method === "manual";
    if (isEpubManual) {
        chaptersCount.textContent = `${bookData.chapter_count} section${bookData.chapter_count !== 1 ? "s" : ""} generated`;
    } else {
        chaptersCount.textContent = `${bookData.chapter_count} chapter${bookData.chapter_count !== 1 ? "s" : ""} detected`;
    }

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

    // Show "switch to manual" button for PDF and EPUB files
    if (ext === "pdf" || ext === "epub") {
        switchToManualBtn.classList.remove("hidden");
        if (ext === "epub") {
            switchToManualBtn.textContent = isEpubManual
                ? "Manually Reassign Sections"
                : "Manually Assign Sections Instead";
        } else {
            const isPdfManual = bookData.detection_method === "manual";
            switchToManualBtn.textContent = isPdfManual
                ? "Manually Reassign Chapters"
                : "Manually Assign Chapters Instead";
        }
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

        const pct = Math.round(data.progress);
        if (bar) bar.style.width = pct + "%";

        if (pct >= 95 && data.status === "processing") {
            if (chapterJobs[index] && !chapterJobs[index].finalizingTimer) {
                startChapterCycle(index, statusEl, pct);
            }
        } else {
            stopChapterCycle(index);
            const prompt = getProgressPrompt(pct);
            if (statusEl) statusEl.textContent = prompt ? `${pct}% — ${prompt}` : `${pct}%`;
        }

        if (data.status === "completed") {
            stopChapterCycle(index);
            source.close();
            chapterJobs[index].status = "completed";
            showChapterDownload(index, jobId);
            updateOverallProgress();
        } else if (data.status === "cancelled") {
            stopChapterCycle(index);
            source.close();
            chapterJobs[index].status = "cancelled";
            const actionDiv = document.getElementById(`chapter-action-${index}`);
            if (actionDiv) {
                actionDiv.innerHTML = `<div class="chapter-cancelled-text">Cancelled</div>`;
            }
            updateOverallProgress();
        } else if (data.status === "error") {
            stopChapterCycle(index);
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
        stopChapterCycle(index);
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
    progressPrompt.textContent = "";
    progressPrompt.classList.remove("visible");

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
        currentWordCount = data.word_count || 0;
        currentEstimatedAudioMinutes = data.estimated_audio_minutes || 0;

        // Route to segment form for both EPUB and PDF
        showEpubSegmentForm();
    } catch (err) {
        progressSection.classList.add("hidden");
        showError("Failed to get page count. Please try again.");
    }
}

function showEpubSegmentForm() {
    const wordCount = currentWordCount || 0;
    const approxPages = Math.round(wordCount / 250);
    const audioMinutes = currentEstimatedAudioMinutes || 0;
    const fileExt = selectedFile ? selectedFile.name.split(".").pop().toLowerCase() : "";

    // Format audio length
    let audioStr;
    if (audioMinutes >= 60) {
        const h = Math.floor(audioMinutes / 60);
        const m = Math.round(audioMinutes % 60);
        audioStr = m > 0 ? `${h}h ${m}m` : `${h}h`;
    } else {
        audioStr = `${Math.round(audioMinutes)} min`;
    }

    // Set title based on file type
    autoSegmentTitle.textContent = fileExt === "epub"
        ? "Manually Assign Sections"
        : "Manually Assign Chapters";

    // Populate stats
    document.getElementById("epub-stat-words").textContent = wordCount.toLocaleString();
    document.getElementById("epub-stat-pages").textContent = approxPages.toLocaleString();
    document.getElementById("epub-stat-audio").textContent = audioStr;

    // Reset radio to audio length
    segMethodAudio.checked = true;
    suboptionAudio.classList.remove("hidden");
    suboptionPages.classList.add("hidden");
    segAudioMinutes.value = "15";

    // Show "By page ranges" option only for PDFs
    if (fileExt === "pdf") {
        segMethodRangesLabel.classList.remove("hidden");
    } else {
        segMethodRangesLabel.classList.add("hidden");
    }

    epubSegmentSection.classList.remove("hidden");
}

function showManualSegmentForm() {
    const ext = selectedFile ? selectedFile.name.split(".").pop().toLowerCase() : "";
    const isEpub = ext === "epub";
    const unitLabel = isEpub ? "sections" : "pages";

    manualSegmentSubtitle.textContent = currentPageCount
        ? `This file has ${currentPageCount} ${unitLabel}. Define your chapter ranges below.`
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
    const ext = selectedFile ? selectedFile.name.split(".").pop().toLowerCase() : "";
    const startLabel = ext === "epub" ? "Start section" : "Start page";
    const endLabel = ext === "epub" ? "End section" : "End page";

    row.innerHTML = `
        <input type="text" class="segment-name-input" placeholder="Chapter name" maxlength="100">
        <input type="number" class="segment-page-input" placeholder="${startLabel}" min="1" max="${maxPage}">
        <input type="number" class="segment-page-input" placeholder="${endLabel}" min="1" max="${maxPage}">
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
        const startVal = inputs[1].value.trim();
        const endVal = inputs[2].value.trim();

        // Skip completely empty rows
        if (!name && !startVal && !endVal) {
            continue;
        }

        // If partially filled, require all fields
        const startPage = parseInt(startVal, 10);
        const endPage = parseInt(endVal, 10);

        if (!name || isNaN(startPage) || isNaN(endPage)) {
            showError(`Row ${i + 1}: Please fill in all fields or leave the row completely empty.`);
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

    if (segments.length === 0) {
        showError("Please fill in at least one chapter row.");
        return;
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
    progressPrompt.textContent = "";
    progressPrompt.classList.remove("visible");

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

// --- EPUB Segment Event Listeners ---

// Radio toggle: show/hide suboptions
segMethodAudio.addEventListener("change", () => {
    suboptionAudio.classList.remove("hidden");
    suboptionPages.classList.add("hidden");
});

segMethodPages.addEventListener("change", () => {
    suboptionAudio.classList.add("hidden");
    suboptionPages.classList.remove("hidden");
});

segMethodRanges.addEventListener("change", () => {
    suboptionAudio.classList.add("hidden");
    suboptionPages.classList.add("hidden");
});

// Back button
epubSegmentBackBtn.addEventListener("click", () => {
    epubSegmentSection.classList.add("hidden");
    uploadSection.classList.remove("hidden");
});

// Submit button — POST to /api/analyze with segment_method + segment_value
epubSegmentSubmitBtn.addEventListener("click", async () => {
    // If "By page ranges" is selected, switch to the manual row form
    if (segMethodRanges.checked) {
        epubSegmentSection.classList.add("hidden");
        showManualSegmentForm();
        return;
    }

    const method = segMethodAudio.checked ? "audio_length" : "page_count";
    const value = method === "audio_length"
        ? segAudioMinutes.value
        : segPageCount.value;

    if (!value || parseInt(value, 10) < 1) {
        showError("Please enter a valid positive number.");
        return;
    }

    epubSegmentSection.classList.add("hidden");
    progressSection.classList.remove("hidden");
    progressBar.style.width = "0%";
    progressText.textContent = "Creating segments...";
    progressPrompt.textContent = "";
    progressPrompt.classList.remove("visible");

    const formData = new FormData();
    formData.append("file", currentFileForManual || selectedFile);
    formData.append("voice", voiceSelect.value);
    formData.append("rate", speedSelect.value);
    formData.append("segment_method", method);
    formData.append("segment_value", value);

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
        console.error("EPUB segment submit error:", err);
        showError("Failed to create segments. Please try again.");
    }
});

// Switch from auto results to manual segment
switchToManualBtn.addEventListener("click", async () => {
    chaptersSection.classList.add("hidden");

    const switchExt = selectedFile ? selectedFile.name.split(".").pop().toLowerCase() : "";

    // If we already have the data, go straight to the form
    if (currentPageCount || currentWordCount) {
        showEpubSegmentForm();
        return;
    }

    // Otherwise, call estimate to get page count / word count
    progressSection.classList.remove("hidden");
    progressBar.style.width = "0%";
    progressText.textContent = "Getting file info...";
    progressPrompt.textContent = "";
    progressPrompt.classList.remove("visible");

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
        currentWordCount = data.word_count || 0;
        currentEstimatedAudioMinutes = data.estimated_audio_minutes || 0;

        showEpubSegmentForm();
    } catch (err) {
        progressSection.classList.add("hidden");
        showError("Failed to get file info. Please try again.");
    }
});


function showError(message, requiresPremium) {
    uploadSection.classList.add("hidden");
    progressSection.classList.add("hidden");
    doneSection.classList.add("hidden");
    confirmSection.classList.add("hidden");
    if (chaptersSection) chaptersSection.classList.add("hidden");
    manualSegmentSection.classList.add("hidden");
    epubSegmentSection.classList.add("hidden");
    premiumTrialSection.classList.add("hidden");
    errorSection.classList.remove("hidden");
    errorText.textContent = message;

    const errorHint = document.getElementById("error-hint");
    const errorPremiumBtn = document.getElementById("error-premium-btn");

    if (requiresPremium) {
        errorHint.textContent = "Upgrade to Narrio Pro for unlimited page uploads.";
        errorPremiumBtn.classList.remove("hidden");
        errorResetBtn.textContent = "Back to Home Page";
    } else {
        errorHint.textContent = "No worries — give it another shot!";
        errorPremiumBtn.classList.add("hidden");
        errorResetBtn.textContent = "Try Again";
    }
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
    epubSegmentSection.classList.add("hidden");
    premiumTrialSection.classList.add("hidden");
    uploadSection.classList.remove("hidden");

    // Reset chapter state
    currentBookId = null;
    chapterJobs = {};

    // Reset manual segment state
    currentPageCount = null;
    currentFileForManual = null;

    // Reset EPUB segment state
    currentWordCount = null;
    currentEstimatedAudioMinutes = null;

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
document.getElementById("error-premium-btn").addEventListener("click", () => {
    errorSection.classList.add("hidden");
    startTrialFlow();
});

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
