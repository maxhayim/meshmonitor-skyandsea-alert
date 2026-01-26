#!/usr/bin/env python3
# mm_meta:
#   name: ✈️ 🛥️ Sky and Sea Alert
#   emoji: ✈️
#   language: Python
"""
Sky and Sea Alert — v1.1.0

KISS aircraft + vessel proximity alerts using free public APIs.

Primary integration: MeshMonitor Auto Responder scripting
- If running under MeshMonitor (MESSAGE env var is set), the script runs single-shot and prints JSON:
  {"response":"..."} then exits.
- MeshMonitor handles Meshtastic/webhooks/routing. This script does not transmit over radios.

Standalone mode:
- Polls continuously and prints status + alerts to console.
- Optional MQTT publish (for non-MeshMonitor ecosystems). MQTT is disabled by default.

Modes:
- aircraft       (ADS-B Exchange only, requires ADSBX_API_KEY)
- vessels        (AIS Hub only, requires AISHUB_API_KEY)
- sky_and_sea    (both)
- demo           (no keys, sample alerts; single-shot)

Environment variables (core):
- SSA_MODE=sky_and_sea|aircraft|vessels|demo
- SSA_LAT=<float>
- SSA_LON=<float>
- SSA_AIRCRAFT_RADIUS_MI=10
- SSA_VESSEL_RADIUS_MI=3
- SSA_POLL_INTERVAL=60
- SSA_SUPPRESS_MINUTES=15
- ADSBX_API_KEY=<key> (required for aircraft mode)
- AISHUB_API_KEY=<key> (required for vessels mode)

Environment variables (MQTT, optional standalone):
- SSA_MQTT_HOST=<host>
- SSA_MQTT_PORT=1883
- SSA_MQTT_TOPIC=sky-and-sea-alert/events
- SSA_MQTT_USERNAME=<optional>
- SSA_MQTT_PASSWORD=<optional>
- SSA_MQTT_TLS=0|1 (default 0)
- SSA_MQTT_ALLOW_IN_MESHMONITOR=0|1 (default 0)
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


# =========================
# CONFIG (KISS)
# =========================

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


SSA_MODE = _env_str("SSA_MODE", "sky_and_sea").strip().lower()
SSA_LAT = _env_float("SSA_LAT", 0.0)
SSA_LON = _env_float("SSA_LON", 0.0)

SSA_AIRCRAFT_RADIUS_MI = _env_float("SSA_AIRCRAFT_RADIUS_MI", 10.0)
SSA_VESSEL_RADIUS_MI = _env_float("SSA_VESSEL_RADIUS_MI", 3.0)

SSA_POLL_INTERVAL = _env_int("SSA_POLL_INTERVAL", 60)
SSA_SUPPRESS_MINUTES = _env_int("SSA_SUPPRESS_MINUTES", 15)

ADSBX_API_KEY = _env_str("ADSBX_API_KEY", "").strip()
AISHUB_API_KEY = _env_str("AISHUB_API_KEY", "").strip()

# MQTT (optional)
SSA_MQTT_HOST = _env_str("SSA_MQTT_HOST", "").strip()
SSA_MQTT_PORT = _env_int("SSA_MQTT_PORT", 1883)
SSA_MQTT_TOPIC = _env_str("SSA_MQTT_TOPIC", "sky-and-sea-alert/events").strip()
SSA_MQTT_USERNAME = _env_str("SSA_MQTT_USERNAME", "").strip()
SSA_MQTT_PASSWORD = _env_str("SSA_MQTT_PASSWORD", "").strip()
SSA_MQTT_TLS = _env_bool("SSA_MQTT_TLS", False)
SSA_MQTT_ALLOW_IN_MESHMONITOR = _env_bool("SSA_MQTT_ALLOW_IN_MESHMONITOR", False)

# MeshMonitor detection
MM_MESSAGE = os.getenv("MESSAGE")  # present when run via MeshMonitor Auto Responder
RUNNING_IN_MESHMONITOR = MM_MESSAGE is not None

# in-memory dedupe (sufficient for KISS)
_last_alert_ts: Dict[str, float] = {}


# =========================
# HELPERS
# =========================

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _status(msg: str) -> None:
    # console-friendly status line
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{ts} {msg}".strip(), flush=True)

def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.7613  # Earth radius in miles
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

def _http_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 10) -> Dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return json.loads(data.decode("utf-8", errors="replace"))

def _clamp_text(s: str, max_len: int = 200) -> str:
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"

def _mm_out(response_text: str) -> None:
    # MeshMonitor expects valid JSON to stdout
    payload = {"response": _clamp_text(response_text, 200)}
    print(json.dumps(payload, ensure_ascii=False))

def _parse_command(message: str) -> Tuple[str, str]:
    """
    Returns (command, arg) where command is 'ssa' or '' and arg is optional.
    Examples:
      "!ssa" -> ("ssa","")
      "!ssa sky" -> ("ssa","sky")
    """
    raw = (message or "").strip()
    if not raw:
        return ("", "")
    parts = raw.split()
    head = parts[0].lower()
    if head not in ("!ssa", "/ssa"):
        return ("", "")
    arg = parts[1].lower() if len(parts) > 1 else ""
    return ("ssa", arg)


# =========================
# MQTT (OPTIONAL)
# =========================

def _mqtt_enabled() -> bool:
    if not SSA_MQTT_HOST:
        return False
    if RUNNING_IN_MESHMONITOR and not SSA_MQTT_ALLOW_IN_MESHMONITOR:
        return False
    return True

def _mqtt_publish(event: Dict[str, Any]) -> None:
    """
    Publishes a single JSON message using mosquitto_pub if available.
    No-op if not enabled or mosquitto_pub is missing.
    """
    if not _mqtt_enabled():
        return

    mosq = shutil.which("mosquitto_pub")
    if not mosq:
        # keep silent in MeshMonitor; console status in standalone
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
        # Minimal TLS toggle; users can wrap with stunnel or provide additional flags later
        cmd += ["--tls-version", "tlsv1.2"]

    try:
        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        # best-effort; never crash
        pass


# =========================
# DATA SOURCES
# =========================

def _fetch_aircraft() -> List[Dict[str, Any]]:
    """
    ADS-B Exchange (API v2 lat/lon/radius)
    Returns list of aircraft objects (may be empty).
    """
    if not ADSBX_API_KEY:
        raise RuntimeError("ADSBX_API_KEY missing")

    # ADSBx endpoint expects radius in KM for this style; use miles->km conversion
    radius_km = max(0.1, SSA_AIRCRAFT_RADIUS_MI * 1.609344)
    url = f"https://api.adsbexchange.com/v2/lat/{SSA_LAT}/{SSA_LON}/{radius_km:.3f}"
    headers = {"api-auth": ADSBX_API_KEY}

    data = _http_json(url, headers=headers, timeout=10)
    ac = data.get("ac")
    if isinstance(ac, list):
        return ac
    return []

def _fetch_vessels() -> List[Dict[str, Any]]:
    """
    AIS Hub ws.php JSON (format=1)
    Returns list of ship objects (may be empty).
    """
    if not AISHUB_API_KEY:
        raise RuntimeError("AISHUB_API_KEY missing")

    radius = max(0.1, SSA_VESSEL_RADIUS_MI)
    url = (
        "https://data.aishub.net/ws.php"
        f"?username={urllib.parse.quote(AISHUB_API_KEY)}"
        "&format=1"
        f"&lat={SSA_LAT}&lon={SSA_LON}"
        f"&radius={radius}"
    )

    data = _http_json(url, headers=None, timeout=10)
    ships = data.get("ships")
    if isinstance(ships, list):
        return ships
    return []


# =========================
# ALERT FORMATTING
# =========================

def _aircraft_alert_lines(ac_list: List[Dict[str, Any]], mesh_compact: bool) -> List[str]:
    out: List[str] = []
    for ac in ac_list:
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

        callsign = (ac.get("flight") or ac.get("call") or "UNKNOWN").strip()
        icao = (ac.get("icao") or ac.get("hex") or "").strip()
        alt = ac.get("alt_baro")
        alt_ft = "?" if alt is None else str(alt)

        dedupe_key = f"air:{callsign or icao or 'unknown'}"
        if _suppress(dedupe_key):
            continue

        if mesh_compact:
            # keep tight for MeshMonitor/Meshtastic
            line = f"✈️ {callsign or (icao or 'UNKNOWN')} {dist:.1f}mi {alt_ft}ft"
        else:
            line = (
                "✈️ Aircraft overhead\n"
                f"Callsign: {callsign or 'UNKNOWN'}\n"
                f"Altitude: {alt_ft} ft\n"
                f"Distance: {dist:.1f} mi"
            )
        out.append(line)

    return out

def _vessel_alert_lines(ship_list: List[Dict[str, Any]], mesh_compact: bool) -> List[str]:
    out: List[str] = []
    for s in ship_list:
        name = (s.get("shipname") or s.get("name") or "UNKNOWN").strip()
        speed = s.get("speed")
        spd = "?" if speed is None else str(speed)
        dist = s.get("distance")
        dmi = "?" if dist is None else str(dist)

        # distance from AIS Hub is typically already in miles for their ws.php output; do not recompute
        dedupe_key = f"sea:{name or 'UNKNOWN'}"
        if _suppress(dedupe_key):
            continue

        if mesh_compact:
            line = f"🚢 {name or 'UNKNOWN'} {dmi}mi {spd}kn"
        else:
            line = (
                "🚢 Vessel nearby\n"
                f"Name: {name or 'UNKNOWN'}\n"
                f"Speed: {spd} kn\n"
                f"Distance: {dmi} mi"
            )
        out.append(line)

    return out


# =========================
# EVENT EMIT
# =========================

def _emit_event(event_type: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
    """
    Emits to console (standalone) and optional MQTT (standalone).
    MeshMonitor emission is handled separately via _mm_out().
    """
    event = {
        "source": "sky-and-sea-alert",
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


# =========================
# RUN MODES
# =========================

def _demo(mesh_compact: bool) -> List[str]:
    if mesh_compact:
        return [
            "🟢 SSA demo OK",
            "✈️ DEMO123 6.1mi 9200ft",
            "🚢 DEMO VESSEL 2.3mi 12.4kn",
        ]
    return [
        "🟢 Sky and Sea Alert demo started",
        "✈️ Aircraft overhead\nCallsign: DEMO123\nAltitude: 9200 ft\nDistance: 6.1 mi",
        "🚢 Vessel nearby\nName: DEMO VESSEL\nSpeed: 12.4 kn\nDistance: 2.3 mi",
        "✅ Demo complete",
    ]

def _single_shot(mode: str, mesh_compact: bool) -> List[str]:
    """
    Runs one pass based on the selected mode and returns alert lines.
    """
    if mode == "demo":
        return _demo(mesh_compact)

    lines: List[str] = []
    had_error = False

    if mode in ("aircraft", "sky_and_sea"):
        try:
            ac = _fetch_aircraft()
            lines.extend(_aircraft_alert_lines(ac, mesh_compact))
        except Exception as e:
            had_error = True
            if mesh_compact:
                lines.append("⚠️ Aircraft fetch error")
            else:
                lines.append(f"⚠️ Aircraft data error: {e}")

    if mode in ("vessels", "sky_and_sea"):
        try:
            ships = _fetch_vessels()
            lines.extend(_vessel_alert_lines(ships, mesh_compact))
        except Exception as e:
            had_error = True
            if mesh_compact:
                lines.append("⚠️ Vessel fetch error")
            else:
                lines.append(f"⚠️ Vessel data error: {e}")

    if not lines and not had_error:
        lines.append("⏸ No aircraft or vessels in range" if mesh_compact else "⏸ No aircraft or vessels in range")

    return lines

def _help_text(mesh_compact: bool) -> str:
    if mesh_compact:
        return "Usage: !ssa [sky|sea|demo|help]"
    return (
        "Sky and Sea Alert (SSA)\n"
        "Commands:\n"
        "  !ssa        run configured mode\n"
        "  !ssa sky    aircraft-only single-shot\n"
        "  !ssa sea    vessels-only single-shot\n"
        "  !ssa demo   sample alerts (no keys)\n"
        "  !ssa help   this help\n"
    )


# =========================
# MAIN
# =========================

def main() -> int:
    # basic sanity (avoid silent misconfig)
    if SSA_MODE not in ("aircraft", "vessels", "sky_and_sea", "demo"):
        SSA_MODE_LOCAL = "sky_and_sea"
    else:
        SSA_MODE_LOCAL = SSA_MODE

    if RUNNING_IN_MESHMONITOR:
        cmd, arg = _parse_command(MM_MESSAGE or "")
        mesh_compact = True

        if cmd != "ssa":
            # If invoked by MeshMonitor but the trigger isn't ours, stay quiet but valid.
            _mm_out("")
            return 0

        if arg in ("help", "h", "?"):
            _mm_out(_help_text(mesh_compact))
            return 0

        if arg == "demo":
            lines = _single_shot("demo", mesh_compact)
        elif arg == "sky":
            lines = _single_shot("aircraft", mesh_compact)
        elif arg == "sea":
            lines = _single_shot("vessels", mesh_compact)
        else:
            lines = _single_shot(SSA_MODE_LOCAL, mesh_compact)

        # Join compactly; keep under MeshMonitor constraints
        joined = " | ".join([l.strip() for l in lines if l.strip()])
        _mm_out(joined if joined else "⏸ No data")
        return 0

    # Standalone mode
    _status("🟢 Sky and Sea Alert started")
    _status(f"Mode: {SSA_MODE_LOCAL}")
    _status(f"Location: {SSA_LAT}, {SSA_LON}")
    _status(f"Polling every {SSA_POLL_INTERVAL}s")

    if _mqtt_enabled():
        _status(f"MQTT: enabled ({SSA_MQTT_HOST}:{SSA_MQTT_PORT} → {SSA_MQTT_TOPIC})")
    else:
        _status("MQTT: disabled")

    if SSA_MODE_LOCAL == "demo":
        for line in _single_shot("demo", mesh_compact=False):
            _emit_event("status" if line.startswith("🟢") else "demo", line)
        return 0

    while True:
        _status("🔄 Checking sky and sea traffic…")
        lines = _single_shot(SSA_MODE_LOCAL, mesh_compact=False)

        for line in lines:
            if line.startswith("⚠️"):
                _emit_event("status", line)
            elif line.startswith("⏸"):
                _emit_event("status", line)
            elif line.startswith("✈️"):
                _emit_event("aircraft", line)
            elif line.startswith("🚢"):
                _emit_event("vessel", line)
            else:
                _emit_event("status", line)

        time.sleep(max(1, SSA_POLL_INTERVAL))

    # unreachable
    # return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        if not RUNNING_IN_MESHMONITOR:
            _status("⏹ Stopped")
        sys.exit(0)
