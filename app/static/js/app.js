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

    if (tabName === "vod" && typeof loadVodCatalog === "function") {
        loadVodCatalog();
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

    // 7. Stalker Portal
    const urlStalker = document.getElementById("url-stalker-portal");
    const btnCopyStalker = document.getElementById("btn-copy-stalker");
    const stalkerUrl = format === "query"
        ? `${origin}/c/?token=${token}`
        : `${origin}/t/${token}/c/`;
    if (urlStalker) urlStalker.textContent = stalkerUrl;
    if (btnCopyStalker) btnCopyStalker.setAttribute("data-copy-url", stalkerUrl);
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

async function saveProfileMacFromModal() {
    const input = document.getElementById("profile-mac-input");
    if (!input) return;
    const mac = input.value.trim();

    try {
        const res = await fetch("/api/profile/stalker-mac", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mac: mac })
        });
        const data = await res.json();
        if (res.ok) {
            showToast(typeof t === "function" ? t("profile.mac_saved_success") : "MAC adresa pro Stalker portál byla úspěšně uložena!", "success");
            input.value = data.stalker_mac || "";
            const display = document.getElementById("user-stalker-mac-display");
            if (display) {
                display.innerHTML = data.stalker_mac ? data.stalker_mac : '<span class="text-slate-500 italic">Není nastavena</span>';
            }
        } else {
            showToast(data.detail || "Chyba při ukládání MAC adresy.", "error");
        }
    } catch (e) {
        showToast("Chyba spojení při ukládání MAC adresy.", "error");
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
            tbody.innerHTML = `<tr><td colspan="7" class="py-6 text-center text-red-400">Chyba načítání uživatelů (${res.status})</td></tr>`;
            return;
        }
        const data = await res.json();
        currentUsers = Array.isArray(data) ? data : (data.users || []);
        renderUsersTable(currentUsers);
    } catch (e) {
        console.error("Failed to load users:", e);
        if (tbody) {
            tbody.innerHTML = `<tr><td colspan="7" class="py-6 text-center text-red-400">Chyba spojení se serverem: ${e.message || e}</td></tr>`;
        }
    }
}

function renderUsersTable(users) {
    const tbody = document.getElementById("users-table-body");
    if (!tbody) return;

    const list = Array.isArray(users) ? users : ((users && Array.isArray(users.users)) ? users.users : []);

    if (!list || list.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="py-8 text-center text-slate-500">${typeof t === "function" ? t("users.empty") : "No users found."}</td></tr>`;
        return;
    }

    const currentUsername = document.getElementById("btn-open-profile")?.querySelector("span")?.textContent?.trim() || "";

    tbody.innerHTML = list.map(u => {
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
        const macStr = u.stalker_mac 
            ? `<span class="font-mono text-cyan-300 font-semibold select-all">${u.stalker_mac}</span>` 
            : `<span class="text-slate-500 italic">Nenastavena</span>`;
        let expiresStr = typeof t === "function" ? t("users.never_expires") : "Bez expirace";
        if (u.expires_at) {
            try {
                expiresStr = new Date(u.expires_at).toLocaleDateString();
            } catch (_) {}
        }
        let lastLoginStr = typeof t === "function" ? t("users.never_active") : "Nikdy";
        const rawLogin = u.last_login_at || u.last_login;
        if (rawLogin) {
            try {
                lastLoginStr = new Date(rawLogin).toLocaleString();
            } catch (_) {}
        }

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
                <td class="py-3 px-4">${macStr}</td>
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
    const macInput = document.getElementById("create-mac");
    if (macInput) macInput.value = "";
    document.getElementById("create-username")?.focus();
}

function closeCreateUserModal() {
    const modal = document.getElementById("modal-create-user");
    if (modal) modal.classList.add("hidden");
}

function openEditUserModalById(id) {
    const list = Array.isArray(currentUsers) ? currentUsers : ((currentUsers && currentUsers.users) ? currentUsers.users : []);
    const user = list.find(u => u.id === id);
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
    const macInput = document.getElementById("edit-mac");
    if (macInput) macInput.value = user.stalker_mac || "";
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

    // Oneplay Settings Form
    const oneplayForm = document.getElementById("oneplay-settings-form");
    if (oneplayForm) {
        oneplayForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const btn = document.getElementById("btn-oneplay-login");
            const userEl = document.getElementById("setting-oneplay-user");
            const pwdEl = document.getElementById("setting-oneplay-pwd");
            const pinEl = document.getElementById("setting-oneplay-pin");
            const devEl = document.getElementById("setting-oneplay-device");
            const enabledEl = document.getElementById("setting-oneplay-enabled");

            if (!userEl || !pwdEl) return;
            if (!userEl.value.trim() || !pwdEl.value.trim()) {
                showToast("Zadejte uživatelské jméno a heslo k Oneplay.", "error");
                return;
            }

            if (btn) {
                btn.disabled = true;
                btn.textContent = "Přihlašuji k Oneplay...";
            }

            try {
                if (enabledEl) {
                    await fetch("/api/settings", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ oneplay_enabled: enabledEl.checked })
                    });
                }

                const res = await fetch("/api/provider/oneplay/login", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        username: userEl.value.trim(),
                        password: pwdEl.value.trim(),
                        pin: pinEl ? pinEl.value.trim() : "4321",
                        device_name: devEl ? devEl.value.trim() : "SWEETtv-Oneplay"
                    })
                });

                if (res.ok) {
                    showToast("Úspěšně přihlášeno k Oneplay!", "success");
                    updateSystemStatus();
                    if (window.loadChannels) window.loadChannels();
                    setTimeout(() => location.reload(), 1200);
                } else {
                    const err = await res.json();
                    showToast(err.detail || "Přihlášení k Oneplay se nezdařilo.", "error");
                }
            } catch (err) {
                showToast("Chyba sítě při komunikaci se serverem.", "error");
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = "Přihlásit & Uložit Oneplay";
                }
            }
        });
    }

    // Oneplay Disconnect Button
    const oneplayLogoutBtn = document.getElementById("btn-oneplay-logout");
    if (oneplayLogoutBtn) {
        oneplayLogoutBtn.addEventListener("click", async () => {
            if (confirm("Opravdu chcete odpojit účet Oneplay?")) {
                try {
                    await fetch("/api/provider/oneplay/logout", { method: "POST" });
                    showToast("Účet Oneplay byl odpojen.", "info");
                    setTimeout(() => location.reload(), 1000);
                } catch (e) {
                    showToast("Chyba při odpojování účtu.", "error");
                }
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
            const macInput = document.getElementById("create-mac");
            const stalkerMac = macInput ? macInput.value.trim() : null;
            const errBox = document.getElementById("create-user-error");

            try {
                const res = await fetch("/api/users", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        username,
                        password,
                        role,
                        is_active: true,
                        expires_at: expires,
                        stalker_mac: stalkerMac || null
                    })
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
            const macInput = document.getElementById("edit-mac");
            const stalkerMac = macInput ? macInput.value.trim() : null;
            const errBox = document.getElementById("edit-user-error");

            try {
                const res = await fetch(`/api/users/${id}`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        role,
                        is_active: isActive,
                        expires_at: expires,
                        new_password: newPassword,
                        stalker_mac: stalkerMac
                    })
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

    // Setup VOD Search listener
    const vodSearchInput = document.getElementById("vod-search-input");
    if (vodSearchInput) {
        let vodSearchTimeout = null;
        vodSearchInput.addEventListener("input", (e) => {
            clearTimeout(vodSearchTimeout);
            vodSearchTimeout = setTimeout(() => {
                const query = e.target.value.trim();
                loadVodCatalog(true, query);
            }, 300);
        });
    }
});

// =========================================================================
// ONEPLAY VOD CATALOG & SERIES CONTROLLER
// =========================================================================

let activeVodCategory = "all";
let currentVodPage = 1;
let vodCatalogLoaded = false;
let currentVodItems = [];

function selectVodCategory(catId, btnEl) {
    activeVodCategory = catId;
    currentVodPage = 1;

    // Update active button state
    document.querySelectorAll(".vod-cat-btn").forEach(btn => {
        btn.classList.remove("active", "bg-amber-500", "text-slate-950", "shadow-md", "font-bold");
        btn.classList.add("bg-slate-900", "text-slate-300", "border-slate-800", "font-medium");
    });
    if (btnEl) {
        btnEl.classList.remove("bg-slate-900", "text-slate-300", "border-slate-800", "font-medium");
        btnEl.classList.add("active", "bg-amber-500", "text-slate-950", "shadow-md", "font-bold");
    }

    const searchInput = document.getElementById("vod-search-input");
    if (searchInput) searchInput.value = "";

    loadVodCatalog(true);
}

async function loadVodCatalog(force = false, searchQuery = "") {
    if (vodCatalogLoaded && !force && !searchQuery) return;

    const loadingEl = document.getElementById("vod-loading");
    const gridEl = document.getElementById("vod-grid");
    const emptyEl = document.getElementById("vod-empty");
    const paginationEl = document.getElementById("vod-pagination");
    const pageInfoEl = document.getElementById("vod-page-info");

    if (loadingEl) loadingEl.classList.remove("hidden");
    if (gridEl) gridEl.classList.add("hidden");
    if (emptyEl) emptyEl.classList.add("hidden");
    if (paginationEl) paginationEl.classList.add("hidden");

    try {
        let url = `/api/provider/oneplay/vod/items?category=${encodeURIComponent(activeVodCategory)}&page=${currentVodPage}`;
        if (searchQuery) {
            url += `&query=${encodeURIComponent(searchQuery)}`;
        }

        const res = await fetch(url);
        if (!res.ok) {
            throw new Error(`HTTP error ${res.status}`);
        }

        const data = await res.json();
        const items = data.items || [];
        currentVodItems = items;
        vodCatalogLoaded = true;

        if (loadingEl) loadingEl.classList.add("hidden");

        if (items.length === 0) {
            if (emptyEl) emptyEl.classList.remove("hidden");
            if (gridEl) {
                gridEl.innerHTML = "";
                gridEl.classList.remove("hidden");
            }
            return;
        }

        renderVodGrid(items);

        if (gridEl) gridEl.classList.remove("hidden");
        if (paginationEl && !searchQuery) {
            paginationEl.classList.remove("hidden");
            if (pageInfoEl) pageInfoEl.textContent = `Strana ${currentVodPage}`;
            const prevBtn = document.getElementById("btn-vod-prev");
            if (prevBtn) prevBtn.disabled = currentVodPage <= 1;
        }

    } catch (err) {
        console.error("Failed to load VOD catalog:", err);
        if (loadingEl) loadingEl.classList.add("hidden");
        if (emptyEl) emptyEl.classList.remove("hidden");
        showToast("Nepodařilo se načíst videotéku Oneplay.", "error");
    }
}

function renderVodGrid(items) {
    const gridEl = document.getElementById("vod-grid");
    if (!gridEl) return;

    gridEl.innerHTML = items.map((item, idx) => {
        const isSeries = item.content_type === "show";
        const isRecording = item.content_type === "recording" || activeVodCategory === "recordings";
        const posterUrl = item.image || "https://staticeu.sweet.tv/images/v2/icons/categories/1000.png";
        const typeBadge = isSeries ? "Seriál" : (isRecording ? "Nahrávka" : "Film");
        const typeBadgeClass = isSeries ? "bg-purple-950 text-purple-300 border-purple-800" : (isRecording ? "bg-amber-950 text-amber-300 border-amber-800" : "bg-blue-950 text-blue-300 border-blue-800");

        return `
            <div class="vod-card group" onclick="handleVodClick(${idx})">
                <div class="vod-poster-wrap">
                    <img src="${posterUrl}" alt="${item.title}" class="vod-poster" loading="lazy" onerror="this.src='https://staticeu.sweet.tv/images/v2/icons/categories/1000.png'">
                    <div class="absolute top-2 left-2 flex items-center gap-1">
                        <span class="text-[9px] font-bold px-1.5 py-0.5 rounded border ${typeBadgeClass}">${typeBadge}</span>
                    </div>
                    <div class="absolute top-2 right-2 flex items-center gap-1">
                        ${item.is_drm ? '<span class="badge-drm">DRM</span>' : '<span class="text-[9px] font-mono bg-emerald-950 text-emerald-300 border border-emerald-800 px-1 py-0.5 rounded font-bold">FREE</span>'}
                    </div>
                    <div class="absolute inset-0 bg-gradient-to-t from-slate-950 via-slate-950/20 to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center p-3">
                        <div class="w-12 h-12 rounded-2xl bg-amber-500 text-slate-950 flex items-center justify-center shadow-lg shadow-amber-500/40 transform scale-90 group-hover:scale-100 transition-transform">
                            <svg class="w-6 h-6 ml-0.5" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                        </div>
                    </div>
                </div>
                <div class="p-2.5 sm:p-3 flex flex-col justify-between flex-1">
                    <div>
                        <h4 class="text-xs sm:text-sm font-bold text-white line-clamp-1 group-hover:text-amber-400 transition-colors">${item.title}</h4>
                        ${item.description ? `<p class="text-[11px] text-slate-400 line-clamp-2 mt-1">${item.description}</p>` : ''}
                    </div>
                    ${item.year ? `<div class="text-[10px] text-slate-500 font-mono mt-2">${item.year}</div>` : ''}
                </div>
            </div>
        `;
    }).join("");
}

function handleVodClick(itemIdx) {
    const item = currentVodItems[itemIdx];
    if (!item) return;

    if (item.content_type === "show") {
        openSeriesModal(item);
    } else {
        playVodItem(item);
    }
}

async function playVodItem(item) {
    showToast(`Načítám přehrávání: ${item.title}...`, "info");
    try {
        const res = await fetch("/api/provider/oneplay/vod/play", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(item.payload || {})
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Chyba při spuštění přehrávání.");
        }

        const streamInfo = await res.json();
        if (typeof window.playVodStream === "function") {
            window.playVodStream(item, streamInfo);
        } else {
            showToast("Přehrávač není připraven.", "error");
        }
    } catch (err) {
        console.error("Failed to start VOD stream:", err);
        showToast(err.message || "Chyba při spuštění přehrávání.", "error");
    }
}

function changeVodPage(delta) {
    const newPage = currentVodPage + delta;
    if (newPage < 1) return;
    currentVodPage = newPage;
    loadVodCatalog(true);
}

// Series Modal Controller
async function openSeriesModal(item) {
    const modal = document.getElementById("series-modal");
    if (!modal) return;

    modal.classList.remove("hidden");
    modal.classList.add("flex");

    const titleEl = document.getElementById("series-modal-title");
    const descEl = document.getElementById("series-modal-desc");
    const posterEl = document.getElementById("series-modal-poster");
    const seasonsBar = document.getElementById("series-seasons-bar");
    const epContainer = document.getElementById("series-episodes-container");

    if (titleEl) titleEl.textContent = item.title;
    if (descEl) descEl.textContent = item.description || "";
    if (posterEl) posterEl.src = item.image || "";

    if (seasonsBar) seasonsBar.innerHTML = '<div class="text-xs text-slate-400 py-1">Načítám série...</div>';
    if (epContainer) epContainer.innerHTML = '<div class="text-xs text-slate-400 py-4 text-center">Načítám epizody...</div>';

    try {
        const res = await fetch("/api/provider/oneplay/vod/series", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(item.payload || {})
        });

        if (!res.ok) throw new Error("Chyba při načítání detailu seriálu.");
        const detail = await res.json();

        if (detail.description && descEl) {
            descEl.textContent = detail.description;
        }

        const seasons = detail.seasons || [];
        if (seasons.length > 0) {
            seasonsBar.innerHTML = seasons.map((s, idx) => `
                <button type="button" class="series-season-btn px-3 py-1 rounded-xl text-xs font-semibold ${idx === 0 ? 'bg-amber-500 text-slate-950 active' : 'bg-slate-900 border border-slate-800 text-slate-300 hover:text-white'}" onclick="selectSeriesSeason('${s.carouselId}', ${JSON.stringify(s.criteria).replace(/"/g, '&quot;')}, this)">
                    ${s.label}
                </button>
            `).join("");

            // Load first season
            selectSeriesSeason(seasons[0].carouselId, seasons[0].criteria, seasonsBar.children[0]);
        } else if (detail.episodes && detail.episodes.length > 0) {
            seasonsBar.innerHTML = '<span class="text-xs text-slate-400 font-semibold px-2">Všechny díly</span>';
            renderEpisodes(detail.episodes);
        } else {
            epContainer.innerHTML = '<div class="text-xs text-slate-500 py-4 text-center">Nebyly nalezeny žádné epizody.</div>';
        }

    } catch (err) {
        console.error("Series detail fetch failed:", err);
        if (epContainer) epContainer.innerHTML = '<div class="text-xs text-red-400 py-4 text-center">Chyba při načítání epizod.</div>';
    }
}

async function selectSeriesSeason(carouselId, criteria, btnEl) {
    const epContainer = document.getElementById("series-episodes-container");
    if (epContainer) epContainer.innerHTML = '<div class="text-xs text-slate-400 py-4 text-center">Načítám díly série...</div>';

    document.querySelectorAll(".series-season-btn").forEach(btn => {
        btn.classList.remove("active", "bg-amber-500", "text-slate-950");
        btn.classList.add("bg-slate-900", "text-slate-300", "border-slate-800");
    });
    if (btnEl) {
        btnEl.classList.remove("bg-slate-900", "text-slate-300", "border-slate-800");
        btnEl.classList.add("active", "bg-amber-500", "text-slate-950");
    }

    try {
        const res = await fetch(`/api/provider/oneplay/vod/season?carousel_id=${encodeURIComponent(carouselId)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(criteria)
        });
        if (!res.ok) throw new Error("Chyba při načítání dílů série.");
        const data = await res.json();
        renderEpisodes(data.episodes || []);
    } catch (err) {
        console.error("Failed to load season episodes:", err);
        if (epContainer) epContainer.innerHTML = '<div class="text-xs text-red-400 py-4 text-center">Chyba při načítání dílů této série.</div>';
    }
}

function renderEpisodes(episodes) {
    const epContainer = document.getElementById("series-episodes-container");
    if (!epContainer) return;

    if (!episodes || episodes.length === 0) {
        epContainer.innerHTML = '<div class="text-xs text-slate-500 py-4 text-center">Žádné epizody v této sérii.</div>';
        return;
    }

    epContainer.innerHTML = episodes.map((ep, idx) => {
        const poster = ep.image || "https://staticeu.sweet.tv/images/v2/icons/categories/1000.png";
        return `
            <div class="flex items-center justify-between gap-3 p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 hover:border-amber-500/50 transition-all">
                <div class="flex items-center gap-3 min-w-0">
                    <img src="${poster}" alt="" class="w-16 h-10 object-cover rounded-lg bg-slate-900 border border-slate-800 flex-shrink-0" onerror="this.src='https://staticeu.sweet.tv/images/v2/icons/categories/1000.png'">
                    <div class="min-w-0">
                        <div class="text-xs font-bold text-white truncate">${ep.title}</div>
                        ${ep.description ? `<div class="text-[11px] text-slate-400 line-clamp-1 mt-0.5">${ep.description}</div>` : ''}
                    </div>
                </div>
                <button type="button" class="btn-primary text-xs px-3 py-1.5 rounded-xl whitespace-nowrap flex items-center gap-1.5 flex-shrink-0" onclick="playEpisode(${idx})">
                    <svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                    <span>Přehrát</span>
                </button>
            </div>
        `;
    }).join("");

    window._currentEpisodes = episodes;
}

function playEpisode(idx) {
    const ep = (window._currentEpisodes || [])[idx];
    if (!ep) return;
    closeSeriesModal();
    playVodItem(ep);
}

function closeSeriesModal() {
    const modal = document.getElementById("series-modal");
    if (modal) {
        modal.classList.add("hidden");
        modal.classList.remove("flex");
    }
}
