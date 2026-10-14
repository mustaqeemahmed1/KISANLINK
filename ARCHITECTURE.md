# ARCHITECTURE — KisanLink AI

## 1. High-Level Flow

```
                 FARMER APP
                      │
                      ▼
        ┌──────────────────────┐
        │ Farmer Input Layer   │
        │ Crop / Qty / Location│
        └──────────┬───────────┘
                    │
                    ▼
        ┌──────────────────────┐
        │ Market Data Layer     │
        │ Price / Demand /      │
        │ Historical Data       │
        └──────────┬───────────┘
                    │
                    ▼
        ┌──────────────────────┐
        │ AI Prediction Layer   │
        │ Price + Demand models │
        └──────────┬───────────┘
                    │
                    ▼
        ┌──────────────────────┐
        │ Recommendation Engine │
        │ (Net Return Scoring)  │
        └──────────┬───────────┘
                    │
                    ▼
        ┌──────────────────────┐
        │ Net Return Ranking    │
        └──────────┬───────────┘
                    │
                    ▼
             🥇 BEST MARKET
             (+ alternatives)
```

## 2. Data Ingestion Flow

```
Government Data (Agmarknet / data.gov.in)
          │
          ▼
   Scheduled Fetch Job
          │
          ▼
   KisanLink Backend (FastAPI)
          │
          ▼
     PostgreSQL (price_history)
          │
          ▼
  AI + Recommendation Engine
          │
          ▼
       Farmer App
```

Supplementary inputs merge in alongside government data:

```
Farmer Report ──► Validation ──► Confidence Score ──► Used in Recommendation
Buyer Requirement ──► Demand Signal ──► Used in Recommendation
```

## 3. Components

| Component | Responsibility |
|---|---|
| Farmer App (Flutter) | Login, produce entry, view recommendations, map, alerts, buyer marketplace |
| Admin Dashboard (Web) | Market overview, analytics, regional surplus/shortage view |
| Backend API (FastAPI) | Auth, produce submission, market data serving, recommendation orchestration |
| Recommendation Engine | Computes transport cost, net return, ranks markets |
| AI Prediction Service | Price forecasting, demand classification, anomaly detection (pluggable models) |
| Data Ingestion Job | Pulls government market data on a schedule, normalizes into `price_history` |
| Database (PostgreSQL) | Stores farmers, markets, price history, buyers, requirements, reports |

## 4. Screens (Farmer App)
1. Login
2. Dashboard (today's opportunities)
3. Add Produce
4. Market Recommendations (ranked list)
5. Market Details
6. Buyer Marketplace
7. Alerts

## 5. Screens (Admin Dashboard)
- Live Market Overview (totals, active buyers, crop prices, anomalies)
- Map (markets colored by demand/risk)
- Analytics (per-crop price change %, demand level)
- Regional Intelligence (surplus/shortage flags)

## 6. Design Principles
- **Net return over raw price**: every ranking surface must show the net-return number, not just price.
- **Confidence over blind trust**: every price data point carries a source and confidence score; anomalies are flagged, not hidden.
- **Pluggable AI**: prediction and demand-classification logic sit behind a stable interface so rule-based MVP versions can be swapped for ML models without touching the API or frontend.
- **MVP-first**: the ranking pipeline must work end-to-end with seeded/mock data before any ML model is added.

## 7. Smart Agricultural Logistics Matching (Implemented)
```
Farmer → Optimal Market Recommendation → Carrier Matching → Guaranteed Freight Quote
```
Downstream of the best-market decision:
- Transporters are registered with base hub, vehicle model, payload capacity (`max_payload_kg`), base fee, and mileage/weight rates.
- Recommender filters carriers by payload (`capacity >= produce quantity`) and calculates guaranteed freight quotes using the TRD.md §4.1 formula.
- Computes estimated transit duration based on highway corridors (45 km/h average speed + 30m loading buffer).

## 8. Certified Deal Sheet Generator (Implemented)
```
Produce Submission + Optimal APMC + Logistics Carrier → Print-Ready A4 Deal Sheet (HTML/PDF)
```
Generates a formal, printable audit document for the farmer:
- Produces line-by-line financial audit: Gross Revenue, Transport Cost, Mandi & Yard Fees, Expected Net Profit.
- Data Provenance stamp: Government APMC data validation, confidence rating (e.g. 96%), and anomaly-free status.
- Direct 1-click browser print / PDF export (`window.print()`, `@page { size: A4 }`).

## 9. Relational Storage & PostgreSQL Support
Operates in dual-driver mode via `backend/db.py`:
- Connects to PostgreSQL when `DATABASE_URL` or `POSTGRES_URL` is set, with connection pooling and `RealDictCursor`.
- Fallback to SQLite (`backend/kisanlink.db`) with identical table structures and index schemas.
- Full transactional migration tool (`backend/migrate_postgres.py`) for syncing SQLite tables and identity sequences to PostgreSQL.
