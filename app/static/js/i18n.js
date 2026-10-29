/**
 * Internationalization (i18n) for Sweet.tv IPTV Server & Web TV
 * Supports English (en) and Czech (cs) with localStorage persistence.
 * Default language: Czech (cs).
 */

const I18N = {
  en: {
    // Navigation
    "nav.live_tv": "Live TV",
    "nav.playlists": "Playlists & EPG",
    "nav.account": "Account",
    "nav.account_short": "Account",
    "nav.status": "Status",
    "nav.settings": "Settings",
    "nav.guides": "Guides",
    "nav.connect": "Connect",
    "nav.reconnect": "Re-connect",
    "nav.connected": "Connected",
    "nav.checking": "Checking...",
    "nav.disconnected": "Disconnected",

    // Quick toggle
    "quick.live_tv": "📺 Live Web TV Player",
    "quick.copy_links": "🔗 Copy M3U & EPG Links",
    "quick.copy_m3u": "📋 Copy M3U",
    "quick.copy_epg": "📅 Copy EPG",

    // Player
    "player.select_channel": "Select a Channel to Watch",
    "player.select_channel_desc": "Browse the channel list on the right and click any channel to start high-definition streaming.",
    "player.buffering": "Buffering stream...",
    "player.quality_label": "Stream Quality & Codec",
    "player.quality_auto": "Auto (Adaptive Multi-Bitrate)",
    "player.quality_best": "Highest Available Bitrate (Force 4K/FHD)",
    "player.catchup_btn": "Catchup Archive",
    "player.reload_btn": "Reload",
    "player.fullscreen_btn": "Fullscreen",
    "player.return_live": "Return to Live TV",
    "player.watching_replay": "Watching Catchup Archive:",
    "player.catchup_schedule": "⏪ 7-Day Catchup Replay Schedule",
    "player.archive_available": "Archive Available",
    "player.close": "Close &times;",
    "player.no_channel": "No Channel Selected",
    "player.catchup_badge": "Catchup Available",
    "player.search_placeholder": "Search channels...",
    "player.all_categories": "All Categories",
    "player.next": "Next",
    "player.now": "NOW",
    "player.replay": "Play",
    "player.live": "LIVE",
    "player.live_broadcast": "Live Broadcast",
    "player.now_playing_badge": "NOW PLAYING",
    "player.not_connected": "Sweet.tv session not connected.",
    "player.connect_account": "Connect Account",
    "player.load_failed": "Failed to load channel list from server.",
    "player.no_matches": "No channels found matching",
    "player.loading_archive": "Loading 7-day TV archive...",
    "player.no_archive_for_channel": "No catchup recordings available for this channel.",
    "player.archive_network_error": "Network error loading catchup archive.",
    "player.no_epg_found": "No schedule details available for this day.",

    // EPG Catchup Day Tabs & Rich Cards
    "epg.today": "Today",
    "epg.yesterday": "Yesterday",
    "epg.search_placeholder": "Search programs on this day...",
    "epg.play_recording": "Play Recording",
    "epg.restart_recording": "Restart",
    "epg.duration": "Duration",
    "epg.no_programs_day": "No programs found for selected day.",
    "epg.programs_found": "programs found",
    "epg.channel_archive": "Catchup Archive:",
    "epg.no_channel_selected": "Please select a channel to view its 7-day replay archive.",

    // Categories
    "category.all": "All",
    "category.favorites": "Favorites",
    "category.national": "National",
    "category.movies": "Movies",
    "category.news": "News",
    "category.sports": "Sports",
    "category.documentary": "Documentary",
    "category.kids": "Kids",
    "category.music": "Music",

    // Account Management Tab
    "account.title": "Sweet.tv Account & Pairing Management",
    "account.subtitle": "Manage active account session, virtual hardware identity, and pairing tokens.",
    "account.session_card": "Account Status",
    "account.token_card": "Token Validity",
    "account.hardware_card": "Emulated Device Identity",
    "account.actions_card": "Account & Device Controls",
    "account.disconnect_btn": "Disconnect Account",
    "account.reset_device_btn": "Reset Device Identity (New UUID/MAC)",
    "account.pair_btn": "Pair / Connect Account",
    "account.pair_desc": "Connect via 4-digit code or QR code on Sweet.tv.",
    "account.active_session": "Active Sweet.tv Session",
    "account.no_session": "Not Connected",

    // Links Tab
    "links.title": "Playlists, EPG & Integration URLs",
    "links.subtitle": "Pre-formatted URLs for IPTV players, Kodi, Smart TVs, and Portals.",
    "links.m3u_best_title": "M3U Playlist • Highest Bitrate",
    "links.m3u_best_desc": "Locks to the highest available bitrate (4K UHD / 1080p FHD 50fps) on all channels.",
    "links.m3u_auto_title": "M3U Playlist • Adaptive Auto",
    "links.m3u_auto_desc": "Adaptive bitrate master playlist. Adjusts resolution and bandwidth based on network speed.",
    "links.epg_xmltv_title": "EPG Guide (XMLTV)",
    "links.epg_xmltv_desc": "Complete TV schedule with program names, times, catchup IDs, descriptions, and channel icons.",
    "links.std_xml_url": "Standard XML URL:",
    "links.gzip_xml_url": "Compressed Gzip URL (Faster loading):",
    "links.copy_epg_btn": "Copy EPG URL",
    "links.copy_gzip_btn": "Copy Gzip URL",
    "links.view_btn": "View",
    "links.m3u_catchup_title": "M3U Playlist • With Catchup Tags",
    "links.m3u_catchup_desc": "Includes embedded catchup replay tags for Kodi PVR and TiviMate to enable 7-day replay.",
    "links.m3u_clean_title": "M3U Playlist • Clean Standalone",
    "links.m3u_clean_desc": "Clean playlist without url-tvg header. Ideal for IPTV portals syncing channels independently of EPG.",
    "links.stalker_title": "Stalker / MAG Portal • Ministra Middleware",
    "links.stalker_desc": "Stalker portal emulation for MAG set-top boxes and IPTV apps. Loads channels, categories, and EPG via native JSON-RPC without M3U parsing.",
    "links.xtream_title": "XTream Codes Server • Native JSON Connection",
    "links.xtream_desc": "Connect via XTream Codes API in IPTV players. Native JSON eliminates M3U parsing bugs and loads 7-day EPG.",
    "links.copy_btn": "Copy URL",
    "links.download_btn": "Download",
    "links.server_url": "Server URL / Host:",
    "links.username": "Username:",
    "links.password": "Password:",
    "links.portal_url": "Portal URL:",
    "links.mac_address": "MAC Address:",
    "links.mac_desc": "Use your device's MAC",
    "links.universal_clean": "Universal Clean",
    "links.ultra_quality": "Ultra Quality",
    "links.max_bitrate_forced": "Max Bitrate Forced",
    "links.electronic_guide": "Electronic Guide",
    "links.xmltv_format": "XMLTV Format",
    "links.archive_replay": "Archive • Replay",
    "links.kodi_tivimate": "Kodi & TiviMate",
    "links.no_auto_epg": "No Auto-EPG Trigger",
    "links.multi_bitrate": "HLS Multi-Bitrate",

    // Status Tab
    "status.title": "System Status & Diagnostics",
    "status.subtitle": "Real-time authentication lifecycle, API token countdown, and provider parameters.",
    "status.account": "Sweet.tv Account",
    "status.channels": "Total Channels",
    "status.token": "Token Valid For",
    "status.uptime": "Server Uptime",
    "status.delivery": "Stream Delivery",
    "status.direct_cdn": "Direct CDN 302",
    "status.proxied": "Server Proxied",
    "status.hardware_info": "Device & Provider Parameters",
    "status.uuid": "Device UUID:",
    "status.mac": "Device MAC:",
    "status.ext_url": "Configured Public URL:",
    "status.direct_stream": "Direct Stream Redirect:",
    "status.device_mgmt_title": "Sweet.tv Device Management & Pairing",
    "status.device_mgmt_desc": "Disconnect your account session or completely regenerate device credentials (UUID/MAC) to release the slot on Sweet.tv.",
    "status.disconnect_btn": "Disconnect Account",
    "status.reset_device_btn": "Reset Device Identity (New UUID/MAC)",
    "status.reset_device_confirm": "Are you sure you want to reset device identity? The active Sweet.tv session will be terminated and a brand new UUID and MAC address will be generated.",
    "status.disconnect_confirm": "Are you sure you want to disconnect from your Sweet.tv account?",

    // Settings Tab
    "settings.title": "Server & Stream Configuration",
    "settings.subtitle": "Customize language/region, external domain for Nginx Proxy Manager, and quality defaults.",
    "settings.country_label": "Country / Region Code",
    "settings.country_desc": "Changes the EPG language and region-specific channel packages.",
    "settings.ext_url_label": "External Domain / Public URL",
    "settings.ext_url_desc": "Set this when running behind Nginx Proxy Manager (NPM) or public domain so M3U and EPG links use your public HTTPS domain.",
    "settings.quality_label": "Default Playlist Stream Quality",
    "settings.delivery_label": "Stream Delivery Technique",
    "settings.xtream_user_label": "Xtream API Username",
    "settings.xtream_user_desc": "Username for Xtream Codes API players.",
    "settings.xtream_pwd_label": "Xtream API Password",
    "settings.xtream_pwd_desc": "Password for Xtream Codes API players.",
    "settings.catchup_checkbox": "Include Catchup Tags in Default M3U Playlist",
    "settings.catchup_desc": "When checked, catchup tags are added to default M3U links for 7-day replay.",
    "settings.save_btn": "Save Configuration",
    "settings.refresh_btn": "Refresh Cache",

    // Guides Tab
    "guides.title": "Setup Guides for IPTV Applications",
    "guides.subtitle": "Step-by-step instructions with 1-click URLs for Smart TVs, Apple TV, Android, Kodi, VLC and STB.",
    "guides.smart_tv_title": "Smart TV (Samsung Tizen, LG webOS)",
    "guides.android_tv_title": "Android TV & Google TV (TiviMate, Sparkle)",
    "guides.apple_tv_title": "Apple TV & iOS (iPhone / iPad)",
    "guides.kodi_title": "Kodi (PVR IPTV Simple Client)",
    "guides.pc_mac_title": "PC & Mac (VLC, IPTVnator, SFVIP)",
    "guides.mag_title": "Stalker / MAG Set-top Boxes",
    "guides.npm_title": "Nginx Proxy Manager & HTTPS Domain",

    // Modals
    "modal.auth_title": "Connect Sweet.tv Account",
    "modal.auth_step1": "1. On your phone or computer, open:",
    "modal.auth_step2": "2. Enter this 4-digit activation code:",
    "modal.auth_waiting": "Waiting for confirmation in Sweet.tv app...",

    // Messages
    "msg.copied": "Copied to clipboard!",
    "msg.settings_saved": "Settings updated successfully!",
    "msg.settings_failed": "Failed to update settings.",
    "msg.cache_refreshed": "Channels and EPG cache refreshed!",
    "msg.logged_out": "Account disconnected.",
    "msg.device_reset": "Device identity reset successfully. Ready for new pairing."
  },
  cs: {
    // Navigace
    "nav.live_tv": "Živé vysílání",
    "nav.playlists": "Playlisty a EPG",
    "nav.account": "Správa účtu",
    "nav.account_short": "Účet",
    "nav.status": "Stav systému",
    "nav.settings": "Nastavení",
    "nav.guides": "Návody",
    "nav.connect": "Připojit",
    "nav.reconnect": "Znovu připojit",
    "nav.connected": "Připojeno",
    "nav.checking": "Ověřuji...",
    "nav.disconnected": "Odpojeno",

    // Rychlé přepínání
    "quick.live_tv": "📺 Živé webové vysílání",
    "quick.copy_links": "🔗 Odkazy na M3U a EPG",
    "quick.copy_m3u": "📋 Kopírovat M3U",
    "quick.copy_epg": "📅 Kopírovat EPG",

    // Přehrávač
    "player.select_channel": "Vyberte kanál pro sledování",
    "player.select_channel_desc": "Procházejte seznam stanic vpravo a klikněte na kanál pro spuštění přehrávání ve vysoké kvalitě.",
    "player.buffering": "Načítám stream...",
    "player.quality_label": "Kvalita a kodek streamu",
    "player.quality_auto": "Auto (Adaptivní kvalita)",
    "player.quality_best": "Nejvyšší datový tok (Vynutit 4K/FHD)",
    "player.catchup_btn": "Archiv pořadů",
    "player.reload_btn": "Obnovit",
    "player.fullscreen_btn": "Celá obrazovka",
    "player.return_live": "Zpět na živé vysílání",
    "player.watching_replay": "Sledujete pořad z archivu:",
    "player.catchup_schedule": "⏪ 7denní televizní archiv (Catchup)",
    "player.archive_available": "Archiv dostupný",
    "player.close": "Zavřít &times;",
    "player.no_channel": "Není vybrán žádný kanál",
    "player.catchup_badge": "Archiv dostupný",
    "player.search_placeholder": "Hledat kanál...",
    "player.all_categories": "Všechny kategorie",
    "player.next": "Další",
    "player.now": "PRÁVĚ BĚŽÍ",
    "player.replay": "Přehrát",
    "player.live": "ŽIVĚ",
    "player.live_broadcast": "Živé vysílání",
    "player.now_playing_badge": "PRÁVĚ HRAJE",
    "player.not_connected": "Relace Sweet.tv není připojena.",
    "player.connect_account": "Připojit účet",
    "player.load_failed": "Nepodařilo se načíst seznam stanic ze serveru.",
    "player.no_matches": "Nebyly nalezeny žádné stanice odpovídající",
    "player.loading_archive": "Načítám 7denní televizní archiv...",
    "player.no_archive_for_channel": "Pro tento kanál není v archivu k dispozici žádný záznam.",
    "player.archive_network_error": "Chyba sítě při načítání archivu pořadů.",
    "player.no_epg_found": "Pro tento den nejsou k dispozici žádné pořady.",

    // EPG Catchup Záložky dnů a bohaté karty
    "epg.today": "Dnes",
    "epg.yesterday": "Včera",
    "epg.search_placeholder": "Hledat v pořadech tohoto dne...",
    "epg.play_recording": "Přehrát záznam",
    "epg.restart_recording": "Znovu přehrát",
    "epg.duration": "Délka",
    "epg.no_programs_day": "Pro vybraný den nebyly nalezeny žádné pořady.",
    "epg.programs_found": "nalezených pořadů",
    "epg.channel_archive": "Archiv pořadů stanice:",
    "epg.no_channel_selected": "Pro zobrazení 7denního archivu vyberte stanici v seznamu vpravo.",

    // Kategorie
    "category.all": "Všechny",
    "category.favorites": "Oblíbené",
    "category.national": "Národní",
    "category.movies": "Filmové",
    "category.news": "Zpravodajské",
    "category.sports": "Sportovní",
    "category.documentary": "Dokumentární",
    "category.kids": "Dětské",
    "category.music": "Hudební",

    // Záložka Správa účtu
    "account.title": "Správa účtu Sweet.tv a párování",
    "account.subtitle": "Správa přihlášené relace, virtuální hardware identita zařízení a párovací nástroje.",
    "account.session_card": "Stav přihlášení",
    "account.token_card": "Platnost tokenu",
    "account.hardware_card": "Virtuální identita zařízení",
    "account.actions_card": "Ovládání účtu a zařízení",
    "account.disconnect_btn": "Odpojit účet",
    "account.reset_device_btn": "Resetovat ID zařízení (nové UUID/MAC)",
    "account.pair_btn": "Spárovat / Připojit účet",
    "account.pair_desc": "Připojte se pomocí 4místného kódu nebo QR kódu na Sweet.tv.",
    "account.active_session": "Aktivní relace Sweet.tv",
    "account.no_session": "Nepřipojeno",

    // Záložka Odkazy
    "links.title": "M3U playlisty, EPG a portálové odkazy",
    "links.subtitle": "Předpřipravené adresy pro IPTV aplikace, Kodi, Smart TV a portály.",
    "links.m3u_best_title": "M3U playlist • Nejvyšší kvalita (Best)",
    "links.m3u_best_desc": "Nastaví nejvyšší dostupný datový tok (4K UHD / 1080p FHD 50fps) na všech kanálech.",
    "links.m3u_auto_title": "M3U playlist • Adaptivní kvalita (Auto)",
    "links.m3u_auto_desc": "Adaptivní master playlist. Automaticky upravuje rozlišení a datový tok podle rychlosti sítě.",
    "links.epg_xmltv_title": "EPG programový průvodce (XMLTV)",
    "links.epg_xmltv_desc": "Kompletní televizní program s názvy, časy, popisy a ikonami kanálů.",
    "links.std_xml_url": "Běžná XML adresa:",
    "links.gzip_xml_url": "Komprimovaná GZIP adresa (rychlejší načítání):",
    "links.copy_epg_btn": "Kopírovat EPG URL",
    "links.copy_gzip_btn": "Kopírovat Gzip URL",
    "links.view_btn": "Zobrazit",
    "links.m3u_catchup_title": "M3U playlist • S tagy pro televizní archiv",
    "links.m3u_catchup_desc": "Obsahuje tagy pro zpětné přehrávání (až 7 dní) pro Kodi PVR a TiviMate.",
    "links.m3u_clean_title": "M3U playlist • Čistý samostatný (bez auto-EPG)",
    "links.m3u_clean_desc": "Čistý playlist bez url-tvg hlavičky. Ideální pro IPTV portály synchronizující kanály nezávisle na EPG.",
    "links.stalker_title": "Stalker / MAG Portál • Ministra Middleware",
    "links.stalker_desc": "Emulace Stalker portálu pro MAG set-top boxy a IPTV aplikace. Načítá kanály, kategorie a EPG přímo přes JSON-RPC bez parsování M3U.",
    "links.xtream_title": "XTream Codes Server • Nativní JSON připojení",
    "links.xtream_desc": "Připojení přes XTream Codes API v IPTV aplikacích. Nativní JSON eliminuje chyby parsování a načítá 7denní EPG.",
    "links.copy_btn": "Kopírovat URL",
    "links.download_btn": "Stáhnout",
    "links.server_url": "Server URL / Hostitel:",
    "links.username": "Uživatelské jméno:",
    "links.password": "Heslo:",
    "links.portal_url": "URL Portálu:",
    "links.mac_address": "MAC adresa:",
    "links.mac_desc": "Použijte MAC vašeho zařízení",
    "links.universal_clean": "Univerzální čistý",
    "links.ultra_quality": "Ultra kvalita",
    "links.max_bitrate_forced": "Maximální datový tok",
    "links.electronic_guide": "Elektronický program",
    "links.xmltv_format": "Formát XMLTV",
    "links.archive_replay": "Archiv • Zpětné přehrávání",
    "links.kodi_tivimate": "Kodi a TiviMate",
    "links.no_auto_epg": "Bez auto-EPG požadavku",
    "links.multi_bitrate": "HLS vícenásobný datový tok",

    // Záložka Stav
    "status.title": "Stav systému a diagnostika",
    "status.subtitle": "Stav přihlášení v reálném čase, odpočet platnosti tokenu a parametry poskytovatele.",
    "status.account": "Sweet.tv Účet",
    "status.channels": "Celkem kanálů",
    "status.token": "Platnost tokenu",
    "status.uptime": "Doba běhu serveru",
    "status.delivery": "Přenos streamu",
    "status.direct_cdn": "Přímé CDN 302",
    "status.proxied": "Proxy přes server",
    "status.hardware_info": "Parametry zařízení a poskytovatele",
    "status.uuid": "UUID zařízení:",
    "status.mac": "MAC adresa zařízení:",
    "status.ext_url": "Nastavená veřejná URL:",
    "status.direct_stream": "Přímé přesměrování streamu:",
    "status.device_mgmt_title": "Správa zařízení Sweet.tv a párování",
    "status.device_mgmt_desc": "Odpojte aktivní relaci nebo vygenerujte zcela novou identitu zařízení (nové UUID/MAC) pro uvolnění slotu na Sweet.tv.",
    "status.disconnect_btn": "Odpojit účet",
    "status.reset_device_btn": "Resetovat ID zařízení (nové UUID/MAC)",
    "status.reset_device_confirm": "Opravdu chcete resetovat identitu zařízení? Stávající přihlášení na Sweet.tv bude ukončeno a server vygeneruje nové UUID a MAC adresu.",
    "status.disconnect_confirm": "Opravdu se chcete odpojit od účtu Sweet.tv?",

    // Záložka Nastavení
    "settings.title": "Konfigurace serveru a streamování",
    "settings.subtitle": "Nastavení jazyka/regionu, veřejné domény pro Nginx Proxy Manager a výchozí kvality.",
    "settings.country_label": "Země / Kód regionu",
    "settings.country_desc": "Mění jazyk EPG průvodce a regionální balíčky kanálů.",
    "settings.ext_url_label": "Veřejná doména / Veřejná URL adresa",
    "settings.ext_url_desc": "Vyplňte při provozu za Nginx Proxy Managerem (NPM) nebo veřejnou doménou, aby odkazy používaly vaši HTTPS doménu.",
    "settings.quality_label": "Výchozí kvalita streamů v playlistu",
    "settings.delivery_label": "Způsob předávání streamu",
    "settings.xtream_user_label": "Xtream API uživatelské jméno",
    "settings.xtream_user_desc": "Uživatelské jméno pro přehrávače s podporou Xtream Codes API.",
    "settings.xtream_pwd_label": "Xtream API heslo",
    "settings.xtream_pwd_desc": "Heslo pro přehrávače s podporou Xtream Codes API.",
    "settings.catchup_checkbox": "Zahrnout tagy pro archiv (Catchup) ve výchozím M3U playlistu",
    "settings.catchup_desc": "Při zaškrtnutí budou do výchozího playlistu vloženy tagy pro 7denní archiv.",
    "settings.save_btn": "Uložit nastavení",
    "settings.refresh_btn": "Obnovit mezipaměť",

    // Záložka Návody
    "guides.title": "Návody k nastavení pro IPTV aplikace",
    "guides.subtitle": "Podrobné návody s odkazy pro Smart TV, Apple TV, Android, Kodi, VLC a set-top boxy.",
    "guides.smart_tv_title": "Smart TV (Samsung Tizen, LG webOS)",
    "guides.android_tv_title": "Android TV a Google TV (TiviMate, Sparkle)",
    "guides.apple_tv_title": "Apple TV a iOS (iPhone / iPad)",
    "guides.kodi_title": "Kodi (PVR IPTV Simple Client)",
    "guides.pc_mac_title": "PC a Mac (VLC, IPTVnator, SFVIP)",
    "guides.mag_title": "Stalker / MAG set-top boxy",
    "guides.npm_title": "Nginx Proxy Manager a HTTPS doména",

    // Modální okna
    "modal.auth_title": "Připojení k účtu Sweet.tv",
    "modal.auth_step1": "1. Na mobilu nebo počítači otevřete:",
    "modal.auth_step2": "2. Zadejte tento 4místný aktivační kód:",
    "modal.auth_waiting": "Čekám na potvrzení v aplikaci Sweet.tv...",

    // Hlášení
    "msg.copied": "Zkopírováno do schránky!",
    "msg.settings_saved": "Nastavení bylo úspěšně uloženo!",
    "msg.settings_failed": "Chyba při ukládání nastavení.",
    "msg.cache_refreshed": "Mezipaměť kanálů a EPG byla obnovena!",
    "msg.logged_out": "Účet byl odpojen.",
    "msg.device_reset": "Identita zařízení byla obnovena. Zobrazuji nový párovací kód."
  }
};

let currentLang = localStorage.getItem("sweettv_lang") || "cs";

function t(key) {
  const dict = I18N[currentLang] || I18N.cs || I18N.en;
  if (dict && dict[key]) return dict[key];
  if (I18N.en && I18N.en[key]) return I18N.en[key];
  if (I18N.cs && I18N.cs[key]) return I18N.cs[key];
  return null;
}

function setLanguage(lang) {
  if (lang !== "en" && lang !== "cs") lang = "cs";
  currentLang = lang;
  localStorage.setItem("sweettv_lang", lang);

  // Update navbar button styles
  const btnEn = document.getElementById("lang-btn-en");
  const btnCs = document.getElementById("lang-btn-cs");
  if (btnEn && btnCs) {
    if (lang === "cs") {
      btnCs.className = "px-2 py-1 rounded font-bold transition-all text-cyan-400 bg-slate-800 shadow-sm";
      btnEn.className = "px-2 py-1 rounded font-bold transition-all text-slate-400 hover:text-white";
    } else {
      btnEn.className = "px-2 py-1 rounded font-bold transition-all text-cyan-400 bg-slate-800 shadow-sm";
      btnCs.className = "px-2 py-1 rounded font-bold transition-all text-slate-400 hover:text-white";
    }
  }

  // Update text of elements with data-i18n (ONLY if a translation exists)
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    const val = t(key);
    if (val !== null && val !== undefined && val !== "") {
      el.innerHTML = val;
    }
  });

  // Update placeholder of elements with data-i18n-placeholder
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    const key = el.getAttribute("data-i18n-placeholder");
    const val = t(key);
    if (val !== null && val !== undefined && val !== "") {
      el.setAttribute("placeholder", val);
    }
  });

  // Update titles/tooltips of elements with data-i18n-title
  document.querySelectorAll("[data-i18n-title]").forEach((el) => {
    const key = el.getAttribute("data-i18n-title");
    const val = t(key);
    if (val !== null && val !== undefined && val !== "") {
      el.setAttribute("title", val);
    }
  });

  // Notify components if needed
  if (typeof window.onLanguageChanged === "function") {
    window.onLanguageChanged(lang);
  }
  window.dispatchEvent(new CustomEvent("sweettv-language-changed", { detail: { lang } }));
}

document.addEventListener("DOMContentLoaded", () => {
  setLanguage(currentLang);
});
