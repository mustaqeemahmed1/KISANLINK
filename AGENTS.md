# AGENTS.md — KisanLink AI

Instructions for any coding agent (Claude Code, Cursor, etc.) working in this repository.

## Project Context
Read these first, in order:
1. `PRD.md` — what we're building and why
2. `TRD.md` — tech stack, data model, API contracts, core formulas
3. `ARCHITECTURE.md` — system diagram and component responsibilities
4. `DECISIONS.md` — settled decisions; don't relitigate these without flagging why

## Core Rule — Do Not Break This
The recommendation logic must always rank markets by **expected net return**, computed as:
```
expected_net_return = (predicted_price_per_kg * quantity_kg) - transport_cost - other_estimated_costs
```
Never simplify this back to "sort by price." This formula is the product's entire differentiator — treat it as load-bearing.

## Build Order
Follow the MVP scope in `PRD.md` §6 strictly in this order:
1. Database schema + seed data (5–10 mock markets, one crop e.g. tomato)
2. Backend: produce submission + market data + net-return recommendation endpoint
3. Frontend: login → add produce → ranked recommendations → market detail
4. Admin dashboard (basic overview)
5. Only after the above works end-to-end: AI price prediction, demand prediction, buyer marketplace, alerts, anomaly detection

Do not start ML model work before the rule-based version of the same feature works end-to-end (see ADR-004).

## Conventions
- **Backend:** Python, FastAPI, type-annotated. Keep prediction/demand logic behind clear function interfaces (`predict_price(...)`, `predict_demand(...)`) so they can be swapped from rule-based to ML without touching callers.
- **Database:** PostgreSQL. Use the table/column names in `TRD.md` §2 unless there's a strong reason to deviate — note any deviation in `DECISIONS.md`.
- **Frontend:** Flutter. Screens and flow should match `ARCHITECTURE.md` §4–5.
- **Every price data point** must carry `source` and `confidence_score` fields — never store a bare price with no provenance.
- **Tests:** any change to the net-return or transport-cost formulas requires an accompanying unit test.

## When Adding a New Feature
1. Check `PRD.md` — is it in MVP scope or post-MVP? Don't jump ahead without being asked.
2. Check `DECISIONS.md` — has a related decision already been made?
3. If the feature involves a new architectural choice (new service, new data source, new model type), add an ADR entry to `DECISIONS.md` before or alongside the implementation.
4. Update `ARCHITECTURE.md` if the component diagram changes.

## What Not To Do
- Don't add web scraping of third-party price sites (see ADR-002).
- Don't add payments or automated logistics booking (out of scope, see ADR-007).
- Don't hard-code ML model choice into API response shapes — keep prediction outputs (`predicted_price`, `trend`, `demand_level`, `confidence`) stable regardless of which model produces them.
- Don't treat farmer-submitted prices as equally trustworthy as government data — always attach a confidence score.

## Definition of Done (per feature)
- Matches the relevant section of `PRD.md`.
- Has a test for any calculation logic.
- Doesn't regress the core net-return ranking flow (manually verify: submit produce → get a ranked list → top result has the highest net return of the candidates).
