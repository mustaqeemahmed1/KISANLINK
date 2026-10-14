# TRD — KisanLink AI

## 1. Tech Stack
| Layer | Choice | Notes |
|---|---|---|
| Frontend | Flutter | Single codebase for Android + web |
| Backend | Python + FastAPI | REST API |
| Database | PostgreSQL (or Firebase for rapid prototyping) | Relational fits price/market/history data well |
| AI/ML | Python — Pandas, Scikit-learn, XGBoost | Start rule-based/linear, swap in ML later |
| Maps | Google Maps / OpenStreetMap | Market map + distance calc |
| Charts | Flutter charts / JS charting lib | Price trend dashboard |

## 2. Data Model (core tables/collections)

**farmers**
`id, name, mobile_number, location (lat/lng), created_at`

**markets**
`id, name, location (lat/lng), region`

**price_history**
`id, market_id, crop, date, min_price, max_price, modal_price, arrival_quantity, source (govt/farmer_report), confidence_score`

**farmer_reports**
`id, farmer_id, crop, market_id (nullable), reported_price, date, validated (bool), confidence_score`

**buyers**
`id, name, verified (bool), location`

**buyer_requirements**
`id, buyer_id, crop, quantity_kg, offered_price, location, pickup_available (bool), posted_at`

**produce_submissions**
`id, farmer_id, crop, quantity_kg, location, harvest_date, quality_grade, submitted_at`

**recommendations** (computed, can be cached)
`id, produce_submission_id, market_id, expected_revenue, transport_cost, expected_net_return, price_trend, demand_level, confidence, rank`

## 3. Core APIs (FastAPI)

- `POST /farmers` — register farmer
- `POST /produce` — submit produce (crop, qty, location, harvest date, grade)
- `GET /markets` — list markets with current prices
- `GET /markets/{id}` — market detail (price, trend, demand, distance from a given location)
- `POST /recommendations` — given a produce submission, return ranked markets by expected net return
- `POST /buyers/requirements` — buyer posts a requirement
- `GET /buyers/requirements?crop=&location=` — farmer views matching buyer requirements
- `POST /farmer-reports` — farmer submits an observed price (goes through validation)
- `GET /admin/overview` — aggregated stats: total markets, active buyers, high-demand crops, anomalies
- `GET /admin/regional` — surplus/shortage signals by region

## 4. Core Computation Logic

### 4.1 Transportation cost
```
transport_cost = f(distance_km, vehicle_type, quantity_kg)
```
Start with a simple linear model: `base_fee + (distance_km * rate_per_km) + (quantity_kg * rate_per_kg)`. Rates configurable per vehicle type.

### 4.2 Net return
```
expected_revenue = predicted_price_per_kg * quantity_kg
expected_net_return = expected_revenue - transport_cost - other_estimated_costs
```

### 4.3 Market score (for ranking, secondary to raw net return)
```
score = w1*price_potential + w2*demand + w3*price_trend + w4*buyer_availability
        - w5*transport_cost - w6*risk
```
Weights configurable; net return is the primary sort key, score can be used as a tiebreaker or confidence signal.

### 4.4 Price prediction (ML)
- Input: historical `price_history` per crop per market.
- Model: start with a simple moving-average/linear trend; upgrade path is Random Forest or XGBoost with features (day-of-week, season, arrival volume, lagged prices).
- Output: predicted price N days ahead + trend label (↑/↓/→).

### 4.5 Demand classification
- Rule-based initial version: bucket by arrival volume vs. historical average (e.g., low arrivals + rising price = High demand).
- Upgrade path: classifier trained on arrival volume, price momentum, buyer requirement volume.

### 4.6 Anomaly detection
- Compute mean/median price across nearby markets for the same crop/date.
- Flag any market whose price deviates beyond a threshold (e.g., >2 standard deviations, or a simple percentage band) as "unusual."

### 4.7 Data confidence scoring
- Government/APMC data: high confidence (e.g., 0.9–1.0).
- Multiple corroborating farmer reports: medium-high confidence.
- Single uncorroborated farmer report: low confidence, shown but flagged.

## 5. Non-Functional Requirements
- Response time: recommendation endpoint should return in <2s for up to ~50 candidate markets.
- Data freshness: government price data refreshed at least daily (batch job).
- Extensibility: AI/ML components must be swappable behind a stable interface (`predict_price()`, `predict_demand()`) so rule-based MVP logic can be replaced without changing API contracts.
- Offline-friendly: farmer app should cache last-fetched recommendations for low-connectivity areas (stretch goal).

## 6. Environments & Ops
- Local dev: SQLite or local Postgres, mocked market data seeds.
- Backend deploy target: any container host (e.g., Render/Fly/Cloud Run) — TBD by team.
- Scheduled job: daily fetch from Agmarknet/data.gov.in into `price_history`.

## 7. Testing Priorities
- Unit tests for net-return and transport-cost calculations (these are the core differentiator — must be correct).
- Integration test: produce submission → recommendation returns a sane, sorted list.
- Anomaly detection test with a synthetic outlier price.
