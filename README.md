[![FR](https://img.shields.io/badge/lang-FR-blue)](#français) [![EN](https://img.shields.io/badge/lang-EN-blue)](#english)

---

<a name="english"></a>

# TrailWaver 🇬🇧

Python toolkit to qualify and edit off-road tracks (GPX/KML).  
Goal: bring what the Trans Euro Trail lacks — fine terrain qualification, legal access filtering, and a usable GPS roadbook.

![TrailWaver Editor — OSM road type colorization](Pr%C3%A9sentation.png)

*Web editor — TET FR track colored by OSM road type (grade 1–5 track, classified road), track/segment sidebar, full toolbar.*

---

## Overview

TrailWaver consists of two independent tools:

| Tool | Description |
|---|---|
| `analyze_gpx.py` | CLI — analyzes a track in 500 m segments, produces a CSV report, an HTML map, and an annotated GPX |
| `editor.py` | Web — interactive GPX editor (Flask + Leaflet), colorization, analysis, drawing, Garmin/OsmAnd export |

---

## Installation

**Requirements: Python 3.10+**

```bash
pip install -r requirements.txt
```

Dependencies: `gpxpy`, `requests`, `folium`, `pandas`, `numpy`, `shapely`, `flask`, `srtm.py`

---

## CLI Analyzer — `analyze_gpx.py`

### Usage

```bash
python analyze_gpx.py input/my_track.gpx
python analyze_gpx.py input/my_track.kml
```

### What it does

1. **Loads** the track (GPX tracks + routes, KML LineString/gx:Track)
2. **Elevation** — uses existing `<ele>` tags; otherwise queries OpenTopoData SRTM-90m
3. **OSM road types** — queries Overpass API per geographic tile of 0.15° (~13 km), with disk cache in `cache/osm/`
4. **Splits** the track into ~500 m segments
5. **Analyzes each segment**: distance, D+/D-, average slope, OSM road type, surface, tracktype

### Outputs (in `output/`)

| File | Content |
|---|---|
| `<name>_report.csv` | Per-segment table: coordinates, altitude, elevation gain, slope, type, surface |
| `<name>_map.html` | Folium map colored by road type, detailed popups |
| `<name>_annotated.gpx` | GPX with one waypoint per segment (type + altitude + elevation) |

### OSM classification

Tracks are classified in French/English from `highway` + `tracktype` tags:

```
grade1 → paved track (hard surface)
grade2 → paved track (compact gravel)
grade3 → track (mixed)
grade4 → difficult track (grass/mud)
grade5 → path (very degraded)
```

### Overpass cache

OSM tiles are cached in `cache/osm/tile_<lat>_<lon>.json`.  
An existing tile is never re-downloaded. Delete the file to force a refresh.

---

## Web Editor — `editor.py`

### Launch

```bash
python editor.py
# or double-click launch.bat
```

Opens automatically at `http://localhost:5050`.

### File management

- GPX files in `input/` are listed at startup
- **Upload** from the UI (`+ Upload` button) — GPX validated server-side before saving
- **Delete** from the sidebar

### Visualization

**Track colorization modes:**

| Mode | Description |
|---|---|
| Default | Single color per track |
| Altitude | Gradient by elevation (Hotline) |
| Slope | Gradient by local slope |
| Difficulty | Score 1–5 per segment (green → red) |
| OSM road types | Color by `highway` + `tracktype` (Overpass call) |

### Segment analysis

`📊 Analyze` button — splits the track into N-metre segments (configurable) and computes per segment:

- Average and maximum slope
- D+ / D-
- **Difficulty score 1–5** based on the 90th percentile of slopes
- Curve bonus (weighted corner density, resampled at fixed intervals)
- Label: Easy / Mild / Medium / Hard / Extreme

Annotated segments become waypoints on export.

### Topo elevation — NASA SRTM

`🏔 Topo elevation` button — queries SRTM 90m tiles (NASA), Gaussian smoothing applied to remove grid artefacts.  
Local cache in `cache/srtm/` (`.hgt.zip` files, auto-downloaded on first use).

### OSM access layer

`🔒 Access` button — queries Overpass on the visible extent and displays:

- **Lines** colored by access right (green = yes, red = forbidden, orange = private, yellow = restricted)
- **Polygons**: military zones (red), nature reserves/parks (yellow), forests (orange — Belgian Forest Code)

Supported vehicle types: `motor_vehicle`, `motorcycle`, `4wd`, `atv`, `bicycle`, `foot`, `horse`

### OSM road types

`🛣️ Road types` button — loads `way[highway]` on the visible extent and colors by type.  
Also enables OSM snap for draw mode.

### Selection and editing

| Action | Description |
|---|---|
| Key `R` | Rectangle mode — selects points in the drawn area |
| Invert selection | Inverts the current selection |
| Delete | Deletes selected points (with Undo) |
| Ctrl+Z | Undo last deletion |

### Draw mode (key `D`)

Allows tracing a new route by hand on the map.

| Interaction | Effect |
|---|---|
| Left click | Adds a point (free or snapped to OSM segment) |
| Double-click | Finishes and validates the track |
| Right click | Undoes the last point |
| Enter | Finishes and validates |
| Esc | Cancels everything |

**OSM snap**: if road types are loaded, the cursor automatically snaps to the nearest OSM segment within a 30px screen radius (highlighted in cyan).

### Measure (key `M`)

Click A → click B (or selection) → displays distance, D+/D- and difficulty score for the segment.

### 3D view

`🗻 3D` button — switches to MapLibre GL view with DEM terrain (AWS Terrarium), adjustable exaggeration.

### Language

`EN`/`FR` button in the toolbar — switches the interface between English and French. Preference is saved in `localStorage`.

### Export

| Mode | Output file |
|---|---|
| Standard | `<name>_annotated.gpx` — track + annotation waypoints |
| Colored (difficulty / slope / altitude / road types) | `<name>_colored_<mode>.gpx` — Garmin (`DisplayColor`) + OsmAnd (`<osmand:color>`) tracks |

---

## Data sources

| Data | Source |
|---|---|
| Road types, access | OpenStreetMap via [Overpass API](https://overpass-api.de) |
| Altitude (CLI) | [OpenTopoData SRTM-90m](https://www.opentopodata.org) |
| Altitude (editor) | NASA SRTM 90m via `srtm.py` (local cache) |
| 3D terrain | AWS Terrarium DEM (MapLibre GL) |

---

## Project structure

```
TrailWaver/
├── analyze_gpx.py       # CLI analyzer
├── editor.py            # Flask server (web editor)
├── templates/
│   └── editor.html      # Leaflet UI (self-contained HTML/JS)
├── requirements.txt
├── launch.bat           # Windows shortcut for the editor
├── input/               # Source GPX files (not versioned)
├── output/              # Generated files (not versioned)
└── cache/
    ├── osm/             # Overpass JSON tiles (not versioned)
    └── srtm/            # SRTM .hgt.zip tiles (not versioned)
```

> `input/`, `output/` and `cache/` are in `.gitignore`.  
> TET files are subject to Trans Euro Trail terms of use — never redistribute them.

---

## Long-term vision

TrailWaver is phase 1 of a larger project:

1. **CLI script** (current) — analysis and qualification of existing tracks
2. **Qualified graph** — scored OSM segments (slope, surface, legality, condition)
3. **Routing engine** — track proposal from a multi-criteria form (NetworkX / GraphHopper)
4. **AI + roadbook** — natural language → constraints → PDF/GPX OpenRally roadbook (DMD, Seekers, Tulip)

Non-negotiable principle: **the AI never draws the route** — it translates constraints; the graph engine computes.

---

---

<a name="français"></a>

# TrailWaver 🇫🇷

Boîte à outils Python pour qualifier et éditer des traces off-road (GPX/KML).  
Objectif : apporter ce qui manque au Trans Euro Trail — la qualification fine du terrain, la légalité de l'accès, et la génération d'un roadbook utilisable sur GPS.

![Éditeur TrailWaver — colorisation par types de route OSM](Pr%C3%A9sentation.png)

*Éditeur web — trace TET FR colorée par type de voie OSM (chemin grade 1–5, route classifiée), sidebar track/segments, toolbar complète.*

---

## Vue d'ensemble

TrailWaver se compose de deux outils indépendants :

| Outil | Description |
|---|---|
| `analyze_gpx.py` | CLI — analyse une trace par tronçons de 500 m, produit un rapport CSV, une carte HTML et un GPX annoté |
| `editor.py` | Web — éditeur GPX interactif (Flask + Leaflet), colorisation, analyse, dessin, export Garmin/OsmAnd |

---

## Installation

**Prérequis : Python 3.10+**

```bash
pip install -r requirements.txt
```

Dépendances : `gpxpy`, `requests`, `folium`, `pandas`, `numpy`, `shapely`, `flask`, `srtm.py`

---

## Analyseur CLI — `analyze_gpx.py`

### Usage

```bash
python analyze_gpx.py input/ma_trace.gpx
python analyze_gpx.py input/ma_trace.kml
```

### Ce que ça fait

1. **Charge** la trace (GPX tracks + routes, KML LineString/gx:Track)
2. **Élévation** — utilise les tags `<ele>` existants ; sinon interroge OpenTopoData SRTM-90m
3. **Types de voies OSM** — interroge Overpass API par tuile géographique de 0,15° (~13 km), avec cache disque dans `cache/osm/`
4. **Découpe** la trace en tronçons de ~500 m
5. **Analyse chaque tronçon** : distance, D+/D-, pente moyenne, type de voie OSM, surface, tracktype

### Sorties (dans `output/`)

| Fichier | Contenu |
|---|---|
| `<nom>_report.csv` | Tableau par tronçon : coordonnées, altitude, dénivelé, pente, type, surface |
| `<nom>_map.html` | Carte Folium colorée par type de voie, popups détaillés |
| `<nom>_annotated.gpx` | GPX avec 1 waypoint par tronçon (type + altitude + dénivelé) |

### Classification OSM

Les chemins sont classés depuis les tags `highway` + `tracktype` :

```
grade1 → chemin roulant (surface dure)
grade2 → chemin roulant (gravier compact)
grade3 → chemin (mixte)
grade4 → chemin difficile (herbe/boue)
grade5 → sentier (très dégradé)
```

### Cache Overpass

Les tuiles OSM sont mises en cache dans `cache/osm/tile_<lat>_<lon>.json`.  
Une tuile déjà présente n'est plus téléchargée. Supprimer le fichier pour forcer le rafraîchissement.

---

## Éditeur web — `editor.py`

### Lancement

```bash
python editor.py
# ou double-cliquer launch.bat
```

Ouvre automatiquement `http://localhost:5050`.

### Chargement de fichiers

- Les fichiers GPX présents dans `input/` sont listés au démarrage
- **Upload** depuis l'interface (bouton `+ Upload`) — validation GPX avant enregistrement
- **Suppression** depuis la sidebar

### Visualisation

**Modes de colorisation du tracé :**

| Mode | Description |
|---|---|
| Défaut | Couleur unique par trace |
| Altitude | Dégradé selon l'élévation (Hotline) |
| Pente | Dégradé selon la pente locale |
| Difficulté | Score 1–5 par segment (vert → rouge) |
| Types route OSM | Couleur par `highway` + `tracktype` (appel Overpass) |

### Analyse de tronçons

Bouton `📊 Analyser` — découpe le track en segments de N mètres (paramétrable) et calcule par segment :

- Pente moyenne et maximale
- D+ / D-
- Score de difficulté **1–5** basé sur le percentile 90 des pentes
- Bonus courbes (densité pondérée des virages, rééchantillonné à pas fixe)
- Label : Facile / Aisé / Moyen / Difficile / Extrême

Les segments annotés deviennent des waypoints à l'export.

### Élévation topo — SRTM NASA

Bouton `🏔 Élévation topo` — interroge les tuiles SRTM 90m (NASA), lissage gaussien appliqué pour supprimer les artefacts de grille.  
Cache local dans `cache/srtm/` (fichiers `.hgt.zip`, téléchargés automatiquement à la première utilisation).

### Couche accès OSM

Bouton `🔒 Accès` — interroge Overpass sur l'emprise visible et affiche :

- **Lignes** colorées par droit d'accès (vert = oui, rouge = interdit, orange = privé, jaune = restreint)
- **Polygones** : zones militaires (rouge), réserves naturelles/parcs (jaune), forêts (orange — Code forestier belge)

Types de véhicule supportés : `motor_vehicle`, `motorcycle`, `4wd`, `atv`, `bicycle`, `foot`, `horse`

### Types de route OSM

Bouton `🛣️ Types route` — charge les `way[highway]` sur l'emprise visible et colore selon le type.  
Active également le snap OSM pour le mode dessin.

### Sélection et édition

| Action | Description |
|---|---|
| Touche `R` | Mode rectangle — sélectionne les points dans la zone dessinée |
| Sélection inverse | Inverse la sélection courante |
| Suppression | Efface les points sélectionnés (avec Undo) |
| Ctrl+Z | Annule la dernière suppression |

### Mode dessin (touche `D`)

Permet de tracer une nouvelle trace à la main sur la carte.

| Interaction | Effet |
|---|---|
| Clic gauche | Ajoute un point (libre ou snappé sur segment OSM) |
| Double-clic | Termine et valide la trace |
| Clic droit | Annule le dernier point |
| Entrée | Termine et valide |
| Échap | Annule tout |

**Snap OSM** : si les types route sont chargés, le curseur se colle automatiquement au segment OSM le plus proche dans un rayon de 30px écran (surligné en cyan).

### Mesure (touche `M`)

Clic A → clic B (ou sélection) → affiche distance, D+/D- et score de difficulté du segment.

### Vue 3D

Bouton `🗻 3D` — bascule en vue MapLibre GL avec terrain DEM (AWS Terrarium), exagération réglable.

### Langue

Bouton `EN`/`FR` dans la toolbar — bascule l'interface entre l'anglais et le français. La préférence est sauvegardée en `localStorage`.

### Export

| Mode | Fichier produit |
|---|---|
| Standard | `<nom>_annotated.gpx` — track + waypoints d'annotation |
| Coloré (difficulté / pente / altitude / types route) | `<nom>_colored_<mode>.gpx` — tracks Garmin (`DisplayColor`) + OsmAnd (`<osmand:color>`) |

---

## Sources de données

| Donnée | Source |
|---|---|
| Types de voies, accès | OpenStreetMap via [Overpass API](https://overpass-api.de) |
| Altitude (CLI) | [OpenTopoData SRTM-90m](https://www.opentopodata.org) |
| Altitude (éditeur) | NASA SRTM 90m via `srtm.py` (cache local) |
| Terrain 3D | AWS Terrarium DEM (MapLibre GL) |

---

## Structure du projet

```
TrailWaver/
├── analyze_gpx.py       # Analyseur CLI
├── editor.py            # Serveur Flask (éditeur web)
├── templates/
│   └── editor.html      # Interface Leaflet (HTML/JS tout-en-un)
├── requirements.txt
├── launch.bat           # Raccourci Windows pour l'éditeur
├── input/               # Fichiers GPX source (non versionnés)
├── output/              # Fichiers générés (non versionnés)
└── cache/
    ├── osm/             # Tuiles Overpass JSON (non versionnées)
    └── srtm/            # Tuiles SRTM .hgt.zip (non versionnées)
```

> Les dossiers `input/`, `output/` et `cache/` sont dans `.gitignore`.  
> Les fichiers TET sont soumis aux CGU Trans Euro Trail — ne jamais les redistribuer.

---

## Vision long terme

TrailWaver est la phase 1 d'un projet plus large :

1. **Script CLI** (actuel) — analyse et qualification de traces existantes
2. **Graphe qualifié** — segments OSM scorés (pente, surface, légalité, état)
3. **Moteur de routage** — proposition de traces depuis un formulaire multicritère (NetworkX / GraphHopper)
4. **IA + roadbook** — traduction langage naturel → contraintes → roadbook PDF/GPX OpenRally (DMD, Seekers, Tulip)

Principe non-négociable : **l'IA ne dessine jamais la trace** — elle traduit les contraintes, le moteur de graphe calcule.
