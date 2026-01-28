
#!/usr/bin/env python3
# mm_meta:
#   name: ✈️ 🛥️ Sky and Sea Alert
#   emoji: ✈️
#   language: Python
"""
Sky and Sea Alert — v2.0.0

Major release: Local-first sensing with optional secure remote access (e.g., Tailscale).

Sky and Sea Alert generates compact aircraft/vessel proximity alerts for a configured lat/lon using:
- Local ADS-B receivers (dump1090/readsb) over HTTP JSON (recommended)
- Local AIS receivers (AIS-catcher / other) over HTTP JSON (recommended)
- Optional cloud sources:
  - ADS-B Exchange via RapidAPI (paid)
  - AIS Hub API (account-based, rate-limited)

MeshMonitor integration:
- When run by MeshMonitor Auto Responder (MESSAGE env var present), script runs single-shot and prints JSON:
    {"response":"..."}
  MeshMonitor handles Meshtastic/webhooks/routing/delivery.

Standalone mode:
- Polls continuously and prints status/alerts to stdout
- Optional MQTT publish via mosquitto_pub (disabled by default)

No scraping. No shared keys. No direct radio transmission.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


SSA_VERSION = "v2.0.0"

# -------------------------
# ENV helpers
# -------------------------

def _env_str(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return default if v is None else v

def _env_bool(name: str, default: bool = False) -> bool:
    v = _env_str(name, "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "y", "on")

def _env_float(name: str, default: float) -> float:
    try:
        return float(_env_str(name, str(default)).strip())
    except Exception:
        return default

def _env_int(name: str, default: int) -> int:
    try:
        return int(_env_str(name, str(default)).strip())
    except Exception:
        return default


# -------------------------
# Core config
# -------------------------

SSA_MODE = _env_str("SSA_MODE", "sky_and_sea").strip().lower()

SSA_LAT = _env_float("SSA_LAT", 0.0)
SSA_LON = _env_float("SSA_LON", 0.0)

SSA_AIRCRAFT_RADIUS_MI = _env_float("SSA_AIRCRAFT_RADIUS_MI", 10.0)
SSA_VESSEL_RADIUS_MI = _env_float("SSA_VESSEL_RADIUS_MI", 3.0)

SSA_POLL_INTERVAL = _env_int("SSA_POLL_INTERVAL", 60)
SSA_SUPPRESS_MINUTES = _env_int("SSA_SUPPRESS_MINUTES", 15)

# Local sources (recommended)
SSA_ADSB_URL = _env_str("SSA_ADSB_URL", "http://127.0.0.1:8080/data/aircraft.json").strip()
SSA_AIS_URL = _env_str("SSA_AIS_URL", "").strip()  # optional: your AIS JSON endpoint

# Cloud sources (optional)
# ADS-B Exchange via RapidAPI (paid)
ADSBX_API_KEY = _env_str("ADSBX_API_KEY", "").strip()  # RapidAPI X-RapidAPI-Key
ADSBX_RAPIDAPI_HOST = _env_str("ADSBX_RAPIDAPI_HOST", "adsbexchange-com1.p.rapidapi.com").strip()
ADSBX_RAPIDAPI_URL_TEMPLATE = _env_str(
    "ADSBX_RAPIDAPI_URL_TEMPLATE",
    "https://adsbexchange-com1.p.rapidapi.com/v2/lat/{lat}/{lon}/{radius_km}",
).strip()

# AIS Hub (account-based, rate-limited)
AISHUB_API_KEY = _env_str("AISHUB_API_KEY", "").strip()  # AIS Hub "username"
AISHUB_URL = _env_str("AISHUB_URL", "https://data.aishub.net/ws.php").strip()

# MQTT (optional)
SSA_MQTT_HOST = _env_str("SSA_MQTT_HOST", "").strip()
SSA_MQTT_PORT = _env_int("SSA_MQTT_PORT", 1883)
SSA_MQTT_TOPIC = _env_str("SSA_MQTT_TOPIC", "sky-and-sea-alert/events").strip()
SSA_MQTT_USERNAME = _env_str("SSA_MQTT_USERNAME", "").strip()
SSA_MQTT_PASSWORD = _env_str("SSA_MQTT_PASSWORD", "").strip()
SSA_MQTT_TLS = _env_bool("SSA_MQTT_TLS", False)
SSA_MQTT_ALLOW_IN_MESHMONITOR = _env_bool("SSA_MQTT_ALLOW_IN_MESHMONITOR", False)

# MeshMonitor detection
MM_MESSAGE = os.getenv("MESSAGE")  # set by MeshMonitor Auto Responder
RUNNING_IN_MESHMONITOR = MM_MESSAGE is not None

# In-memory dedupe (KISS)
_last_alert_ts: Dict[str, float] = {}


# -------------------------
# Utility
# -------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _status(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{ts} {msg}".strip(), flush=True)

def _clamp_text(s: str, max_len: int = 200) -> str:
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"

def _mm_out(response_text: str) -> None:
    print(json.dumps({"response": _clamp_text(response_text, 200)}, ensure_ascii=False))

def _parse_command(message: str) -> Tuple[str, str]:
    raw = (message or "").strip()
    if not raw:
        return ("", "")
    parts = raw.split()
    head = parts[0].lower()
    if head not in ("!ssa", "/ssa"):
        return ("", "")
    arg = parts[1].lower() if len(parts) > 1 else ""
    return ("ssa", arg)

def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.7613
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return r * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

def _suppress(key: str) -> bool:
    now = time.time()
    window = max(0, SSA_SUPPRESS_MINUTES) * 60
    if window <= 0:
        _last_alert_ts[key] = now
        return False
    if key in _last_alert_ts and (now - _last_alert_ts[key]) < window:
        return True
    _last_alert_ts[key] = now
    return False

def _http_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 10) -> Any:
    req = urllib.request.Request(url, method="GET")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return json.loads(data.decode("utf-8", errors="replace"))


# -------------------------
# MQTT (optional)
# -------------------------

def _mqtt_enabled() -> bool:
    if not SSA_MQTT_HOST:
        return False
    if RUNNING_IN_MESHMONITOR and not SSA_MQTT_ALLOW_IN_MESHMONITOR:
        return False
    return True

def _mqtt_publish(event: Dict[str, Any]) -> None:
    if not _mqtt_enabled():
        return

    mosq = shutil.which("mosquitto_pub")
    if not mosq:
        if not RUNNING_IN_MESHMONITOR:
            _status("⚠️ MQTT enabled but mosquitto_pub not found; skipping MQTT publish")
        return

    msg = json.dumps(event, ensure_ascii=False)
    cmd = [mosq, "-h", SSA_MQTT_HOST, "-p", str(SSA_MQTT_PORT), "-t", SSA_MQTT_TOPIC, "-m", msg]
    if SSA_MQTT_USERNAME:
        cmd += ["-u", SSA_MQTT_USERNAME]
    if SSA_MQTT_PASSWORD:
        cmd += ["-P", SSA_MQTT_PASSWORD]
    if SSA_MQTT_TLS:
        cmd += ["--tls-version", "tlsv1.2"]

    try:
        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def _emit_event(event_type: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
    event = {
        "source": "sky-and-sea-alert",
        "version": SSA_VERSION,
        "ts": _now_iso(),
        "type": event_type,
        "mode": SSA_MODE,
        "geo": {"lat": SSA_LAT, "lon": SSA_LON},
        "message": message,
        "data": data or {},
    }
    if not RUNNING_IN_MESHMONITOR:
        print(message, flush=True)
    _mqtt_publish(event)


# -------------------------
# Data acquisition
# -------------------------

def _fetch_aircraft_local() -> List[Dict[str, Any]]:
    # Typical dump1090/readsb endpoint:
    #   http://<host>:8080/data/aircraft.json
    data = _http_json(SSA_ADSB_URL, headers=None, timeout=8)
    # Common formats:
    # 1) {"aircraft":[...]} (dump1090/readsb)
    if isinstance(data, dict) and isinstance(data.get("aircraft"), list):
        return data["aircraft"]
    # 2) direct list
    if isinstance(data, list):
        return data
    return []

def _fetch_aircraft_rapidapi() -> List[Dict[str, Any]]:
    if not ADSBX_API_KEY:
        raise RuntimeError("ADSBX_API_KEY missing (RapidAPI X-RapidAPI-Key)")

    radius_km = max(0.1, SSA_AIRCRAFT_RADIUS_MI * 1.609344)
    url = ADSBX_RAPIDAPI_URL_TEMPLATE.format(
        lat=SSA_LAT,
        lon=SSA_LON,
        radius_km=f"{radius_km:.3f}",
    )

    headers = {
        "X-RapidAPI-Key": ADSBX_API_KEY,
        "X-RapidAPI-Host": ADSBX_RAPIDAPI_HOST,
    }
    data = _http_json(url, headers=headers, timeout=10)

    # ADSBx-style responses often include "ac": [...]
    if isinstance(data, dict) and isinstance(data.get("ac"), list):
        return data["ac"]
    # Some endpoints may return "aircraft": [...]
    if isinstance(data, dict) and isinstance(data.get("aircraft"), list):
        return data["aircraft"]
    # Fallback: list
    if isinstance(data, list):
        return data
    return []

def _fetch_vessels_local() -> List[Dict[str, Any]]:
    if not SSA_AIS_URL:
        raise RuntimeError("SSA_AIS_URL missing (local AIS JSON endpoint)")
    data = _http_json(SSA_AIS_URL, headers=None, timeout=8)
    # Accept:
    # - {"vessels":[...]} or {"ships":[...]} or list
    if isinstance(data, dict):
        for k in ("vessels", "ships", "targets", "ais"):
            v = data.get(k)
            if isinstance(v, list):
                return v
    if isinstance(data, list):
        return data
    return []

def _fetch_vessels_aishub() -> List[Dict[str, Any]]:
    if not AISHUB_API_KEY:
        raise RuntimeError("AISHUB_API_KEY missing (AIS Hub username/key)")

    radius = max(0.1, SSA_VESSEL_RADIUS_MI)
    url = (
        f"{AISHUB_URL}"
        f"?username={urllib.parse.quote(AISHUB_API_KEY)}"
        "&format=1"
        f"&lat={SSA_LAT}&lon={SSA_LON}"
        f"&radius={radius}"
    )
    data = _http_json(url, headers=None, timeout=10)
    if isinstance(data, dict) and isinstance(data.get("ships"), list):
        return data["ships"]
    if isinstance(data, dict) and isinstance(data.get("vessels"), list):
        return data["vessels"]
    if isinstance(data, list):
        return data
    return []


# -------------------------
# Alert formatting
# -------------------------

def _aircraft_alert_lines(ac_list: List[Dict[str, Any]], mesh_compact: bool) -> List[str]:
    out: List[str] = []
    for ac in ac_list:
        # dump1090/readsb: lat/lon fields are "lat", "lon"
        # ADSBx: also lat/lon typically
        lat = ac.get("lat")
        lon = ac.get("lon")
        if lat is None or lon is None:
            continue

        try:
            dist = _haversine_miles(SSA_LAT, SSA_LON, float(lat), float(lon))
        except Exception:
            continue
        if dist > SSA_AIRCRAFT_RADIUS_MI:
            continue

        callsign = (ac.get("flight") or ac.get("call") or ac.get("callsign") or "").strip()
        icao = (ac.get("hex") or ac.get("icao") or ac.get("icao24") or "").strip()
        alt = ac.get("alt_baro")
        if alt is None:
            alt = ac.get("altitude")
        alt_ft = "?" if alt is None else str(alt)

        label = callsign or icao or "UNKNOWN"
        dedupe_key = f"air:{label}"
        if _suppress(dedupe_key):
            continue

        if mesh_compact:
            out.append(f"✈️ {label} {dist:.1f}mi {alt_ft}ft")
        else:
            out.append(
                "✈️ Aircraft overhead\n"
                f"ID: {label}\n"
                f"Altitude: {alt_ft} ft\n"
                f"Distance: {dist:.1f} mi"
            )
    return out

def _vessel_alert_lines(v_list: List[Dict[str, Any]], mesh_compact: bool) -> List[str]:
    out: List[str] = []
    for v in v_list:
        # AIS Hub often provides distance directly; local feeds might provide lat/lon.
        name = (v.get("shipname") or v.get("name") or v.get("vessel") or v.get("callsign") or "UNKNOWN").strip()
        mmsi = str(v.get("mmsi") or v.get("MMSI") or "").strip()

        speed = v.get("speed")
        if speed is None:
            speed = v.get("sog")  # speed over ground
        spd = "?" if speed is None else str(speed)

        dmi = None
        if v.get("distance") is not None:
            try:
                dmi = float(v.get("distance"))
            except Exception:
                dmi = None

        if dmi is None:
            # Try compute from lat/lon if present
            lat = v.get("lat") if v.get("lat") is not None else v.get("latitude")
            lon = v.get("lon") if v.get("lon") is not None else v.get("longitude")
            if lat is not None and lon is not None:
                try:
                    dmi = _haversine_miles(SSA_LAT, SSA_LON, float(lat), float(lon))
                except Exception:
                    dmi = None

        if dmi is None:
            # If we cannot compute distance, still allow but do not enforce radius
            pass
        else:
            if dmi > SSA_VESSEL_RADIUS_MI:
                continue

        label = name if name != "UNKNOWN" else (mmsi or "UNKNOWN")
        dedupe_key = f"sea:{label}"
        if _suppress(dedupe_key):
            continue

        if mesh_compact:
            if dmi is None:
                out.append(f"🚢 {label} ?mi {spd}kn")
            else:
                out.append(f"🚢 {label} {dmi:.1f}mi {spd}kn")
        else:
            out.append(
                "🚢 Vessel nearby\n"
                f"ID: {label}\n"
                f"Speed: {spd} kn\n"
                f"Distance: {('?' if dmi is None else f'{dmi:.1f}')} mi"
            )
    return out


# -------------------------
# Modes
# -------------------------

def _demo(mesh_compact: bool) -> List[str]:
    if mesh_compact:
        return [
            "🟢 SSA demo OK",
            "✈️ DEMO123 6.1mi 9200ft",
            "🚢 DEMO VESSEL 2.3mi 12.4kn",
        ]
    return [
        "🟢 Sky and Sea Alert demo started",
        "✈️ Aircraft overhead\nID: DEMO123\nAltitude: 9200 ft\nDistance: 6.1 mi",
        "🚢 Vessel nearby\nID: DEMO VESSEL\nSpeed: 12.4 kn\nDistance: 2.3 mi",
        "✅ Demo complete",
    ]

def _help_text(mesh_compact: bool) -> str:
    if mesh_compact:
        return "Usage: !ssa [sky|sea|demo|help]"
    return (
        f"Sky and Sea Alert {SSA_VERSION}\n"
        "\n"
        "Primary (recommended): local receivers\n"
        "  ADS-B: dump1090/readsb JSON (SSA_ADSB_URL)\n"
        "  AIS:   AIS-catcher/other JSON (SSA_AIS_URL)\n"
        "\n"
        "Optional cloud sources\n"
        "  ADS-B Exchange via RapidAPI (paid): ADSBX_API_KEY + ADSBX_RAPIDAPI_HOST\n"
        "  AIS Hub (account-based): AISHUB_API_KEY (username)\n"
        "\n"
        "MeshMonitor commands:\n"
        "  !ssa        run configured mode\n"
        "  !ssa sky    aircraft single-shot\n"
        "  !ssa sea    vessels single-shot\n"
        "  !ssa demo   sample alerts\n"
        "  !ssa help   this help\n"
    )

def _single_shot(mode: str, mesh_compact: bool) -> List[str]:
    mode = mode.strip().lower()

    if mode == "demo":
        return _demo(mesh_compact)

    lines: List[str] = []
    had_error = False

    # Aircraft
    if mode in ("aircraft-local", "sky_and_sea", "sky_and_sea_local", "aircraft"):
        try:
            ac = _fetch_aircraft_local()
            lines.extend(_aircraft_alert_lines(ac, mesh_compact))
        except Exception as e:
            had_error = True
            lines.append("⚠️ Aircraft local fetch error" if mesh_compact else f"⚠️ Aircraft local error: {e}")

    if mode in ("aircraft-cloud",):
        try:
            ac = _fetch_aircraft_rapidapi()
            lines.extend(_aircraft_alert_lines(ac, mesh_compact))
        except Exception as e:
            had_error = True
            lines.append("⚠️ Aircraft cloud fetch error" if mesh_compact else f"⚠️ Aircraft cloud error: {e}")

    # Vessels
    if mode in ("vessels-local", "sky_and_sea", "sky_and_sea_local", "vessels", "sea_and_sky_local"):
        try:
            ships = _fetch_vessels_local()
            lines.extend(_vessel_alert_lines(ships, mesh_compact))
        except Exception as e:
            had_error = True
            lines.append("⚠️ Vessel local fetch error" if mesh_compact else f"⚠️ Vessel local error: {e}")

    if mode in ("vessels-cloud",):
        try:
            ships = _fetch_vessels_aishub()
            lines.extend(_vessel_alert_lines(ships, mesh_compact))
        except Exception as e:
            had_error = True
            lines.append("⚠️ Vessel cloud fetch error" if mesh_compact else f"⚠️ Vessel cloud error: {e}")

    if not lines and not had_error:
        lines.append("⏸ No aircraft or vessels in range")

    return lines


# -------------------------
# Main
# -------------------------

def main() -> int:
    # Normalize mode aliases (keep KISS)
    mode = SSA_MODE
    if mode in ("sky+sea", "sky-sea", "sky_and_sea_local", "local", "default"):
        mode = "sky_and_sea"
    if mode in ("aircraft_only", "sky"):
        mode = "aircraft-local"
    if mode in ("vessels_only", "sea"):
        mode = "vessels-local"

    if RUNNING_IN_MESHMONITOR:
        cmd, arg = _parse_command(MM_MESSAGE or "")
        mesh_compact = True

        if cmd != "ssa":
            _mm_out("")
            return 0

        if arg in ("help", "h", "?"):
            _mm_out(_help_text(mesh_compact))
            return 0

        if arg == "demo":
            lines = _single_shot("demo", mesh_compact)
        elif arg == "sky":
            # Use local by default for aircraft
            lines = _single_shot("aircraft-local", mesh_compact)
        elif arg == "sea":
            # Use local by default for vessels
            lines = _single_shot("vessels-local", mesh_compact)
        else:
            lines = _single_shot(mode, mesh_compact)

        joined = " | ".join([l.strip() for l in lines if l.strip()])
        _mm_out(joined if joined else "⏸ No data")
        return 0

    # Standalone loop
    _status(f"🟢 Sky and Sea Alert started ({SSA_VERSION})")
    _status(f"Mode: {mode}")
    _status(f"Location: {SSA_LAT}, {SSA_LON}")
    _status(f"ADS-B local: {SSA_ADSB_URL}")
    _status(f"AIS local: {SSA_AIS_URL or '(not set)'}")
    _status(f"MQTT: {'enabled' if _mqtt_enabled() else 'disabled'}")
    _status(f"Polling every {max(1, SSA_POLL_INTERVAL)}s")

    if mode == "demo":
        for line in _single_shot("demo", mesh_compact=False):
            _emit_event("demo", line)
        return 0

    # Gentle first-run hints (do not spam, just informative)
    if mode in ("aircraft-local", "sky_and_sea") and not SSA_ADSB_URL:
        _status("⚠️ SSA_ADSB_URL not set; aircraft-local will not work")
    if mode in ("vessels-local", "sky_and_sea") and not SSA_AIS_URL:
        _status("⚠️ SSA_AIS_URL not set; vessels-local will not work (set SSA_AIS_URL or use vessels-cloud)")

    if mode == "aircraft-cloud" and not ADSBX_API_KEY:
        _status("🔑 Missing ADSBX_API_KEY (RapidAPI key) for aircraft-cloud")
    if mode == "vessels-cloud" and not AISHUB_API_KEY:
        _status("🔑 Missing AISHUB_API_KEY (AIS Hub username) for vessels-cloud")

    while True:
        _status("🔄 Checking sky and sea traffic…")
        lines = _single_shot(mode, mesh_compact=False)

        for line in lines:
            if line.startswith("⚠️") or line.startswith("🔑") or line.startswith("⏸") or line.startswith("🟢") or line.startswith("✅"):
                _emit_event("status", line)
            elif line.startswith("✈️"):
                _emit_event("aircraft", line)
            elif line.startswith("🚢"):
                _emit_event("vessel", line)
            else:
                _emit_event("status", line)

        time.sleep(max(1, SSA_POLL_INTERVAL))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        if not RUNNING_IN_MESHMONITOR:
            _status("⏹ Stopped")
        sys.exit(0)
