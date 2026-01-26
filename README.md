<p align="center">
  <a href="https://www.python.org/">
    <img src="https://img.shields.io/badge/Python-3.8%2B-blue" alt="Python Version">
  </a>
  <a href="https://opensource.org/licenses/MIT">
    <img src="https://img.shields.io/badge/License-MIT-green" alt="License">
  </a>
</p>

# ✈️ 🛥️ Sky and Sea Alert

**Sky and Sea Alert** is a lightweight Python [**MeshMonitor**](https://github.com/Yeraze/MeshMonitor) script that provides **aircraft overhead** and **vessel nearby** alerts for a configured latitude/longitude using **free public data APIs**.

No SDRs.  
No radios.  
No hardware required.

This project is intentionally **KISS**.

---

## This repository contains

- `sky_and_sea_alert.py` — the runtime Python script
- `README.md` — setup and usage instructions

---

## What this does

Sky and Sea Alert monitors activity around your location and prints human-readable alerts with emojis.

It supports **THREE modes**:

1) **Aircraft only**
   - Alerts when aircraft pass within a configured radius
   - Uses ADS-B Exchange (free API key)

2) **Vessels only**
   - Alerts when vessels pass within a configured radius
   - Uses AIS Hub (free API key)

3) **Sky + Sea**
   - Aircraft **and** vessel alerts together
   - Independent alert logic with shared deduplication

Design goals:

- KISS configuration (lat / lon + radius)
- Emoji-based alerts that are easy to read
- Status messages so you always know what the script is doing
- No scraping, no shared API keys, no ToS violations

---

## Repository layout

    .
    ├── sky_and_sea_alert.py   # Runtime script
    └── README.md              # Documentation

---

## IMPORTANT: Which file do I use?

### Use this file

    sky_and_sea_alert.py

This is the only file you need to run.

---

## Requirements

- Python 3.8+
- Internet connection
- Free API keys (see below)

No Docker.  
No pip installs required beyond `requests`.

---

## Setup — REQUIRED

### Step 1: Get free API keys

Each user **must use their own API keys**.  
This is normal, free, and required for reliability.

---

### ✈️ Aircraft data — ADS-B Exchange

1. Visit: https://www.adsbexchange.com/data/
2. Create a free account
3. Generate an API key
4. Copy the key

---

### 🛥️ Vessel data — AIS Hub

1. Visit: https://www.aishub.net/
2. Create a free account
3. Request an API key
4. Wait for approval (usually quick)
5. Copy the key

---

## Step 2: Configure environment variables

Example (Linux / macOS):

    export SSA_MODE=sky_and_sea
    export SSA_LAT=25.7816
    export SSA_LON=-80.2220

    export SSA_AIRCRAFT_RADIUS_MI=10
    export SSA_VESSEL_RADIUS_MI=3

    export SSA_POLL_INTERVAL=60
    export SSA_SUPPRESS_MINUTES=15

    export ADSBX_API_KEY=your_adsbx_key_here
    export AISHUB_API_KEY=your_aishub_key_here

### Mode options

    aircraft
    vessels
    sky_and_sea

---

## Step 3: Run

    python sky_and_sea_alert.py

---

## Example alerts

Aircraft:

    ✈️ Aircraft overhead
    Callsign: AAL123
    Altitude: 9200 ft
    Distance: 6.1 mi

Vessel:

    🚢 Vessel nearby
    Name: MSC Aurora
    Speed: 12.4 kn
    Distance: 2.3 mi

---

## Status messages

Sky and Sea Alert prints status messages so you always know what’s happening:

- Startup confirmation
- Active mode
- Missing API keys
- API errors (non-fatal)
- Idle checks when nothing is nearby

Examples:

    🟢 Sky and Sea Alert started
    🔄 Checking sky and sea traffic…
    ⏸ No aircraft or vessels in range
    🔑 API key missing

---

## Deduplication (no spam)

- Alerts are fingerprinted per aircraft or vessel
- Repeat alerts are suppressed for a configurable time window
- Default suppression: 15 minutes

This keeps output clean and useful.

---

## Configuration summary

Required:
- `SSA_LAT`
- `SSA_LON`
- `SSA_MODE`

Optional:
- `SSA_AIRCRAFT_RADIUS_MI`
- `SSA_VESSEL_RADIUS_MI`
- `SSA_POLL_INTERVAL`
- `SSA_SUPPRESS_MINUTES`

Required per mode:
- Aircraft: `ADSBX_API_KEY`
- Vessels: `AISHUB_API_KEY`

---

## Common setup issues

### “Nothing happens”

- Verify latitude / longitude
- Increase radius
- Confirm API keys are set
- Check internet connectivity

### “API key missing”

- Ensure the environment variable is exported
- Restart your shell/session
- Keys are required — the script will not guess or share keys

---

## Roadmap (future)

- Demo mode (no keys, sample alerts)
- Webhook output
- MeshMonitor Auto Responder integration
- MQTT / radio output

These are **not included in v1.0.0**.

---

## License

MIT License

---

## Acknowledgments

* MeshMonitor built by [Yeraze](https://github.com/Yeraze) 
* Shout out to [ADS-B Exchange](https://www.adsbexchange.com)
* Shout out to [AIS Hub](https://www.aishub.net)

Discover other community-contributed Auto Responder scripts for MeshMonitor [here](https://meshmonitor.org/user-scripts.html).
