# PRD — KisanLink AI

## 1. Summary
KisanLink AI is an agricultural market-linkage and price-discovery platform (SIH26132) that recommends the market or buyer offering a farmer the highest **expected net return** for their produce — not simply the highest listed price.

**Tagline:** "The right market. The right price. The right decision."

## 2. Problem Statement
Farmers often don't know where to sell produce for the best actual return. Prices fluctuate across markets, transportation cost varies by distance and vehicle, demand shifts, and farmers frequently rely on intermediaries for price information. Showing raw mandi prices is not enough — a market with a higher price can still leave the farmer worse off once transport cost is subtracted.

**Example:** A farmer has 500 kg of tomatoes. Market B has the highest price, but Market C gives the highest net return once transport cost is factored in. KisanLink solves this comparison automatically.

## 3. Users
- **Primary: Farmers** — need a simple way to decide where to sell.
- **Secondary: Buyers** — post produce requirements to source directly from farmers.
- **Tertiary: Government/Agricultural authorities** — need regional market intelligence (surplus/shortage, demand trends) to plan interventions.

## 4. Goals
- Help a farmer decide, in under a minute, which market maximizes net return for a given crop/quantity/location.
- Reduce farmer dependence on intermediaries via a verified buyer marketplace.
- Give authorities visibility into regional supply-demand imbalances.

## 5. Non-Goals (out of scope for MVP)
- Live web scraping of unofficial price sources (use official APIs/datasets instead).
- Payments/escrow between farmer and buyer.
- Logistics booking automation (tracked as a future feature).

## 6. Key Features

### MVP (must build first)
- Farmer login (mobile number / farmer ID)
- Add produce: crop, quantity, location, harvest date, quality/grade
- 5–10 seeded sample markets with price data
- Transportation cost calculation (distance × vehicle × quantity)
- Net-return calculation: `Revenue − Transport Cost − Other Costs`
- Market ranking (🥇🥈🥉) with expected net return
- Market detail view (price, distance, transport cost, demand, expected profit)
- Interactive market map
- Price trend graph (last 30 days)
- Basic admin dashboard (market overview, crop prices)

### Post-MVP
- AI price prediction (Random Forest / XGBoost / time-series)
- Demand prediction (High / Medium / Low)
- Buyer marketplace (buyers post requirements; farmers view/connect)
- Price anomaly detection (flag outlier prices)
- Smart alerts (price change, selling opportunity, demand drop)
- Government dashboard: regional surplus/shortage detection
- Future: smart logistics / vehicle matching

## 7. Core Differentiator
> "Existing systems primarily provide market information. KisanLink converts that information into a personalized selling decision by estimating the farmer's actual net return across multiple markets."

Price ≠ Profit. A market offering ₹30/kg isn't necessarily better than one offering ₹27/kg once transport, demand, and trend are considered.

## 8. Success Metrics
- Recommendation accuracy: net-return ranking matches or beats naive highest-price choice in backtests.
- Time-to-decision: farmer gets a ranked recommendation in a single flow (< 5 taps).
- Data confidence: every price data point carries a confidence score; anomalies are flagged, not silently trusted.
- Adoption proxy (demo/judging): a judge can go from "enter produce" to "see best market" in the live demo in under 60 seconds.

## 9. Data Sources (priority order)
1. Government/APMC open data (e.g., Agmarknet, data.gov.in) — primary.
2. Verified buyer-submitted requirements — real demand signal.
3. Farmer-submitted prices — crowdsourced, validated, given a confidence score before use.
4. Historical price archive — for trend modeling.

## 10. One-Sentence Pitch
"KisanLink helps farmers decide where to sell their produce by comparing market prices, predicted trends, demand, and transportation costs to recommend the market that can provide the highest expected net return."
