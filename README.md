# TrailWaver

Boîte à outils Python pour qualifier et éditer des traces off-road (GPX/KML).  
Objectif : apporter ce qui manque au Trans Euro Trail — la qualification fine du terrain, la légalité de l'accès, et la génération d'un roadbook utilisable sur GPS.

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

Les chemins sont classés en français depuis les tags `highway` + `tracktype` :

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
| Défaut | Couleur unique |
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