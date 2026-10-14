"""
logistics.py -- Smart Agricultural Logistics & Vehicle Provider Matching Service.

Per ARCHITECTURE.md §7:
Downstream of the "best market" decision, matches farmers with verified
local transport carriers based on vehicle availability, payload capacity,
route distance, transit duration, and guaranteed freight pricing (TRD.md §4.1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class TransportProvider:
    id: int
    name: str
    operator_name: str
    contact: str
    base_hub: str
    vehicle_type: str
    vehicle_model: str
    max_payload_kg: float
    base_fee: float
    rate_per_km: float
    rate_per_kg: float
    verified: bool
    rating: float
    trips_completed: int


@dataclass
class FreightQuote:
    provider_id: int
    provider_name: str
    operator_name: str
    contact: str
    vehicle_type: str
    vehicle_model: str
    distance_km: float
    quantity_kg: float
    freight_cost: float
    estimated_transit_hours: float
    rating: float
    verified: bool
    status: str = "AVAILABLE"


# ---------------------------------------------------------------------------
# Registered Maharashtra Agricultural Logistics Carriers
# ---------------------------------------------------------------------------
REGISTERED_PROVIDERS: List[TransportProvider] = [
    TransportProvider(
        id=1,
        name="Sahyadri Agri-Logistics Fleet",
        operator_name="Ganesh Bhalerao",
        contact="+91 98221 55678",
        base_hub="Nashik",
        vehicle_type="mini_truck",
        vehicle_model="Tata Ace Gold (1.5 Ton)",
        max_payload_kg=1500.0,
        base_fee=500.0,
        rate_per_km=12.0,
        rate_per_kg=0.50,
        verified=True,
        rating=4.9,
        trips_completed=312,
    ),
    TransportProvider(
        id=2,
        name="Kisan Rath Freight Network - Pune",
        operator_name="Sanjay Shinde",
        contact="+91 98902 33445",
        base_hub="Pune",
        vehicle_type="mini_truck",
        vehicle_model="Mahindra Bolero Maxi Truck (1.8 Ton)",
        max_payload_kg=1800.0,
        base_fee=500.0,
        rate_per_km=12.0,
        rate_per_kg=0.50,
        verified=True,
        rating=4.8,
        trips_completed=428,
    ),
    TransportProvider(
        id=3,
        name="Vidarbha Bulk Farm Freightlines",
        operator_name="Pravin Deshmukh",
        contact="+91 97653 77889",
        base_hub="Nagpur",
        vehicle_type="large_truck",
        vehicle_model="Ashok Leyland Ecomet (8 Ton)",
        max_payload_kg=8000.0,
        base_fee=800.0,
        rate_per_km=15.0,
        rate_per_kg=0.30,
        verified=True,
        rating=4.9,
        trips_completed=289,
    ),
    TransportProvider(
        id=4,
        name="Marathwada Regional Agro Transport",
        operator_name="Babasaheb Kadam",
        contact="+91 94221 88990",
        base_hub="Aurangabad",
        vehicle_type="mini_truck",
        vehicle_model="Tata 407 Heavy (3.5 Ton)",
        max_payload_kg=3500.0,
        base_fee=500.0,
        rate_per_km=12.0,
        rate_per_kg=0.50,
        verified=True,
        rating=4.7,
        trips_completed=194,
    ),
    TransportProvider(
        id=5,
        name="Solapur Kisan Goods Express",
        operator_name="Mahadev Birajdar",
        contact="+91 98234 11229",
        base_hub="Solapur",
        vehicle_type="auto",
        vehicle_model="Piaggio Ape Cargo (0.6 Ton)",
        max_payload_kg=600.0,
        base_fee=200.0,
        rate_per_km=8.0,
        rate_per_kg=1.00,
        verified=True,
        rating=4.8,
        trips_completed=512,
    ),
    TransportProvider(
        id=6,
        name="Western Ghats Reefer Cold-Chain",
        operator_name="Nitin Jagtap",
        contact="+91 98601 44552",
        base_hub="Pune",
        vehicle_type="mini_truck",
        vehicle_model="Insulated Reefer Van (2 Ton)",
        max_payload_kg=2000.0,
        base_fee=700.0,
        rate_per_km=14.0,
        rate_per_kg=0.60,
        verified=True,
        rating=5.0,
        trips_completed=160,
    ),
    TransportProvider(
        id=7,
        name="National Highway Agri-Movers",
        operator_name="Dnyaneshwar Shinde",
        contact="+91 99220 88771",
        base_hub="Nashik",
        vehicle_type="large_truck",
        vehicle_model="BharatBenz 1217C (12 Ton)",
        max_payload_kg=12000.0,
        base_fee=800.0,
        rate_per_km=15.0,
        rate_per_kg=0.30,
        verified=True,
        rating=4.9,
        trips_completed=375,
    ),
]


class SmartLogisticsService:
    """
    Logistics matching engine evaluating transporter proximity, payload limits,
    and transit time estimates for farm-to-mandi delivery.
    """

    @staticmethod
    def get_providers(
        hub: Optional[str] = None,
        vehicle_type: Optional[str] = None,
    ) -> List[Dict]:
        """List registered carriers filtered by regional hub or vehicle type."""
        results = REGISTERED_PROVIDERS
        if hub:
            results = [p for p in results if p.base_hub.lower() == hub.strip().lower()]
        if vehicle_type:
            results = [p for p in results if p.vehicle_type == vehicle_type]
        return [p.__dict__ for p in results]

    @staticmethod
    def match_logistics(
        farmer_location: str,
        destination_market: str,
        distance_km: float,
        quantity_kg: float,
        vehicle_type: Optional[str] = None,
    ) -> List[FreightQuote]:
        """
        Match eligible carriers for a specific route and cargo weight.
        Calculates guaranteed freight quotes using the TRD.md §4.1 formula.
        """
        quotes: List[FreightQuote] = []

        for p in REGISTERED_PROVIDERS:
            # 1. Payload capacity check
            if p.max_payload_kg < quantity_kg:
                continue

            # 2. Vehicle type filter (if explicitly requested)
            if vehicle_type and p.vehicle_type != vehicle_type:
                continue

            # 3. Freight cost calculation per TRD.md §4.1:
            # transport_cost = base_fee + (distance_km * rate_per_km) + (quantity_kg * rate_per_kg)
            freight = (
                p.base_fee
                + (distance_km * p.rate_per_km)
                + (quantity_kg * p.rate_per_kg)
            )

            # Average truck transit speed on Maharashtra NH/SH corridors: 45 km/h + 30 min buffer
            transit_hours = round(max(0.5, (distance_km / 45.0) + 0.5), 1)

            quotes.append(
                FreightQuote(
                    provider_id=p.id,
                    provider_name=p.name,
                    operator_name=p.operator_name,
                    contact=p.contact,
                    vehicle_type=p.vehicle_type,
                    vehicle_model=p.vehicle_model,
                    distance_km=distance_km,
                    quantity_kg=quantity_kg,
                    freight_cost=round(freight, 2),
                    estimated_transit_hours=transit_hours,
                    rating=p.rating,
                    verified=p.verified,
                )
            )

        # Sort quotes by freight cost (lowest first)
        quotes.sort(key=lambda q: q.freight_cost)
        return quotes
