#!/usr/bin/env python3
"""
TrailWeaver — Analyse GPX/KML par tronçon de 500 m
Usage  : python analyze_gpx.py input/fichier.gpx
         python analyze_gpx.py input/fichier.kml
Sortie : output/<nom>_report.csv + output/<nom>_map.html

Sources :
  - Types de voies : Overpass API (OSM highway/tracktype/surface/smoothness)
  - Altitude       : tags GPX <ele> / KML altitude existants, sinon OpenTopoData SRTM-90m

Formats supportés :
  GPX : tracks et routes
  KML : LineString, MultiGeometry, gx:Track, gx:MultiTrack
"""

import sys
import math
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
import gpxpy
import folium
import pandas as pd
import numpy as np
from shapely.geometry import Point, LineString

# ── Constantes ────────────────────────────────────────────────────────────────

import json

SEGMENT_LEN_M    = 500
OUTPUT_DIR       = Path("output")
CACHE_DIR        = Path("cache/osm")   # cache tuiles Overpass — évite les re-requêtes
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
OVERPASS_HEADERS = {
    "User-Agent": "TrailWeaver/1.0 (trail analysis tool)",
}
TOPO_URL         = "https://api.opentopodata.org/v1/srtm90m"
TILE_DEG         = 0.15   # taille d'une tuile géographique (~13 km) — ajustable

# ── Classification OSM → étiquette française ──────────────────────────────────

HIGHWAY_FR = {
    "motorway":         "autoroute",
    "trunk":            "route nationale",
    "primary":          "route principale",
    "secondary":        "route secondaire",
    "tertiary":         "route tertiaire",
    "unclassified":     "route non classée",
    "residential":      "rue",
    "living_street":    "rue résidentielle",
    "service":          "voie de service",
    "track":            "chemin",           # affiné par tracktype ci-dessous
    "path":             "sentier",
    "footway":          "sentier pédestre",
    "bridleway":        "piste cavalière",
    "cycleway":         "piste cyclable",
    "steps":            "escaliers",
}

TRACKTYPE_FR = {
    "grade1": "chemin roulant (grade 1)",   # surface dure, stabilisé
    "grade2": "chemin roulant (grade 2)",   # gravier compact
    "grade3": "chemin (grade 3)",           # mixte, cailloux
    "grade4": "chemin difficile (grade 4)", # herbe/boue dominante
    "grade5": "sentier (grade 5)",          # très dégradé, naturel
}

# Couleurs carte par type
TYPE_COLOR = {
    "autoroute":                "#cc0000",
    "route nationale":          "#e05000",
    "route principale":         "#e07000",
    "route secondaire":         "#e0a000",
    "route tertiaire":          "#c8c800",
    "route non classée":        "#aaa000",
    "rue":                      "#a0a0a0",
    "rue résidentielle":        "#b8b8b8",
    "voie de service":          "#909090",
    "chemin roulant (grade 1)": "#00bb00",
    "chemin roulant (grade 2)": "#55aa00",
    "chemin (grade 3)":         "#99aa00",
    "chemin difficile (grade 4)":"#bb6600",
    "sentier (grade 5)":        "#cc3300",
    "chemin":                   "#888800",
    "sentier":                  "#cc6600",
    "sentier pédestre":         "#cc8800",
    "piste cavalière":          "#996600",
    "piste cyclable":           "#0066cc",
    "escaliers":                "#666666",
    "inconnu":                  "#999999",
}

# ── Géographie ────────────────────────────────────────────────────────────────

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance en mètres entre deux coordonnées WGS-84."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi   = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Chargement GPX / KML ──────────────────────────────────────────────────────

def load_gpx(path: str) -> list:
    """Retourne liste (lat, lon, ele|None) depuis un fichier GPX (tracks + routes)."""
    with open(path, "r", encoding="utf-8") as f:
        gpx = gpxpy.parse(f)
    pts = []
    for track in gpx.tracks:
        for seg in track.segments:
            for pt in seg.points:
                pts.append((pt.latitude, pt.longitude, pt.elevation))
    for route in gpx.routes:
        for pt in route.points:
            pts.append((pt.latitude, pt.longitude, pt.elevation))
    return pts


def load_kml(path: str) -> list:
    """
    Retourne liste (lat, lon, ele|None) depuis un fichier KML.
    Supporte : LineString, MultiGeometry, gx:Track, gx:MultiTrack.
    Note KML : ordre des coordonnées = longitude, latitude[, altitude].
    """
    KML_NS = "http://www.opengis.net/kml/2.2"
    GX_NS  = "http://www.google.com/kml/ext/2.2"

    tree = ET.parse(path)
    root = tree.getroot()
    pts  = []

    # ── LineString / LinearRing / Point : <coordinates>lon,lat,ele …</coordinates>
    for el in root.iter(f"{{{KML_NS}}}coordinates"):
        text = (el.text or "").strip()
        for token in text.split():
            parts = token.split(",")
            if len(parts) >= 2:
                lon = float(parts[0])
                lat = float(parts[1])
                ele = float(parts[2]) if len(parts) >= 3 and parts[2] else None
                pts.append((lat, lon, ele))

    # ── gx:Track / gx:MultiTrack : <gx:coord>lon lat ele</gx:coord>
    if not pts:
        for el in root.iter(f"{{{GX_NS}}}coord"):
            text = (el.text or "").strip().split()
            if len(text) >= 2:
                lon = float(text[0])
                lat = float(text[1])
                ele = float(text[2]) if len(text) >= 3 else None
                pts.append((lat, lon, ele))

    return pts


def load_points(path: str) -> list:
    """Dispatch GPX ou KML selon l'extension. Retourne liste (lat, lon, ele|None)."""
    ext = Path(path).suffix.lower()
    if ext == ".gpx":
        return load_gpx(path)
    elif ext == ".kml":
        return load_kml(path)
    else:
        raise ValueError(f"Format non supporté : {ext}  (attendu : .gpx ou .kml)")


def segment_track(points: list, seg_len: int = SEGMENT_LEN_M) -> list:
    """Découpe la liste de points (lat, lon, ele) en segments de ~seg_len m."""
    segments, current, dist = [], [points[0]], 0.0
    for i in range(1, len(points)):
        p0, p1 = points[i - 1], points[i]
        dist += haversine(p0[0], p0[1], p1[0], p1[1])
        current.append(p1)
        if dist >= seg_len:
            segments.append(current)
            current, dist = [p1], 0.0
    if len(current) > 1:
        segments.append(current)
    return segments

# ── API Overpass ───────────────────────────────────────────────────────────────

def _overpass_query(bbox: tuple, mirror: str) -> dict:
    """Envoie une requête Overpass sur un mirror donné. Lève une exception si échec."""
    south, west, north, east = bbox
    query = f"""
[out:json][timeout:90][maxsize:1073741824];
(
  way[highway]({south},{west},{north},{east});
);
out body;
>;
out skel qt;
"""
    r = requests.post(mirror, data={"data": query},
                      headers=OVERPASS_HEADERS,
                      timeout=90)
    r.raise_for_status()
    return r.json()


def build_way_geometries(osm_data: dict) -> list:
    """Construit une liste (LineString, tags) depuis la réponse Overpass."""
    nodes = {el["id"]: (el["lat"], el["lon"])
             for el in osm_data["elements"] if el["type"] == "node"}
    ways = []
    for el in osm_data["elements"]:
        if el["type"] == "way" and "tags" in el:
            coords = [nodes[n] for n in el["nodes"] if n in nodes]
            if len(coords) >= 2:
                line = LineString([(lon, lat) for lat, lon in coords])
                ways.append((line, el["tags"]))
    return ways


def _tile_cache_path(tlat: float, tlon: float) -> Path:
    return CACHE_DIR / f"tile_{tlat:.3f}_{tlon:.3f}.json"


def _overpass_query_cached(bbox: tuple) -> dict:
    """Interroge Overpass avec cache disque. Si la tuile est déjà en cache, pas de requête."""
    tlat, tlon = bbox[0], bbox[1]
    cp = _tile_cache_path(tlat, tlon)
    if cp.exists():
        return json.loads(cp.read_text(encoding="utf-8"))

    for i, mirror in enumerate(OVERPASS_MIRRORS):
        host = mirror.split("/")[2]
        for attempt in range(2):   # 2 tentatives par mirror (504 transitoire)
            try:
                data = _overpass_query(bbox, mirror)
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cp.write_text(json.dumps(data), encoding="utf-8")
                return data
            except Exception as e:
                print(f"\n      [{host}] tentative {attempt+1}: {e}", end="")
                if attempt == 0:
                    print(" → retry 20s", end="")
                    time.sleep(20)
        # Mirror épuisé, délai avant le suivant
        if i + 1 < len(OVERPASS_MIRRORS):
            print(f" → mirror suivant (attente 10s)", end="")
            time.sleep(10)

    raise RuntimeError("Tous les mirrors Overpass ont échoué")


def fetch_all_ways_tiled(raw_points: list, tile_deg: float = TILE_DEG) -> list:
    """
    Découpe la zone couverte par la route en tuiles géographiques fixes (tile_deg × tile_deg).
    Interroge Overpass une fois par tuile (avec cache disque).
    Évite le 406 qui survient quand le bbox couvre toute une grande région.
    """
    # Identifier les tuiles qui contiennent au moins un point de la route
    tile_keys: set = set()
    for lat, lon, _ in raw_points:
        tl = (math.floor(lat / tile_deg) * tile_deg,
              math.floor(lon / tile_deg) * tile_deg)
        tile_keys.add(tl)

    tiles    = sorted(tile_keys)
    all_ways: list = []
    seen:     set  = set()
    n = len(tiles)
    cached = sum(1 for tl in tiles if _tile_cache_path(*tl).exists())

    print(f"  {n} tuiles géographiques ({tile_deg}° ≈ {int(tile_deg*111)} km)  "
          f"— {cached} déjà en cache, {n-cached} à télécharger")

    for idx, (tlat, tlon) in enumerate(tiles):
        bbox = (tlat, tlon, tlat + tile_deg, tlon + tile_deg)
        cached_flag = "cache" if _tile_cache_path(tlat, tlon).exists() else "API"
        print(f"  Tuile {idx+1}/{n}  ({tlat:.2f},{tlon:.2f})  [{cached_flag}]", end=" ")

        try:
            osm_data = _overpass_query_cached(bbox)
            new_ways = build_way_geometries(osm_data)
            added = 0
            for line, tags in new_ways:
                key = line.coords[0]
                if key not in seen:
                    seen.add(key)
                    all_ways.append((line, tags))
                    added += 1
            print(f"→ {added} voies")
        except Exception as e:
            print(f"\n    Tuile ignorée : {e}")

        # Pause uniquement si la tuile était nouvelle (pas en cache)
        if cached_flag == "API" and idx + 1 < n:
            time.sleep(2.0)

    return all_ways


def nearest_way_tags(lat: float, lon: float, ways: list, max_dist_deg: float = 0.0015) -> dict:
    """Retourne les tags OSM du chemin le plus proche du point (lat, lon)."""
    pt = Point(lon, lat)
    best_dist, best_tags = float("inf"), {}
    for line, tags in ways:
        d = pt.distance(line)
        if d < best_dist:
            best_dist, best_tags = d, tags
    return best_tags if best_dist <= max_dist_deg else {}


def classify_way(tags: dict) -> tuple:
    """Retourne (type_fr, surface) à partir des tags OSM."""
    highway  = tags.get("highway", "")
    tracktype = tags.get("tracktype", "")
    surface  = tags.get("surface", "")
    if highway == "track" and tracktype in TRACKTYPE_FR:
        return TRACKTYPE_FR[tracktype], surface
    return HIGHWAY_FR.get(highway, highway or "inconnu"), surface

# ── API OpenTopoData ───────────────────────────────────────────────────────────

def fetch_elevations(latlons: list) -> list:
    """Interroge OpenTopoData SRTM-90m par batch de 100 points."""
    elevations = []
    for i in range(0, len(latlons), 100):
        batch = latlons[i:i + 100]
        locations = "|".join(f"{lat},{lon}" for lat, lon in batch)
        r = requests.get(TOPO_URL, params={"locations": locations}, timeout=30)
        r.raise_for_status()
        elevations.extend(res["elevation"] or 0 for res in r.json()["results"])
        if i + 100 < len(latlons):
            time.sleep(0.6)   # respecter la limite 1 req/s
    return elevations

# ── Carte Folium ───────────────────────────────────────────────────────────────

def build_legend_html() -> str:
    items = "".join(
        f'<li><span style="background:{c};width:14px;height:14px;display:inline-block;border-radius:2px;margin-right:6px"></span>{t}</li>'
        for t, c in TYPE_COLOR.items() if t != "inconnu"
    )
    return f"""
    <div style="position:fixed;bottom:30px;left:30px;z-index:1000;background:white;
                padding:10px 14px;border-radius:8px;box-shadow:0 2px 6px rgba(0,0,0,.3);
                font-family:sans-serif;font-size:12px;max-height:320px;overflow-y:auto">
      <b>Types de voies</b>
      <ul style="list-style:none;padding:0;margin:6px 0 0">{items}</ul>
    </div>"""


def save_map(segments: list, df: pd.DataFrame, raw_points: list, path: Path) -> None:
    lats = [p[0] for p in raw_points]
    lons = [p[1] for p in raw_points]
    m = folium.Map(location=[np.mean(lats), np.mean(lons)], zoom_start=12)

    for _, row in df.iterrows():
        seg   = segments[int(row["troncon"]) - 1]
        color = TYPE_COLOR.get(row["type_voie"], "#999999")
        popup = (
            f"<b>Tronçon {row['troncon']}</b><br>"
            f"Type : {row['type_voie']}<br>"
            f"Surface : {row['surface'] or '—'}<br>"
            f"Alt. : {row['ele_debut_m']} m → {row['ele_fin_m']} m<br>"
            f"D+ : {row['dplus_m']} m / D- : {row['dminus_m']} m<br>"
            f"Pente moy. : {row['pente_pct']} %<br>"
            f"Distance : {row['distance_m']} m"
        )
        folium.PolyLine(
            [(p[0], p[1]) for p in seg],
            color=color, weight=5, opacity=0.85,
            popup=folium.Popup(popup, max_width=260),
            tooltip=f"T{row['troncon']} — {row['type_voie']} — {row['ele_debut_m']} m",
        ).add_to(m)

    folium.Marker([raw_points[0][0],  raw_points[0][1]],  popup="Départ",  icon=folium.Icon(color="green", icon="play")).add_to(m)
    folium.Marker([raw_points[-1][0], raw_points[-1][1]], popup="Arrivée", icon=folium.Icon(color="red",   icon="stop")).add_to(m)
    m.get_root().html.add_child(folium.Element(build_legend_html()))
    m.save(str(path))

# ── Export GPX annoté ─────────────────────────────────────────────────────────

def save_gpx(segments: list, df: pd.DataFrame, raw_points: list, path: Path) -> None:
    """
    Génère un GPX avec :
    - 1 track contenant tous les points (avec altitude)
    - 1 waypoint par tronçon au point de départ : nom = type + altitude
    """
    out = gpxpy.gpx.GPX()
    out.name = path.stem

    # Track principal
    track = gpxpy.gpx.GPXTrack()
    out.tracks.append(track)
    seg = gpxpy.gpx.GPXTrackSegment()
    track.segments.append(seg)
    for lat, lon, ele in raw_points:
        seg.points.append(gpxpy.gpx.GPXTrackPoint(lat, lon, elevation=ele))

    # Waypoints : un par tronçon au point de départ
    for _, row in df.iterrows():
        surface_str = f" [{row['surface']}]" if row["surface"] else ""
        name = f"T{row['troncon']:03d} {row['type_voie']}{surface_str}"
        desc = (
            f"Alt. {row['ele_debut_m']}m → {row['ele_fin_m']}m | "
            f"D+{row['dplus_m']}m D-{row['dminus_m']}m | "
            f"Pente {row['pente_pct']}% | {row['distance_m']}m"
        )
        wpt = gpxpy.gpx.GPXWaypoint(
            latitude=row["lat_debut"],
            longitude=row["lon_debut"],
            elevation=row["ele_debut_m"],
            name=name,
            description=desc,
        )
        out.waypoints.append(wpt)

    with open(path, "w", encoding="utf-8") as f:
        f.write(out.to_xml())


# ── Point d'entrée ────────────────────────────────────────────────────────────

def analyze_gpx(gpx_path: str) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    stem = Path(gpx_path).stem

    # 1. Charger le fichier (GPX ou KML)
    fmt = Path(gpx_path).suffix.upper().lstrip(".")
    print(f"\nChargement {fmt} : {gpx_path}")
    raw_points = load_points(gpx_path)

    if not raw_points:
        print(f"Aucun point trouvé dans le fichier {fmt}.")
        return
    print(f"  {len(raw_points)} points {fmt}")

    # 2. Élévation (fichier ou API)
    has_ele = any(p[2] is not None for p in raw_points)
    if has_ele:
        print(f"  Altitude : données {fmt} utilisées")
        raw_points = [(lat, lon, ele or 0) for lat, lon, ele in raw_points]
    else:
        print("  Altitude : requête OpenTopoData SRTM-90m...")
        eles = fetch_elevations([(p[0], p[1]) for p in raw_points])
        raw_points = [(p[0], p[1], e) for p, e in zip(raw_points, eles)]

    # 3. OSM : voies par tuile géographique (cache disque dans cache/osm/)
    ways = fetch_all_ways_tiled(raw_points)
    print(f"  {len(ways)} voies OSM chargées au total")

    # 4. Découper en tronçons
    segments = segment_track(raw_points)
    print(f"  {len(segments)} tronçons de ~{SEGMENT_LEN_M} m")

    # 5. Analyser chaque tronçon
    rows = []
    for i, seg in enumerate(segments):
        lats_s = [p[0] for p in seg]
        lons_s = [p[1] for p in seg]
        eles_s = [p[2] for p in seg]

        dist   = sum(haversine(seg[j][0], seg[j][1], seg[j+1][0], seg[j+1][1]) for j in range(len(seg)-1))
        dplus  = sum(max(0, eles_s[j+1] - eles_s[j]) for j in range(len(eles_s)-1))
        dminus = sum(max(0, eles_s[j]   - eles_s[j+1]) for j in range(len(eles_s)-1))
        slope  = abs(eles_s[-1] - eles_s[0]) / max(dist, 1) * 100

        tags              = nearest_way_tags(np.mean(lats_s), np.mean(lons_s), ways)
        road_type, surface = classify_way(tags)

        rows.append({
            "troncon":      i + 1,
            "lat_debut":    round(seg[0][0],  6),
            "lon_debut":    round(seg[0][1],  6),
            "lat_fin":      round(seg[-1][0], 6),
            "lon_fin":      round(seg[-1][1], 6),
            "distance_m":   round(dist),
            "ele_debut_m":  round(eles_s[0]),
            "ele_fin_m":    round(eles_s[-1]),
            "ele_min_m":    round(min(eles_s)),
            "ele_max_m":    round(max(eles_s)),
            "dplus_m":      round(dplus),
            "dminus_m":     round(dminus),
            "pente_pct":    round(slope, 1),
            "type_voie":    road_type,
            "surface":      surface,
            "tracktype":    tags.get("tracktype", ""),
            "smoothness":   tags.get("smoothness", ""),
            "highway_raw":  tags.get("highway", ""),
        })

    df = pd.DataFrame(rows)

    # 6. Sauvegarder
    csv_path = OUTPUT_DIR / f"{stem}_report.csv"
    map_path = OUTPUT_DIR / f"{stem}_map.html"
    gpx_path_out = OUTPUT_DIR / f"{stem}_annotated.gpx"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    save_map(segments, df, raw_points, map_path)
    save_gpx(segments, df, raw_points, gpx_path_out)

    # 7. Résumé console
    total_km    = df["distance_m"].sum() / 1000
    total_dplus = df["dplus_m"].sum()
    print(f"\n{'='*50}")
    print(f"  Distance totale  : {total_km:.1f} km")
    print(f"  Dénivelé +       : {total_dplus} m")
    print(f"  Altitude min/max : {df['ele_min_m'].min()} m / {df['ele_max_m'].max()} m")
    print(f"\n  Types de voies :")
    for vtype, count in df["type_voie"].value_counts().items():
        km  = df[df["type_voie"] == vtype]["distance_m"].sum() / 1000
        pct = count / len(df) * 100
        print(f"    {vtype:<38} {count:>3} tronçons  {km:>6.1f} km  ({pct:.0f}%)")
    print(f"\n  CSV         → {csv_path}")
    print(f"  Carte HTML  → {map_path}")
    print(f"  GPX annoté  → {gpx_path_out}")
    print("="*50)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze_gpx.py input/fichier.gpx")
        sys.exit(1)
    analyze_gpx(sys.argv[1])
