#!/usr/bin/env python3
"""
Sky and Sea Alert
Simple aircraft and vessel proximity alerts using free public APIs.
"""

import os
import time
import math
import requests
from datetime import datetime

# =========================
# CONFIG (KISS)
# =========================

MODE = os.getenv("SSA_MODE", "sky_and_sea")  
# aircraft | vessels | sky_and_sea

LAT = float(os.getenv("SSA_LAT", "0.0"))
LON = float(os.getenv("SSA_LON", "0.0"))

AIRCRAFT_RADIUS_MI = float(os.getenv("SSA_AIRCRAFT_RADIUS_MI", "10"))
VESSEL_RADIUS_MI   = float(os.getenv("SSA_VESSEL_RADIUS_MI", "3"))

POLL_INTERVAL = int(os.getenv("SSA_POLL_INTERVAL", "60"))
SUPPRESS_MINUTES = int(os.getenv("SSA_SUPPRESS_MINUTES", "15"))

ADSBX_API_KEY = os.getenv("ADSBX_API_KEY")
AISHUB_API_KEY = os.getenv("AISHUB_API_KEY")

last_alerts = {}

# =========================
# HELPERS
# =========================

def miles_between(lat1, lon1, lat2, lon2):
    r = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dl/2)**2
    return r * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))

def suppress(key):
    now = time.time()
    if key in last_alerts and now - last_alerts[key] < SUPPRESS_MINUTES * 60:
        return True
    last_alerts[key] = now
    return False

def status(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} {msg}")

# =========================
# AIRCRAFT
# =========================

def check_aircraft():
    if not ADSBX_API_KEY:
        status("🔑 ADS-B Exchange API key missing")
        return

    url = "https://api.adsbexchange.com/v2/lat/{}/{}/{}".format(
        LAT, LON, AIRCRAFT_RADIUS_MI * 1.609
    )
    headers = {"api-auth": ADSBX_API_KEY}

    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json().get("ac", [])
    except Exception as e:
        status(f"⚠️ Aircraft data error: {e}")
        return

    for ac in data:
        if "lat" not in ac or "lon" not in ac:
            continue

        dist = miles_between(LAT, LON, ac["lat"], ac["lon"])
        if dist > AIRCRAFT_RADIUS_MI:
            continue

        callsign = ac.get("flight", "UNKNOWN").strip()
        alt = ac.get("alt_baro", "?")

        key = f"air-{callsign}"
        if suppress(key):
            continue

        print(f"""
✈️ Aircraft overhead
Callsign: {callsign}
Altitude: {alt} ft
Distance: {dist:.1f} mi
""")

# =========================
# VESSELS
# =========================

def check_vessels():
    if not AISHUB_API_KEY:
        status("🔑 AIS Hub API key missing")
        return

    url = (
        "https://data.aishub.net/ws.php"
        f"?username={AISHUB_API_KEY}"
        f"&format=1"
        f"&lat={LAT}&lon={LON}"
        f"&radius={VESSEL_RADIUS_MI}"
    )

    try:
        r = requests.get(url, timeout=10)
        data = r.json().get("ships", [])
    except Exception as e:
        status(f"⚠️ Vessel data error: {e}")
        return

    for ship in data:
        name = ship.get("shipname", "UNKNOWN")
        speed = ship.get("speed", "?")
        dist = ship.get("distance", "?")

        key = f"sea-{name}"
        if suppress(key):
            continue

        print(f"""
🚢 Vessel nearby
Name: {name}
Speed: {speed} kn
Distance: {dist} mi
""")

# =========================
# MAIN LOOP
# =========================

status("🟢 Sky and Sea Alert started")
status(f"Mode: {MODE}")
status(f"Location: {LAT}, {LON}")
status(f"Polling every {POLL_INTERVAL}s")

while True:
    status("🔄 Checking sky and sea traffic…")

    if MODE in ("aircraft", "sky_and_sea"):
        check_aircraft()

    if MODE in ("vessels", "sky_and_sea"):
        check_vessels()

    time.sleep(POLL_INTERVAL)
