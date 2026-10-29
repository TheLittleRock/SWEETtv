/**
 * Sweet.tv IPTV Proxy Server & Web TV Dashboard Controller
 */

// Tab Switching with Quick Mode Switcher integration
function switchTab(tabName) {
    document.querySelectorAll(".tab-content").forEach(el => el.classList.add("hidden"));
    const target = document.getElementById(`tab-${tabName}`);
    if (target) {
        target.classList.remove("hidden");
    }

    // Top Navigation Tabs
    document.querySelectorAll(".nav-tab, .mobile-nav-tab").forEach(tab => {
        if (tab.getAttribute("data-tab") === tabName) {
            tab.classList.add("active");
        } else {
            tab.classList.remove("active");
        }
    });

    // 1-Click Quick Mode Switcher
    const qPlayer = document.getElementById("quick-toggle-player");
    const qLinks = document.getElementById("quick-toggle-links");
    if (qPlayer && qLinks) {
        if (tabName === "player") {
            qPlayer.className = "quick-mode-btn active flex items-center justify-center gap-2 px-3 sm:px-4 py-2 rounded-lg text-xs font-bold transition-all bg-slate-800 text-cyan-400 border border-slate-700 shadow-sm";
            qLinks.className = "quick-mode-btn flex items-center justify-center gap-2 px-3 sm:px-4 py-2 rounded-lg text-xs font-bold transition-all text-slate-400 hover:text-white";
        } else if (tabName === "links") {
            qPlayer.className = "quick-mode-btn flex items-center justify-center gap-2 px-3 sm:px-4 py-2 rounded-lg text-xs font-bold transition-all text-slate-400 hover:text-white";
            qLinks.className = "quick-mode-btn active flex items-center justify-center gap-2 px-3 sm:px-4 py-2 rounded-lg text-xs font-bold transition-all bg-slate-800 text-emerald-400 border border-slate-700 shadow-sm";
        } else {
            qPlayer.className = "quick-mode-btn flex items-center justify-center gap-2 px-3 sm:px-4 py-2 rounded-lg text-xs font-bold transition-all text-slate-400 hover:text-white";
            qLinks.className = "quick-mode-btn flex items-center justify-center gap-2 px-3 sm:px-4 py-2 rounded-lg text-xs font-bold transition-all text-slate-400 hover:text-white";
        }
    }

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

    toast.innerHTML = `<span>${message}</span>`;
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
        const accountCardStatus = document.getElementById("account-card-status");
        const accountCardChannels = document.getElementById("account-card-channels");
        const accountDisplayMac = document.getElementById("account-display-mac");
        const accountDisplayUuid = document.getElementById("account-display-uuid");

        if (data.logged) {
            indicatorDot.className = "w-2 h-2 rounded-full bg-emerald-400";
            const connStr = typeof t === "function" ? t("nav.connected") : "Connected";
            statusText.textContent = `${connStr} (${data.country_code.toUpperCase()})`;
            authBtn.textContent = typeof t === "function" ? t("nav.reconnect") : "Re-connect";
            authBtn.className = "btn-secondary text-xs px-2.5 sm:px-3 py-1.5 whitespace-nowrap";

            if (accountCard) {
                accountCard.innerHTML = `<span class="w-2.5 h-2.5 rounded-full bg-emerald-400"></span> ${typeof t === "function" ? t("status.account") : "Active Session"}`;
            }
            if (accountCardStatus) {
                accountCardStatus.innerHTML = `<span class="w-2.5 h-2.5 rounded-full bg-emerald-400"></span> ${typeof t === "function" ? (t("account.active_session") || "Aktivní relace Sweet.tv") : "Active Session"}`;
            }
        } else {
            indicatorDot.className = "w-2 h-2 rounded-full bg-amber-400 animate-pulse";
            statusText.textContent = typeof t === "function" ? t("nav.disconnected") : "Disconnected";
            authBtn.textContent = typeof t === "function" ? t("nav.connect") : "Connect";
            authBtn.className = "btn-primary text-xs px-2.5 sm:px-3 py-1.5 whitespace-nowrap";

            if (accountCard) {
                accountCard.innerHTML = `<span class="w-2.5 h-2.5 rounded-full bg-amber-400"></span> ${typeof t === "function" ? t("nav.disconnected") : "Logged Out"}`;
            }
            if (accountCardStatus) {
                accountCardStatus.innerHTML = `<span class="w-2.5 h-2.5 rounded-full bg-amber-400"></span> ${typeof t === "function" ? (t("account.no_session") || "Nepřipojeno") : "Not Connected"}`;
            }
        }

        if (channelsCard && data.total_channels > 0) {
            channelsCard.textContent = `${data.total_channels}`;
        }
        if (accountCardChannels && data.total_channels > 0) {
            accountCardChannels.textContent = `${data.total_channels}`;
        }

        if (document.getElementById("display-virtual-mac") && data.mac) {
            document.getElementById("display-virtual-mac").textContent = data.mac;
        }
        if (accountDisplayMac && data.mac) {
            accountDisplayMac.textContent = data.mac;
        }
        if (document.getElementById("display-virtual-uuid") && data.uuid) {
            document.getElementById("display-virtual-uuid").textContent = data.uuid;
        }
        if (accountDisplayUuid && data.uuid) {
            accountDisplayUuid.textContent = data.uuid;
        }

        tokenRemaining = data.token_expires_in_seconds || 0;
    } catch (err) {
        console.error("Failed to update status:", err);
    }
}

// Countdown loop
setInterval(() => {
    if (tokenRemaining > 0) {
        tokenRemaining--;
        const timerEl = document.getElementById("status-card-token-timer");
        const accountTimerEl = document.getElementById("account-card-token-timer");
        const formatted = formatTime(tokenRemaining);
        if (timerEl) {
            timerEl.textContent = formatted;
        }
        if (accountTimerEl) {
            accountTimerEl.textContent = formatted;
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

// Copy to Clipboard Helper
function copyText(text, btnElement) {
    navigator.clipboard.writeText(text).then(() => {
        const originalText = btnElement ? btnElement.innerHTML : "";
        if (btnElement) {
            btnElement.textContent = typeof t === "function" ? t("msg.copied") : "Copied!";
            btnElement.classList.add("bg-emerald-600");
        }
        showToast(typeof t === "function" ? t("msg.copied") : "URL copied to clipboard!", "success");
        setTimeout(() => {
            if (btnElement) {
                btnElement.innerHTML = originalText;
                btnElement.classList.remove("bg-emerald-600");
            }
        }, 2000);
    });
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
        if (["player", "links", "account", "status", "settings", "guides"].includes(tab)) {
            switchTab(tab);
        }
    }

    // Universal Copy Buttons (handles both input targets and direct URLs)
    document.querySelectorAll(".btn-copy").forEach(btn => {
        btn.addEventListener("click", () => {
            const directUrl = btn.getAttribute("data-copy-url");
            if (directUrl) {
                copyText(directUrl, btn);
                return;
            }
            const targetId = btn.getAttribute("data-target");
            const input = document.getElementById(targetId);
            if (input) {
                copyText(input.value, btn);
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
            const catchupInput = document.getElementById("setting-m3u-catchup");
            const xUserEl = document.getElementById("setting-xtream-user");
            const xPwdEl = document.getElementById("setting-xtream-password");

            const payload = {
                countryCode: document.getElementById("setting-country-code").value,
                external_url: document.getElementById("setting-external-url").value,
                default_quality: document.getElementById("setting-default-quality").value,
                direct_redirect: document.getElementById("setting-direct-redirect").value === "true",
                m3u_catchup: catchupInput ? catchupInput.checked : true,
                xtream_user: xUserEl ? xUserEl.value.trim() : "sweettv",
                xtream_password: xPwdEl ? xPwdEl.value.trim() : "sweet",
            };

            try {
                const res = await fetch("/api/settings", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                if (res.ok) {
                    showToast(typeof t === "function" ? t("msg.settings_saved") : "Settings updated successfully!", "success");
                    // Update display on XTream card if present
                    const dispUser = document.getElementById("display-xtream-user");
                    const dispPwd = document.getElementById("display-xtream-pwd");
                    if (dispUser && payload.xtream_user) dispUser.textContent = payload.xtream_user;
                    if (dispPwd && payload.xtream_password) dispPwd.textContent = payload.xtream_password;
                    updateSystemStatus();
                    if (window.loadChannels) window.loadChannels();
                } else {
                    showToast(typeof t === "function" ? t("msg.settings_failed") : "Failed to update settings.", "error");
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
                showToast(typeof t === "function" ? t("msg.cache_refreshed") : "Channels and EPG cache refreshed!", "success");
                updateSystemStatus();
                if (window.loadChannels) window.loadChannels();
            } finally {
                refreshBtn.disabled = false;
                refreshBtn.textContent = typeof t === "function" ? t("settings.refresh_btn") : "Refresh Cache";
            }
        });
    }

    // Account Disconnect Routine
    async function handleAccountDisconnect() {
        const confirmMsg = typeof t === "function" ? t("status.disconnect_confirm") : "Are you sure you want to disconnect from your Sweet.tv account?";
        if (confirm(confirmMsg)) {
            await fetch("/api/auth/logout", { method: "POST" });
            showToast(typeof t === "function" ? t("msg.logged_out") : "Account disconnected.", "info");
            updateSystemStatus();
            location.reload();
        }
    }

    const logoutBtn = document.getElementById("btn-logout");
    if (logoutBtn) {
        logoutBtn.addEventListener("click", handleAccountDisconnect);
    }
    const statusDisconnectBtn = document.getElementById("btn-status-disconnect");
    if (statusDisconnectBtn) {
        statusDisconnectBtn.addEventListener("click", handleAccountDisconnect);
    }
    const accountDisconnectBtn = document.getElementById("btn-account-disconnect");
    if (accountDisconnectBtn) {
        accountDisconnectBtn.addEventListener("click", handleAccountDisconnect);
    }

    // Reset Device Hardware Identity (New UUID & MAC)
    async function handleDeviceReset(btnElement) {
        const confirmMsg = typeof t === "function" ? t("status.reset_device_confirm") : "Are you sure you want to reset device identity?";
        if (confirm(confirmMsg)) {
            if (btnElement) btnElement.disabled = true;
            try {
                const res = await fetch("/api/auth/reset-device", { method: "POST" });
                const data = await res.json();
                if (data.status === "OK") {
                    showToast(typeof t === "function" ? t("msg.device_reset") : "Device identity reset successfully.", "success");
                    if (document.getElementById("display-virtual-mac")) {
                        document.getElementById("display-virtual-mac").textContent = data.mac;
                    }
                    if (document.getElementById("account-display-mac")) {
                        document.getElementById("account-display-mac").textContent = data.mac;
                    }
                    if (document.getElementById("display-virtual-uuid")) {
                        document.getElementById("display-virtual-uuid").textContent = data.uuid;
                    }
                    if (document.getElementById("account-display-uuid")) {
                        document.getElementById("account-display-uuid").textContent = data.uuid;
                    }
                    updateSystemStatus();
                    openConnectModal();
                }
            } catch (e) {
                showToast("Error resetting device identity.", "error");
            } finally {
                if (btnElement) btnElement.disabled = false;
            }
        }
    }

    const resetDeviceBtn = document.getElementById("btn-status-reset-device");
    if (resetDeviceBtn) {
        resetDeviceBtn.addEventListener("click", () => handleDeviceReset(resetDeviceBtn));
    }
    const accountResetBtn = document.getElementById("btn-account-reset-device");
    if (accountResetBtn) {
        accountResetBtn.addEventListener("click", () => handleDeviceReset(accountResetBtn));
    }

    const accountPairBtn = document.getElementById("btn-account-pair");
    if (accountPairBtn) {
        accountPairBtn.addEventListener("click", openConnectModal);
    }

    // Listen for language changes to update live status indicators
    window.addEventListener("sweettv-language-changed", () => {
        updateSystemStatus();
    });

    // Initial Status Check & periodic poll
    updateSystemStatus();
    statusInterval = setInterval(updateSystemStatus, 30000);
});
