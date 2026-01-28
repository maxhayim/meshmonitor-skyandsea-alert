<p align="center">
  <a href="https://www.python.org/">
    <img src="https://img.shields.io/badge/Python-3.8%2B-blue" alt="Python Version">
  </a>
  <a href="https://opensource.org/licenses/MIT">
    <img src="https://img.shields.io/badge/License-MIT-green" alt="License">
  </a>
</p>

# ✈️ 🛥️ Sky and Sea Alert

**Sky and Sea Alert** is a lightweight Python [**MeshMonitor**](https://github.com/Yeraze/MeshMonitor) script that provides **aircraft overhead** and **vessel nearby** alerts for a configured latitude/longitude using **your own locally collected data** or **official cloud APIs**.

MeshMonitor handles **Meshtastic, webhooks, routing, and delivery**.  
Sky and Sea Alert focuses purely on **detection, filtering, and alert formatting**.

No scraping.  
No shared API keys.  
No direct radio transmission.

---

## 🚨 Major Release Notice (v2.0.0)

Sky and Sea Alert v2.0.0 introduces a **breaking architectural change**:

- ❌ No longer positioned as “free cloud API” software  
- ✅ Local receivers are now the **primary and recommended data source**  
- ✅ Cloud APIs are **explicitly optional and clearly labeled (paid / rate-limited)**  

This change removes API shutdown risk, ToS ambiguity, and onboarding confusion.

---

## Quick Start (5-minute setup)

### 1) Clone or download

git clone https://github.com/maxhayim/sky-and-sea-alert.git  
cd sky-and-sea-alert

Or download `sky_and_sea_alert.py` directly.

---

### 2) Run demo mode (no hardware, no APIs)

export SSA_MODE=demo  
python sky_and_sea_alert.py

You should immediately see sample ✈️ and 🛥️ alerts.  
This verifies your environment and MeshMonitor formatting.

---

### 3) Set your location

export SSA_LAT=25.7816  
export SSA_LON=-80.2220

---

### 4) Choose your data source (recommended paths below)

- **Free & unlimited** → Local receivers (ADS-B + AIS)
- **Convenience** → Paid / account-based cloud APIs

---

## Supported Data Sources (v2.0.0)

### ✈️ Aircraft (ADS-B)

#### ✅ Recommended: Local ADS-B Receiver (FREE)

- Hardware: RTL-SDR + ADS-B antenna
- Software:
  - dump1090
  - readsb
- Output: local JSON over HTTP

Flow:
ADS-B receiver → dump1090/readsb → Sky and Sea Alert → MeshMonitor → Meshtastic

No API keys.  
No rate limits.  
Real-time data.

---

#### 🌍 Remote Access (NEW)

Local receivers can be accessed securely over the internet using a VPN.

**Recommended VPN:** Tailscale

- No port forwarding
- Encrypted
- Works behind NAT / CGNAT
- Ideal for Raspberry Pi deployments

Example:
Remote Pi (ADS-B) → Tailscale → Sky and Sea Alert → MeshMonitor

---

#### 💲 Optional: ADS-B Exchange (Paid, Cloud)

ADS-B Exchange no longer provides free API access.

**Official low-cost option:**  
https://www.adsbexchange.com/api-lite/

**RapidAPI listing:**  
https://rapidapi.com/adsbx/api/adsbexchange-com1

##### How to get access
1) Create a RapidAPI account  
2) Open the ADS-B Exchange API listing  
3) Choose a pricing plan  
4) Copy your **X-RapidAPI-Key**

##### Environment variable
export ADSBX_API_KEY="YOUR_RAPIDAPI_KEY"

This option is **paid**, **official**, and **supported**, but not required.

---

### 🛥️ Vessels (AIS)

#### ✅ Recommended: Local AIS Receiver (FREE)

- Hardware: RTL-SDR + VHF AIS antenna
- Software:
  - AIS-catcher
  - rtl_ais
- Output: local JSON or NMEA

Flow:
AIS receiver → AIS-catcher → Sky and Sea Alert → MeshMonitor → Meshtastic

---

#### 🌐 Optional: AIS Hub (Account-Based)

**AIS Hub API page:**  
https://www.aishub.net/api

##### How to get access
1) Create an AIS Hub account  
2) Visit the API page above  
3) Use the **AIS API** tab  
4) Your API “key” is your **AIS Hub username**  
5) Observe the documented rate limit (≈1 request/minute)

##### Environment variable
export AISHUB_API_KEY="YOUR_AISHUB_USERNAME"

AIS Hub is free for hobby use but **rate-limited**.

---

## Operating Modes

- demo — sample alerts, no data sources
- aircraft-local — local ADS-B receiver
- vessels-local — local AIS receiver
- sky_and_sea — local ADS-B + local AIS
- aircraft-cloud — ADS-B Exchange API Lite (paid)
- vessels-cloud — AIS Hub (account-based)

---

## Repository layout

    .
    ├── sky_and_sea_alert.py   # Runtime script
    └── README.md              # Documentation

---

## Requirements

- Python 3.8+
- Internet (optional for local-only mode)
- SDR hardware (optional, recommended)

No Docker required.  
No scraping.  
No shared credentials.

---

## Configuration (Environment Variables)

SSA_MODE=sky_and_sea  
SSA_LAT=25.7816  
SSA_LON=-80.2220  

SSA_AIRCRAFT_RADIUS_MI=10  
SSA_VESSEL_RADIUS_MI=3  

SSA_POLL_INTERVAL=60  
SSA_SUPPRESS_MINUTES=15  

Optional (cloud):
ADSBX_API_KEY=your_rapidapi_key  
AISHUB_API_KEY=your_aishub_username  

---

## MeshMonitor Auto Responder Integration

Sky and Sea Alert is fully compatible with MeshMonitor Auto Responder scripting.

### Commands

!ssa  
!ssa sky  
!ssa sea  
!ssa demo  
!ssa help  

### Output

{ "response": "✈️ AAL123 6.1mi 9200ft" }

MeshMonitor handles:
- Meshtastic
- Webhooks
- Routing
- Channels
- Retries

Sky and Sea Alert **never transmits on radios directly**.

---

## Design Goals (v2.0.0)

- Local-first sensing
- Honest cost model
- Community-aligned architecture
- MeshMonitor-first integration
- Secure remote access
- Long-term sustainability

---

## Roadmap

- Receiver health monitoring

---

## License

MIT License

---

## Acknowledgments

* MeshMonitor built by [Yeraze](https://github.com/Yeraze) 
* Shout out to [ADS-B Exchange](https://www.adsbexchange.com)
* Shout out to [AIS Hub](https://www.aishub.net)

Discover other community-contributed Auto Responder scripts for MeshMonitor [here](https://meshmonitor.org/user-scripts.html).
