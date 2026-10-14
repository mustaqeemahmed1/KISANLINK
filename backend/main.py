"""
main.py -- KisanLink FastAPI backend (Phase 2 Full REST Suite).

Implements Core APIs (TRD.md §3):
  - POST /farmers                 Register or retrieve farmer profile (login/upsert)
  - GET  /farmers/{id}            Retrieve farmer profile and stats
  - POST /produce                 Submit produce + persist net-return recommendations
  - GET  /produce/history         Retrieve farmer submission history & stored recommendations
  - POST /recommendations         Instant net-return market ranking
  - GET  /markets                 List all APMC markets with current modal prices
  - GET  /markets/{id}            Market detail with coordinates, price trend, and distance
  - POST /buyers/requirements     Post buyer requirement order (Buyer Marketplace)
  - GET  /buyers/requirements     Browse active buyer requirements by crop/location
  - POST /farmer-reports          Submit crowdsourced mandi price with validation & confidence
  - GET  /farmer-reports          Recent crowdsourced farmer price reports
  - GET  /admin/overview          Aggregated market stats, crop prices, anomaly count
  - GET  /admin/regional          Regional supply-demand analysis (surplus/shortage flags)
"""

from __future__ import annotations

import datetime
import hashlib
import os
import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field, field_validator

# Make backend/ importable from any CWD.
sys.path.insert(0, str(Path(__file__).parent))
from alerts import SmartAlertService
from db import get_connection
from deal_sheet import generate_deal_sheet_html
from ingestion import DataIngestionService
from logistics import REGISTERED_PROVIDERS, SmartLogisticsService, TransportProvider
from ml_service import PriceAnomalyDetector
from recommender import (
    MARKET_DISTANCES_KM,
    calculate_transport_cost,
    get_price_history,
    get_recommendations,
    haversine_km,
    predict_demand,
    predict_price,
)

FRONTEND_INDEX = Path(__file__).parent.parent / "frontend" / "index.html"

# Preset locations (lat, lng)
FARMER_LOCATIONS: dict[str, tuple[float, float]] = {
    "Pune":       (18.5204, 73.8567),
    "Nashik":     (20.0059, 73.7797),
    "Aurangabad": (19.8762, 75.3433),
    "Nagpur":     (21.1458, 79.0882),
    "Solapur":    (17.6868, 75.9064),
}

# Multi-crop catalog
SUPPORTED_CROPS = ["Tomato", "Onion", "Potato", "Soybean", "Wheat"]

# ---------------------------------------------------------------------------
# App setup & Lifespan Handler (Deployment Auto-Init)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure database schema and initial data are ready on container/server boot."""
    try:
        from db import create_tables
        create_tables()
        conn = get_connection()
        try:
            m_row = conn.execute("SELECT COUNT(*) AS total FROM markets").fetchone()
            cnt = m_row["total"] if isinstance(m_row, dict) or (hasattr(m_row, "keys") and "total" in m_row.keys()) else m_row[0]
            if cnt == 0:
                from seed import seed_database
                print("[*] Empty datastore detected on boot. Seeding default market & commodity data...")
                seed_database()
                print("[✓] Datastore automatically seeded for deployment.")
        finally:
            conn.close()
    except Exception as e:
        print(f"[!] Startup initialization notice: {e}")
    yield


app = FastAPI(
    title="KisanLink AI",
    description="Agricultural market-linkage and net-return price discovery API.",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
def serve_index():
    if FRONTEND_INDEX.exists():
        return FileResponse(
            FRONTEND_INDEX,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
                "Clear-Site-Data": '"cache"',
            },
        )
    return {"message": "KisanLink AI API is running. Interactive docs at /docs"}


# ---------------------------------------------------------------------------
# Password & Auth Utilities
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """Generate salted PBKDF2-HMAC-SHA256 hash."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000).hex()
    return f"{salt}${key}"


def verify_password(password: str, hashed: Optional[str]) -> bool:
    """Verify password against stored salt$key hash."""
    if not hashed:
        return True  # Backward compatibility for legacy accounts
    try:
        salt, key = hashed.split("$", 1)
        computed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000).hex()
        return secrets.compare_digest(key, computed)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Pydantic Request / Response Models
# ---------------------------------------------------------------------------

# 1. Farmers
class FarmerCreate(BaseModel):
    name: str = Field(..., min_length=2, example="Ramesh Patil")
    mobile_number: str = Field(..., min_length=10, max_length=15, example="9876543210")
    password: Optional[str] = Field(None, min_length=4, example="kisan123")
    location: str = Field("Pune", example="Pune")
    lat: Optional[float] = None
    lng: Optional[float] = None
    farm_size_acres: Optional[float] = Field(5.0, example=5.0)
    upi_id: Optional[str] = Field(None, example="farmer@oksbi")
    bio: Optional[str] = Field(None, example="Organic vegetable cultivator.")
    profile_pic: Optional[str] = Field(None, description="Base64 or image URL")

    @field_validator("location")
    @classmethod
    def validate_location(cls, v: str) -> str:
        title = v.strip().title()
        return title


class FarmerResponse(BaseModel):
    id: int
    name: str
    mobile_number: str
    location: str
    lat: Optional[float]
    lng: Optional[float]
    farm_size_acres: Optional[float] = 5.0
    upi_id: Optional[str] = None
    bio: Optional[str] = None
    profile_pic: Optional[str] = None
    created_at: str
    submission_count: int = 0


class FarmerLoginRequest(BaseModel):
    mobile_number: str = Field(..., min_length=10, max_length=15, example="9876543210")
    password: Optional[str] = Field(None, example="kisan123")


class FarmerProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    farm_size_acres: Optional[float] = None
    upi_id: Optional[str] = None
    bio: Optional[str] = None
    profile_pic: Optional[str] = None
    password: Optional[str] = None


class AuthResponse(BaseModel):
    farmer: FarmerResponse
    message: str


# 2. Recommendations & Produce
class RecommendationRequest(BaseModel):
    crop: str = Field(..., example="Tomato")
    quantity_kg: float = Field(..., gt=0, example=500.0)
    location: str = Field(..., example="Pune")
    vehicle_type: Literal["mini_truck", "large_truck", "auto"] = Field("mini_truck")

    @field_validator("location")
    @classmethod
    def location_must_be_known(cls, v: str) -> str:
        title = v.strip().title()
        if title not in FARMER_LOCATIONS:
            raise ValueError(f"Unknown location '{v}'. Supported: {list(FARMER_LOCATIONS)}")
        return title

    @field_validator("crop")
    @classmethod
    def crop_must_be_supported(cls, v: str) -> str:
        title = v.strip().title()
        if title not in SUPPORTED_CROPS:
            raise ValueError(f"Crop '{v}' not supported. Supported: {SUPPORTED_CROPS}")
        return title


class MarketRecommendation(BaseModel):
    rank:                int
    market_id:           int
    market_name:         str
    region:              str
    distance_km:         float
    predicted_price:     float
    trend:               str
    demand_level:        str
    transport_cost:      float
    other_costs:         float
    expected_revenue:    float
    expected_net_return: float
    confidence:          float
    lat:                 Optional[float] = None
    lng:                 Optional[float] = None
    price_history:       list[dict] = Field(default_factory=list)


class RecommendationResponse(BaseModel):
    crop:         str
    quantity_kg:  float
    location:     str
    vehicle_type: str
    markets:      list[MarketRecommendation]


class ProduceSubmissionRequest(BaseModel):
    farmer_id: Optional[int] = Field(1, description="ID of registered farmer")
    crop: str = Field(..., example="Tomato")
    quantity_kg: float = Field(..., gt=0, example=500.0)
    location: str = Field(..., example="Pune")
    harvest_date: Optional[str] = Field(None, example="2026-08-25")
    quality_grade: Optional[str] = Field("Grade A", example="Grade A")
    vehicle_type: Literal["mini_truck", "large_truck", "auto"] = Field("mini_truck")

    @field_validator("crop")
    @classmethod
    def crop_check(cls, v: str) -> str:
        title = v.strip().title()
        if title not in SUPPORTED_CROPS:
            raise ValueError(f"Crop '{v}' not supported. Supported: {SUPPORTED_CROPS}")
        return title

    @field_validator("location")
    @classmethod
    def loc_check(cls, v: str) -> str:
        title = v.strip().title()
        if title not in FARMER_LOCATIONS:
            raise ValueError(f"Location '{v}' not in supported preset cities: {list(FARMER_LOCATIONS)}")
        return title


class ProduceSubmissionResponse(BaseModel):
    submission_id: int
    farmer_id: Optional[int]
    crop: str
    quantity_kg: float
    location: str
    harvest_date: Optional[str]
    quality_grade: str
    vehicle_type: str
    submitted_at: str
    recommendations: list[MarketRecommendation]


# 3. Buyer Marketplace
class BuyerRequirementCreate(BaseModel):
    buyer_id: int = Field(..., example=1)
    crop: str = Field(..., example="Tomato")
    quantity_kg: float = Field(..., gt=0, example=5000.0)
    offered_price: float = Field(..., gt=0, example=27.5)
    location: str = Field(..., example="Nashik")
    pickup_available: bool = Field(True, example=True)

    @field_validator("crop")
    @classmethod
    def crop_check(cls, v: str) -> str:
        title = v.strip().title()
        if title not in SUPPORTED_CROPS:
            raise ValueError(f"Crop '{v}' not supported. Supported: {SUPPORTED_CROPS}")
        return title


class BuyerRequirementResponse(BaseModel):
    id: int
    buyer_id: int
    buyer_name: str
    verified: bool
    contact: Optional[str]
    crop: str
    quantity_kg: float
    offered_price: float
    location: str
    pickup_available: bool
    posted_at: str


# 4. Farmer Crowdsourced Reports
class FarmerReportCreate(BaseModel):
    farmer_id: Optional[int] = Field(1, example=1)
    crop: str = Field(..., example="Tomato")
    market_id: int = Field(..., example=2)
    reported_price: float = Field(..., gt=0, example=23.0)
    date: Optional[str] = Field(None, example="2026-08-25")

    @field_validator("crop")
    @classmethod
    def crop_check(cls, v: str) -> str:
        title = v.strip().title()
        if title not in SUPPORTED_CROPS:
            raise ValueError(f"Crop '{v}' not supported. Supported: {SUPPORTED_CROPS}")
        return title


class FarmerReportResponse(BaseModel):
    id: int
    farmer_id: Optional[int]
    crop: str
    market_id: int
    market_name: str
    reported_price: float
    official_modal_price: Optional[float]
    date: str
    validated: bool
    confidence_score: float
    message: str


# 5. Smart Logistics & Deal Sheet Models
class LogisticsMatchRequest(BaseModel):
    farmer_location: str = Field(..., example="Pune")
    destination_market: str = Field(..., example="Nashik APMC")
    distance_km: float = Field(..., gt=0, example=210.0)
    quantity_kg: float = Field(..., gt=0, example=500.0)
    vehicle_type: Optional[str] = Field(None, example="mini_truck")


class DealSheetPreviewRequest(BaseModel):
    crop: str = Field(..., example="Tomato")
    quantity_kg: float = Field(..., gt=0, example=500.0)
    farmer_name: Optional[str] = Field("Ramesh Patil")
    farmer_location: Optional[str] = Field("Pune")
    market_name: str = Field(..., example="Nashik APMC")
    predicted_price: float = Field(..., example=28.5)
    distance_km: float = Field(..., example=210.0)
    transport_cost: float = Field(..., example=3270.0)
    other_costs: float = Field(..., example=750.0)
    expected_revenue: float = Field(..., example=14250.0)
    expected_net_return: float = Field(..., example=10230.0)
    confidence: float = Field(0.95, example=0.96)
    trend: str = Field("rising", example="rising")
    demand_level: str = Field("High", example="High")
    carrier_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Farmer Authentication (Login & Register)
# ---------------------------------------------------------------------------

@app.post(
    "/auth/register",
    response_model=AuthResponse,
    tags=["Authentication"],
    summary="Register a new farmer account",
    description="Registers a new farmer with unique mobile number, password, full name, and farm location.",
)
def register_farmer(farmer: FarmerCreate):
    lat = farmer.lat
    lng = farmer.lng
    if lat is None or lng is None:
        loc_coords = FARMER_LOCATIONS.get(farmer.location)
        if loc_coords:
            lat, lng = loc_coords

    if not farmer.password or len(farmer.password) < 4:
        raise HTTPException(
            status_code=400,
            detail="Password is required and must be at least 4 characters long."
        )

    pwd_hash = hash_password(farmer.password)

    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT * FROM farmers WHERE mobile_number = ?", (farmer.mobile_number,)
        ).fetchone()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Mobile number {farmer.mobile_number} is already registered. Please log in directly."
            )

        cur = conn.execute(
            """
            INSERT INTO farmers (name, mobile_number, password_hash, location, lat, lng, profile_pic, farm_size_acres, upi_id, bio)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                farmer.name,
                farmer.mobile_number,
                pwd_hash,
                farmer.location,
                lat,
                lng,
                farmer.profile_pic,
                farmer.farm_size_acres or 5.0,
                farmer.upi_id,
                farmer.bio,
            ),
        )
        conn.commit()
        farmer_id = cur.lastrowid
        created_row = conn.execute("SELECT created_at FROM farmers WHERE id = ?", (farmer_id,)).fetchone()
        farmer_data = FarmerResponse(
            id=farmer_id,
            name=farmer.name,
            mobile_number=farmer.mobile_number,
            location=farmer.location,
            lat=lat,
            lng=lng,
            farm_size_acres=farmer.farm_size_acres or 5.0,
            upi_id=farmer.upi_id,
            bio=farmer.bio,
            profile_pic=farmer.profile_pic,
            created_at=created_row["created_at"],
            submission_count=0,
        )
        return AuthResponse(farmer=farmer_data, message="Registration successful! Welcome to KisanLink AI.")
    finally:
        conn.close()


@app.post(
    "/auth/login",
    response_model=AuthResponse,
    tags=["Authentication"],
    summary="Farmer login with mobile number and password",
    description="Authenticates and logs in a registered farmer by their mobile number and password.",
)
def login_farmer(req: FarmerLoginRequest):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM farmers WHERE mobile_number = ?", (req.mobile_number,)
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"No account found for mobile number '{req.mobile_number}'. Please register first."
            )

        stored_hash = row["password_hash"] if "password_hash" in row.keys() else None
        if stored_hash:
            if not req.password:
                raise HTTPException(
                    status_code=401,
                    detail="Password is required. Please enter your password to log in."
                )
            if not verify_password(req.password, stored_hash):
                raise HTTPException(
                    status_code=401,
                    detail="Incorrect password. Please verify and try again."
                )

        sub_count = conn.execute(
            "SELECT COUNT(*) FROM produce_submissions WHERE farmer_id = ?", (row["id"],)
        ).fetchone()[0]
        farmer_data = FarmerResponse(
            id=row["id"],
            name=row["name"],
            mobile_number=row["mobile_number"],
            location=row["location"],
            lat=row["lat"],
            lng=row["lng"],
            farm_size_acres=row["farm_size_acres"] if "farm_size_acres" in row.keys() and row["farm_size_acres"] is not None else 5.0,
            upi_id=row["upi_id"] if "upi_id" in row.keys() else None,
            bio=row["bio"] if "bio" in row.keys() else None,
            profile_pic=row["profile_pic"] if "profile_pic" in row.keys() else None,
            created_at=row["created_at"],
            submission_count=sub_count,
        )
        return AuthResponse(farmer=farmer_data, message=f"Welcome back, {row['name']}!")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Farmer APIs
# ---------------------------------------------------------------------------

@app.post(
    "/farmers",
    response_model=FarmerResponse,
    tags=["Farmers"],
    summary="Register or login farmer",
    description="Registers a new farmer or returns existing farmer profile matching the mobile number.",
)
def create_or_login_farmer(farmer: FarmerCreate):
    lat = farmer.lat
    lng = farmer.lng
    if lat is None or lng is None:
        loc_coords = FARMER_LOCATIONS.get(farmer.location)
        if loc_coords:
            lat, lng = loc_coords

    conn = get_connection()
    try:
        # Check if already exists
        row = conn.execute(
            "SELECT * FROM farmers WHERE mobile_number = ?", (farmer.mobile_number,)
        ).fetchone()

        if row:
            # Update location if provided
            conn.execute(
                "UPDATE farmers SET location = ?, lat = ?, lng = ? WHERE id = ?",
                (farmer.location, lat, lng, row["id"]),
            )
            conn.commit()
            sub_count = conn.execute(
                "SELECT COUNT(*) FROM produce_submissions WHERE farmer_id = ?", (row["id"],)
            ).fetchone()[0]
            return FarmerResponse(
                id=row["id"],
                name=row["name"],
                mobile_number=row["mobile_number"],
                location=farmer.location,
                lat=lat,
                lng=lng,
                farm_size_acres=row["farm_size_acres"] if "farm_size_acres" in row.keys() and row["farm_size_acres"] is not None else 5.0,
                upi_id=row["upi_id"] if "upi_id" in row.keys() else None,
                bio=row["bio"] if "bio" in row.keys() else None,
                profile_pic=row["profile_pic"] if "profile_pic" in row.keys() else None,
                created_at=row["created_at"],
                submission_count=sub_count,
            )

        pwd_hash = hash_password(farmer.password) if farmer.password else None
        cur = conn.execute(
            """
            INSERT INTO farmers (name, mobile_number, password_hash, location, lat, lng, profile_pic, farm_size_acres, upi_id, bio)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                farmer.name,
                farmer.mobile_number,
                pwd_hash,
                farmer.location,
                lat,
                lng,
                farmer.profile_pic,
                farmer.farm_size_acres or 5.0,
                farmer.upi_id,
                farmer.bio,
            ),
        )
        conn.commit()
        farmer_id = cur.lastrowid
        created_row = conn.execute("SELECT created_at FROM farmers WHERE id = ?", (farmer_id,)).fetchone()
        return FarmerResponse(
            id=farmer_id,
            name=farmer.name,
            mobile_number=farmer.mobile_number,
            location=farmer.location,
            lat=lat,
            lng=lng,
            farm_size_acres=farmer.farm_size_acres or 5.0,
            upi_id=farmer.upi_id,
            bio=farmer.bio,
            profile_pic=farmer.profile_pic,
            created_at=created_row["created_at"],
            submission_count=0,
        )
    finally:
        conn.close()


@app.get(
    "/farmers/{farmer_id}",
    response_model=FarmerResponse,
    tags=["Farmers"],
    summary="Get farmer profile",
)
def get_farmer_profile(farmer_id: int):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM farmers WHERE id = ?", (farmer_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Farmer not found")
        sub_count = conn.execute(
            "SELECT COUNT(*) FROM produce_submissions WHERE farmer_id = ?", (farmer_id,)
        ).fetchone()[0]
        return FarmerResponse(
            id=row["id"],
            name=row["name"],
            mobile_number=row["mobile_number"],
            location=row["location"],
            lat=row["lat"],
            lng=row["lng"],
            farm_size_acres=row["farm_size_acres"] if "farm_size_acres" in row.keys() and row["farm_size_acres"] is not None else 5.0,
            upi_id=row["upi_id"] if "upi_id" in row.keys() else None,
            bio=row["bio"] if "bio" in row.keys() else None,
            profile_pic=row["profile_pic"] if "profile_pic" in row.keys() else None,
            created_at=row["created_at"],
            submission_count=sub_count,
        )
    finally:
        conn.close()


@app.put(
    "/farmers/{farmer_id}",
    response_model=FarmerResponse,
    tags=["Farmers"],
    summary="Update farmer profile",
    description="Updates farmer details, farm size, UPI ID, bio, profile picture, or password.",
)
def update_farmer_profile(farmer_id: int, req: FarmerProfileUpdateRequest):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM farmers WHERE id = ?", (farmer_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Farmer not found")

        updates: list[str] = []
        params: list[any] = []

        if req.name is not None and req.name.strip():
            updates.append("name = ?")
            params.append(req.name.strip())

        if req.location is not None and req.location.strip():
            loc = req.location.strip().title()
            updates.append("location = ?")
            params.append(loc)
            coords = FARMER_LOCATIONS.get(loc)
            if coords:
                updates.append("lat = ?")
                params.append(coords[0])
                updates.append("lng = ?")
                params.append(coords[1])

        if req.farm_size_acres is not None and req.farm_size_acres > 0:
            updates.append("farm_size_acres = ?")
            params.append(req.farm_size_acres)

        if req.upi_id is not None:
            updates.append("upi_id = ?")
            params.append(req.upi_id.strip())

        if req.bio is not None:
            updates.append("bio = ?")
            params.append(req.bio.strip())

        if req.profile_pic is not None:
            updates.append("profile_pic = ?")
            params.append(req.profile_pic)

        if req.password is not None and req.password.strip():
            if len(req.password.strip()) < 4:
                raise HTTPException(status_code=400, detail="New password must be at least 4 characters long.")
            updates.append("password_hash = ?")
            params.append(hash_password(req.password.strip()))

        if updates:
            params.append(farmer_id)
            query = f"UPDATE farmers SET {', '.join(updates)} WHERE id = ?"
            conn.execute(query, params)
            conn.commit()

        updated_row = conn.execute("SELECT * FROM farmers WHERE id = ?", (farmer_id,)).fetchone()
        sub_count = conn.execute(
            "SELECT COUNT(*) FROM produce_submissions WHERE farmer_id = ?", (farmer_id,)
        ).fetchone()[0]

        return FarmerResponse(
            id=updated_row["id"],
            name=updated_row["name"],
            mobile_number=updated_row["mobile_number"],
            location=updated_row["location"],
            lat=updated_row["lat"],
            lng=updated_row["lng"],
            farm_size_acres=updated_row["farm_size_acres"] if "farm_size_acres" in updated_row.keys() and updated_row["farm_size_acres"] is not None else 5.0,
            upi_id=updated_row["upi_id"] if "upi_id" in updated_row.keys() else None,
            bio=updated_row["bio"] if "bio" in updated_row.keys() else None,
            profile_pic=updated_row["profile_pic"] if "profile_pic" in updated_row.keys() else None,
            created_at=updated_row["created_at"],
            submission_count=sub_count,
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Produce Submissions & Recommendations
# ---------------------------------------------------------------------------

@app.post(
    "/produce",
    response_model=ProduceSubmissionResponse,
    tags=["Produce & Recommendations"],
    summary="Submit produce and persist net-return recommendations",
    description="Records produce submission in the database, executes the net-return recommendation engine, persists ranked alternatives in the recommendations table, and returns results.",
)
def post_produce_submission(sub: ProduceSubmissionRequest):
    coords = FARMER_LOCATIONS.get(sub.location, (18.5204, 73.8567))
    farmer_lat, farmer_lng = coords
    harvest_dt = sub.harvest_date or datetime.date.today().isoformat()

    conn = get_connection()
    try:
        # 1. Insert produce submission
        cur = conn.execute(
            """
            INSERT INTO produce_submissions
                (farmer_id, crop, quantity_kg, location, harvest_date, quality_grade, vehicle_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sub.farmer_id,
                sub.crop,
                sub.quantity_kg,
                sub.location,
                harvest_dt,
                sub.quality_grade,
                sub.vehicle_type,
            ),
        )
        submission_id = cur.lastrowid

        # 2. Compute recommendations
        ranked = get_recommendations(
            crop=sub.crop,
            quantity_kg=sub.quantity_kg,
            farmer_lat=farmer_lat,
            farmer_lng=farmer_lng,
            farmer_location=sub.location,
            vehicle_type=sub.vehicle_type,
            conn=conn,
        )

        if not ranked:
            raise HTTPException(status_code=404, detail=f"No market data found for crop '{sub.crop}'.")

        # 3. Persist recommendation results
        for r in ranked:
            conn.execute(
                """
                INSERT INTO recommendations
                    (produce_submission_id, market_id, expected_revenue, transport_cost,
                     expected_net_return, price_trend, demand_level, confidence, rank)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    submission_id,
                    r["market_id"],
                    r["expected_revenue"],
                    r["transport_cost"],
                    r["expected_net_return"],
                    r["trend"],
                    r["demand_level"],
                    r["confidence"],
                    r["rank"],
                ),
            )
        conn.commit()

        submission_row = conn.execute(
            "SELECT submitted_at FROM produce_submissions WHERE id = ?", (submission_id,)
        ).fetchone()

        markets = [MarketRecommendation(**m) for m in ranked]

        return ProduceSubmissionResponse(
            submission_id=submission_id,
            farmer_id=sub.farmer_id,
            crop=sub.crop,
            quantity_kg=sub.quantity_kg,
            location=sub.location,
            harvest_date=harvest_dt,
            quality_grade=sub.quality_grade or "Grade A",
            vehicle_type=sub.vehicle_type,
            submitted_at=submission_row["submitted_at"],
            recommendations=markets,
        )
    finally:
        conn.close()


@app.get(
    "/produce/history",
    tags=["Produce & Recommendations"],
    summary="Get produce submission history",
    description="Returns previous produce submissions and their rank-1 recommended market.",
)
def get_produce_history(farmer_id: Optional[int] = None, limit: int = 20):
    conn = get_connection()
    try:
        query = """
        SELECT ps.id, ps.farmer_id, ps.crop, ps.quantity_kg, ps.location,
               ps.harvest_date, ps.quality_grade, ps.vehicle_type, ps.submitted_at,
               r.market_id, m.name as best_market_name, r.expected_net_return, r.rank
        FROM produce_submissions ps
        LEFT JOIN recommendations r ON ps.id = r.produce_submission_id AND r.rank = 1
        LEFT JOIN markets m ON r.market_id = m.id
        """
        params = []
        if farmer_id:
            query += " WHERE ps.farmer_id = ?"
            params.append(farmer_id)
        query += " ORDER BY ps.id DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post(
    "/recommendations",
    response_model=RecommendationResponse,
    tags=["Produce & Recommendations"],
    summary="Instant market recommendation ranking",
    description="Evaluates all seeded markets for expected net return without writing to history.",
)
def post_recommendations(req: RecommendationRequest) -> RecommendationResponse:
    lat, lng = FARMER_LOCATIONS[req.location]

    conn = get_connection()
    try:
        ranked = get_recommendations(
            crop=req.crop,
            quantity_kg=req.quantity_kg,
            farmer_lat=lat,
            farmer_lng=lng,
            farmer_location=req.location,
            vehicle_type=req.vehicle_type,
            conn=conn,
        )
    finally:
        conn.close()

    if not ranked:
        raise HTTPException(
            status_code=404,
            detail=f"No market data found for crop '{req.crop}'.",
        )

    markets = [MarketRecommendation(**m) for m in ranked]

    return RecommendationResponse(
        crop=req.crop,
        quantity_kg=req.quantity_kg,
        location=req.location,
        vehicle_type=req.vehicle_type,
        markets=markets,
    )


# ---------------------------------------------------------------------------
# Market Directory & Detail APIs
# ---------------------------------------------------------------------------

@app.get(
    "/markets",
    tags=["Markets"],
    summary="List all APMC markets with current prices",
    description="Returns all registered APMC markets with their latest modal prices.",
)
def get_markets(crop: Optional[str] = None):
    conn = get_connection()
    try:
        markets = conn.execute("SELECT id, name, lat, lng, region FROM markets ORDER BY id").fetchall()
        results = []
        for m in markets:
            m_dict = dict(m)
            # Find latest modal prices
            if crop:
                price_row = conn.execute(
                    """
                    SELECT modal_price, arrival_quantity, date, min_price, max_price
                    FROM price_history
                    WHERE market_id = ? AND crop = ?
                    ORDER BY date DESC LIMIT 1
                    """,
                    (m["id"], crop.strip().title()),
                ).fetchone()
                m_dict["latest_price"] = dict(price_row) if price_row else None
            else:
                prices = conn.execute(
                    """
                    SELECT crop, modal_price, arrival_quantity, date
                    FROM price_history
                    WHERE market_id = ?
                    GROUP BY crop
                    ORDER BY date DESC
                    """,
                    (m["id"],),
                ).fetchall()
                m_dict["crop_prices"] = [dict(p) for p in prices]
            results.append(m_dict)
        return results
    finally:
        conn.close()


@app.get(
    "/markets/{market_id}",
    tags=["Markets"],
    summary="Get detailed market profile and historical trends",
)
def get_market_detail(
    market_id: int,
    crop: str = "Tomato",
    farmer_location: Optional[str] = "Pune",
):
    conn = get_connection()
    try:
        m = conn.execute("SELECT * FROM markets WHERE id = ?", (market_id,)).fetchone()
        if not m:
            raise HTTPException(status_code=404, detail="Market not found")

        # Distance calculation
        dist_table = MARKET_DISTANCES_KM.get(farmer_location, {})
        distance = dist_table.get(m["name"])
        if distance is None and farmer_location in FARMER_LOCATIONS:
            f_lat, f_lng = FARMER_LOCATIONS[farmer_location]
            distance = haversine_km(f_lat, f_lng, m["lat"], m["lng"])

        # Price history
        history = get_price_history(market_id, crop.strip().title(), conn, limit=10)
        prediction = predict_price(market_id, crop.strip().title(), conn)
        demand = predict_demand(market_id, crop.strip().title(), conn)

        return {
            "market_id": m["id"],
            "name": m["name"],
            "region": m["region"],
            "lat": m["lat"],
            "lng": m["lng"],
            "farmer_location": farmer_location,
            "distance_km": round(distance, 1) if distance else None,
            "crop": crop.strip().title(),
            "predicted_price": prediction.predicted_price,
            "trend": prediction.trend,
            "demand_level": demand.value,
            "confidence": prediction.confidence,
            "price_history": history,
        }
    finally:
        conn.close()


@app.get(
    "/markets/{market_id}/history",
    tags=["Markets"],
    summary="Get recent price history for a market",
)
def get_market_history_endpoint(market_id: int, crop: str = "Tomato", days: int = 5):
    conn = get_connection()
    try:
        rows = get_price_history(market_id, crop.strip().title(), conn, limit=days)
    finally:
        conn.close()
    return {"market_id": market_id, "crop": crop, "days": len(rows), "history": rows}


# ---------------------------------------------------------------------------
# Buyer Marketplace APIs
# ---------------------------------------------------------------------------

@app.post(
    "/buyers/requirements",
    response_model=BuyerRequirementResponse,
    tags=["Buyer Marketplace"],
    summary="Post buyer wholesale requirement",
)
def post_buyer_requirement(req: BuyerRequirementCreate):
    conn = get_connection()
    try:
        buyer = conn.execute("SELECT * FROM buyers WHERE id = ?", (req.buyer_id,)).fetchone()
        if not buyer:
            raise HTTPException(status_code=404, detail="Buyer not registered.")

        cur = conn.execute(
            """
            INSERT INTO buyer_requirements
                (buyer_id, crop, quantity_kg, offered_price, location, pickup_available)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                req.buyer_id,
                req.crop,
                req.quantity_kg,
                req.offered_price,
                req.location,
                1 if req.pickup_available else 0,
            ),
        )
        conn.commit()
        req_id = cur.lastrowid
        row = conn.execute("SELECT posted_at FROM buyer_requirements WHERE id = ?", (req_id,)).fetchone()

        return BuyerRequirementResponse(
            id=req_id,
            buyer_id=buyer["id"],
            buyer_name=buyer["name"],
            verified=bool(buyer["verified"]),
            contact=buyer["contact"],
            crop=req.crop,
            quantity_kg=req.quantity_kg,
            offered_price=req.offered_price,
            location=req.location,
            pickup_available=req.pickup_available,
            posted_at=row["posted_at"],
        )
    finally:
        conn.close()


@app.get(
    "/buyers/requirements",
    response_model=List[BuyerRequirementResponse],
    tags=["Buyer Marketplace"],
    summary="Browse active buyer requirements",
    description="Allows farmers to view direct buyer orders matching crop and regional proximity.",
)
def get_buyer_requirements(
    crop: Optional[str] = None,
    location: Optional[str] = None,
):
    conn = get_connection()
    try:
        query = """
        SELECT br.id, br.buyer_id, b.name as buyer_name, b.verified, b.contact,
               br.crop, br.quantity_kg, br.offered_price, br.location,
               br.pickup_available, br.posted_at
        FROM buyer_requirements br
        JOIN buyers b ON br.buyer_id = b.id
        WHERE 1=1
        """
        params = []
        if crop:
            query += " AND br.crop = ?"
            params.append(crop.strip().title())
        if location:
            query += " AND br.location LIKE ?"
            params.append(f"%{location.strip()}%")

        query += " ORDER BY br.id DESC"
        rows = conn.execute(query, params).fetchall()

        return [
            BuyerRequirementResponse(
                id=r["id"],
                buyer_id=r["buyer_id"],
                buyer_name=r["buyer_name"],
                verified=bool(r["verified"]),
                contact=r["contact"],
                crop=r["crop"],
                quantity_kg=r["quantity_kg"],
                offered_price=r["offered_price"],
                location=r["location"],
                pickup_available=bool(r["pickup_available"]),
                posted_at=r["posted_at"],
            )
            for r in rows
        ]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Crowdsourced Farmer Reports (Price Discovery & Validation)
# ---------------------------------------------------------------------------

@app.post(
    "/farmer-reports",
    response_model=FarmerReportResponse,
    tags=["Farmer Reports & Crowdsourcing"],
    summary="Submit crowdsourced mandi price",
    description="Validates reported price against recent APMC modal prices, calculates dynamic confidence score, and flags anomalies (TRD.md §4.7 & ADR-003).",
)
def post_farmer_report(report: FarmerReportCreate):
    conn = get_connection()
    try:
        market = conn.execute("SELECT name FROM markets WHERE id = ?", (report.market_id,)).fetchone()
        if not market:
            raise HTTPException(status_code=404, detail="Market does not exist.")

        report_dt = report.date or datetime.date.today().isoformat()

        # Check official modal price benchmark
        latest_official = conn.execute(
            """
            SELECT modal_price FROM price_history
            WHERE market_id = ? AND crop = ?
            ORDER BY date DESC LIMIT 1
            """,
            (report.market_id, report.crop),
        ).fetchone()

        official_price = latest_official["modal_price"] if latest_official else None

        # Validation logic per TRD.md §4.7 & ADR-003
        if official_price:
            deviation = abs(report.reported_price - official_price) / official_price
            if deviation <= 0.20:
                validated = 1
                confidence = 0.85
                msg = "Price validated against official mandi benchmarks."
            elif deviation <= 0.40:
                validated = 1
                confidence = 0.65
                msg = "Price within acceptable market variance."
            else:
                validated = 0
                confidence = 0.35
                msg = "Outlier price flagged for administrative verification."
        else:
            validated = 0
            confidence = 0.50
            msg = "Uncorroborated report (no existing official benchmark)."

        cur = conn.execute(
            """
            INSERT INTO farmer_reports
                (farmer_id, crop, market_id, reported_price, date, validated, confidence_score)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.farmer_id,
                report.crop,
                report.market_id,
                report.reported_price,
                report_dt,
                validated,
                confidence,
            ),
        )
        conn.commit()

        return FarmerReportResponse(
            id=cur.lastrowid,
            farmer_id=report.farmer_id,
            crop=report.crop,
            market_id=report.market_id,
            market_name=market["name"],
            reported_price=report.reported_price,
            official_modal_price=official_price,
            date=report_dt,
            validated=bool(validated),
            confidence_score=confidence,
            message=msg,
        )
    finally:
        conn.close()


@app.get(
    "/farmer-reports",
    tags=["Farmer Reports & Crowdsourcing"],
    summary="List recent crowdsourced mandi reports",
)
def get_farmer_reports(
    crop: Optional[str] = None,
    market_id: Optional[int] = None,
    limit: int = 20,
):
    conn = get_connection()
    try:
        query = """
        SELECT fr.id, fr.farmer_id, f.name as farmer_name, fr.crop, fr.market_id,
               m.name as market_name, fr.reported_price, fr.date,
               fr.validated, fr.confidence_score
        FROM farmer_reports fr
        LEFT JOIN farmers f ON fr.farmer_id = f.id
        JOIN markets m ON fr.market_id = m.id
        WHERE 1=1
        """
        params = []
        if crop:
            query += " AND fr.crop = ?"
            params.append(crop.strip().title())
        if market_id:
            query += " AND fr.market_id = ?"
            params.append(market_id)

        query += " ORDER BY fr.id DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Admin & Regional Intelligence APIs
# ---------------------------------------------------------------------------

@app.get(
    "/admin/overview",
    tags=["Admin Intelligence"],
    summary="System-wide agricultural intelligence overview",
    description="Aggregates market counts, active buyers, buyer volume, crop price ranges, and detected price anomalies.",
)
def get_admin_overview():
    conn = get_connection()
    try:
        total_farmers = conn.execute("SELECT COUNT(*) FROM farmers").fetchone()[0]
        total_markets = conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
        total_buyers = conn.execute("SELECT COUNT(*) FROM buyers WHERE verified = 1").fetchone()[0]
        total_requirements = conn.execute("SELECT COUNT(*) FROM buyer_requirements").fetchone()[0]
        total_demand_kg = conn.execute("SELECT COALESCE(SUM(quantity_kg), 0) FROM buyer_requirements").fetchone()[0]
        total_submissions = conn.execute("SELECT COUNT(*) FROM produce_submissions").fetchone()[0]

        # Crop prices summary
        crops_summary = conn.execute(
            """
            SELECT crop,
                   COUNT(DISTINCT market_id) as reporting_markets,
                   ROUND(MIN(modal_price), 1) as min_price,
                   ROUND(MAX(modal_price), 1) as max_price,
                   ROUND(AVG(modal_price), 1) as avg_price,
                   ROUND(SUM(arrival_quantity), 1) as total_arrivals_qtl
            FROM price_history
            GROUP BY crop
            ORDER BY crop
            """
        ).fetchall()

        # Outlier / Anomaly flags (reports or prices with confidence < 0.6)
        anomalies = conn.execute(
            """
            SELECT fr.id, fr.crop, m.name as market_name, fr.reported_price,
                   fr.confidence_score, fr.date
            FROM farmer_reports fr
            JOIN markets m ON fr.market_id = m.id
            WHERE fr.confidence_score < 0.60
            ORDER BY fr.id DESC LIMIT 10
            """
        ).fetchall()

        # Statistical market price anomalies (Z-score > 1.8 or dev > 28%)
        stat_anomalies = PriceAnomalyDetector.detect_anomalies(conn)
        combined_anomalies = [dict(a) for a in anomalies]
        for sa in stat_anomalies:
            combined_anomalies.append({
                "crop": sa.crop,
                "market_name": sa.market_name,
                "reported_price": sa.price,
                "confidence_score": 0.50,
                "date": datetime.date.today().isoformat(),
                "reason": sa.reason,
            })

        return {
            "total_farmers": total_farmers,
            "total_markets": total_markets,
            "total_active_buyers": total_buyers,
            "total_buyer_requirements": total_requirements,
            "total_buyer_demand_kg": round(total_demand_kg, 1),
            "total_produce_submissions": total_submissions,
            "crops_summary": [dict(c) for c in crops_summary],
            "flagged_anomalies": combined_anomalies,
        }
    finally:
        conn.close()


@app.get(
    "/admin/regional",
    tags=["Admin Intelligence"],
    summary="Regional supply-demand analysis",
    description="Computes supply vs. demand balance across Maharashtra agricultural regions.",
)
def get_admin_regional_intelligence():
    conn = get_connection()
    try:
        regions = ["Nashik", "Pune", "Aurangabad", "Nagpur", "Solapur"]
        results = []

        for reg in regions:
            # Regional arrival volume (quintals)
            arrival_row = conn.execute(
                """
                SELECT COALESCE(SUM(ph.arrival_quantity), 0) as total_arrivals
                FROM price_history ph
                JOIN markets m ON ph.market_id = m.id
                WHERE m.region = ?
                """,
                (reg,),
            ).fetchone()
            arrivals_qtl = arrival_row["total_arrivals"]

            # Regional buyer demand (kg)
            demand_row = conn.execute(
                """
                SELECT COALESCE(SUM(quantity_kg), 0) as total_demand
                FROM buyer_requirements
                WHERE location LIKE ?
                """,
                (f"%{reg}%",),
            ).fetchone()
            demand_kg = demand_row["total_demand"]

            # Status determination
            demand_qtl = demand_kg / 100.0  # 1 quintal = 100 kg
            if demand_qtl > arrivals_qtl * 0.4:
                status = "HIGH DEMAND / SHORTAGE"
            elif arrivals_qtl > demand_qtl * 3:
                status = "SURPLUS"
            else:
                status = "BALANCED"

            results.append({
                "region": reg,
                "total_arrivals_qtl": round(arrivals_qtl, 1),
                "total_buyer_demand_kg": round(demand_kg, 1),
                "status": status,
            })

        return {"regional_intelligence": results}
    finally:
        conn.close()


@app.post(
    "/admin/sync-prices",
    tags=["Admin Intelligence"],
    summary="Trigger automated Agmarknet daily price ingestion",
    description="Fetches / synchronizes daily official APMC market prices and arrival quantities into price_history from data.gov.in or benchmark feeds.",
)
def sync_agmarknet_prices(
    date: Optional[str] = None,
    api_key: Optional[str] = None,
    force_sim: bool = False,
):
    conn = get_connection()
    try:
        return DataIngestionService.sync_daily_prices(
            conn, target_date=date, api_key=api_key, force_sim=force_sim
        )
    finally:
        conn.close()


@app.get(
    "/admin/data-gov-status",
    tags=["Admin Intelligence"],
    summary="Check data.gov.in Agmarknet API connection status",
)
def get_data_gov_status():
    env_key = os.environ.get("DATA_GOV_IN_API_KEY", "").strip()
    is_configured = bool(env_key)
    masked_key = f"{env_key[:4]}...{env_key[-4:]}" if len(env_key) >= 8 else ("Configured" if env_key else "None")
    return {
        "status": "ready",
        "api_key_configured": is_configured,
        "api_key_masked": masked_key,
        "source": "https://data.gov.in",
        "resource_id": "9ef84268-d588-465a-a308-a864a43d0070",
        "resource_title": "Current Daily Price of Various Commodities from Various Mandis (Agmarknet)",
        "coverage": {
            "state": "Maharashtra",
            "crops": SUPPORTED_CROPS,
            "markets": ["Pune Market A", "Nashik APMC", "Aurangabad Market B", "Nagpur Market C", "Solapur Market D"],
        },
        "instructions": "To use live data.gov.in feeds, set environment variable DATA_GOV_IN_API_KEY or supply api_key in POST /admin/sync-prices. If omitted, verified APMC benchmark model is used automatically.",
    }


@app.get(
    "/alerts",
    tags=["Smart Alerts"],
    summary="Get personalized smart opportunity & price alerts",
    description="Returns high-yield buyer premiums, price surge spikes, and supply influx warnings (PRD.md §6).",
)
def get_smart_alerts(crop: Optional[str] = None, location: Optional[str] = None):
    conn = get_connection()
    try:
        return SmartAlertService.get_alerts(conn, crop=crop, farmer_location=location)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Smart Logistics Matching (ARCHITECTURE.md §7)
# ---------------------------------------------------------------------------

@app.get(
    "/logistics/providers",
    tags=["Smart Logistics"],
    summary="List registered agricultural freight providers",
    description="Returns verified transport operators with vehicle models, payload capacities, base hubs, and verified ratings.",
)
def get_logistics_providers(
    hub: Optional[str] = Query(None, description="Filter by base hub city (e.g. Pune, Nashik)"),
    vehicle_type: Optional[str] = Query(None, description="Filter by vehicle type (mini_truck, large_truck, auto)"),
):
    return SmartLogisticsService.get_providers(hub=hub, vehicle_type=vehicle_type)


@app.post(
    "/logistics/match",
    tags=["Smart Logistics"],
    summary="Match carriers for a produce route and weight",
    description="Matches verified transporters capable of hauling the specified cargo quantity and computes guaranteed freight quotes based on TRD.md §4.1 formula.",
)
def match_logistics(req: LogisticsMatchRequest):
    quotes = SmartLogisticsService.match_logistics(
        farmer_location=req.farmer_location,
        destination_market=req.destination_market,
        distance_km=req.distance_km,
        quantity_kg=req.quantity_kg,
        vehicle_type=req.vehicle_type,
    )
    return [q.__dict__ for q in quotes]


# ---------------------------------------------------------------------------
# Certified Deal Sheet Generation (Export / Print / PDF)
# ---------------------------------------------------------------------------

@app.get(
    "/produce/{submission_id}/deal-sheet",
    response_class=HTMLResponse,
    tags=["Deal Sheet"],
    summary="Generate print-ready Deal Sheet certificate for a produce submission",
    description="Renders a print-ready HTML/PDF deal sheet documenting produce specs, optimal APMC recommendation, financial audit, and matched logistics carrier.",
)
def get_produce_deal_sheet(
    submission_id: int,
    market_id: Optional[int] = Query(None, description="Specific market recommendation to feature (defaults to rank #1 net-return)"),
    carrier_id: Optional[int] = Query(None, description="Optional chosen logistics provider ID"),
):
    conn = get_connection()
    try:
        sub_row = conn.execute(
            "SELECT * FROM produce_submissions WHERE id = ?", (submission_id,)
        ).fetchone()
        if not sub_row:
            raise HTTPException(status_code=404, detail="Produce submission not found")

        submission = dict(sub_row)

        # Get farmer info
        farmer = {"name": "Registered Farmer", "mobile_number": "9876543210", "location": submission.get("location", "Pune")}
        if submission.get("farmer_id"):
            f_row = conn.execute("SELECT * FROM farmers WHERE id = ?", (submission["farmer_id"],)).fetchone()
            if f_row:
                farmer = dict(f_row)

        # Get recommendations
        if market_id:
            rec_row = conn.execute(
                """
                SELECT r.*, m.name as market_name, m.region, m.lat as market_lat, m.lng as market_lng
                FROM recommendations r
                JOIN markets m ON r.market_id = m.id
                WHERE r.produce_submission_id = ? AND r.market_id = ?
                """,
                (submission_id, market_id),
            ).fetchone()
        else:
            rec_row = conn.execute(
                """
                SELECT r.*, m.name as market_name, m.region, m.lat as market_lat, m.lng as market_lng
                FROM recommendations r
                JOIN markets m ON r.market_id = m.id
                WHERE r.produce_submission_id = ?
                ORDER BY r.expected_net_return DESC
                LIMIT 1
                """,
                (submission_id,),
            ).fetchone()

        if not rec_row:
            raise HTTPException(status_code=404, detail="No recommendation found for this submission")

        rec = dict(rec_row)

        qty_kg = float(submission.get("quantity_kg", 500))
        predicted_price = round(rec["expected_revenue"] / qty_kg, 2) if qty_kg > 0 else 0.0
        rec["predicted_price"] = predicted_price

        # Lookup distance
        dist = MARKET_DISTANCES_KM.get((submission.get("location", "Pune"), rec.get("market_name", "")))
        if dist is None:
            f_coords = FARMER_LOCATIONS.get(submission.get("location", "Pune"), (18.5204, 73.8567))
            m_lat = rec.get("market_lat") or 18.5204
            m_lng = rec.get("market_lng") or 73.8567
            dist = round(haversine_km(f_coords[0], f_coords[1], m_lat, m_lng), 1)
        rec["distance_km"] = dist
        rec["trend"] = rec.get("price_trend", "stable")
        rec["other_costs"] = round(1.50 * qty_kg, 2)

        # Logistics carrier match
        carrier_dict = None
        if carrier_id:
            carrier_obj = next((p for p in REGISTERED_PROVIDERS if p.id == carrier_id), None)
            if carrier_obj:
                carrier_dict = carrier_obj.__dict__
        if not carrier_dict:
            matched = SmartLogisticsService.match_logistics(
                farmer_location=submission.get("location", "Pune"),
                destination_market=rec["market_name"],
                distance_km=dist,
                quantity_kg=qty_kg,
                vehicle_type=submission.get("vehicle_type"),
            )
            if matched:
                carrier_dict = matched[0].__dict__

        html = generate_deal_sheet_html(submission, rec, farmer, carrier_dict)
        return HTMLResponse(content=html, media_type="text/html")
    finally:
        conn.close()


@app.post(
    "/produce/deal-sheet/preview",
    response_class=HTMLResponse,
    tags=["Deal Sheet"],
    summary="Instant Deal Sheet certificate preview from active recommendations",
    description="Generates an on-the-fly print-ready HTML/PDF deal sheet certificate directly from client-side recommendation results.",
)
def preview_deal_sheet(req: DealSheetPreviewRequest):
    submission = {
        "id": "PREVIEW",
        "crop": req.crop,
        "quantity_kg": req.quantity_kg,
        "location": req.farmer_location,
        "harvest_date": datetime.date.today().isoformat(),
        "quality_grade": "Grade A",
        "vehicle_type": "mini_truck",
    }
    farmer = {
        "name": req.farmer_name or "Farmer",
        "mobile_number": "+91 98765 43210",
        "location": req.farmer_location or "Pune",
    }
    rec = {
        "market_name": req.market_name,
        "predicted_price": req.predicted_price,
        "distance_km": req.distance_km,
        "transport_cost": req.transport_cost,
        "other_costs": req.other_costs,
        "expected_revenue": req.expected_revenue,
        "expected_net_return": req.expected_net_return,
        "confidence": req.confidence,
        "trend": req.trend,
        "demand_level": req.demand_level,
    }
    carrier_dict = None
    if req.carrier_id:
        c_obj = next((p for p in REGISTERED_PROVIDERS if p.id == req.carrier_id), None)
        if c_obj:
            carrier_dict = c_obj.__dict__
    if not carrier_dict:
        matched = SmartLogisticsService.match_logistics(
            farmer_location=req.farmer_location or "Pune",
            destination_market=req.market_name,
            distance_km=req.distance_km,
            quantity_kg=req.quantity_kg,
        )
        if matched:
            carrier_dict = matched[0].__dict__

    html = generate_deal_sheet_html(submission, rec, farmer, carrier_dict)
    return HTMLResponse(content=html, media_type="text/html")


# ---------------------------------------------------------------------------
# Health Check Endpoint
# ---------------------------------------------------------------------------

@app.get("/health", include_in_schema=False)
def health():
    conn = get_connection()
    try:
        market_count = conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
        price_rows   = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
        farmer_count = conn.execute("SELECT COUNT(*) FROM farmers").fetchone()[0]
        buyer_count  = conn.execute("SELECT COUNT(*) FROM buyers").fetchone()[0]
        return {
            "status": "ok",
            "markets_seeded": market_count,
            "price_history_rows": price_rows,
            "farmers_count": farmer_count,
            "buyers_count": buyer_count,
            "supported_crops": SUPPORTED_CROPS,
            "supported_locations": list(FARMER_LOCATIONS),
        }
    finally:
        conn.close()
