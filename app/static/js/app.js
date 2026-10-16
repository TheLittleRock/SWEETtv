/**
 * Sweet.tv IPTV Proxy Server & Web TV Dashboard Controller
 */

// Tab Switching
function switchTab(tabName) {
    document.querySelectorAll(".tab-content").forEach(el => el.classList.add("hidden"));
    const target = document.getElementById(`tab-${tabName}`);
    if (target) {
        target.classList.remove("hidden");
    }

    document.querySelectorAll(".nav-tab, .mobile-nav-tab").forEach(tab => {
        if (tab.getAttribute("data-tab") === tabName) {
            tab.classList.add("active");
        } else {
            tab.classList.remove("active");
        }
    });

    if (history.pushState) {
        history.pushState(null, null, `#${tabName}`);
    }
}

// Toast Notifications
function showToast(message, type = "info") {
    const container = document.getElementById("toast-container");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = `px-4 py-3 rounded-xl text-xs font-medium shadow-xl border flex items-center gap-2 transform transition-all duration-300 pointer-events-auto ${
        type === "success"
            ? "bg-emerald-950 text-emerald-200 border-emerald-800"
            : type === "error"
            ? "bg-red-950 text-red-200 border-red-800"
            : "bg-slate-900 text-slate-200 border-slate-700"
    }`;

    toast.innerHTML = `
        <span>${message}</span>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateY(10px)";
        setTimeout(() => toast.remove(), 300);
    }, 3200);
}

// Format Seconds to HH:MM:SS
function formatTime(seconds) {
    if (seconds <= 0) return "Expired";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

// System Status Poller
let tokenRemaining = 0;
let statusInterval = null;

async function updateSystemStatus() {
    try {
        const res = await fetch("/api/status");
        if (!res.ok) return;
        const data = await res.json();

        const indicatorDot = document.getElementById("status-indicator-dot");
        const statusText = document.getElementById("status-text");
        const authBtn = document.getElementById("btn-header-auth");
        const accountCard = document.getElementById("status-card-account");
        const channelsCard = document.getElementById("status-card-channels");

        if (data.logged) {
            indicatorDot.className = "w-2 h-2 rounded-full bg-emerald-400";
            statusText.textContent = `Connected (${data.country_code.toUpperCase()})`;
            authBtn.textContent = "Re-connect";
            authBtn.className = "btn-secondary text-xs px-3 py-1.5";

            if (accountCard) {
                accountCard.innerHTML = `<span class="w-2.5 h-2.5 rounded-full bg-emerald-400"></span> Active Session`;
            }
        } else {
            indicatorDot.className = "w-2 h-2 rounded-full bg-amber-400 animate-pulse";
            statusText.textContent = "Not Connected";
            authBtn.textContent = "Connect Account";
            authBtn.className = "btn-primary text-xs px-3 py-1.5";

            if (accountCard) {
                accountCard.innerHTML = `<span class="w-2.5 h-2.5 rounded-full bg-amber-400"></span> Logged Out`;
            }
        }

        if (channelsCard && data.total_channels > 0) {
            channelsCard.textContent = `${data.total_channels} Channels`;
        }

        tokenRemaining = data.token_expires_in_seconds || 0;
    } catch (err) {
        console.error("Failed to update status:", err);
    }
}

// Timer Countdown
setInterval(() => {
    if (tokenRemaining > 0) {
        tokenRemaining--;
        const timerEl = document.getElementById("status-card-token-timer");
        if (timerEl) {
            timerEl.textContent = formatTime(tokenRemaining);
        }
    }
}, 1000);

// Connect Modal & Auth Logic
let authPollInterval = null;

async function openConnectModal() {
    const modal = document.getElementById("login-modal");
    const loading = document.getElementById("modal-auth-loading");
    const content = document.getElementById("modal-auth-content");

    modal.classList.remove("hidden");
    loading.classList.remove("hidden");
    content.classList.add("hidden");

    try {
        const res = await fetch("/api/auth/start", { method: "POST" });
        const data = await res.json();

        if (data.result === "OK") {
            document.getElementById("modal-code-display").textContent = data.auth_code;
            document.getElementById("modal-activate-link").href = data.activate_url;
            document.getElementById("modal-qr-image").src = data.qr_url;

            loading.classList.add("hidden");
            content.classList.remove("hidden");

            // Start Polling for confirmation
            if (authPollInterval) clearInterval(authPollInterval);
            authPollInterval = setInterval(async () => {
                try {
                    const checkRes = await fetch(`/api/auth/status?code=${data.auth_code}`);
                    const checkData = await checkRes.json();
                    if (checkData.status === "COMPLETED") {
                        clearInterval(authPollInterval);
                        modal.classList.add("hidden");
                        showToast("Account connected successfully! Loading channels...", "success");
                        updateSystemStatus();
                        if (window.loadChannels) window.loadChannels();
                    }
                } catch (e) {
                    console.error("Auth check failed:", e);
                }
            }, 2500);
        } else {
            showToast("Failed to start authentication with provider.", "error");
        }
    } catch (err) {
        showToast("Error initiating login.", "error");
    }
}

function closeConnectModal() {
    document.getElementById("login-modal").classList.add("hidden");
    if (authPollInterval) {
        clearInterval(authPollInterval);
        authPollInterval = null;
    }
}

// Initialize on DOM Ready
document.addEventListener("DOMContentLoaded", () => {
    // Tab event listeners
    document.querySelectorAll(".nav-tab, .mobile-nav-tab").forEach(tab => {
        tab.addEventListener("click", () => {
            const target = tab.getAttribute("data-tab");
            switchTab(target);
        });
    });

    // Check URL hash for direct tab linking
    if (window.location.hash) {
        const tab = window.location.hash.replace("#", "");
        if (["player", "links", "status", "settings", "guides"].includes(tab)) {
            switchTab(tab);
        }
    }

    // Copy Buttons
    document.querySelectorAll(".btn-copy").forEach(btn => {
        btn.addEventListener("click", () => {
            const targetId = btn.getAttribute("data-target");
            const input = document.getElementById(targetId);
            if (input) {
                navigator.clipboard.writeText(input.value).then(() => {
                    const originalText = btn.textContent;
                    btn.textContent = "Copied!";
                    btn.classList.add("bg-emerald-600");
                    showToast("URL copied to clipboard!", "success");
                    setTimeout(() => {
                        btn.textContent = originalText;
                        btn.classList.remove("bg-emerald-600");
                    }, 2000);
                });
            }
        });
    });

    // Header Auth Button
    document.getElementById("btn-header-auth").addEventListener("click", openConnectModal);
    document.getElementById("btn-close-modal").addEventListener("click", closeConnectModal);

    // Settings Form
    const settingsForm = document.getElementById("settings-form");
    if (settingsForm) {
        settingsForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const payload = {
                countryCode: document.getElementById("setting-country-code").value,
                external_url: document.getElementById("setting-external-url").value,
                default_quality: document.getElementById("setting-default-quality").value,
                direct_redirect: document.getElementById("setting-direct-redirect").value === "true",
            };

            try {
                const res = await fetch("/api/settings", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                if (res.ok) {
                    showToast("Settings updated successfully!", "success");
                    updateSystemStatus();
                    if (window.loadChannels) window.loadChannels();
                } else {
                    showToast("Failed to update settings.", "error");
                }
            } catch (err) {
                showToast("Network error saving settings.", "error");
            }
        });
    }

    // Force Refresh Cache Button
    const refreshBtn = document.getElementById("btn-force-refresh-cache");
    if (refreshBtn) {
        refreshBtn.addEventListener("click", async () => {
            refreshBtn.disabled = true;
            refreshBtn.textContent = "Refreshing...";
            try {
                await fetch("/api/cache/refresh", { method: "POST" });
                showToast("Channels and EPG cache refreshed!", "success");
                updateSystemStatus();
                if (window.loadChannels) window.loadChannels();
            } finally {
                refreshBtn.disabled = false;
                refreshBtn.textContent = "Refresh Cache";
            }
        });
    }

    // Logout Button
    const logoutBtn = document.getElementById("btn-logout");
    if (logoutBtn) {
        logoutBtn.addEventListener("click", async () => {
            if (confirm("Are you sure you want to disconnect your Sweet.tv account?")) {
                await fetch("/api/auth/logout", { method: "POST" });
                showToast("Account disconnected.", "info");
                updateSystemStatus();
                location.reload();
            }
        });
    }

    // Initial Status Check & periodic poll
    updateSystemStatus();
    statusInterval = setInterval(updateSystemStatus, 30000);
});
