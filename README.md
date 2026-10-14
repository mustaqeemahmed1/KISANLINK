# 🌿 KisanLink AI — Smart Agricultural Market Linkage & Net Return Platform

> **SIH26132 Problem Statement Solution**  
> *"The Right Market. The Right Price. The Right Selling Decision."*

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![Leaflet](https://img.shields.io/badge/Leaflet-1.9.4-199900.svg)](https://leafletjs.com/)
[![Tests](https://img.shields.io/badge/tests-64%20passed-brightgreen.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)]()

---

## 📌 Executive Summary

**KisanLink AI** is an intelligent agricultural market-linkage platform that solves the fundamental dilemma Indian farmers face after every harvest: **where to sell produce to maximize actual take-home profit**.

Most agricultural tools simply display listed APMC mandi prices. However, **Price ≠ Profit**. A mandi offering ₹30/kg 85 km away can easily yield less money in a farmer's pocket than a nearby mandi offering ₹27/kg once transport fuel, vehicle hiring fees, loading, and mandi cess are deducted.

KisanLink AI converts raw mandi data and buyer requirements into a personalized, mathematically optimized decision by ranking candidate markets by **expected net return**:

$$\text{Expected Net Return} = (\text{Predicted Price/kg} \times \text{Quantity kg}) - \text{Transport Cost} - \text{Mandi \& Handling Fees}$$

---

## 🚀 Key Features & Capabilities

### 1. 🌾 Smart Produce Recommender (Core Engine)
- **Instant Net Return Ranking:** Evaluates candidate APMC markets and ranks them (🥇 **#1 Best Return**, 🥈 **#2**, 🥉 **#3**).
- **Price vs. Profit Differentiator:** Highlights when the highest listed price mandi is *not* the highest net return mandi due to transport overhead.
- **Interactive 2D Geographic Map:** Powered by Leaflet OpenStreetMap, displaying the farmer's origin, candidate APMC locations, transport routes, and net return summary popups.
- **Historical Price Trends:** SVG price trend charts showing 30-day modal price trajectory and AI price forecasts.

### 2. 📜 Produce Submissions & Official Deal Sheets
- **Submission History:** Logs evaluated produce batches, vehicle types, and recommended APMCs.
- **Formal Deal Sheet Generation:** Generates printable, auditable agricultural deal sheets (`/produce/{id}/deal-sheet`) detailing cost breakdowns, logistics estimates, and expected net profit.

### 3. 🏢 Direct Wholesale Buyer Marketplace
- **Middleman Disintermediation:** Connects farmers directly with food processors, supermarkets, and certified agricultural aggregators.
- **Filtered Requirements:** Search active purchase orders by crop and region with explicit purchase prices and delivery terms.

### 4. 🚚 Smart Logistics Fleet Directory
- **Carrier Matchmaking:** Calibrated transport quotes for 2-wheelers, pickup vans, mini-trucks, and heavy multi-axle trucks.
- **Transparent Distance & Fuel Rates:** Calculates hauling costs based on verified road distances and commodity payloads.

### 5. 📢 Crowdsourced Mandi Price Reporting
- **Peer Verification:** Farmers submit local spot prices observed at APMC yards.
- **Provenance & Confidence Scoring:** Every price data point carries an explicit `source` and `confidence_score` (0.0 to 1.0) to prevent unverified data contamination.

### 6. 🗺️ APMC Markets Directory
- **Regional Mandi Coverage:** Complete profiles of Maharashtra APMC hubs (Pune, Nashik, Aurangabad, Nagpur, Solapur) with current modal prices, commodity arrivals, and coordinates.

### 7. 🏛️ Regional Agricultural Admin Intelligence
- **Supply-Demand Intelligence:** Detects regional commodity surpluses and shortages to alert state agricultural authorities.
- **Price Anomaly Radar:** Statistical outlier detection flagging unusual mandi price spikes or dumps (>2 standard deviations).
- **Official Agmarknet Daily Sync:** Ingests live data from the Government of India open data platform (`data.gov.in`, Agmarknet Resource ID `9ef84268-d588-465a-a308-a864a43d0070`).

---

## 🛠️ Technology Stack

| Layer | Technologies | Description |
| :--- | :--- | :--- |
| **Backend** | Python 3.10+, FastAPI, Pydantic v2, Uvicorn | High-performance RESTful API service with automated OpenAPI Swagger documentation. |
| **Data Layer** | SQLite (default demo) / PostgreSQL | Relational datastore for market prices, arrival volumes, buyer orders, and submission logs. |
| **AI / ML** | Scikit-Learn, NumPy, Pandas | Random Forest price forecasting, arrival volume demand classification, and price anomaly detection. |
| **Frontend** | HTML5, Modern CSS, Vanilla JavaScript, Leaflet.js | Zero-build, lightweight, responsive Single Page Application with interactive 2D OpenStreetMap. |
| **External Feeds**| OGD India (`data.gov.in`) | Official Agmarknet daily price and arrival feeds with offline benchmark fallback. |

---

## 📂 Repository Structure

```
KisanLink/
├── backend/                        # FastAPI REST API & Core Engine
│   ├── main.py                     # API routing, CORS, and endpoint definitions
│   ├── recommender.py              # Core Net-Return formula & ranking logic
│   ├── ml_service.py               # AI price prediction & anomaly detection
│   ├── ingestion.py                # Agmarknet / data.gov.in synchronization service
│   ├── logistics.py                # Transport provider directory & rate calculator
│   ├── deal_sheet.py               # Printable transaction deal sheet generator
│   ├── alerts.py                   # Smart price alerts & buyer opportunity engine
│   ├── db.py                       # Database connection & schema migration
│   ├── seed.py                     # Initial seeding for markets, buyers & prices
│   ├── postgres_migrate.py         # SQLite to PostgreSQL migration utility
│   └── tests/                      # Comprehensive test suite (64 unit tests)
│       ├── test_recommender.py
│       ├── test_phase2_apis.py
│       ├── test_logistics_and_deal_sheet.py
│       ├── test_ml_models.py
│       └── ...
├── data/                           # Authentic agricultural benchmark datasets
│   ├── agmarknet_real_prices.csv   # Calibrated Maharashtra APMC daily price history
│   └── kisanlink.db                # SQLite database (auto-generated on first run)
├── frontend/                       # Web Single Page Application
│   └── index.html                  # Responsive UI with 2D Leaflet OpenStreetMap
├── AGENTS.md                       # Coding conventions & architecture guardrails
├── ARCHITECTURE.md                 # System diagrams, data flow & component contracts
├── DECISIONS.md                    # Architecture Decision Records (ADR log)
├── PRD.md                          # Product Requirements Document
├── TRD.md                          # Technical Requirements Document
├── requirements.txt                # Python dependencies
├── run.py                          # 1-command startup launcher
└── run.bat                         # Windows quick-launch script
```

---

## ⚡ Quick Start Guide

### Option 1: 1-Click Launch (Windows)
Double-click `run.bat` in the project root:
```bat
run.bat
```
*This activates the virtual environment, launches the FastAPI server on port 8000, and automatically opens your browser to `http://localhost:8000`.*

---

### Option 2: Command Line (Cross-Platform)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/mustaqeemahmed1/KISANLINK.git
   cd KISANLINK
   ```

2. **Create and activate a virtual environment:**
   ```bash
   # Windows (PowerShell)
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1

   # Linux / macOS
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Launch the platform:**
   ```bash
   python run.py
   ```

5. **Open in browser:**
   - Web Application: **[http://localhost:8000](http://localhost:8000)**
   - Interactive Swagger API Docs: **[http://localhost:8000/docs](http://localhost:8000/docs)**
   - Alternative ReDoc: **[http://localhost:8000/redoc](http://localhost:8000/redoc)**

---

## ⚙️ Environment Variables (Optional)

Create a `.env` file in the project root to configure external services (see [`.env.example`](file:///c:/Users/DELL/OneDrive/Desktop/KisanLink/.env.example)):

```ini
# Server Configuration
PORT=8000
HOST=127.0.0.1

# Database (Default is SQLite; specify PostgreSQL URI for production)
DATABASE_URL=sqlite:///./data/kisanlink.db
# DATABASE_URL=postgresql://user:password@localhost:5432/kisanlink

# Official Government Agmarknet Integration (data.gov.in)
DATA_GOV_IN_API_KEY=your_api_key_here
```

---

## 🧪 Running Unit Tests

The backend includes a comprehensive test suite covering net return math, price predictions, transport calculations, API contracts, and database migrations:

```bash
# Using Python unittest
python -m unittest discover -s backend/tests -p "test_*.py"
```

Expected output:
```text
Ran 64 tests in 0.465s

OK
```

---

## 📐 The Core Formula (Mathematical Specification)

KisanLink AI adheres strictly to the net return formula defined in [AGENTS.md](file:///c:/Users/DELL/OneDrive/Desktop/KisanLink/AGENTS.md) and [TRD.md](file:///c:/Users/DELL/OneDrive/Desktop/KisanLink/TRD.md):

$$\text{Expected Net Return} = (\hat{P}_{\text{mandi}} \times Q) - C_{\text{transport}} - C_{\text{handling}}$$

Where:
- $\hat{P}_{\text{mandi}}$ = AI predicted price per kg at destination mandi
- $Q$ = Total produce quantity in kg
- $C_{\text{transport}} = \text{Base Fee} + (D_{\text{km}} \times R_{\text{km}}) + (Q \times R_{\text{kg}})$
  - $D_{\text{km}}$ = Great-circle Haversine road distance between farm origin and mandi
  - $R_{\text{km}}, R_{\text{kg}}$ = Vehicle-specific hauling rates (e.g., mini truck, pickup, multi-axle)
- $C_{\text{handling}}$ = Mandi cess (typically 1.05% of gross revenue) + unloading fees

---

## 🏛️ Government & SIH Alignment

- **Theme:** Smart Agriculture, Market Linkages & Price Discovery
- **Problem Statement:** SIH26132
- **Data Provenance:** Integrates with official Agmarknet / OGD India APIs to ensure legal, auditable price discovery without screen-scraping.
- **Intervention Ready:** Provides regional surplus/shortage alerts allowing agricultural departments to preemptively reroute supply and stabilize market volatility.

---

## 📄 License

This project is open-source under the [MIT License](LICENSE).
