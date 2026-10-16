/**
 * Sweet.tv Web TV Player & Channel Browser Controller
 */

let hlsInstance = null;
let currentChannel = null;
let allChannels = [];
let activeCategory = "all";
let currentVariants = [];

// DOM References
const videoEl = document.getElementById("tv-player");
const placeholderEl = document.getElementById("player-placeholder");
const loadingEl = document.getElementById("player-loading");
const qualitySelect = document.getElementById("player-quality-select");
const codecBadge = document.getElementById("player-codec-badge");
const channelsListEl = document.getElementById("channels-list");
const categoryPillsEl = document.getElementById("category-pills-container");
const searchInput = document.getElementById("channel-search-input");

// Format Unix Timestamp to HH:MM
function formatTimeHourMin(unixTimestamp) {
    if (!unixTimestamp) return "--:--";
    const d = new Date(unixTimestamp * 1000);
    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
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
            channelsListEl.innerHTML = `
                <div class="text-center py-12 px-4 space-y-3">
                    <p class="text-xs text-amber-400 font-medium">Sweet.tv session not connected.</p>
                    <button onclick="openConnectModal()" class="btn-primary text-xs py-2 px-4">Connect Account</button>
                </div>
            `;
            return;
        }

        const data = await res.json();
        allChannels = data.channels || [];

        // Render Category Pills
        renderCategories(data.categories || []);

        // Render Channels
        renderChannels();

        // Auto-select first channel if none selected
        if (!currentChannel && allChannels.length > 0) {
            selectChannel(allChannels[0]);
        }
    } catch (err) {
        console.error("Failed to load channels:", err);
        channelsListEl.innerHTML = `
            <div class="text-center py-12 text-xs text-red-400">
                Failed to load channel list from server.
            </div>
        `;
    }
}

// Render Categories
function renderCategories(categories) {
    if (!categoryPillsEl) return;

    let html = `<button class="cat-pill ${activeCategory === 'all' ? 'active' : ''}" data-cat="all">All</button>`;
    categories.forEach(cat => {
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
        channelsListEl.innerHTML = `
            <div class="text-center py-12 text-xs text-slate-500">
                No channels found matching "${searchTerm}".
            </div>
        `;
        return;
    }

    channelsListEl.innerHTML = filtered.map(ch => {
        const isCurrent = currentChannel && currentChannel.id === ch.id;
        const progTitle = ch.current_programme ? ch.current_programme.title : "Live Broadcast";
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

    if (progTitleEl) {
        if (channel.current_programme) {
            const cp = channel.current_programme;
            progTitleEl.textContent = cp.title;
            if (progTimesEl) progTimesEl.textContent = `${formatTimeHourMin(cp.start)} - ${formatTimeHourMin(cp.stop)}`;
            if (progProgressEl) progProgressEl.style.width = `${cp.progress}%`;
        } else {
            progTitleEl.textContent = "Live Broadcast";
            if (progTimesEl) progTimesEl.textContent = "Live";
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

    // Play stream
    playCurrentChannelStream();
}

// Fetch Stream Variants & Codecs
async function fetchStreamInfo(channelId) {
    try {
        const res = await fetch(`/api/stream/${channelId}/info`);
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
    const currentVal = qualitySelect.value;
    let optionsHtml = `
        <option value="auto">Auto (Adaptive Multi-Bitrate)</option>
        <option value="best">Highest Available Bitrate (Force 4K/FHD)</option>
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
            <option value="1080p">1080p (Full HD)</option>
            <option value="720p">720p (HD)</option>
            <option value="360p">360p (Data Saver)</option>
        `;
    }

    qualitySelect.innerHTML = optionsHtml;

    if ([...qualitySelect.options].some(o => o.value === currentVal)) {
        qualitySelect.value = currentVal;
    }
}

// Play Channel Stream using HLS Proxy
function playCurrentChannelStream() {
    if (!currentChannel || !videoEl) return;

    if (placeholderEl) placeholderEl.classList.add("hidden");
    if (loadingEl) loadingEl.classList.remove("hidden");

    const quality = qualitySelect ? qualitySelect.value : "auto";
    // Target the clean, standard HLS proxy endpoint
    const streamEndpoint = `/stream/${currentChannel.id}.m3u8?quality=${quality}`;

    if (Hls.isSupported()) {
        if (hlsInstance) {
            hlsInstance.destroy();
        }

        hlsInstance = new Hls({
            enableWorker: true,
            lowLatencyMode: true,
            backBufferLength: 60,
            maxBufferLength: 30,
            maxMaxBufferLength: 60,
        });

        hlsInstance.loadSource(streamEndpoint);
        hlsInstance.attachMedia(videoEl);

        hlsInstance.on(Hls.Events.MANIFEST_PARSED, (event, data) => {
            if (loadingEl) loadingEl.classList.add("hidden");
            videoEl.play().catch(() => {
                console.log("Autoplay waiting for user gesture.");
            });
        });

        hlsInstance.on(Hls.Events.ERROR, (event, data) => {
            if (data.fatal) {
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
            if (loadingEl) loadingEl.classList.add("hidden");
            videoEl.play();
        });
    } else {
        if (loadingEl) loadingEl.classList.add("hidden");
        if (typeof showToast === 'function') {
            showToast("HLS playback is not supported by your browser.", "error");
        }
    }
}

// Event Listeners
document.addEventListener("DOMContentLoaded", () => {
    if (searchInput) {
        let searchTimeout = null;
        searchInput.addEventListener("input", () => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(renderChannels, 150);
        });
    }

    if (qualitySelect) {
        qualitySelect.addEventListener("change", () => {
            playCurrentChannelStream();
            if (typeof showToast === 'function') {
                showToast(`Stream quality set to: ${qualitySelect.options[qualitySelect.selectedIndex].text}`, "info");
            }
        });
    }

    const reloadBtn = document.getElementById("btn-reload-stream");
    if (reloadBtn) {
        reloadBtn.addEventListener("click", () => {
            playCurrentChannelStream();
            if (typeof showToast === 'function') {
                showToast("Reloading stream...", "info");
            }
        });
    }

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

    window.loadChannels = loadChannels;
    loadChannels();
});
