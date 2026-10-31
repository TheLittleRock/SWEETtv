import base64
import logging
import os
import re
import struct
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import requests
import urllib.parse

from app.config import config

logger = logging.getLogger("SweetTV.DRM.Oneplay")

# Standard Widevine System ID in UUID hex and raw bytes
WIDEVINE_SYSTEM_ID_HEX = "edef8ba979d64ace88c820d2ac11e1f1"
WIDEVINE_SYSTEM_ID_BYTES = bytes.fromhex(WIDEVINE_SYSTEM_ID_HEX)


class OneplayDRMManager:
    """
    Manages Widevine DRM key derivation and validation for Oneplay streams
    mirroring the Media-Downloader DRM plugin architecture by Sunecz.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # Cache: pssh -> (timestamp, list of (kid, key))
        self._key_cache: Dict[str, Tuple[float, List[Tuple[str, str]]]] = {}
        self._cache_ttl = 3600 * 12  # 12 hours

    @property
    def wv_api_url(self) -> str:
        url = config.get("oneplay_wv_api_url", "https://wv.api.md.sune.app/v1/")
        return url.rstrip("/") + "/"

    @property
    def license_url(self) -> str:
        return config.get("oneplay_drm_license_url", "https://drm-proxy-widevine.cms.jyxo-tls.cz/AcquireLicense")

    @property
    def upstream_repo(self) -> str:
        return config.get("oneplay_drm_upstream_repo", "sunecz/Media-Downloader-Default-Plugins")

    def extract_pssh_from_mpd(self, mpd_text: str, base_url: Optional[str] = None) -> Optional[str]:
        """
        Extracts base64-encoded Widevine PSSH from a DASH MPD manifest.
        Checks for <cenc:pssh> or <pssh> tags, and parses init segments if necessary.
        """
        if not mpd_text:
            return None

        # 1. Regex search for <cenc:pssh>...</cenc:pssh> or <pssh>...</pssh>
        pssh_matches = re.findall(r'<(?:\w+:)?pssh[^>]*>([A-Za-z0-9+/=\s]+)</(?:\w+:)?pssh>', mpd_text, re.IGNORECASE)
        for match in pssh_matches:
            clean = "".join(match.split())
            if len(clean) >= 16:
                try:
                    raw = base64.b64decode(clean)
                    # Verify Widevine system ID is present
                    if WIDEVINE_SYSTEM_ID_BYTES in raw or "edef8ba9" in raw.hex().lower():
                        logger.debug("Found Widevine PSSH directly in MPD manifest")
                        return clean
                except Exception:
                    continue

        # If any PSSH was found even without explicit Widevine system ID match, use the first valid one
        if pssh_matches:
            first_clean = "".join(pssh_matches[0].split())
            if len(first_clean) >= 16:
                return first_clean

        # 2. If PSSH not in MPD XML, inspect initialization segment URL
        init_match = re.search(r'initialization=["\']([^"\']+)["\']', mpd_text, re.IGNORECASE)
        if not init_match:
            init_match = re.search(r'<Initialization[^>]+sourceURL=["\']([^"\']+)["\']', mpd_text, re.IGNORECASE)

        if init_match and base_url:
            init_rel = init_match.group(1)
            init_url = urllib.parse.urljoin(base_url, init_rel)
            try:
                logger.info(f"PSSH not directly in MPD; probing init segment: {init_url}")
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
                    "Range": "bytes=0-8192"
                }
                r = requests.get(init_url, headers=headers, timeout=8)
                if r.status_code in (200, 206) and len(r.content) > 32:
                    pssh = self._extract_pssh_from_init_bytes(r.content)
                    if pssh:
                        return pssh
            except Exception as e:
                logger.warning(f"Error fetching init segment for PSSH extraction: {e}")

        return None

    def _extract_pssh_from_init_bytes(self, data: bytes) -> Optional[str]:
        """Scans MP4 box structure for the 'pssh' box."""
        idx = 0
        length = len(data)
        while idx + 8 <= length:
            box_size = struct.unpack(">I", data[idx:idx+4])[0]
            box_type = data[idx+4:idx+8]

            if box_size == 1:
                # 64-bit size
                if idx + 16 > length:
                    break
                box_size = struct.unpack(">Q", data[idx+8:idx+16])[0]
                box_header_size = 16
            elif box_size == 0:
                box_size = length - idx
                box_header_size = 8
            else:
                box_header_size = 8

            if box_size < 8 or idx + box_size > length:
                # Malformed or partial box; search by raw fourcc
                p_idx = data.find(b"pssh", idx)
                if p_idx >= 4:
                    pssh_start = p_idx - 4
                    p_size = struct.unpack(">I", data[pssh_start:pssh_start+4])[0]
                    if 12 <= p_size <= 4096 and pssh_start + p_size <= length:
                        return base64.b64encode(data[pssh_start:pssh_start+p_size]).decode("ascii")
                break

            if box_type == b"pssh":
                pssh_box = data[idx:idx+box_size]
                return base64.b64encode(pssh_box).decode("ascii")

            idx += box_size

        return None

    def get_decryption_keys(
        self,
        pssh: str,
        drm_token: str,
        license_url: Optional[str] = None
    ) -> List[Tuple[str, str]]:
        """
        Derives Widevine decryption keys (KID, KEY) using Sune's Widevine Cloud CDM
        and the Jyxo AxDRM license proxy.
        """
        if not pssh or not drm_token:
            logger.error("Missing required pssh or drm_token for key acquisition")
            return []

        # Check cache
        with self._lock:
            cached = self._key_cache.get(pssh)
            if cached:
                cached_time, keys = cached
                if (time.time() - cached_time) < self._cache_ttl:
                    logger.debug(f"Returning {len(keys)} cached decryption keys for PSSH {pssh[:16]}...")
                    return keys

        eff_license_url = license_url or self.license_url
        logger.info(f"Acquiring DRM decryption keys for PSSH {pssh[:20]}... via {self.wv_api_url}")

        try:
            # 1. Generate license request challenge via Sune WV API
            gen_url = f"{self.wv_api_url}generate"
            gen_resp = requests.post(gen_url, json={"pssh": pssh}, timeout=10)
            if gen_resp.status_code != 200:
                logger.error(f"Sune WV API /generate failed (HTTP {gen_resp.status_code}): {gen_resp.text}")
                return []

            gen_data = gen_resp.json()
            session_id = gen_data.get("id")
            request_b64 = gen_data.get("request")
            if not session_id or not request_b64:
                logger.error("Invalid response from Sune WV API /generate: missing id or request")
                return []

            challenge_bytes = base64.b64decode(request_b64)

            # 2. Acquire license from Jyxo CMS Widevine Proxy
            lic_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
                "Referer": "https://www.oneplay.cz/",
                "Origin": "https://www.oneplay.cz",
                "X-AxDRM-Message": drm_token,
                "Content-Type": "application/octet-stream",
            }
            lic_resp = requests.post(eff_license_url, data=challenge_bytes, headers=lic_headers, timeout=12)
            if lic_resp.status_code != 200:
                logger.error(f"Jyxo License Server failed (HTTP {lic_resp.status_code}): {lic_resp.text[:200]}")
                return []

            license_bytes = lic_resp.content

            # 3. Extract clear decryption keys from license response via Sune WV API
            extract_url = f"{self.wv_api_url}extract"
            extract_payload = {
                "id": session_id,
                "response": base64.b64encode(license_bytes).decode("ascii")
            }
            extract_resp = requests.post(extract_url, json=extract_payload, timeout=10)
            if extract_resp.status_code != 200:
                logger.error(f"Sune WV API /extract failed (HTTP {extract_resp.status_code}): {extract_resp.text}")
                return []

            extract_data = extract_resp.json()
            raw_keys = extract_data.get("keys") or []
            keys: List[Tuple[str, str]] = []

            for item in raw_keys:
                ktype = str(item.get("type") or "").upper()
                kid = str(item.get("kid") or "")
                key = str(item.get("key") or "")
                if kid and key:
                    # Content keys are required for decrypting media tracks
                    if not ktype or ktype == "CONTENT":
                        keys.append((kid, key))

            if not keys:
                # If no key was specifically marked as CONTENT, include all returned keys
                for item in raw_keys:
                    kid = str(item.get("kid") or "")
                    key = str(item.get("key") or "")
                    if kid and key:
                        keys.append((kid, key))

            logger.info(f"Successfully obtained {len(keys)} Widevine decryption key(s)")
            for kid, key in keys:
                logger.info(f"  -> KID: {kid} | KEY: {key}")

            # Update cache
            with self._lock:
                self._key_cache[pssh] = (time.time(), keys)

            return keys

        except Exception as e:
            logger.error(f"Unexpected error obtaining DRM keys: {e}", exc_info=True)
            return []

    def test_drm_pipeline(self) -> Dict[str, Any]:
        """
        Tests connectivity to Sune WV Cloud API and Jyxo License Proxy.
        Returns status report for Web Admin interface.
        """
        report: Dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "wv_api_url": self.wv_api_url,
            "license_url": self.license_url,
            "wv_service_ok": False,
            "license_service_ok": False,
            "overall_status": "error",
            "message": ""
        }

        # 1. Test Sune WV API with sample challenge
        sample_pssh = "CAESEO12345678901234567890Q="
        t0 = time.time()
        try:
            r = requests.post(f"{self.wv_api_url}generate", json={"pssh": sample_pssh}, timeout=6)
            elapsed_wv = round((time.time() - t0) * 1000, 1)
            report["wv_latency_ms"] = elapsed_wv
            if r.status_code == 200 and "id" in r.json():
                report["wv_service_ok"] = True
            else:
                report["wv_error"] = f"HTTP {r.status_code}: {r.text[:100]}"
        except Exception as e:
            report["wv_error"] = str(e)

        # 2. Test Jyxo license server endpoint reachability
        t0 = time.time()
        try:
            r = requests.post(self.license_url, data=b"", timeout=6)
            elapsed_lic = round((time.time() - t0) * 1000, 1)
            report["license_latency_ms"] = elapsed_lic
            # Without token, Jyxo usually returns 400 or 401, which proves reachability
            if r.status_code in (400, 401, 403, 200):
                report["license_service_ok"] = True
            else:
                report["license_error"] = f"Unexpected HTTP status {r.status_code}"
        except Exception as e:
            report["license_error"] = str(e)

        if report["wv_service_ok"] and report["license_service_ok"]:
            report["overall_status"] = "ok"
            report["message"] = "DRM služby jsou online a připraveny k dešifrování."
        else:
            report["overall_status"] = "degraded" if report["wv_service_ok"] or report["license_service_ok"] else "error"
            report["message"] = "Některá z DRM služeb neodpovídá."

        return report

    def check_upstream_updates(self) -> Dict[str, Any]:
        """Checks for new commits in Sunecz's upstream repository."""
        repo = self.upstream_repo
        url = f"https://api.github.com/repos/{repo}/commits?per_page=1"
        try:
            r = requests.get(url, headers={"User-Agent": "SweetTV-Oneplay-Proxy"}, timeout=6)
            if r.status_code == 200:
                commits = r.json()
                if commits and isinstance(commits, list):
                    last_c = commits[0]
                    return {
                        "status": "ok",
                        "repo": repo,
                        "latest_sha": last_c.get("sha")[:8],
                        "latest_date": last_c.get("commit", {}).get("author", {}).get("date"),
                        "message": last_c.get("commit", {}).get("message", "").splitlines()[0],
                        "url": last_c.get("html_url")
                    }
            return {"status": "error", "message": f"GitHub API error {r.status_code}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}


# Global DRM manager instance
drm_manager = OneplayDRMManager()

