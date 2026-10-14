# DECISIONS — KisanLink AI

Lightweight architecture decision record (ADR) log. Add a new entry per significant decision; don't edit past entries — supersede them instead.

---

### ADR-001: Optimize for net return, not raw price
**Decision:** The core recommendation is ranked by expected net return (`revenue − transport cost − other costs`), not by listed market price alone.
**Why:** This is the project's core differentiator. Existing tools already show prices; the value-add is turning that into an actual selling decision.
**Status:** Accepted.

---

### ADR-002: Use official/government data sources, not scraping
**Decision:** Primary market data comes from official sources (Agmarknet, data.gov.in) rather than scraping third-party sites.
**Why:** Scraping is fragile, may be blocked or prohibited, and undermines the "trustworthy data" pitch. Official data + a confidence-scoring layer is both safer and a stronger differentiator.
**Status:** Accepted.

---

### ADR-003: Assign confidence scores to all price data
**Decision:** Every price data point (government, farmer-reported, buyer-submitted) carries a source and a confidence score rather than being treated as equally reliable.
**Why:** Farmer-submitted prices are useful but unverified; this lets the system use them without compromising trust, and turns "data trustworthiness" into a visible feature.
**Status:** Accepted.

---

### ADR-004: Start with rule-based AI, upgrade to ML behind a stable interface
**Decision:** Price prediction and demand classification start as simple rule-based/linear-trend logic for the MVP, exposed behind `predict_price()` / `predict_demand()` interfaces, with Random Forest/XGBoost as the upgrade path.
**Why:** Ensures a working end-to-end prototype exists before investing in ML tuning, and avoids the MVP being blocked on model quality.
**Status:** Accepted.

---

### ADR-005: Flutter for frontend, FastAPI for backend
**Decision:** Flutter (single codebase, Android + web) for the client; Python + FastAPI for the backend.
**Why:** Single codebase reduces frontend effort for a hackathon timeline; FastAPI pairs naturally with the Python ML stack (Pandas/Scikit-learn/XGBoost) used for prediction.
**Status:** Accepted.
**Alternatives considered:** React Native (rejected — team more familiar with Flutter for this project); Node backend (rejected — would separate the API layer from the ML stack language).

---

### ADR-006: PostgreSQL over NoSQL for core data
**Decision:** Use PostgreSQL as the primary datastore; Firebase acceptable only as a rapid-prototyping fallback.
**Why:** Price history, market rankings, and buyer/farmer relationships are relational by nature and benefit from SQL joins and constraints.
**Status:** Accepted.

---

### ADR-007: No payments/logistics booking in MVP
**Decision:** Payments between farmer and buyer, and automated logistics booking, are explicitly out of scope for the MVP.
**Why:** Keeps the MVP scoped to the core recommendation loop; logistics matching is tracked as a documented future feature (see ARCHITECTURE.md §7).
**Status:** Accepted.

---

### ADR-008: Web SPA interface and OpenStreetMap Leaflet integration
**Decision:** Provide a zero-dependency responsive Web Single Page Application (HTML5/CSS3/Vanilla JS with Leaflet.js / OpenStreetMap) served directly by FastAPI as the primary interactive client; retain Flutter as the mobile native client roadmap.
**Why:** Enables instant, 1-command startup on any machine without requiring the Flutter SDK or Android toolchain, while delivering interactive geographic mapping, live charts, and real-time net-return simulation directly in any modern browser.
**Status:** Accepted.

---

### ADR-009: Authentic Agmarknet Government Data Ingestion & Dual-Mode API
**Decision:** Ingest authentic Maharashtra APMC daily commodity prices and arrival volumes (`data/agmarknet_real_prices.csv`) with `source='govt_agmarknet_ogd'` and `confidence_score=0.96`. The ingestion engine (`backend/ingestion.py`) operates in dual-mode: consumes live government feeds via `data.gov.in` (Agmarknet Resource ID `9ef84268-d588-465a-a308-a864a43d0070`) when `DATA_GOV_IN_API_KEY` is provided, and automatically falls back to verified calibrated APMC benchmarks when offline.
**Why:** Completely removes synthetic sample data, guarantees statistical integrity across all 5 crops and 5 APMCs, and ensures zero network disruption during presentations.
**Status:** Accepted.

---

### ADR-010: Smart Agricultural Logistics Matching Architecture
**Decision:** Implement carrier fleet discovery and freight calculation service (`backend/logistics.py`) downstream of the net-return recommender (ARCHITECTURE.md §7). Transporters are filtered by payload capacity (`max_payload_kg >= quantity_kg`) and regional hub, with guaranteed quotes calculated strictly using TRD.md §4.1 formula (`freight = base_fee + distance_km * rate_per_km + quantity_kg * rate_per_kg`).
**Why:** Bridges the gap between the optimal market recommendation and physical produce transit, providing guaranteed hauling costs and transit estimates.
**Status:** Accepted.

---

### ADR-011: Downloadable Deal Sheet Certificate Generation
**Decision:** Generate standardized, print-ready A4 HTML/PDF Deal Sheet certificates (`backend/deal_sheet.py`, `GET /produce/{id}/deal-sheet`, `POST /produce/deal-sheet/preview`) featuring the farmer's produce specs, recommended APMC, line-by-line financial net-return audit, official government provenance stamp, and matched carrier assignment.
**Why:** Farmers need a physical or downloadable certificate to present to truck drivers, APMC market commission agents, and wholesale buyer sourcing hubs to lock in terms and prevent margin erosion.
**Status:** Accepted.

---

### ADR-012: Farmer Password Authentication & Profile Management System
**Decision:** Implement secure password-based farmer authentication (`POST /auth/register` and `POST /auth/login`) with salted PBKDF2-HMAC-SHA256 password hashing and a profile management interface (`PUT /farmers/{id}` and `GET /farmers/{id}`). Farmer identity is keyed by a unique 10-digit mobile number, full name, secure password, primary farm region, farm land size (acres), UPI ID for settlements, bio notes, and custom profile photo/avatar. The frontend maintains session state in `localStorage`, renders the farmer's avatar and details in the header, provides a dedicated Profile editing modal with real-time photo compression/preset selection, and guards all personalized operations.
**Why:** Real agricultural operations require secure, credentialed access tied to the specific farmer's verifiable identity, contact number, payment info (UPI), and transaction history rather than artificial hardcoded profiles or unsecured logins.
**Status:** Accepted.

### ADR-013: Dual-Engine PostgreSQL Migration & Transparent Query Adapter
**Decision:** Provide a zero-friction migration path from SQLite to PostgreSQL (`backend/migrate_postgres.py`, `backend/check_db.py`, and `PostgresConnectionWrapper` in `backend/db.py`). The adapter automatically translates `?` placeholders to `%s`, emulates `cursor.lastrowid` via injected `RETURNING id` on inserts, supports `.env` auto-discovery, and permits switching seamlessly between local SQLite and live cloud PostgreSQL instances (Neon, Supabase, RDS) simply by setting `DATABASE_URL`.
**Why:** Production deployments and multi-region scaling require a managed relational engine (PostgreSQL per ADR-006), while development and offline judging benefit from lightweight SQLite without requiring external daemon setup.
**Status:** Accepted.

---

### ADR-014: 3D Spatial Logistics Engine & Authentication Gateway Architecture
**Decision:** Implement a native Three.js 3D spatial interface in `frontend/index.html` consisting of:
1. **Full-Screen 3D Authentication Gateway (`#view-auth-gateway`)**: When unauthenticated, the application displays a dedicated full-screen 3D landing view featuring an interactive Maharashtra agricultural topological node grid, glowing APMC mandis, pulsing transit vectors, floating profit particles, and mouse/gyro parallax. In front is a glassmorphic card supporting credentialed Login, Registration, and a 1-Click Guest Demo / Judge Preview button (`quickDemoLogin()`).
2. **3D Command Center Logistics Map (`#three-logistics-wrapper`)**: In the main dashboard view, provide a seamless toggle between 2D OpenStreetMap (Leaflet) and a 3D Spatial Terrain plate (Three.js). The 3D view renders farmer origin beacons, 3D golden/silver/bronze net-return pedestals with rotating gem polyhedra and sharp billboard sprites, glowing quadratic Bezier transit laser arcs, and an animated 3D mini-truck mesh traversing along the #1 winning route curve. Tooltip raycasting enables interactive 3D APMC metric inspection.
3. **Zero Heavy Build Dependencies**: Powered via Three.js CDN with vanilla JavaScript and CSS, requiring no Node.js or npm compilation steps and remaining 100% runnable via `python run.py`.
**Why:** Elevates user engagement and gives farmers and evaluators an intuitive, high-tech spatial visualization of distance vs. profit trade-offs while maintaining zero-setup portability and fallback support.
**Status:** Accepted.

---

## Template for new entries
```
### ADR-00X: <short title>
**Decision:** <what was decided>
**Why:** <reasoning>
**Status:** Proposed | Accepted | Superseded by ADR-00Y
**Alternatives considered:** <optional>
```
