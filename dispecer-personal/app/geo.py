"""Geografie: stații, distanțe și estimarea timpului de deplasare al personalului."""
from __future__ import annotations

import math

# cod -> (nume, lat, lon). Coordonate aproximative ale stațiilor principale.
STATIONS: dict[str, tuple[str, float, float]] = {
    "BN": ("București Nord", 44.4466, 26.0745),
    "PV": ("Ploiești Vest", 44.9400, 25.9980),
    "CP": ("Câmpina", 45.1250, 25.7380),
    "PR": ("Predeal", 45.5050, 25.5770),
    "BV": ("Brașov", 45.6610, 25.6157),
    "SG": ("Sighișoara", 46.2197, 24.7900),
    "MD": ("Mediaș", 46.1630, 24.3510),
    "CM": ("Copșa Mică", 46.1120, 24.2310),
    "TE": ("Teiuș", 46.2000, 23.6800),
    "AI": ("Alba Iulia", 46.0700, 23.5800),
    "SI": ("Simeria", 45.8500, 23.0100),
    "DE": ("Deva", 45.8800, 22.9000),
    "AR": ("Arad", 46.1900, 21.3200),
    "TM": ("Timișoara Nord", 45.7500, 21.2100),
    "CJ": ("Cluj-Napoca", 46.7840, 23.5860),
    "RA": ("Războieni", 46.4200, 23.8700),
    "BZ": ("Buzău", 45.1500, 26.8200),
    "FO": ("Focșani", 45.6900, 27.1800),
    "MR": ("Mărășești", 45.8770, 27.2300),
    "AD": ("Adjud", 46.1000, 27.1800),
    "BC": ("Bacău", 46.5670, 26.9200),
    "PS": ("Pașcani", 47.2500, 26.7200),
    "SV": ("Suceava", 47.6700, 26.2800),
    "IS": ("Iași", 47.1700, 27.5700),
    "FT": ("Fetești", 44.3800, 27.8300),
    "MG": ("Medgidia", 44.2500, 28.2700),
    "CT": ("Constanța", 44.1700, 28.6300),
    "PT": ("Pitești", 44.8600, 24.8700),
    "CR": ("Craiova", 44.3200, 23.8000),
    "FI": ("Filiași", 44.5500, 23.5200),
    "TJ": ("Târgu Jiu", 45.0400, 23.2800),
    "PE": ("Petroșani", 45.4200, 23.3700),
}

ROAD_FACTOR = 1.3        # drumul real e mai lung decât linia dreaptă
EARTH_R_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(a))


def station_km(a: str, b: str) -> float:
    _, la, lo = STATIONS[a]
    _, lb, lob = STATIONS[b]
    return haversine_km(la, lo, lb, lob)


def road_km(lat: float, lon: float, station: str) -> float:
    _, ls, los = STATIONS[station]
    return haversine_km(lat, lon, ls, los) * ROAD_FACTOR


def travel_minutes(km: float, speed_kmh: float, prep_min: float) -> float:
    """Timpul din momentul acceptării până la prezentarea în stație."""
    return prep_min + km / max(speed_kmh, 1.0) * 60.0


def station_name(code: str) -> str:
    return STATIONS.get(code, (code, 0, 0))[0]


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Direcția de mers (0 = nord, 90 = est)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def closest_on_segment(lat1: float, lon1: float, lat2: float, lon2: float,
                       plat: float, plon: float) -> tuple[float, float]:
    """(distanța minimă în km de la punct la segment, fracția 0..1 pe segment) – aproximare plană."""
    kx = 111.32 * math.cos(math.radians((lat1 + lat2) / 2))
    ky = 110.57
    ax, ay = 0.0, 0.0
    bx, by = (lon2 - lon1) * kx, (lat2 - lat1) * ky
    px, py = (plon - lon1) * kx, (plat - lat1) * ky
    seg = bx * bx + by * by
    f = 0.0 if seg == 0 else max(0.0, min(1.0, (px * bx + py * by) / seg))
    dx, dy = px - (ax + f * bx), py - (ay + f * by)
    return math.hypot(dx, dy), f
