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

    if (tabName === "users" && typeof loadUsersList === "function") {
        loadUsersList();
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
            if (authBtn) {
                authBtn.textContent = typeof t === "function" ? t("nav.reconnect") : "Re-connect";
                authBtn.className = "btn-secondary text-xs px-2.5 sm:px-3 py-1.5 whitespace-nowrap";
            }

            if (accountCard) {
                accountCard.innerHTML = `<span class="w-2.5 h-2.5 rounded-full bg-emerald-400"></span> ${typeof t === "function" ? t("status.account") : "Active Session"}`;
            }
            if (accountCardStatus) {
                accountCardStatus.innerHTML = `<span class="w-2.5 h-2.5 rounded-full bg-emerald-400"></span> ${typeof t === "function" ? (t("account.active_session") || "Aktivní relace Sweet.tv") : "Active Session"}`;
            }
        } else {
            indicatorDot.className = "w-2 h-2 rounded-full bg-amber-400 animate-pulse";
            statusText.textContent = typeof t === "function" ? t("nav.disconnected") : "Disconnected";
            if (authBtn) {
                authBtn.textContent = typeof t === "function" ? t("nav.connect") : "Connect";
                authBtn.className = "btn-primary text-xs px-2.5 sm:px-3 py-1.5 whitespace-nowrap";
            }

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
        const res = await fetch("/api/provider/auth/start", { method: "POST" });
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
                    const checkRes = await fetch(`/api/provider/auth/status?code=${data.auth_code}`);
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

// Link Format Switcher (Query vs Path)
let currentLinkFormat = localStorage.getItem("sweettv_link_format") || "query";

function updateLinksFormat(format) {
    currentLinkFormat = format;
    localStorage.setItem("sweettv_link_format", format);

    const btnQuery = document.getElementById("btn-fmt-query");
    const btnPath = document.getElementById("btn-fmt-path");
    if (btnQuery && btnPath) {
        if (format === "query") {
            btnQuery.className = "px-2.5 py-1 rounded-lg font-semibold bg-slate-800 text-cyan-400 shadow-sm transition-all";
            btnPath.className = "px-2.5 py-1 rounded-lg font-semibold text-slate-400 hover:text-white transition-all";
        } else {
            btnPath.className = "px-2.5 py-1 rounded-lg font-semibold bg-slate-800 text-cyan-400 shadow-sm transition-all";
            btnQuery.className = "px-2.5 py-1 rounded-lg font-semibold text-slate-400 hover:text-white transition-all";
        }
    }

    const tokenInput = document.getElementById("profile-token-display");
    const token = tokenInput ? tokenInput.value.trim() : "";
    if (!token) return;

    const origin = window.location.origin;

    // 1. Adaptive M3U
    const inputAdaptive = document.getElementById("url-m3u-adaptive");
    const dlAdaptive = document.getElementById("download-m3u-adaptive");
    const adaptiveUrl = format === "query" 
        ? `${origin}/playlist.m3u?token=${token}` 
        : `${origin}/t/${token}/playlist.m3u`;
    if (inputAdaptive) inputAdaptive.value = adaptiveUrl;
    if (dlAdaptive) dlAdaptive.href = adaptiveUrl;

    // 2. Best M3U
    const inputBest = document.getElementById("url-m3u-best");
    const dlBest = document.getElementById("download-m3u-best");
    const bestUrl = format === "query" 
        ? `${origin}/playlist.m3u?token=${token}&quality=best` 
        : `${origin}/t/${token}/playlist.m3u?quality=best`;
    if (inputBest) inputBest.value = bestUrl;
    if (dlBest) dlBest.href = bestUrl;

    // 3. Catchup M3U
    const inputCatchup = document.getElementById("url-m3u-catchup");
    const dlCatchup = document.getElementById("download-m3u-catchup");
    const catchupUrl = format === "query" 
        ? `${origin}/playlist.m3u?token=${token}&quality=best&catchup=vod` 
        : `${origin}/t/${token}/playlist.m3u?quality=best&catchup=vod`;
    if (inputCatchup) inputCatchup.value = catchupUrl;
    if (dlCatchup) dlCatchup.href = catchupUrl;

    // 4. Clean M3U
    const inputClean = document.getElementById("url-m3u-clean");
    const dlClean = document.getElementById("download-m3u-clean");
    const cleanUrl = format === "query" 
        ? `${origin}/playlist_clean.m3u?token=${token}&quality=best` 
        : `${origin}/t/${token}/playlist_clean.m3u?quality=best`;
    if (inputClean) inputClean.value = cleanUrl;
    if (dlClean) dlClean.href = cleanUrl;

    // 5. EPG XML
    const inputEpg = document.getElementById("url-epg-xml");
    const linkEpg = document.getElementById("link-epg-xml");
    const epgUrl = format === "query" 
        ? `${origin}/epg.xml?token=${token}` 
        : `${origin}/t/${token}/epg.xml`;
    if (inputEpg) inputEpg.value = epgUrl;
    if (linkEpg) linkEpg.href = epgUrl;

    // 6. EPG GZ
    const inputEpgGz = document.getElementById("url-epg-gz");
    const epgGzUrl = format === "query" 
        ? `${origin}/epg.xml.gz?token=${token}` 
        : `${origin}/t/${token}/epg.xml.gz`;
    if (inputEpgGz) inputEpgGz.value = epgGzUrl;
}

function setLinkFormat(fmt) {
    updateLinksFormat(fmt);
}

// User Profile & Security Modal
function openProfileModal() {
    const modal = document.getElementById("profile-modal");
    if (modal) modal.classList.remove("hidden");
    const alertBox = document.getElementById("profile-pwd-alert");
    if (alertBox) alertBox.classList.add("hidden");
}

function closeProfileModal() {
    const modal = document.getElementById("profile-modal");
    if (modal) modal.classList.add("hidden");
}

async function regenerateMyToken() {
    const confirmMsg = typeof t === "function" 
        ? (t("profile.regen_confirm") || "Opravdu chcete vygenerovat nový M3U token? Všechny vaše stávající playlisty v aplikacích přestanou fungovat, dokud do nich nezadáte nový odkaz.")
        : "Generate a new M3U token? Existing playlists will stop working until updated.";
    if (!confirm(confirmMsg)) return;

    try {
        const res = await fetch("/api/profile/regenerate-token", { method: "POST" });
        const data = await res.json();
        if (res.ok && data.token) {
            const tokenInput = document.getElementById("profile-token-display");
            if (tokenInput) tokenInput.value = data.token;
            updateLinksFormat(currentLinkFormat);
            showToast(typeof t === "function" ? t("profile.token_success") : "New M3U security token generated!", "success");
        } else {
            showToast("Failed to regenerate token.", "error");
        }
    } catch (e) {
        showToast("Network error regenerating token.", "error");
    }
}

// Admin User Management Controller
let currentUsers = [];

async function loadUsersList() {
    const tbody = document.getElementById("users-table-body");
    if (!tbody) return;

    try {
        const res = await fetch("/api/users");
        if (!res.ok) {
            tbody.innerHTML = `<tr><td colspan="7" class="py-6 text-center text-red-400">Chyba načítání uživatelů</td></tr>`;
            return;
        }
        currentUsers = await res.json();
        renderUsersTable(currentUsers);
    } catch (e) {
        console.error("Failed to load users:", e);
        if (tbody) {
            tbody.innerHTML = `<tr><td colspan="7" class="py-6 text-center text-red-400">Chyba spojení se serverem</td></tr>`;
        }
    }
}

function renderUsersTable(users) {
    const tbody = document.getElementById("users-table-body");
    if (!tbody) return;

    if (!users || users.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="py-8 text-center text-slate-500">${typeof t === "function" ? t("users.empty") : "No users found."}</td></tr>`;
        return;
    }

    const currentUsername = document.getElementById("btn-open-profile")?.querySelector("span")?.textContent?.trim() || "";

    tbody.innerHTML = users.map(u => {
        const isAdmin = u.role === "admin";
        const roleBadge = isAdmin
            ? `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-cyan-950 text-cyan-300 border border-cyan-700/60">Admin</span>`
            : `<span class="px-2 py-0.5 rounded-full text-[10px] font-medium bg-slate-800 text-slate-300 border border-slate-700">Uživatel</span>`;

        let statusBadge;
        if (!u.is_active) {
            statusBadge = `<span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium bg-red-950/60 text-red-400 border border-red-800/60"><span class="w-1.5 h-1.5 rounded-full bg-red-400"></span>${typeof t === "function" ? t("users.inactive") : "Inactive"}</span>`;
        } else if (u.is_expired) {
            statusBadge = `<span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-950/60 text-amber-400 border border-amber-800/60"><span class="w-1.5 h-1.5 rounded-full bg-amber-400"></span>${typeof t === "function" ? t("users.expired") : "Expired"}</span>`;
        } else {
            statusBadge = `<span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-950/60 text-emerald-400 border border-emerald-800/60"><span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>${typeof t === "function" ? t("users.active") : "Active"}</span>`;
        }

        const maskedToken = u.token ? `${u.token.substring(0, 6)}••••••••` : "—";
        const expiresStr = u.expires_at ? new Date(u.expires_at).toLocaleDateString() : (typeof t === "function" ? t("users.never_expires") : "Never");
        const lastLoginStr = u.last_login ? new Date(u.last_login).toLocaleString() : (typeof t === "function" ? t("users.never_active") : "Never");

        const isSelf = u.username === currentUsername;
        const deleteBtn = isSelf 
            ? `<span class="text-slate-600 text-xs cursor-not-allowed p-1" title="Nelze smazat vlastní přihlášený účet">🗑️</span>`
            : `<button onclick="deleteUser(${u.id}, '${u.username}')" class="text-slate-400 hover:text-red-400 transition-colors p-1" title="${typeof t === "function" ? t("users.delete") : "Delete"}"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg></button>`;

        return `
            <tr class="hover:bg-slate-800/40 transition-colors">
                <td class="py-3 px-4 font-semibold text-white">
                    <div class="flex items-center gap-2">
                        <span>${u.username}</span>
                        ${u.must_change_password ? '<span class="text-[9px] px-1.5 py-0.2 rounded bg-amber-950 text-amber-300 font-bold border border-amber-800" title="Výchozí heslo">Výchozí heslo</span>' : ''}
                    </div>
                </td>
                <td class="py-3 px-4">${roleBadge}</td>
                <td class="py-3 px-4 font-mono text-[11px] text-cyan-300">
                    <div class="flex items-center gap-1.5">
                        <span>${maskedToken}</span>
                        <button type="button" onclick="copyText('${u.token}', this)" class="text-slate-400 hover:text-white p-1" title="Kopírovat token">📋</button>
                    </div>
                </td>
                <td class="py-3 px-4">${statusBadge}</td>
                <td class="py-3 px-4 text-slate-400 text-[11px]">${expiresStr}</td>
                <td class="py-3 px-4 text-slate-400 text-[11px]">${lastLoginStr}</td>
                <td class="py-3 px-4 text-right">
                    <div class="flex items-center justify-end gap-1">
                        <button onclick="adminRegenerateToken(${u.id}, '${u.username}')" class="text-slate-400 hover:text-amber-400 transition-colors p-1" title="${typeof t === "function" ? t("users.regen_token") : "Regenerate Token"}">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
                        </button>
                        <button onclick="openEditUserModalById(${u.id})" class="text-slate-400 hover:text-cyan-400 transition-colors p-1" title="${typeof t === "function" ? t("users.edit") : "Edit"}">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>
                        </button>
                        ${deleteBtn}
                    </div>
                </td>
            </tr>
        `;
    }).join("");
}

function openCreateUserModal() {
    const modal = document.getElementById("modal-create-user");
    if (modal) modal.classList.remove("hidden");
    const err = document.getElementById("create-user-error");
    if (err) err.classList.add("hidden");
    document.getElementById("create-username")?.focus();
}

function closeCreateUserModal() {
    const modal = document.getElementById("modal-create-user");
    if (modal) modal.classList.add("hidden");
}

function openEditUserModalById(id) {
    const user = currentUsers.find(u => u.id === id);
    if (!user) return;
    openEditUserModal(user);
}

function openEditUserModal(user) {
    const modal = document.getElementById("modal-edit-user");
    if (!modal) return;
    document.getElementById("edit-user-id").value = user.id;
    document.getElementById("edit-user-subtitle").textContent = `${user.username} (ID #${user.id})`;
    document.getElementById("edit-role").value = user.role;
    document.getElementById("edit-is-active").checked = !!user.is_active;
    document.getElementById("edit-expires").value = user.expires_at ? user.expires_at.split("T")[0] : "";
    document.getElementById("edit-new-pwd").value = "";
    document.getElementById("edit-user-error").classList.add("hidden");
    modal.classList.remove("hidden");
}

function closeEditUserModal() {
    const modal = document.getElementById("modal-edit-user");
    if (modal) modal.classList.add("hidden");
}

async function deleteUser(id, username) {
    const confirmMsg = typeof t === "function" 
        ? t("users.delete_confirm").replace("{username}", username)
        : `Are you sure you want to delete user ${username}?`;
    if (!confirm(confirmMsg)) return;

    try {
        const res = await fetch(`/api/users/${id}`, { method: "DELETE" });
        if (res.ok) {
            showToast(typeof t === "function" ? t("users.deleted_success") : "User deleted successfully!", "success");
            loadUsersList();
        } else {
            const data = await res.json();
            showToast(data.detail || "Error deleting user.", "error");
        }
    } catch (e) {
        showToast("Network error deleting user.", "error");
    }
}

async function adminRegenerateToken(id, username) {
    const confirmMsg = typeof t === "function" 
        ? t("users.token_regen_confirm").replace("{username}", username)
        : `Regenerate M3U token for ${username}?`;
    if (!confirm(confirmMsg)) return;

    try {
        const res = await fetch(`/api/users/${id}/regenerate-token`, { method: "POST" });
        if (res.ok) {
            showToast(typeof t === "function" ? t("users.token_regen_success") : "Token regenerated successfully!", "success");
            loadUsersList();
        } else {
            showToast("Failed to regenerate user token.", "error");
        }
    } catch (e) {
        showToast("Network error regenerating user token.", "error");
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
        if (["player", "links", "users", "account", "status", "settings", "guides"].includes(tab)) {
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

    // Header Auth Button (if present)
    const headerAuthBtn = document.getElementById("btn-header-auth");
    if (headerAuthBtn) {
        headerAuthBtn.addEventListener("click", openConnectModal);
    }
    const closeModalBtn = document.getElementById("btn-close-modal");
    if (closeModalBtn) {
        closeModalBtn.addEventListener("click", closeConnectModal);
    }

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
            await fetch("/api/provider/auth/logout", { method: "POST" });
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
                const res = await fetch("/api/provider/auth/reset-device", { method: "POST" });
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

    // Profile Change Password Form
    const profilePwdForm = document.getElementById("profile-password-form");
    if (profilePwdForm) {
        profilePwdForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const oldPwd = document.getElementById("profile-old-pwd").value;
            const newPwd = document.getElementById("profile-new-pwd").value;
            const confirmPwd = document.getElementById("profile-confirm-pwd").value;
            const alertBox = document.getElementById("profile-pwd-alert");

            if (newPwd !== confirmPwd) {
                alertBox.className = "text-xs p-2.5 rounded-xl bg-red-950 text-red-300 border border-red-800";
                alertBox.textContent = typeof t === "function" ? t("profile.pwd_mismatch") : "New passwords do not match.";
                alertBox.classList.remove("hidden");
                return;
            }

            try {
                const res = await fetch("/api/profile/password", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ old_password: oldPwd, new_password: newPwd })
                });
                const data = await res.json();
                if (res.ok) {
                    alertBox.className = "text-xs p-2.5 rounded-xl bg-emerald-950 text-emerald-300 border border-emerald-800";
                    alertBox.textContent = typeof t === "function" ? t("profile.pwd_success") : "Password changed successfully!";
                    alertBox.classList.remove("hidden");
                    profilePwdForm.reset();
                    // Remove default password banner if visible
                    const banner = document.getElementById("warning-default-password");
                    if (banner) banner.remove();
                    showToast(typeof t === "function" ? t("profile.pwd_success") : "Password changed successfully!", "success");
                    setTimeout(() => closeProfileModal(), 1500);
                } else {
                    alertBox.className = "text-xs p-2.5 rounded-xl bg-red-950 text-red-300 border border-red-800";
                    alertBox.textContent = data.detail || "Error changing password.";
                    alertBox.classList.remove("hidden");
                }
            } catch (err) {
                alertBox.className = "text-xs p-2.5 rounded-xl bg-red-950 text-red-300 border border-red-800";
                alertBox.textContent = "Network error changing password.";
                alertBox.classList.remove("hidden");
            }
        });
    }

    // Admin Create User Form
    const createUserForm = document.getElementById("form-create-user");
    if (createUserForm) {
        createUserForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const username = document.getElementById("create-username").value.trim();
            const password = document.getElementById("create-password").value;
            const role = document.getElementById("create-role").value;
            const expires = document.getElementById("create-expires").value || null;
            const errBox = document.getElementById("create-user-error");

            try {
                const res = await fetch("/api/users", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ username, password, role, is_active: true, expires_at: expires })
                });
                const data = await res.json();
                if (res.ok) {
                    closeCreateUserModal();
                    createUserForm.reset();
                    showToast(typeof t === "function" ? t("users.created_success") : "User created successfully!", "success");
                    loadUsersList();
                } else {
                    errBox.textContent = data.detail || "Error creating user.";
                    errBox.classList.remove("hidden");
                }
            } catch (err) {
                errBox.textContent = "Network error creating user.";
                errBox.classList.remove("hidden");
            }
        });
    }

    // Admin Edit User Form
    const editUserForm = document.getElementById("form-edit-user");
    if (editUserForm) {
        editUserForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const id = document.getElementById("edit-user-id").value;
            const role = document.getElementById("edit-role").value;
            const isActive = document.getElementById("edit-is-active").checked;
            const expires = document.getElementById("edit-expires").value || null;
            const newPassword = document.getElementById("edit-new-pwd").value || null;
            const errBox = document.getElementById("edit-user-error");

            try {
                const res = await fetch(`/api/users/${id}`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ role, is_active: isActive, expires_at: expires, new_password: newPassword })
                });
                const data = await res.json();
                if (res.ok) {
                    closeEditUserModal();
                    showToast(typeof t === "function" ? t("users.updated_success") : "User updated successfully!", "success");
                    loadUsersList();
                } else {
                    errBox.textContent = data.detail || "Error updating user.";
                    errBox.classList.remove("hidden");
                }
            } catch (err) {
                errBox.textContent = "Network error updating user.";
                errBox.classList.remove("hidden");
            }
        });
    }

    // Initialize link formats
    updateLinksFormat(currentLinkFormat);

    // Load users if on users tab
    if (window.location.hash === "#users") {
        loadUsersList();
    }

    // Listen for language changes to update live status indicators
    window.addEventListener("sweettv-language-changed", () => {
        updateSystemStatus();
    });

    // Initial Status Check & periodic poll
    updateSystemStatus();
    statusInterval = setInterval(updateSystemStatus, 30000);
});
