## sky_and_sea_alert.py

#!/usr/bin/env python3
# mm_meta:
#   name: Sky and Sea Alert
#   emoji: ✈️ 🛥️
#   language: Python
"""
Sky and Sea Alert — v2.2.0

v2.x philosophy: Local-first sensing with optional secure remote access (e.g., Tailscale).
v2.2 standardizes provider docs + keeps expanded aircraft cloud providers.

Aircraft providers:
- local (recommended): dump1090/readsb aircraft.json over HTTP
- adsblol (free): ADSB.lol (ADSBexchange v2 point endpoint)
- airplaneslive (free): airplanes.live REST API (/v2/point)
- adsbfi (free/open): adsb.fi Open Data API (ADSBexchange v2 compatible)
- adsbone (free/open): ADSB One (ADSBexchange v2 compatible)
- opensky (limited): OpenSky REST (bounding-box query)
- adsbx_rapidapi (paid): ADSBexchange via RapidAPI

Vessel providers:
- local (recommended): user-provided AIS JSON endpoint
- aishub (account-based): AIS Hub webservice

MeshMonitor integration:
- If MESSAGE env var exists, script runs single-shot and prints JSON {"response":"..."}.

Standalone mode:
- Polls continuously and prints status/alerts to stdout.
- Optional MQTT publish via mosquitto_pub (disabled by default).

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
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

SSA_VERSION = "v2.2.0"

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

# Aircraft provider selector (v2.2.0)
# local | adsblol | airplaneslive | adsbfi | adsbone | opensky | adsbx_rapidapi
SSA_AIRCRAFT_PROVIDER = _env_str("SSA_AIRCRAFT_PROVIDER", "local").strip().lower()

# Local sources (recommended)
SSA_ADSB_URL = _env_str("SSA_ADSB_URL", "http://127.0.0.1:8080/data/aircraft.json").strip()
SSA_AIS_URL = _env_str("SSA_AIS_URL", "").strip()

# Cloud bases
SSA_ADSBLOL_BASE = _env_str("SSA_ADSBLOL_BASE", "https://api.adsb.lol").strip()
SSA_AIRPLANESLIVE_BASE = _env_str("SSA_AIRPLANESLIVE_BASE", "https://api.airplanes.live").strip()
SSA_ADSBFI_BASE = _env_str("SSA_ADSBFI_BASE", "https://opendata.adsb.fi/api").strip()
SSA_ADSBONE_BASE = _env_str("SSA_ADSBONE_BASE", "https://api.adsb.one").strip()
SSA_OPENSKY_BASE = _env_str("SSA_OPENSKY_BASE", "https://opensky-network.org/api").strip()

# Paid ADSBexchange via RapidAPI
ADSBX_API_KEY = _env_str("ADSBX_API_KEY", "").strip()
ADSBX_RAPIDAPI_HOST = _env_str("ADSBX_RAPIDAPI_HOST", "adsbexchange-com1.p.rapidapi.com").strip()
ADSBX_RAPIDAPI_URL_TEMPLATE = _env_str(
    "ADSBX_RAPIDAPI_URL_TEMPLATE",
    "https://adsbexchange-com1.p.rapidapi.com/v2/lat/{lat}/{lon}/{radius_km}",
).strip()

# AIS Hub (account-based)
AISHUB_API_KEY = _env_str("AISHUB_API_KEY", "").strip()
AISHUB_URL = _env_str("AISHUB_URL", "https://data.aishub.net/ws.php").strip()

# Optional MQTT
SSA_MQTT_HOST = _env_str("SSA_MQTT_HOST", "").strip()
SSA_MQTT_PORT = _env_int("SSA_MQTT_PORT", 1883)
SSA_MQTT_TOPIC = _env_str("SSA_MQTT_TOPIC", "sky-and-sea-alert/events").strip()
SSA_MQTT_USERNAME = _env_str("SSA_MQTT_USERNAME", "").strip()
SSA_MQTT_PASSWORD = _env_str("SSA_MQTT_PASSWORD", "").strip()
SSA_MQTT_TLS = _env_bool("SSA_MQTT_TLS", False)
SSA_MQTT_ALLOW_IN_MESHMONITOR = _env_bool("SSA_MQTT_ALLOW_IN_MESHMONITOR", False)

# MeshMonitor detection
MM_MESSAGE = os.getenv("MESSAGE")
RUNNING_IN_MESHMONITOR = MM_MESSAGE is not None

# In-memory dedupe (KISS)
_last_alert_ts: Dict[str, float] = {}

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

def _mi_to_nm(mi: float) -> float:
    return mi / 1.15078

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
        "aircraft_provider": SSA_AIRCRAFT_PROVIDER,
        "geo": {"lat": SSA_LAT, "lon": SSA_LON},
        "message": message,
        "data": data or {},
    }
    if not RUNNING_IN_MESHMONITOR:
        print(message, flush=True)
    _mqtt_publish(event)

def _extract_aircraft_list(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        for k in ("aircraft", "ac"):
            v = payload.get(k)
            if isinstance(v, list):
                return v
    if isinstance(payload, list):
        return payload
    return []

def _fetch_aircraft_local() -> List[Dict[str, Any]]:
    data = _http_json(SSA_ADSB_URL, headers=None, timeout=8)
    return _extract_aircraft_list(data)

def _fetch_aircraft_v2_point(base: str, lat: float, lon: float, radius_nm: float) -> List[Dict[str, Any]]:
    url = f"{base.rstrip('/')}/v2/point/{lat}/{lon}/{radius_nm:.1f}"
    data = _http_json(url, headers=None, timeout=10)
    return _extract_aircraft_list(data)

def _fetch_aircraft_opensky() -> List[Dict[str, Any]]:
    r_mi = max(0.1, SSA_AIRCRAFT_RADIUS_MI)
    lat = SSA_LAT
    lon = SSA_LON

    lat_delta = r_mi / 69.0
    cos_lat = max(0.1, abs(math.cos(math.radians(lat))))
    lon_delta = r_mi / (69.0 * cos_lat)

    lamin = lat - lat_delta
    lamax = lat + lat_delta
    lomin = lon - lon_delta
    lomax = lon + lon_delta

    url = f"{SSA_OPENSKY_BASE.rstrip('/')}/states/all?lamin={lamin}&lamax={lamax}&lomin={lomin}&lomax={lomax}"
    data = _http_json(url, headers=None, timeout=12)

    states = []
    if isinstance(data, dict) and isinstance(data.get("states"), list):
        states = data["states"]

    out: List[Dict[str, Any]] = []
    for s in states:
        if not isinstance(s, list) or len(s) < 8:
            continue
        icao24 = (s[0] or "").strip()
        callsign = (s[1] or "").strip()
        slon = s[5]
        slat = s[6]
        baro_alt_m = s[7]

        alt_ft = None
        try:
            if baro_alt_m is not None:
                alt_ft = int(float(baro_alt_m) * 3.28084)
        except Exception:
            alt_ft = None

        out.append({
            "hex": icao24,
            "flight": callsign,
            "lat": slat,
            "lon": slon,
            "alt_baro": alt_ft,
        })
    return out

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
    return _extract_aircraft_list(data)

def _fetch_aircraft() -> List[Dict[str, Any]]:
    p = (SSA_AIRCRAFT_PROVIDER or "local").strip().lower()
    radius_nm = max(1.0, min(250.0, _mi_to_nm(SSA_AIRCRAFT_RADIUS_MI)))

    if p == "local":
        return _fetch_aircraft_local()
    if p in ("adsblol", "adsb.lol"):
        return _fetch_aircraft_v2_point(SSA_ADSBLOL_BASE, SSA_LAT, SSA_LON, radius_nm)
    if p in ("airplaneslive", "airplanes.live", "airplanes"):
        return _fetch_aircraft_v2_point(SSA_AIRPLANESLIVE_BASE, SSA_LAT, SSA_LON, radius_nm)
    if p in ("adsbfi", "adsb.fi"):
        return _fetch_aircraft_v2_point(SSA_ADSBFI_BASE, SSA_LAT, SSA_LON, radius_nm)
    if p in ("adsbone", "adsb.one", "adsb-one"):
        return _fetch_aircraft_v2_point(SSA_ADSBONE_BASE, SSA_LAT, SSA_LON, radius_nm)
    if p in ("opensky", "opensky-network"):
        return _fetch_aircraft_opensky()
    if p in ("adsbx_rapidapi", "rapidapi", "adsbx", "adsbexchange"):
        return _fetch_aircraft_rapidapi()

    raise RuntimeError(f"Unknown SSA_AIRCRAFT_PROVIDER '{p}'")

def _fetch_vessels_local() -> List[Dict[str, Any]]:
    if not SSA_AIS_URL:
        raise RuntimeError("SSA_AIS_URL missing (local AIS JSON endpoint)")
    data = _http_json(SSA_AIS_URL, headers=None, timeout=8)
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

def _aircraft_alert_lines(ac_list: List[Dict[str, Any]], mesh_compact: bool) -> List[str]:
    out: List[str] = []
    for ac in ac_list:
        lat = ac.get("lat")
        lon = ac.get("lon")
        if lat is None or lon is None:
            lp = ac.get("lastPosition") or {}
            lat = lat if lat is not None else lp.get("lat")
            lon = lon if lon is not None else lp.get("lon")
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
        name = (v.get("shipname") or v.get("name") or v.get("vessel") or v.get("callsign") or "UNKNOWN").strip()
        mmsi = str(v.get("mmsi") or v.get("MMSI") or "").strip()

        speed = v.get("speed")
        if speed is None:
            speed = v.get("sog")
        spd = "?" if speed is None else str(speed)

        dmi = None
        if v.get("distance") is not None:
            try:
                dmi = float(v.get("distance"))
            except Exception:
                dmi = None

        if dmi is None:
            lat = v.get("lat") if v.get("lat") is not None else v.get("latitude")
            lon = v.get("lon") if v.get("lon") is not None else v.get("longitude")
            if lat is not None and lon is not None:
                try:
                    dmi = _haversine_miles(SSA_LAT, SSA_LON, float(lat), float(lon))
                except Exception:
                    dmi = None

        if dmi is not None and dmi > SSA_VESSEL_RADIUS_MI:
            continue

        label = name if name != "UNKNOWN" else (mmsi or "UNKNOWN")
        dedupe_key = f"sea:{label}"
        if _suppress(dedupe_key):
            continue

        if mesh_compact:
            out.append(f"🚢 {label} {('?' if dmi is None else f'{dmi:.1f}')}mi {spd}kn")
        else:
            out.append(
                "🚢 Vessel nearby\n"
                f"ID: {label}\n"
                f"Speed: {spd} kn\n"
                f"Distance: {('?' if dmi is None else f'{dmi:.1f}')} mi"
            )
    return out

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
        "Aircraft providers (SSA_AIRCRAFT_PROVIDER):\n"
        "  local (recommended)\n"
        "  adsblol (free)\n"
        "  airplaneslive (free)\n"
        "  adsbfi (free/open)\n"
        "  adsbone (free/open)\n"
        "  opensky (limited)\n"
        "  adsbx_rapidapi (paid)\n"
        "\n"
        "Vessels:\n"
        "  local (recommended) -> SSA_AIS_URL\n"
        "  vessels-cloud       -> AISHUB_API_KEY\n"
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

    if mode in ("aircraft-local", "aircraft", "sky_and_sea", "sky_and_sea_local"):
        try:
            ac = _fetch_aircraft_local()
            lines.extend(_aircraft_alert_lines(ac, mesh_compact))
        except Exception as e:
            had_error = True
            lines.append("⚠️ Aircraft local fetch error" if mesh_compact else f"⚠️ Aircraft local error: {e}")

    if mode in ("aircraft-cloud",):
        try:
            ac = _fetch_aircraft()
            lines.extend(_aircraft_alert_lines(ac, mesh_compact))
        except Exception as e:
            had_error = True
            lines.append("⚠️ Aircraft cloud fetch error" if mesh_compact else f"⚠️ Aircraft cloud error: {e}")

    if mode in ("vessels-local", "vessels", "sky_and_sea", "sky_and_sea_local"):
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

def main() -> int:
    mode = SSA_MODE
    if mode in ("sky+sea", "sky-sea", "local", "default"):
        mode = "sky_and_sea"
    if mode in ("aircraft_only", "sky"):
        mode = "aircraft-local"
    if mode in ("vessels_only", "sea"):
        mode = "vessels-local"
    if mode in ("aircraft_cloud", "sky_cloud"):
        mode = "aircraft-cloud"

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
            lines = _single_shot("aircraft-local", mesh_compact)
        elif arg == "sea":
            lines = _single_shot("vessels-local", mesh_compact)
        else:
            lines = _single_shot(mode, mesh_compact)

        joined = " | ".join([l.strip() for l in lines if l.strip()])
        _mm_out(joined if joined else "⏸ No data")
        return 0

    _status(f"🟢 Sky and Sea Alert started ({SSA_VERSION})")
    _status(f"Mode: {mode}")
    _status(f"Location: {SSA_LAT}, {SSA_LON}")
    _status(f"Aircraft provider: {SSA_AIRCRAFT_PROVIDER}")
    _status(f"ADS-B local: {SSA_ADSB_URL}")
    _status(f"AIS local: {SSA_AIS_URL or '(not set)'}")
    _status(f"MQTT: {'enabled' if _mqtt_enabled() else 'disabled'}")
    _status(f"Polling every {max(1, SSA_POLL_INTERVAL)}s")

    if mode == "demo":
        for line in _single_shot("demo", mesh_compact=False):
            _emit_event("demo", line)
        return 0

    if mode in ("aircraft-local", "sky_and_sea") and not SSA_ADSB_URL:
        _status("⚠️ SSA_ADSB_URL not set; aircraft-local will not work")
    if mode in ("vessels-local", "sky_and_sea") and not SSA_AIS_URL:
        _status("⚠️ SSA_AIS_URL not set; vessels-local will not work (set SSA_AIS_URL or use vessels-cloud)")

    if mode == "aircraft-cloud" and SSA_AIRCRAFT_PROVIDER in ("adsbx_rapidapi", "rapidapi", "adsbx", "adsbexchange") and not ADSBX_API_KEY:
        _status("🔑 Missing ADSBX_API_KEY (RapidAPI key) for adsbx_rapidapi provider")
    if mode == "vessels-cloud" and not AISHUB_API_KEY:
        _status("🔑 Missing AISHUB_API_KEY (AIS Hub username) for vessels-cloud")

    while True:
        _status("🔄 Checking sky and sea traffic…")
        lines = _single_shot(mode, mesh_compact=False)

        for line in lines:
            if line.startswith(("⚠️", "🔑", "⏸", "🟢", "✅")):
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
