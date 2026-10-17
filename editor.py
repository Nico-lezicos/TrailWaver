#!/usr/bin/env python3
"""
TrailWaver — Éditeur GPX interactif
Usage : python editor.py
        Ouvre http://localhost:5050 dans le navigateur
"""
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file
import re
import gpxpy
import gpxpy.gpx
import srtm as _srtm_lib
import math

app = Flask(__name__)
BASE    = Path(__file__).parent
INPUT   = BASE / 'input'
OUTPUT  = BASE / 'output'
OUTPUT.mkdir(exist_ok=True)

_srtm_cache = BASE / 'cache' / 'srtm'
_srtm_cache.mkdir(parents=True, exist_ok=True)
_srtm_data = None

def get_srtm():
    global _srtm_data
    if _srtm_data is None:
        _srtm_data = _srtm_lib.get_data(local_cache_dir=str(_srtm_cache), leave_zipped=True)
    return _srtm_data


@app.route('/')
def index():
    files = sorted(f.name for f in INPUT.glob('*.gpx'))
    return render_template('editor.html', files=files)


@app.route('/upload', methods=['POST'])
def upload():
    f = request.files.get('gpx')
    if not f:
        return jsonify({'error': 'Aucun fichier'}), 400
    # sanitize filename — keep only safe chars, force .gpx extension
    safe = re.sub(r'[^\w\-. ]', '_', Path(f.filename).stem).strip() or 'trace'
    name = safe[:80] + '.gpx'
    dest = INPUT / name
    # avoid path traversal
    if dest.resolve().parent != INPUT.resolve():
        return jsonify({'error': 'Nom de fichier invalide'}), 400
    # validate GPX before saving
    content = f.read()
    try:
        gpxpy.parse(content.decode('utf-8', errors='replace'))
    except Exception as e:
        return jsonify({'error': f'GPX invalide : {e}'}), 400
    dest.write_bytes(content)
    files = sorted(p.name for p in INPUT.glob('*.gpx'))
    return jsonify({'name': name, 'files': files})


@app.route('/delete', methods=['POST'])
def delete_gpx():
    name = request.json.get('file', '') if request.is_json else request.form.get('file', '')
    if not name:
        return jsonify({'error': 'Nom manquant'}), 400
    path = (INPUT / name).resolve()
    if path.parent != INPUT.resolve() or path.suffix.lower() != '.gpx':
        return jsonify({'error': 'Fichier invalide'}), 400
    if not path.exists():
        return jsonify({'error': 'Fichier introuvable'}), 404
    path.unlink()
    files = sorted(p.name for p in INPUT.glob('*.gpx'))
    return jsonify({'files': files})


@app.route('/load')
def load():
    name = request.args.get('file', '')
    path = INPUT / name
    if not path.exists() or path.suffix.lower() != '.gpx':
        return jsonify({'error': 'fichier introuvable'}), 404

    with open(path, encoding='utf-8') as f:
        gpx = gpxpy.parse(f)

    points = []
    idx = 0
    for t, track in enumerate(gpx.tracks):
        for s, seg in enumerate(track.segments):
            for pt in seg.points:
                points.append({
                    'id':   idx,
                    'lat':  pt.latitude,
                    'lon':  pt.longitude,
                    'ele':  pt.elevation,
                    'time': pt.time.isoformat() if pt.time else None,
                    'kind': 'trk',
                    'name': None,
                    't':    t,
                    's':    s,
                })
                idx += 1
    for r, route in enumerate(gpx.routes):
        for pt in route.points:
            points.append({
                'id':   idx,
                'lat':  pt.latitude,
                'lon':  pt.longitude,
                'ele':  pt.elevation,
                'time': None,
                'kind': 'rte',
                'name': getattr(pt, 'name', None),
                't':    -1,
                's':    r,
            })
            idx += 1
    for wpt in gpx.waypoints:
        points.append({
            'id':   idx,
            'lat':  wpt.latitude,
            'lon':  wpt.longitude,
            'ele':  wpt.elevation,
            'time': wpt.time.isoformat() if wpt.time else None,
            'kind': 'wpt',
            'name': wpt.name or '',
            'desc': wpt.description or '',
            'sym':  wpt.symbol or '',
            't':    -2,
            's':    -1,
        })
        idx += 1

    tracks_meta = []
    for t, track in enumerate(gpx.tracks):
        segs_meta = [{'idx': s, 'count': len(seg.points)}
                     for s, seg in enumerate(track.segments)]
        tracks_meta.append({
            'idx':      t,
            'name':     track.name or f'Track {t + 1}',
            'count':    sum(len(seg.points) for seg in track.segments),
            'segments': segs_meta,
        })

    routes_meta = []
    for r, route in enumerate(gpx.routes):
        routes_meta.append({
            'idx':   r,
            'name':  route.name or f'Route {r + 1}',
            'count': len(route.points),
        })

    wpts_meta = [{'id': p['id'], 'name': p.get('name', ''), 'sym': p.get('sym', '')}
                 for p in points if p['kind'] == 'wpt']

    return jsonify({
        'points':      points,
        'total':       len(points),
        'trk':         sum(1 for p in points if p['kind'] == 'trk'),
        'wpt':         len(wpts_meta),
        'tracks_meta': tracks_meta,
        'routes_meta': routes_meta,
        'wpts_meta':   wpts_meta,
    })


DIFF_SYMS = {1: 'Flag, Green', 2: 'Flag, Blue', 3: 'Flag, White',
             4: 'Flag, Red',  5: 'Skull and Crossbones'}

_GARMIN = {  # hex → Garmin DisplayColor (nearest)
    '#22c55e':'Green',  '#60a5fa':'Blue',   '#fde047':'Yellow',
    '#fb923c':'Red',    '#f87171':'DarkRed', '#4a9eff':'Blue',
    '#f59e0b':'Yellow', '#a855f7':'Magenta','#10b981':'DarkGreen',
    '#e94560':'Red',    '#ef4444':'Red',     '#eab308':'Yellow',
    '#f97316':'Red',    '#dc2626':'DarkRed', '#7f1d1d':'DarkRed',
    '#6366f1':'DarkBlue','#3b82f6':'Blue',  '#06b6d4':'Cyan',
    '#84cc16':'Green',  '#888':'LightGray',  '#aaa':'LightGray',
}

def _garmin_color(hex_col):
    return _GARMIN.get(hex_col, 'Blue')

def _build_colored_gpx(track_segs, waypoints, annotations):
    """
    track_segs : list of {color, label, pts:[{lat,lon,ele}]}
    waypoints  : list of wpt dicts
    annotations: dict key→ann for segment waypoints
    """
    stars = ['', '★', '★★', '★★★', '★★★★', '★★★★★']
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="TrailWaver"'
        ' xmlns="http://www.topografix.com/GPX/1/1"'
        ' xmlns:gpxx="http://www.garmin.com/xmlschemas/GpxExtensions/v3"'
        ' xmlns:osmand="https://osmand.net">'
    ]

    # Waypoints
    for w in waypoints:
        lines.append(f'  <wpt lat="{w["lat"]}" lon="{w["lon"]}">')
        if w.get('ele') is not None: lines.append(f'    <ele>{w["ele"]}</ele>')
        if w.get('name'): lines.append(f'    <name><![CDATA[{w["name"]}]]></name>')
        if w.get('desc'): lines.append(f'    <desc><![CDATA[{w["desc"]}]]></desc>')
        lines.append('  </wpt>')

    # Annotation waypoints
    for ann in annotations.values():
        sc = max(1, min(5, ann.get('score', 3)))
        name = f"{stars[sc]} {ann.get('label','')} – {ann.get('dist0',0)/1000:.1f}km"
        parts = [f"Difficulté : {ann.get('label','')}",
                 f"Pente moy : {ann.get('avg_slope',0)}%  max : {ann.get('max_slope',0)}%"]
        if ann.get('comment'): parts.append(f"Note : {ann['comment']}")
        lines += [f'  <wpt lat="{ann["lat"]}" lon="{ann["lon"]}">',
                  f'    <name><![CDATA[{name}]]></name>',
                  f'    <desc><![CDATA[{chr(10).join(parts)}]]></desc>',
                  f'    <sym>{DIFF_SYMS.get(sc,"Flag, White")}</sym>',
                   '  </wpt>']

    # Colored tracks
    for seg in track_segs:
        color = seg['color']
        label = seg.get('label', '')
        pts   = seg['pts']
        if not pts: continue
        gc = _garmin_color(color)
        lines += [
            '  <trk>',
            f'    <name><![CDATA[{label}]]></name>',
            '    <extensions>',
            '      <gpxx:TrackExtension>',
            f'        <gpxx:DisplayColor>{gc}</gpxx:DisplayColor>',
            '      </gpxx:TrackExtension>',
            f'      <color>{color}</color>',       # OsmAnd / Locus
            f'      <osmand:color>{color}</osmand:color>',
            '    </extensions>',
            '    <trkseg>',
        ]
        for p in pts:
            lines.append(f'      <trkpt lat="{p["lat"]}" lon="{p["lon"]}">')
            if p.get('ele') is not None:
                lines.append(f'        <ele>{p["ele"]}</ele>')
            lines.append('      </trkpt>')
        lines += ['    </trkseg>', '  </trk>']

    lines.append('</gpx>')
    return '\n'.join(lines)

@app.route('/save', methods=['POST'])
def save():
    data        = request.get_json()
    filename    = data.get('filename', 'edited.gpx')
    pts         = data.get('points', [])
    annotations = data.get('annotations', {})
    color_mode  = data.get('colorMode', 'default')

    gpx   = gpxpy.gpx.GPX()
    track = gpxpy.gpx.GPXTrack()
    gpx.tracks.append(track)
    seg   = gpxpy.gpx.GPXTrackSegment()
    track.segments.append(seg)

    for p in pts:
        if p.get('kind') == 'wpt':
            gpx.waypoints.append(gpxpy.gpx.GPXWaypoint(
                latitude=p['lat'], longitude=p['lon'], elevation=p.get('ele'),
                name=p.get('name', ''), description=p.get('desc', ''), symbol=p.get('sym', ''),
            ))
        else:
            seg.points.append(gpxpy.gpx.GPXTrackPoint(
                latitude=p['lat'], longitude=p['lon'], elevation=p.get('ele'),
            ))

    # Annotation waypoints at the start of each annotated segment
    stars = ['', '★', '★★', '★★★', '★★★★', '★★★★★']
    for key, ann in annotations.items():
        sc   = max(1, min(5, ann.get('score', 3)))
        name = f"{stars[sc]} {ann.get('label', '')}  –  {ann.get('dist0', 0)//1000:.1f}km"
        desc_parts = [
            f"Difficulté : {ann.get('label', '')}",
            f"Pente moy : {ann.get('avg_slope', 0)}%  max : {ann.get('max_slope', 0)}%",
            f"D+ : {ann.get('d_plus', 0)} m   D- : {ann.get('d_minus', 0)} m",
        ]
        if ann.get('comment'):
            desc_parts.append(f"Note : {ann['comment']}")
        gpx.waypoints.append(gpxpy.gpx.GPXWaypoint(
            latitude=ann['lat'], longitude=ann['lon'], elevation=ann.get('ele'),
            name=name, description='\n'.join(desc_parts),
            symbol=DIFF_SYMS.get(sc, 'Flag, White'),
        ))

    # ── Export coloré (difficulté / type route / pente / altitude) ──────────────
    if color_mode != 'default' and any(p.get('_export_color') for p in pts):
        wpts  = [p for p in pts if p.get('kind') == 'wpt']
        trks  = [p for p in pts if p.get('kind') != 'wpt']

        # Groupe les points trk par couleur consécutive
        track_segs = []
        if trks:
            cur_color = trks[0].get('_export_color', '#4a9eff')
            cur_label = trks[0].get('_export_label', '')
            cur_pts   = [trks[0]]
            for p in trks[1:]:
                c = p.get('_export_color', '#4a9eff')
                if c == cur_color:
                    cur_pts.append(p)
                else:
                    track_segs.append({'color': cur_color, 'label': cur_label, 'pts': cur_pts})
                    cur_color = c
                    cur_label = p.get('_export_label', '')
                    cur_pts   = [p]
            track_segs.append({'color': cur_color, 'label': cur_label, 'pts': cur_pts})

        ann_with_coords = {}
        for k, ann in annotations.items():
            if ann.get('lat'): ann_with_coords[k] = ann

        out_name = Path(filename).stem + f'_colored_{color_mode}.gpx'
        out_path = OUTPUT / out_name
        xml = _build_colored_gpx(track_segs, wpts, ann_with_coords)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(xml)
        return jsonify({'saved': out_name, 'count': len(trks),
                        'segments': len(track_segs), 'annotations': len(ann_with_coords)})

    # ── Export standard ───────────────────────────────────────────────────────
    out_name = Path(filename).stem + '_annotated.gpx'
    out_path = OUTPUT / out_name
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(gpx.to_xml())

    return jsonify({'saved': out_name, 'count': len(pts), 'annotations': len(annotations)})


@app.route('/download')
def download():
    name = request.args.get('file', '')
    path = (OUTPUT / name).resolve()
    if path.parent != OUTPUT.resolve() or not path.exists():
        return 'Fichier introuvable', 404
    return send_file(str(path), as_attachment=True, download_name=name)


def _hav(lat1, lon1, lat2, lon2):
    R = 6_371_000
    d = math.pi / 180
    dlat, dlon = (lat2 - lat1) * d, (lon2 - lon1) * d
    a = math.sin(dlat/2)**2 + math.cos(lat1*d) * math.cos(lat2*d) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


DIFF_LABELS = {1: 'Facile', 2: 'Aisé', 3: 'Moyen', 4: 'Difficile', 5: 'Extrême'}

def _diff_score_p90(slopes):
    """Score 1-5 basé sur le percentile 90 des pentes du segment.
    Seuils calibrés pour données SRTM 90m (terrain Ardennes/TET).
    """
    if not slopes:
        return 1
    slopes_s = sorted(slopes)
    p90 = slopes_s[int(len(slopes_s) * 0.90)]
    if p90 <  3: return 1   # Facile    < 3 %
    if p90 <  7: return 2   # Aisé      3–7 %
    if p90 < 13: return 3   # Moyen     7–13 %
    if p90 < 22: return 4   # Difficile 13–22 %
    return 5                # Extrême   ≥ 22 %


def _bearing(lat1, lon1, lat2, lon2):
    """Cap initial en degrés (0-360) du point 1 vers le point 2."""
    d = math.pi / 180
    dlon = (lon2 - lon1) * d
    y = math.sin(dlon) * math.cos(lat2 * d)
    x = math.cos(lat1 * d) * math.sin(lat2 * d) - math.sin(lat1 * d) * math.cos(lat2 * d) * math.cos(dlon)
    return (math.atan2(y, x) * 180 / math.pi) % 360


def _angle_diff(b1, b2):
    """Différence absolue entre deux caps (0-180°)."""
    d = abs(b1 - b2) % 360
    return d if d <= 180 else 360 - d


def _curve_bonus(pts, dist_m, step=25):
    """Bonus de difficulté (0.0-1.5) basé sur la densité pondérée des virages.
    Rééchantillonne à 1 point tous les `step` mètres pour être indépendant
    de la fréquence GPS (évite les faux-positifs sur enregistrements denses).
    """
    if len(pts) < 3 or dist_m < step * 2:
        return 0.0
    # Rééchantillonnage à pas fixe
    sampled, acc = [pts[0]], 0.0
    for i in range(1, len(pts)):
        acc += _hav(pts[i-1][1], pts[i-1][2], pts[i][1], pts[i][2])
        if acc >= step:
            sampled.append(pts[i])
            acc = 0.0
    if len(sampled) < 3:
        return 0.0
    weighted = 0.0
    for i in range(1, len(sampled) - 1):
        b1 = _bearing(sampled[i-1][1], sampled[i-1][2], sampled[i][1],   sampled[i][2])
        b2 = _bearing(sampled[i][1],   sampled[i][2],   sampled[i+1][1], sampled[i+1][2])
        a  = _angle_diff(b1, b2)
        if   a < 15:  continue
        elif a < 45:  weighted += 0.5   # courbe douce
        elif a < 90:  weighted += 1.0   # virage
        elif a < 150: weighted += 1.5   # virage serré
        else:         weighted += 2.0   # épingle
    wtpk = weighted / (dist_m / 1000)
    if wtpk <  3: return 0.0
    if wtpk <  8: return 0.3
    if wtpk < 15: return 0.7
    if wtpk < 25: return 1.0
    return 1.5


def _smooth_ele_list(eles, window=5):
    """Gaussian-weighted moving average on an elevation list (None = skip).
    Removes SRTM 90 m grid artefacts without destroying real terrain shape.
    window=5 → ±2 neighbours; sigma = window/3.
    """
    half = window // 2
    sigma = window / 3.0
    weights = [math.exp(-0.5 * ((i - half) / sigma) ** 2) for i in range(window)]
    n = len(eles)
    result = []
    for i, e in enumerate(eles):
        if e is None:
            result.append(None)
            continue
        num = den = 0.0
        for di in range(window):
            j = i + di - half
            if 0 <= j < n and eles[j] is not None:
                num += weights[di] * eles[j]
                den += weights[di]
        result.append(num / den if den > 0 else e)
    return result


@app.route('/analyze')
def analyze():
    name    = request.args.get('file', '')
    seg_len = float(request.args.get('seg', 500))   # metres
    path    = INPUT / name
    if not path.exists() or path.suffix.lower() != '.gpx':
        return jsonify({'error': 'fichier introuvable'}), 404

    with open(path, encoding='utf-8') as f:
        gpx = gpxpy.parse(f)

    srtm = get_srtm()   # tiles chargés depuis cache ; download auto si nécessaire

    result_tracks = []
    pt_idx = 0  # must mirror /load ordering

    for t, track in enumerate(gpx.tracks):
        all_pts = []  # (id, lat, lon, ele, from_srtm)
        for s, seg in enumerate(track.segments):
            for pt in seg.points:
                # Option A : GPX en priorité, SRTM seulement si absent
                if pt.elevation is not None:
                    all_pts.append((pt_idx, pt.latitude, pt.longitude, pt.elevation, False))
                else:
                    srtm_ele = srtm.get_elevation(pt.latitude, pt.longitude)
                    ele = float(srtm_ele) if srtm_ele is not None else None
                    all_pts.append((pt_idx, pt.latitude, pt.longitude, ele, True))
                pt_idx += 1

        # Option C : lissage gaussien si la majorité des points vient de SRTM
        n_srtm = sum(1 for p in all_pts if p[4])
        if n_srtm > len(all_pts) * 0.5:
            smoothed = _smooth_ele_list([p[3] for p in all_pts], window=5)
            all_pts = [(p[0], p[1], p[2], e, p[4]) for p, e in zip(all_pts, smoothed)]

        # Slice into seg_len-metre chunks
        chunks = []
        chunk, cum = [all_pts[0]], 0.0
        for i in range(1, len(all_pts)):
            d = _hav(all_pts[i-1][1], all_pts[i-1][2], all_pts[i][1], all_pts[i][2])
            cum += d
            chunk.append(all_pts[i])
            if cum >= seg_len and i < len(all_pts) - 1:
                chunks.append((chunk, cum))
                chunk, cum = [all_pts[i]], 0.0
        if len(chunk) > 1 or not chunks:
            rem = sum(_hav(chunk[j-1][1], chunk[j-1][2], chunk[j][1], chunk[j][2])
                      for j in range(1, len(chunk)))
            chunks.append((chunk, rem))

        # Stats per chunk
        segs_out = []
        dist_acc = 0.0
        for ci, (cpts, cdist) in enumerate(chunks):
            slopes, d_plus, d_minus = [], 0.0, 0.0
            for i in range(1, len(cpts)):
                d = _hav(cpts[i-1][1], cpts[i-1][2], cpts[i][1], cpts[i][2])
                if cpts[i-1][3] is not None and cpts[i][3] is not None and d > 2:
                    diff = cpts[i][3] - cpts[i-1][3]
                    slopes.append(abs(diff / d) * 100)
                    if diff > 0: d_plus += diff
                    else:        d_minus += abs(diff)

            avg_s      = round(sum(slopes) / len(slopes), 1) if slopes else 0.0
            max_s      = round(max(slopes), 1)                if slopes else 0.0
            base_score = _diff_score_p90(slopes)
            curve_b    = _curve_bonus(cpts, cdist)
            score      = min(5, base_score + round(curve_b))
            eles       = [p[3] for p in cpts if p[3] is not None]

            segs_out.append({
                'idx':         ci,
                'start_id':    cpts[0][0],
                'end_id':      cpts[-1][0],
                'dist0':       round(dist_acc),
                'dist1':       round(dist_acc + cdist),
                'dist':        round(cdist),
                'avg_slope':   avg_s,
                'max_slope':   max_s,
                'd_plus':      round(d_plus),
                'd_minus':     round(d_minus),
                'avg_ele':     round(sum(eles) / len(eles)) if eles else None,
                'score':       score,
                'base_score':  base_score,
                'curve_bonus': round(curve_b, 2),
                'label':       DIFF_LABELS[score],
                'comment':     '',
            })
            dist_acc += cdist

        result_tracks.append({'t': t, 'total_km': round(dist_acc / 1000, 1), 'segments': segs_out})

    # skip routes + waypoints in idx (not needed for analysis)
    return jsonify({'tracks': result_tracks, 'seg_len': seg_len})


@app.route('/elevation')
def elevation():
    name = request.args.get('file', '')
    path = INPUT / name
    if not path.exists() or path.suffix.lower() != '.gpx':
        return jsonify({'error': 'fichier introuvable'}), 404

    with open(path, encoding='utf-8') as f:
        gpx = gpxpy.parse(f)

    srtm = get_srtm()
    elevations = {}   # point_id -> elevation (m)
    idx = 0

    for track in gpx.tracks:
        for seg in track.segments:
            seg_ids, raw = [], []
            for pt in seg.points:
                ele = srtm.get_elevation(pt.latitude, pt.longitude)
                seg_ids.append(idx)
                raw.append(round(float(ele), 1) if ele is not None else None)
                idx += 1
            # Option C : lissage gaussien par segment
            smoothed = _smooth_ele_list(raw, window=5)
            for pt_id, e in zip(seg_ids, smoothed):
                if e is not None:
                    elevations[pt_id] = round(e, 1)

    for route in gpx.routes:
        seg_ids, raw = [], []
        for pt in route.points:
            ele = srtm.get_elevation(pt.latitude, pt.longitude)
            seg_ids.append(idx)
            raw.append(round(float(ele), 1) if ele is not None else None)
            idx += 1
        smoothed = _smooth_ele_list(raw, window=5)
        for pt_id, e in zip(seg_ids, smoothed):
            if e is not None:
                elevations[pt_id] = round(e, 1)

    # skip waypoints (idx must match /load)
    for _ in gpx.waypoints:
        idx += 1

    return jsonify({'elevations': elevations, 'count': len(elevations)})


# ── OSM access tags hierarchy per vehicle type ────────────────────────────────
_VEHICLE_TAGS = {
    'motor_vehicle': ['motor_vehicle', 'vehicle', 'access'],
    'motorcycle':    ['motorcycle', 'motor_vehicle', 'vehicle', 'access'],
    '4wd':           ['motor_vehicle', 'vehicle', 'access'],
    'atv':           ['atv', 'motor_vehicle', 'vehicle', 'access'],
    'bicycle':       ['bicycle', 'vehicle', 'access'],
    'foot':          ['foot', 'access'],
    'horse':         ['horse', 'access'],
}

def _classify_access(tags, vehicle):
    """Couleur d'accès pour un chemin (ligne) selon le type de véhicule."""
    keys = _VEHICLE_TAGS.get(vehicle, ['access'])
    val = next((tags[k] for k in keys if k in tags), None)
    if val is None:
        return None
    if val in ('yes', 'permissive', 'designated'):
        return '#22c55e'
    if val == 'no':
        return '#ef4444'
    if val == 'private':
        return '#f97316'
    if val in ('agricultural', 'forestry', 'customers', 'restricted', 'delivery'):
        return '#eab308'
    return None


def _classify_area(tags, vehicle):
    """Couleur pour une zone fermée (polygone)."""
    # Priorité aux tags d'accès explicites
    explicit = _classify_access(tags, vehicle)
    if explicit:
        return explicit, tags.get('access') or tags.get(vehicle, '')

    landuse  = tags.get('landuse', '')
    natural  = tags.get('natural', '')
    leisure  = tags.get('leisure', '')
    boundary = tags.get('boundary', '')
    military = tags.get('military', '')

    # Militaire → toujours interdit
    if landuse == 'military' or military:
        return '#ef4444', 'militaire'

    # Réserves naturelles, parcs nationaux → restriction variable
    if leisure == 'nature_reserve' or boundary in ('protected_area', 'national_park'):
        return '#eab308', 'réserve/parc'

    # Forêts — moteur interdit en Wallonie (Code forestier)
    if (landuse == 'forest' or natural == 'wood') and \
            vehicle in ('motor_vehicle', 'motorcycle', '4wd', 'atv'):
        return '#f97316', 'forêt (Code forestier BE)'

    return None, None


@app.route('/overpass')
def overpass_route():
    try:
        south   = float(request.args['south'])
        west    = float(request.args['west'])
        north   = float(request.args['north'])
        east    = float(request.args['east'])
        vehicle = request.args.get('vehicle', 'motor_vehicle')
    except (KeyError, ValueError):
        return jsonify({'error': 'paramètres invalides'}), 400

    query = f"""
[out:json][timeout:30][bbox:{south},{west},{north},{east}];
(
  way["highway"~"^(track|path|footway|bridleway|cycleway|service|unclassified|residential)$"];
  way["landuse"~"^(military|forest)$"];
  way["natural"="wood"];
  way["leisure"~"^(nature_reserve|park)$"];
  way["boundary"~"^(protected_area|national_park)$"];
  way["military"];
);
out body;>;out skel qt;
""".strip()

    try:
        resp = requests.post(
            'https://overpass-api.de/api/interpreter',
            data={'data': query}, timeout=60
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return jsonify({'error': str(e)}), 502

    nodes = {e['id']: (e['lat'], e['lon'])
             for e in data.get('elements', []) if e['type'] == 'node'}

    features = []
    for e in data.get('elements', []):
        if e['type'] != 'way':
            continue
        tags   = e.get('tags', {})
        nids   = e['nodes']
        closed = len(nids) >= 4 and nids[0] == nids[-1]
        has_hw = 'highway' in tags

        if closed and not has_hw:
            # Zone fermée (polygone)
            color, reason = _classify_area(tags, vehicle)
            if color is None:
                continue
            ring   = [[nodes[n][1], nodes[n][0]] for n in nids if n in nodes]
            if len(ring) < 4:
                continue
            features.append({
                'type': 'Feature',
                'geometry': {'type': 'Polygon', 'coordinates': [ring]},
                'properties': {
                    'color':   color,
                    'kind':    'area',
                    'name':    tags.get('name', ''),
                    'reason':  reason,
                    'landuse': tags.get('landuse', tags.get('natural', tags.get('leisure', ''))),
                }
            })
        else:
            # Chemin (ligne)
            color = _classify_access(tags, vehicle)
            if color is None:
                continue
            coords = [[nodes[n][1], nodes[n][0]] for n in nids if n in nodes]
            if len(coords) < 2:
                continue
            features.append({
                'type': 'Feature',
                'geometry': {'type': 'LineString', 'coordinates': coords},
                'properties': {
                    'color':   color,
                    'kind':    'road',
                    'highway': tags.get('highway', ''),
                    'name':    tags.get('name', ''),
                    'access':  tags.get('access', ''),
                }
            })

    return jsonify({'type': 'FeatureCollection', 'features': features,
                    'count': len(features)})


@app.route('/osm_types')
def osm_types():
    try:
        south = float(request.args['south'])
        west  = float(request.args['west'])
        north = float(request.args['north'])
        east  = float(request.args['east'])
    except (KeyError, ValueError):
        return jsonify({'error': 'paramètres invalides'}), 400

    query = f"""
[out:json][timeout:30][bbox:{south},{west},{north},{east}];
way["highway"];
out body;>;out skel qt;
""".strip()

    try:
        resp = requests.post('https://overpass-api.de/api/interpreter',
                             data={'data': query}, timeout=60)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return jsonify({'error': str(e)}), 502

    nodes = {e['id']: [e['lon'], e['lat']]
             for e in data.get('elements', []) if e['type'] == 'node'}

    ways = []
    for e in data.get('elements', []):
        if e['type'] != 'way': continue
        tags = e.get('tags', {})
        hw = tags.get('highway', '')
        if not hw: continue
        coords = [nodes[n] for n in e['nodes'] if n in nodes]
        if len(coords) < 2: continue
        ways.append({
            'hw':        hw,
            'surface':   tags.get('surface', ''),
            'tracktype': tags.get('tracktype', ''),
            'name':      tags.get('name', ''),
            'coords':    coords,
        })

    return jsonify({'ways': ways, 'count': len(ways)})


if __name__ == '__main__':
    import webbrowser, threading
    threading.Timer(0.8, lambda: webbrowser.open('http://localhost:5050')).start()
    app.run(port=5050, debug=False, threaded=True)
