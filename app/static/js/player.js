/**
 * Sweet.tv Web TV Player & Channel Browser Controller
 * Includes Multi-bitrate HLS Player, 7-Day Catchup Replay, and Search
 */

let hlsInstance = null;
let currentChannel = null;
let allChannels = [];
let allCategories = [];
let activeCategory = "all";
let currentVariants = [];
let currentReplayProgram = null;
let lastDayKeys = [];
let lastTimestampsMap = {};

// DOM References
const videoEl = document.getElementById("tv-player");
const placeholderEl = document.getElementById("player-placeholder");
const loadingEl = document.getElementById("player-loading");
const qualitySelect = document.getElementById("player-quality-select");
const codecBadge = document.getElementById("player-codec-badge");
const channelsListEl = document.getElementById("channels-list");
const categoryPillsEl = document.getElementById("category-pills-container");
const searchInput = document.getElementById("channel-search-input");

// Catchup & Replay DOM References
const catchupDrawer = document.getElementById("catchup-drawer");
const catchupBtn = document.getElementById("btn-toggle-catchup");
const catchupListEl = document.getElementById("catchup-programs-list");
const catchupCloseBtn = document.getElementById("btn-close-catchup");
const replayBanner = document.getElementById("active-replay-banner");
const replayProgName = document.getElementById("replay-program-name");
const returnLiveBtn = document.getElementById("btn-return-live");

// Format Unix Timestamp to HH:MM
function formatTimeHourMin(unixTimestamp) {
    if (!unixTimestamp) return "--:--";
    const d = new Date(unixTimestamp * 1000);
    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
}

// Format Unix Timestamp to Friendly Date
function formatProgrammeDate(unixTimestamp) {
    if (!unixTimestamp) return "";
    const d = new Date(unixTimestamp * 1000);
    const today = new Date();
    const yesterday = new Date();
    yesterday.setDate(today.getDate() - 1);
    const isCs = typeof currentLang !== "undefined" && currentLang === "cs";

    if (d.toDateString() === today.toDateString()) {
        return isCs ? "Dnes" : "Today";
    } else if (d.toDateString() === yesterday.toDateString()) {
        return isCs ? "Včera" : "Yesterday";
    } else {
        return d.toLocaleDateString(isCs ? "cs-CZ" : "en-US", { weekday: 'short', month: 'short', day: 'numeric' });
    }
}

// Format Bitrate to Mbps
function formatBitrate(bps) {
    if (!bps) return "";
    return `(${(bps / 1000000).toFixed(1)} Mbps)`;
}

// Load Channel Lineup from API
async function loadChannels() {
    if (!channelsListEl) return;
    try {
        const res = await fetch("/api/channels");
        if (res.status === 401) {
            const notConnMsg = typeof t === "function" ? (t("player.not_connected") || "Relace Sweet.tv není připojena.") : "Relace Sweet.tv není připojena.";
            const connBtnText = typeof t === "function" ? (t("player.connect_account") || "Připojit účet") : "Připojit účet";
            channelsListEl.innerHTML = `
                <div class="text-center py-12 px-4 space-y-3">
                    <p class="text-xs text-amber-400 font-medium">${notConnMsg}</p>
                    <button onclick="openConnectModal()" class="btn-primary text-xs py-2 px-4">${connBtnText}</button>
                </div>
            `;
            return;
        }

        const data = await res.json();
        allChannels = data.channels || [];
        allCategories = data.categories || [];

        // Render Category Pills
        renderCategories(allCategories);

        // Render Channels
        renderChannels();

        // Auto-select first channel if none selected
        if (!currentChannel && allChannels.length > 0) {
            selectChannel(allChannels[0]);
        }
    } catch (err) {
        console.error("Failed to load channels:", err);
        const loadFailMsg = typeof t === "function" ? (t("player.load_failed") || "Nepodařilo se načíst seznam stanic ze serveru.") : "Nepodařilo se načíst seznam stanic ze serveru.";
        channelsListEl.innerHTML = `
            <div class="text-center py-12 text-xs text-red-400">
                ${loadFailMsg}
            </div>
        `;
    }
}

// Render Categories
function renderCategories(categories) {
    if (!categoryPillsEl) return;
    if (categories) allCategories = categories;

    const allLabel = typeof t === "function" ? (t("category.all") || "Všechny") : "Všechny";
    let html = `<button class="cat-pill ${activeCategory === 'all' ? 'active' : ''}" data-cat="all">${allLabel}</button>`;
    (categories || []).forEach(cat => {
        if (cat.id !== 1000) {
            html += `<button class="cat-pill ${activeCategory === cat.caption ? 'active' : ''}" data-cat="${cat.caption}">${cat.caption}</button>`;
        }
    });

    categoryPillsEl.innerHTML = html;

    // Attach click listeners
    categoryPillsEl.querySelectorAll(".cat-pill").forEach(pill => {
        pill.addEventListener("click", () => {
            categoryPillsEl.querySelectorAll(".cat-pill").forEach(p => p.classList.remove("active"));
            pill.classList.add("active");
            activeCategory = pill.getAttribute("data-cat");
            renderChannels();
        });
    });
}

// Render Channels List
function renderChannels() {
    if (!channelsListEl) return;

    const searchTerm = (searchInput ? searchInput.value || "" : "").toLowerCase().trim();

    const filtered = allChannels.filter(ch => {
        const matchSearch = ch.name.toLowerCase().includes(searchTerm) ||
                            (ch.current_programme && ch.current_programme.title.toLowerCase().includes(searchTerm));
        if (!matchSearch) return false;

        if (activeCategory === "all") return true;
        return ch.categories && ch.categories.includes(activeCategory);
    });

    if (filtered.length === 0) {
        const noMatchMsg = typeof t === "function" ? (t("player.no_matches") || "Nebyly nalezeny žádné stanice odpovídající") : "Nebyly nalezeny žádné stanice odpovídající";
        channelsListEl.innerHTML = `
            <div class="text-center py-12 text-xs text-slate-500">
                ${noMatchMsg} "${searchTerm}".
            </div>
        `;
        return;
    }

    const fallbackProg = typeof t === "function" ? (t("player.live_broadcast") || "Živé vysílání") : "Živé vysílání";

    channelsListEl.innerHTML = filtered.map(ch => {
        const isCurrent = currentChannel && currentChannel.id === ch.id;
        const progTitle = ch.current_programme ? ch.current_programme.title : fallbackProg;
        const progress = ch.current_programme ? ch.current_programme.progress : 0;
        const logo = ch.icon || "https://staticeu.sweet.tv/images/v2/icons/categories/1000.png";

        return `
            <div class="channel-card ${isCurrent ? 'active' : ''}" data-id="${ch.id}">
                <img src="${logo}" alt="${ch.name}" class="w-10 h-10 rounded-lg bg-slate-950 p-1 object-contain border border-slate-800 flex-shrink-0" onerror="this.src='https://staticeu.sweet.tv/images/v2/icons/categories/1000.png'">
                <div class="flex-1 min-w-0">
                    <div class="flex items-center justify-between gap-1 mb-0.5">
                        <span class="text-xs font-bold text-white truncate">${ch.name}</span>
                        ${ch.catchup ? '<span class="text-[9px] font-mono px-1.5 py-0.2 rounded bg-emerald-950 text-emerald-400 border border-emerald-800/60">Catchup</span>' : ''}
                    </div>
                    <div class="text-[11px] text-slate-400 truncate">${progTitle}</div>
                    ${ch.current_programme ? `
                        <div class="w-full bg-slate-800 rounded-full h-1 mt-1.5 overflow-hidden">
                            <div class="bg-cyan-500 h-1 rounded-full" style="width: ${progress}%"></div>
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    }).join("");

    channelsListEl.querySelectorAll(".channel-card").forEach(card => {
        card.addEventListener("click", () => {
            const cid = parseInt(card.getAttribute("data-id"));
            const channel = allChannels.find(c => c.id === cid);
            if (channel) selectChannel(channel);
        });
    });
}

// Select and Play Channel
async function selectChannel(channel) {
    currentChannel = channel;
    currentReplayProgram = null;

    // Update active highlight
    document.querySelectorAll(".channel-card").forEach(c => {
        if (parseInt(c.getAttribute("data-id")) === channel.id) {
            c.classList.add("active");
        } else {
            c.classList.remove("active");
        }
    });

    // Update Now Playing Info
    const logoEl = document.getElementById("active-channel-logo");
    const nameEl = document.getElementById("active-channel-name");
    const catEl = document.getElementById("active-channel-category");
    const catchupEl = document.getElementById("active-channel-catchup");
    const progTitleEl = document.getElementById("active-prog-title");
    const progTimesEl = document.getElementById("active-prog-times");
    const progProgressEl = document.getElementById("active-prog-progress");
    const nextProgBox = document.getElementById("active-next-prog-box");
    const nextProgTitle = document.getElementById("active-next-prog-title");

    if (logoEl) {
        if (channel.icon) {
            logoEl.src = channel.icon;
            logoEl.classList.remove("hidden");
        } else {
            logoEl.classList.add("hidden");
        }
    }

    if (nameEl) nameEl.textContent = channel.name;

    if (catEl) {
        if (channel.categories && channel.categories.length > 0) {
            catEl.textContent = channel.categories.join(", ");
            catEl.classList.remove("hidden");
        } else {
            catEl.classList.add("hidden");
        }
    }

    if (catchupEl) {
        if (channel.catchup) {
            catchupEl.classList.remove("hidden");
        } else {
            catchupEl.classList.add("hidden");
        }
    }

    // Toggle Catchup Archive button visibility
    if (catchupBtn) {
        if (channel.catchup) {
            catchupBtn.classList.remove("hidden");
        } else {
            catchupBtn.classList.add("hidden");
            if (catchupDrawer) catchupDrawer.classList.add("hidden");
        }
    }

    // If catchup drawer is currently open and channel supports it, refresh drawer schedule
    if (catchupDrawer && !catchupDrawer.classList.contains("hidden") && channel.catchup) {
        loadCatchupSchedule(channel.id);
    }

    if (progTitleEl) {
        if (channel.current_programme) {
            const cp = channel.current_programme;
            progTitleEl.textContent = cp.title;
            if (progTimesEl) progTimesEl.textContent = `${formatTimeHourMin(cp.start)} - ${formatTimeHourMin(cp.stop)}`;
            if (progProgressEl) progProgressEl.style.width = `${cp.progress}%`;
        } else {
            progTitleEl.textContent = typeof t === "function" ? (t("player.live_broadcast") || "Živé vysílání") : "Živé vysílání";
            if (progTimesEl) progTimesEl.textContent = typeof t === "function" ? (t("player.live") || "ŽIVĚ") : "ŽIVĚ";
            if (progProgressEl) progProgressEl.style.width = "100%";
        }
    }

    if (nextProgBox && nextProgTitle) {
        if (channel.next_programme) {
            nextProgBox.classList.remove("hidden");
            nextProgTitle.textContent = `${formatTimeHourMin(channel.next_programme.start)} ${channel.next_programme.title}`;
        } else {
            nextProgBox.classList.add("hidden");
        }
    }

    // Inspect stream info
    fetchStreamInfo(channel.id);

    // Play live channel stream
    playCurrentChannelStream();
}

// Fetch Stream Variants & Codecs
async function fetchStreamInfo(channelId, epgId = null) {
    try {
        const query = epgId ? `?epg_id=${epgId}` : "";
        const res = await fetch(`/api/stream/${channelId}/info${query}`);
        if (!res.ok) return;
        const data = await res.json();

        currentVariants = data.variants || [];
        updateQualitySelectOptions(currentVariants);
    } catch (e) {
        console.warn("Could not fetch stream info variants:", e);
    }
}

// Populate Quality Selector Options
function updateQualitySelectOptions(variants) {
    if (!qualitySelect) return;
    const currentVal = qualitySelect.value || "1080p";
    const autoLabel = typeof t === "function" ? (t("player.quality_auto") || "Auto (Adaptivní kvalita)") : "Auto (Adaptivní kvalita)";
    const bestLabel = typeof t === "function" ? (t("player.quality_best") || "Nejvyšší datový tok (Vynutit 4K/FHD)") : "Nejvyšší datový tok (Vynutit 4K/FHD)";
    
    let optionsHtml = `
        <option value="1080p">1080p (Full HD - Doporučeno)</option>
        <option value="best">${bestLabel}</option>
    `;

    if (variants && variants.length > 0) {
        variants.forEach(v => {
            const bitrateStr = formatBitrate(v.bandwidth);
            optionsHtml += `<option value="${v.name}">${v.name} &bull; ${v.resolution} ${bitrateStr}</option>`;
        });

        const highest = variants[0];
        if (codecBadge && highest && highest.codecs) {
            codecBadge.textContent = highest.codecs.includes("hev") ? "HEVC / AAC" : "H.264 / AAC";
        }
    } else {
        optionsHtml += `
            <option value="720p">720p (HD)</option>
            <option value="360p">360p (Úsporný režim / Data Saver)</option>
        `;
    }
    optionsHtml += `<option value="auto">${autoLabel}</option>`;

    qualitySelect.innerHTML = optionsHtml;

    if ([...qualitySelect.options].some(o => o.value === currentVal)) {
        qualitySelect.value = currentVal;
    } else {
        qualitySelect.value = "1080p";
    }
}

// Low-level HLS loader helper
function loadHlsStream(streamEndpoint, isCatchup = false, replayTitle = "") {
    if (!videoEl) return;

    if (placeholderEl) placeholderEl.classList.add("hidden");
    if (loadingEl) loadingEl.classList.remove("hidden");
    const unmuteBtn = document.getElementById("btn-unmute-overlay");
    if (unmuteBtn) unmuteBtn.classList.add("hidden");

    // Manage Replay Notification Banner
    if (replayBanner) {
        if (isCatchup) {
            replayBanner.classList.remove("hidden");
            if (replayProgName) replayProgName.textContent = replayTitle;
        } else {
            replayBanner.classList.add("hidden");
        }
    }

    function attemptPlay() {
        const playPromise = videoEl.play();
        if (playPromise !== undefined) {
            playPromise.then(() => {
                if (loadingEl) loadingEl.classList.add("hidden");
            }).catch(err => {
                console.log("Autoplay with audio blocked by browser, attempting muted play...", err);
                videoEl.muted = true;
                videoEl.play().then(() => {
                    if (loadingEl) loadingEl.classList.add("hidden");
                    if (unmuteBtn) unmuteBtn.classList.remove("hidden");
                }).catch(e => {
                    console.warn("Muted autoplay also blocked (requires user tap):", e);
                    if (loadingEl) loadingEl.classList.add("hidden");
                });
            });
        }

        // Mobile safety watchdog: ensure loading spinner never blocks video controls indefinitely
        setTimeout(() => {
            if (loadingEl && (videoEl.currentTime > 0 || !videoEl.paused)) {
                loadingEl.classList.add("hidden");
            }
        }, 3000);
    }

    if (Hls.isSupported()) {
        if (hlsInstance) {
            hlsInstance.destroy();
        }

        hlsInstance = new Hls({
            enableWorker: true,
            lowLatencyMode: false, // Disabled for standard CDN to prevent live-edge stalls
            liveSyncDurationCount: 2, // 2-segment buffer (~8s) for fast, reliable live sync on mobile
            liveMaxLatencyDurationCount: 10, // Generous tolerance for mobile network jitter
            maxBufferLength: 15,
            maxMaxBufferLength: 30,
            backBufferLength: 15, // Free played memory on mobile devices
            maxBufferSize: 30 * 1000 * 1000, // 30 MB buffer limit for mobile stability
            maxBufferHole: 0.5,
            highBufferWatchdogPeriod: 2,
            nudgeOffset: 0.2,
            nudgeMaxRetry: 10
        });

        hlsInstance.loadSource(streamEndpoint);
        hlsInstance.attachMedia(videoEl);

        hlsInstance.on(Hls.Events.MANIFEST_PARSED, (event, data) => {
            attemptPlay();
        });

        hlsInstance.on(Hls.Events.ERROR, (event, data) => {
            if (data.details === Hls.ErrorDetails.BUFFER_STALLED_ERROR) {
                console.warn("Buffer stall detected on live edge, nudging playback...");
                if (videoEl && !videoEl.paused) {
                    videoEl.currentTime = videoEl.currentTime + 0.2;
                }
            } else if (data.fatal) {
                if (loadingEl) loadingEl.classList.add("hidden");
                switch (data.type) {
                    case Hls.ErrorTypes.NETWORK_ERROR:
                        console.warn("Network error in HLS, retrying...");
                        hlsInstance.startLoad();
                        break;
                    case Hls.ErrorTypes.MEDIA_ERROR:
                        console.warn("Media error in HLS, attempting recovery...");
                        hlsInstance.recoverMediaError();
                        break;
                    default:
                        console.error("Fatal unrecoverable stream error:", data);
                        hlsInstance.destroy();
                        if (typeof showToast === 'function') {
                            showToast("Error buffering stream from provider.", "error");
                        }
                        break;
                }
            }
        });
    } else if (videoEl.canPlayType("application/vnd.apple.mpegurl")) {
        // Native HLS (Safari on macOS/iOS)
        videoEl.src = streamEndpoint;
        videoEl.addEventListener("loadedmetadata", () => {
            attemptPlay();
        }, { once: true });
    } else {
        if (loadingEl) loadingEl.classList.add("hidden");
        if (typeof showToast === 'function') {
            showToast("HLS playback is not supported by your browser.", "error");
        }
    }
}

// Play Live Channel Stream using HLS Proxy
function playCurrentChannelStream() {
    if (!currentChannel) return;
    currentReplayProgram = null;

    const quality = qualitySelect ? qualitySelect.value : "1080p";
    const userToken = window.SWEET_USER_TOKEN || "";
    const tokenParam = userToken ? `&token=${encodeURIComponent(userToken)}` : "";
    const streamEndpoint = `/stream/${currentChannel.id}.m3u8?quality=${quality}${tokenParam}`;

    loadHlsStream(streamEndpoint, false);
}

// Play Catchup Replay Archive Program
function playCatchupProgram(prog) {
    if (!currentChannel || !prog) return;
    currentReplayProgram = prog;

    const quality = qualitySelect ? qualitySelect.value : "1080p";
    const userToken = window.SWEET_USER_TOKEN || "";
    const tokenParam = userToken ? `&token=${encodeURIComponent(userToken)}` : "";
    const streamEndpoint = `/stream/${currentChannel.id}/${prog.id}.m3u8?quality=${quality}${tokenParam}`;
    const replayTitle = `${prog.title} (${formatProgrammeDate(prog.start)} ${formatTimeHourMin(prog.start)} - ${formatTimeHourMin(prog.stop)})`;

    loadHlsStream(streamEndpoint, true, replayTitle);

    if (typeof showToast === 'function') {
        showToast(`Playing Catchup Archive: ${prog.title}`, "info");
    }

    // Scroll smoothly to player
    videoEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// Catchup Programs Cache and Day Filter State
let channelCatchupPrograms = [];
let activeCatchupDateKey = "";
const catchupDayTabsEl = document.getElementById("catchup-day-tabs");
const catchupSearchInput = document.getElementById("catchup-search-input");

function getDayKey(unixTimestamp) {
    const d = new Date(unixTimestamp * 1000);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
}

function formatDayTabLabel(unixTimestamp) {
    const d = new Date(unixTimestamp * 1000);
    const now = new Date();
    const isCs = typeof currentLang === "undefined" || currentLang === "cs";

    const dDate = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const nowDate = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const diffDays = Math.round((nowDate - dDate) / (1000 * 60 * 60 * 24));
    const dayMonth = `${d.getDate()}.${d.getMonth() + 1}.`;

    if (diffDays === 0) {
        return `${isCs ? "Dnes" : "Today"} (${dayMonth})`;
    } else if (diffDays === 1) {
        return `${isCs ? "Včera" : "Yesterday"} (${dayMonth})`;
    } else {
        const daysCs = ["Ne", "Po", "Út", "St", "Čt", "Pá", "So"];
        const daysEn = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
        const dayName = isCs ? daysCs[d.getDay()] : daysEn[d.getDay()];
        return `${dayName} (${dayMonth})`;
    }
}

function renderCatchupDayTabs(uniqueDayKeys, timestampsMap) {
    if (!catchupDayTabsEl) return;
    let html = "";
    uniqueDayKeys.forEach(key => {
        const isActive = key === activeCatchupDateKey;
        const sampleTs = timestampsMap[key] || 0;
        const label = formatDayTabLabel(sampleTs);
        html += `
            <button type="button" class="catchup-day-tab px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
                isActive
                    ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/60 shadow-sm'
                    : 'bg-slate-950 text-slate-400 hover:text-white border border-slate-800'
            }" data-day="${key}">${label}</button>
        `;
    });
    catchupDayTabsEl.innerHTML = html;

    catchupDayTabsEl.querySelectorAll(".catchup-day-tab").forEach(tab => {
        tab.addEventListener("click", () => {
            const day = tab.getAttribute("data-day");
            if (day && day !== activeCatchupDateKey) {
                activeCatchupDateKey = day;
                renderCatchupDayTabs(uniqueDayKeys, timestampsMap);
                renderCatchupDayPrograms();
            }
        });
    });
}

function renderCatchupDayPrograms() {
    if (!catchupListEl) return;
    const query = catchupSearchInput ? catchupSearchInput.value.trim().toLowerCase() : "";

    let dayPrograms = channelCatchupPrograms.filter(p => getDayKey(p.start) === activeCatchupDateKey);
    if (query) {
        dayPrograms = dayPrograms.filter(p => (p.title && p.title.toLowerCase().includes(query)));
    }

    if (dayPrograms.length === 0) {
        const noProgMsg = typeof t === "function" ? t("epg.no_programs_day") : "Pro vybraný den nebyly nalezeny žádné pořady.";
        catchupListEl.innerHTML = `
            <div class="text-center py-8 text-xs text-slate-400">
                ${noProgMsg}
            </div>
        `;
        return;
    }

    const isCs = typeof currentLang === "undefined" || currentLang === "cs";
    const playText = typeof t === "function" ? (t("epg.play_recording") || (isCs ? 'Přehrát záznam' : 'Play Recording')) : (isCs ? 'Přehrát záznam' : 'Play Recording');
    const restartText = typeof t === "function" ? (t("epg.restart_recording") || (isCs ? 'Znovu přehrát' : 'Restart')) : (isCs ? 'Znovu přehrát' : 'Restart');
    const nowPlayingText = typeof t === "function" ? (t("player.now_playing_badge") || (isCs ? 'PRÁVĚ HRAJE' : 'NOW PLAYING')) : (isCs ? 'PRÁVĚ HRAJE' : 'NOW PLAYING');
    const itemsHtml = [];

    dayPrograms.forEach(prog => {
        const timeRange = `${formatTimeHourMin(prog.start)} - ${formatTimeHourMin(prog.stop)}`;
        const durationMin = Math.round((prog.stop - prog.start) / 60);
        const isCurrentlyPlayingThis = currentReplayProgram && currentReplayProgram.id === prog.id;

        itemsHtml.push(`
            <div class="catchup-item flex items-center justify-between p-3 rounded-xl border transition cursor-pointer group ${
                isCurrentlyPlayingThis
                    ? 'bg-cyan-950/40 border-cyan-600/80 text-cyan-300'
                    : 'bg-slate-950/60 border-slate-800/80 hover:bg-slate-800/80 hover:border-slate-700'
            }" data-prog-id="${prog.id}">
                <div class="flex-1 min-w-0 pr-3">
                    <div class="flex items-center gap-2 mb-1">
                        <span class="text-[11px] font-mono text-cyan-400 font-semibold">${timeRange}</span>
                        <span class="text-[10px] text-slate-500 font-mono">${durationMin} min</span>
                        ${isCurrentlyPlayingThis ? `<span class="text-[10px] font-bold text-amber-400 animate-pulse">${nowPlayingText}</span>` : ''}
                    </div>
                    <div class="text-xs font-medium text-white truncate group-hover:text-cyan-300">${prog.title}</div>
                </div>
                <button class="btn-secondary text-[11px] py-1.5 px-3 flex items-center gap-1.5 group-hover:border-cyan-500 flex-shrink-0">
                    <svg class="w-3.5 h-3.5 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/></svg>
                    <span>${isCurrentlyPlayingThis ? restartText : playText}</span>
                </button>
            </div>
        `);
    });

    catchupListEl.innerHTML = itemsHtml.join("");

    catchupListEl.querySelectorAll(".catchup-item").forEach(item => {
        item.addEventListener("click", () => {
            const progId = parseInt(item.getAttribute("data-prog-id"));
            const prog = channelCatchupPrograms.find(p => p.id === progId);
            if (prog) {
                playCatchupProgram(prog);
                renderCatchupDayPrograms();
            }
        });
    });
}

// Load and Render 7-Day Catchup Replay Schedule with Day Tabs
async function loadCatchupSchedule(channelId) {
    if (!catchupListEl) return;

    // Update Catchup Header with active channel
    const catchupLogo = document.getElementById("catchup-channel-logo");
    const catchupName = document.getElementById("catchup-channel-name");
    if (currentChannel) {
        if (catchupName) catchupName.textContent = currentChannel.name;
        if (catchupLogo) {
            if (currentChannel.icon) {
                catchupLogo.src = currentChannel.icon;
                catchupLogo.classList.remove("hidden");
            } else {
                catchupLogo.classList.add("hidden");
            }
        }
    }

    const loadingText = typeof t === "function" ? (t("player.loading_archive") || "Načítám 7denní televizní archiv...") : "Načítám 7denní televizní archiv...";
    catchupListEl.innerHTML = `
        <div class="flex items-center justify-center py-8 text-xs text-slate-400 gap-2">
            <div class="inline-block animate-spin rounded-full h-4 w-4 border-2 border-cyan-400 border-t-transparent"></div>
            <span>${loadingText}</span>
        </div>
    `;

    try {
        const res = await fetch(`/api/channel/${channelId}/epg`);
        if (!res.ok) {
            catchupListEl.innerHTML = `
                <div class="text-center py-6 text-xs text-slate-500">
                    Chyba při načítání programového průvodce.
                </div>
            `;
            return;
        }

        const data = await res.json();
        const programs = data.programs || [];

        // Filter replayable past programs
        const replayable = programs.filter(p => p.can_replay && p.is_past);
        replayable.sort((a, b) => b.start - a.start);
        channelCatchupPrograms = replayable;

        if (channelCatchupPrograms.length === 0) {
            if (catchupDayTabsEl) catchupDayTabsEl.innerHTML = "";
            const noArchiveText = typeof t === "function" ? (t("player.no_archive_for_channel") || "Pro tento kanál není v archivu k dispozici žádný záznam.") : "Pro tento kanál není v archivu k dispozici žádný záznam.";
            catchupListEl.innerHTML = `
                <div class="text-center py-6 text-xs text-slate-500">
                    ${noArchiveText}
                </div>
            `;
            return;
        }

        // Collect unique day keys and sample timestamps
        const uniqueDayKeys = [];
        const timestampsMap = {};
        channelCatchupPrograms.forEach(prog => {
            const dKey = getDayKey(prog.start);
            if (!uniqueDayKeys.includes(dKey)) {
                uniqueDayKeys.push(dKey);
                timestampsMap[dKey] = prog.start;
            }
        });

        lastDayKeys = uniqueDayKeys;
        lastTimestampsMap = timestampsMap;

        // Set default active day to the newest day
        if (!activeCatchupDateKey || !uniqueDayKeys.includes(activeCatchupDateKey)) {
            activeCatchupDateKey = uniqueDayKeys[0];
        }

        renderCatchupDayTabs(uniqueDayKeys, timestampsMap);
        renderCatchupDayPrograms();

    } catch (err) {
        console.error("Failed to load catchup schedule:", err);
        const errorText = typeof t === "function" ? (t("player.archive_network_error") || "Chyba sítě při načítání archivu pořadů.") : "Chyba sítě při načítání archivu pořadů.";
        catchupListEl.innerHTML = `
            <div class="text-center py-6 text-xs text-red-400">
                ${errorText}
            </div>
        `;
    }
}

// Event Listeners
document.addEventListener("DOMContentLoaded", () => {
    // Channel Search with Debounce
    if (searchInput) {
        let searchTimeout = null;
        searchInput.addEventListener("input", () => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(renderChannels, 150);
        });
    }

    // Stream Quality Selector
    if (qualitySelect) {
        qualitySelect.addEventListener("change", () => {
            if (currentReplayProgram) {
                playCatchupProgram(currentReplayProgram);
            } else {
                playCurrentChannelStream();
            }
            if (typeof showToast === 'function') {
                showToast(`Stream quality set to: ${qualitySelect.options[qualitySelect.selectedIndex].text}`, "info");
            }
        });
    }

    // Stream Reload Button
    const reloadBtn = document.getElementById("btn-reload-stream");
    if (reloadBtn) {
        reloadBtn.addEventListener("click", () => {
            if (currentReplayProgram) {
                playCatchupProgram(currentReplayProgram);
            } else {
                playCurrentChannelStream();
            }
            if (typeof showToast === 'function') {
                showToast("Reloading stream...", "info");
            }
        });
    }

    // Fullscreen Toggle
    const fsBtn = document.getElementById("btn-fullscreen-player");
    if (fsBtn && videoEl) {
        fsBtn.addEventListener("click", () => {
            if (!document.fullscreenElement) {
                if (videoEl.requestFullscreen) {
                    videoEl.requestFullscreen();
                } else if (videoEl.webkitRequestFullscreen) {
                    videoEl.webkitRequestFullscreen();
                }
            } else {
                if (document.exitFullscreen) {
                    document.exitFullscreen();
                }
            }
        });
    }

    // Video Playback Events to manage loading indicator & unmute overlay
    if (videoEl) {
        videoEl.addEventListener("playing", () => {
            if (loadingEl) loadingEl.classList.add("hidden");
        });
        videoEl.addEventListener("canplay", () => {
            if (loadingEl) loadingEl.classList.add("hidden");
        });
        videoEl.addEventListener("timeupdate", () => {
            if (loadingEl && !loadingEl.classList.contains("hidden")) {
                loadingEl.classList.add("hidden");
            }
        });
        videoEl.addEventListener("waiting", () => {
            if (loadingEl) loadingEl.classList.remove("hidden");
        });
        videoEl.addEventListener("seeking", () => {
            if (loadingEl) loadingEl.classList.remove("hidden");
        });
        videoEl.addEventListener("seeked", () => {
            if (loadingEl) loadingEl.classList.add("hidden");
        });
        videoEl.addEventListener("volumechange", () => {
            const unmuteBtn = document.getElementById("btn-unmute-overlay");
            if (!videoEl.muted && unmuteBtn) {
                unmuteBtn.classList.add("hidden");
            }
        });
    }

    // Unmute Overlay Button
    const unmuteOverlayBtn = document.getElementById("btn-unmute-overlay");
    if (unmuteOverlayBtn && videoEl) {
        unmuteOverlayBtn.addEventListener("click", () => {
            videoEl.muted = false;
            unmuteOverlayBtn.classList.add("hidden");
        });
    }

    // Catchup In-Day Program Filter
    if (catchupSearchInput) {
        let catchupSearchTimeout = null;
        catchupSearchInput.addEventListener("input", () => {
            clearTimeout(catchupSearchTimeout);
            catchupSearchTimeout = setTimeout(renderCatchupDayPrograms, 100);
        });
    }

    // Catchup Archive Toggle Button
    if (catchupBtn) {
        catchupBtn.addEventListener("click", () => {
            if (!catchupDrawer) return;
            const isHidden = catchupDrawer.classList.contains("hidden");
            if (isHidden) {
                catchupDrawer.classList.remove("hidden");
                if (currentChannel) {
                    loadCatchupSchedule(currentChannel.id);
                }
            } else {
                catchupDrawer.classList.add("hidden");
            }
        });
    }

    // Close Catchup Drawer
    if (catchupCloseBtn && catchupDrawer) {
        catchupCloseBtn.addEventListener("click", () => {
            catchupDrawer.classList.add("hidden");
        });
    }

    // Return to Live TV Button
    if (returnLiveBtn) {
        returnLiveBtn.addEventListener("click", () => {
            currentReplayProgram = null;
            if (replayBanner) replayBanner.classList.add("hidden");
            playCurrentChannelStream();
            if (typeof showToast === 'function') {
                const liveToast = typeof t === "function" ? (t("player.return_live") || "Zpět na živé vysílání") : "Zpět na živé vysílání";
                showToast(liveToast, "info");
            }
        });
    }

    // Listen for language changes to update dynamic player elements
    window.addEventListener("sweettv-language-changed", () => {
        updateQualitySelectOptions(currentVariants);
        if (allCategories && allCategories.length > 0) renderCategories(allCategories);
        renderChannels();
        if (catchupDrawer && !catchupDrawer.classList.contains("hidden")) {
            if (lastDayKeys.length > 0) renderCatchupDayTabs(lastDayKeys, lastTimestampsMap);
            renderCatchupDayPrograms();
        }
    });

    window.loadChannels = loadChannels;
    loadChannels();
});
