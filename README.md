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

It is designed to run **standalone** or as a **MeshMonitor Auto Responder**, with MeshMonitor handling **Meshtastic, webhooks, routing, and delivery**.

No SDRs.  
No radios.  
No hardware required.

---

## This repository contains

- `sky_and_sea_alert.py` — runtime Python script
- `README.md` — documentation

---

## What this does

Sky and Sea Alert detects nearby aircraft and vessels and emits **compact, emoji-based alerts**.

It supports **FOUR modes** (v1.1.0):

1) **Aircraft only**
   - ADS-B Exchange
   - Requires ADSBX API key

2) **Vessels only**
   - AIS Hub
   - Requires AIS Hub API key

3) **Sky + Sea**
   - Aircraft and vessels together

4) **Demo mode**
   - No API keys
   - Sample alerts
   - Single-shot (no loop)

Design goals:

- KISS configuration (lat / lon + radius)
- Clean, radio-friendly output
- Built-in deduplication (no spam)
- MeshMonitor-first integration
- Clear status messaging

---

## Repository layout

    .
    ├── sky_and_sea_alert.py   # Runtime script
    └── README.md              # Documentation

---

## IMPORTANT: Which file do I use?

### Use this file

    sky_and_sea_alert.py

This is the only file you run or install in MeshMonitor.

---

## Requirements

- Python 3.8+
- Internet connection
- Free API keys (except demo mode)

No Docker required.  
No pip installs required beyond `requests` (standard library + urllib is used internally).

---

## API Keys (Required for live data)

Each user **must use their own free API keys**.

---

### ✈️ Aircraft — ADS-B Exchange

1. Visit https://www.adsbexchange.com/data/
2. Create a free account
3. Generate an API key
4. Copy the key

---

### 🛥️ Vessels — AIS Hub

1. Visit https://www.aishub.net/
2. Create a free account
3. Request an API key
4. Wait for approval (usually quick)
5. Copy the key

---

## Configuration (Environment Variables)

### Core

    SSA_MODE=sky_and_sea        # aircraft | vessels | sky_and_sea | demo
    SSA_LAT=25.7816
    SSA_LON=-80.2220

    SSA_AIRCRAFT_RADIUS_MI=10
    SSA_VESSEL_RADIUS_MI=3

    SSA_POLL_INTERVAL=60
    SSA_SUPPRESS_MINUTES=15

    ADSBX_API_KEY=your_adsbx_key_here
    AISHUB_API_KEY=your_aishub_key_here

---

## Running Standalone

    python sky_and_sea_alert.py

Standalone mode:
- Prints status and alerts to console
- Optional MQTT output (see below)
- Continuous polling unless in demo mode

---

## Demo Mode (No Keys)

Demo mode verifies installation and output formatting.

    export SSA_MODE=demo
    python sky_and_sea_alert.py

Behavior:
- No API calls
- Sample ✈️ and 🛥️ alerts
- Exits immediately

---

## MeshMonitor Auto Responder Integration (v1.1.0)

Sky and Sea Alert is fully compatible with **MeshMonitor Auto Responder scripting**.

### Script Metadata (mm_meta)

The script includes `mm_meta` in the first 1 KB for clean UI display:

- Name
- Emoji
- Language

Reference:  
https://meshmonitor.org/developers/auto-responder-scripting.html#script-metadata-mm-meta

---

### Installing into MeshMonitor

Copy the script into the container:

    /data/scripts/sky_and_sea_alert.py

Make it executable:

    chmod +x /data/scripts/sky_and_sea_alert.py

---

### MeshMonitor Commands

Sky and Sea Alert responds to the following triggers:

    !ssa
    !ssa sky
    !ssa sea
    !ssa demo
    !ssa help

Behavior:
- Single-shot execution
- Outputs valid JSON:
  
      { "response": "✈️ AAL123 6.1mi 9200ft" }

MeshMonitor handles:
- Meshtastic delivery
- Webhooks
- Routing
- Channels
- Retries

The script **does not transmit on radios directly**.

---

## Example Alerts

Aircraft:

    ✈️ AAL123 6.1mi 9200ft

Vessel:

    🚢 MSC Aurora 2.3mi 12.4kn

Idle:

    ⏸ No aircraft or vessels in range

---

## Deduplication (No Spam)

- Alerts are fingerprinted per aircraft or vessel
- Repeats suppressed for `SSA_SUPPRESS_MINUTES`
- Default: 15 minutes

---

## MQTT Output (Optional, Standalone Only)

MQTT is **optional** and **not required** for MeshMonitor or Meshtastic.

Used for:
- Node-RED
- Dashboards
- External automation

### MQTT Variables

    SSA_MQTT_HOST
    SSA_MQTT_PORT=1883
    SSA_MQTT_TOPIC=sky-and-sea-alert/events
    SSA_MQTT_USERNAME
    SSA_MQTT_PASSWORD
    SSA_MQTT_TLS=0
    SSA_MQTT_ALLOW_IN_MESHMONITOR=0

MQTT uses `mosquitto_pub` if available.

---

## Correct Data Flow

### MeshMonitor + Meshtastic (Primary)

    Sky and Sea Alert
            ↓
        MeshMonitor
            ↓
        Meshtastic
            ↓
        LoRa / Mesh radios

### Standalone (Optional)

    Sky and Sea Alert
            ↓
        Console / MQTT

---

## Roadmap

- Enhanced alert classification
- Persistent state (optional)
- Additional providers
- Packaging under MaXHyM-Scripts

---

## License

MIT License

---

## Acknowledgments

* MeshMonitor built by [Yeraze](https://github.com/Yeraze) 
* Shout out to [ADS-B Exchange](https://www.adsbexchange.com)
* Shout out to [AIS Hub](https://www.aishub.net)

Discover other community-contributed Auto Responder scripts for MeshMonitor [here](https://meshmonitor.org/user-scripts.html).
