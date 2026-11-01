import logging
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from app.config import config

logger = logging.getLogger("SweetTV.CatalogDB")

DB_PATH = os.path.join(os.path.dirname(config.filepath), "users.db")


def get_db_connection() -> sqlite3.Connection:
    """Returns a thread-safe connection to users.db with Row factory enabled."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_catalog_db() -> None:
    """Initializes the persistent VOD catalog ID mapping table."""
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vod_catalog_mapping (
                    stream_id INTEGER PRIMARY KEY,
                    provider TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    title TEXT,
                    created_at REAL NOT NULL,
                    UNIQUE(provider, external_id, content_type)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_vod_ext ON vod_catalog_mapping(provider, external_id, content_type)"
            )
            # Ensure Ulice is always mapped to series base ID 40011
            cur = conn.cursor()
            cur.execute(
                "SELECT stream_id FROM vod_catalog_mapping WHERE provider = 'oneplay' AND (external_id IN ('40011', '40014', '40482', 'show.40482') OR title = 'Ulice')"
            )
            row = cur.fetchone()
            if not row:
                conn.execute("""
                    INSERT OR IGNORE INTO vod_catalog_mapping (stream_id, provider, external_id, content_type, title, created_at)
                    VALUES (40011, 'oneplay', 'show.40482', 'series', 'Ulice', ?)
                """, (time.time(),))
    except Exception as e:
        logger.error(f"Error initializing vod_catalog_mapping: {e}")
    finally:
        conn.close()


def get_or_create_stream_id(
    provider: str,
    external_id: str,
    content_type: str,
    title: Optional[str] = None
) -> int:
    """
    Returns the persistent integer stream_id for a given provider item.
    If the item is not yet recorded, assigns a new persistent ID in the appropriate range:
      - Movies ('movie'): 30001+
      - Recordings ('recording'): 31001+
      - Series ('series', 'show'): 40001+
    """
    if not external_id:
        external_id = f"title_{title or 'unknown'}"

    # Normalize content_type
    ct = "series" if content_type in ("show", "series") else ("recording" if content_type == "recording" else "movie")

    # Hardcoded alias check for Ulice
    if title == "Ulice" or external_id in ("40011", "40014", "40482", "show.40482"):
        return 40011

    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            # 1. Lookup by provider + external_id + content_type
            cur.execute(
                "SELECT stream_id FROM vod_catalog_mapping WHERE provider = ? AND external_id = ? AND content_type = ?",
                (provider, external_id, ct)
            )
            row = cur.fetchone()
            if row:
                return int(row["stream_id"])

            # 2. Lookup by title + content_type if external_id format shifted
            if title:
                cur.execute(
                    "SELECT stream_id FROM vod_catalog_mapping WHERE provider = ? AND title = ? AND content_type = ?",
                    (provider, title, ct)
                )
                row_t = cur.fetchone()
                if row_t:
                    # Update external_id to new format
                    conn.execute(
                        "UPDATE vod_catalog_mapping SET external_id = ? WHERE stream_id = ?",
                        (external_id, row_t["stream_id"])
                    )
                    return int(row_t["stream_id"])

            # 3. Allocate new ID in dedicated range
            if ct == "movie":
                base_start = 30001
                base_end = 39999
            elif ct == "recording":
                base_start = 50001
                base_end = 59999
            else:
                base_start = 40001
                base_end = 49999

            cur.execute(
                "SELECT stream_id FROM vod_catalog_mapping WHERE stream_id >= ? AND stream_id <= ? ORDER BY stream_id ASC",
                (base_start, base_end)
            )
            used_ids = {r["stream_id"] for r in cur.fetchall()}
            # Reserve known aliases for Ulice
            used_ids.update({40011, 40014, 40482})

            next_id = base_start
            while next_id in used_ids:
                next_id += 1

            for attempt in range(10):
                try:
                    conn.execute("""
                        INSERT INTO vod_catalog_mapping (stream_id, provider, external_id, content_type, title, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (next_id, provider, external_id, ct, title or "", time.time()))
                    logger.info(f"Assigned persistent {ct} stream_id={next_id} for '{title}' ({external_id})")
                    return next_id
                except sqlite3.IntegrityError:
                    # Check if already inserted concurrently
                    cur.execute(
                        "SELECT stream_id FROM vod_catalog_mapping WHERE provider = ? AND external_id = ? AND content_type = ?",
                        (provider, external_id, ct)
                    )
                    r = cur.fetchone()
                    if r:
                        return int(r["stream_id"])
                    next_id += 1
            return next_id
    except Exception as e:
        logger.error(f"Error getting/creating stream_id: {e}")
        try:
            # Re-check if already inserted
            conn_fallback = get_db_connection()
            cur_fb = conn_fallback.cursor()
            cur_fb.execute(
                "SELECT stream_id FROM vod_catalog_mapping WHERE provider = ? AND external_id = ?",
                (provider, external_id)
            )
            r_fb = cur_fb.fetchone()
            conn_fallback.close()
            if r_fb:
                return int(r_fb["stream_id"])
        except Exception:
            pass
        return (30000 if ct == "movie" else (50000 if ct == "recording" else 40000)) + (abs(hash(external_id)) % 900) + 1
    finally:
        conn.close()


def get_all_stream_id_mappings(provider: str = "oneplay") -> Dict[str, int]:
    """Returns a lookup dictionary mapping external_id -> stream_id."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT external_id, stream_id FROM vod_catalog_mapping WHERE provider = ?", (provider,))
        return {r["external_id"]: r["stream_id"] for r in cur.fetchall()}
    except Exception as e:
        logger.error(f"Error fetching stream_id mappings: {e}")
        return {}
    finally:
        conn.close()
