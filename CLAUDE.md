# Projet TET+ — traces off-road qualifiées et voyages sur mesure

## Vision
App où l'utilisateur décrit sa sortie (ex. « off-road à 3, trail mid-size, difficile,
2 jours, restauration légère ») et reçoit une trace + un roadbook enrichi
(difficulté, % de pente, type de terrain, passages étroits, chemins abîmés, arrêts).
Objectif : apporter ce qui manque au Trans Euro Trail (TET) — la qualification du terrain.

## Principe d'architecture (non négociable)
- L'IA ne dessine JAMAIS la trace. Elle : (1) traduit la demande en contraintes,
  (2) le moteur de routage calcule sur un graphe de segments qualifiés,
  (3) l'IA rédige le roadbook.
- Problème de type « orienteering » : maximiser l'intérêt sous contraintes
  distance/temps → NetworkX ou GraphHopper (profils custom).
- Ne pas refaire la navigation : exporter en GPX OpenRally (lu par DMD, Seekers, Tulip)
  + roadbook PDF.

## Contraintes légales
- GPX TET : redistribution interdite par les CGU. Ne jamais stocker la géométrie TET
  côté serveur. Mode « apporte ton GPX » : l'utilisateur charge son fichier officiel,
  la comparaison se fait localement.
- Mention « segment commun avec le TET » descriptive uniquement : pas de logo,
  pas d'affiliation implicite, lien vers transeurotrail.org. TET = marque déposée.
- Nos annotations terrain = notre donnée propre, indexée sur la géographie (OSM), pas sur le TET.
- Filtre de légalité = contrainte DURE : tags OSM motor_vehicle/access ;
  Wallonie : Code forestier interdit les véhicules à moteur sur la plupart des chemins forestiers.

## Données par critère
- Pente : LiDAR Wallonie / Flandre (DHM), sinon Copernicus GLO-30
- Terrain : OSM surface, tracktype (grade1–5), smoothness
- Largeur : OSM width (souvent vide) → LiDAR / orthophotos
- Sinuosité / flow : géométrie
- État réel : télémétrie (accéléromètre → indice de rugosité), vision sur vidéos
  GoPro/dashcam, signalements datés, météo (boue après pluie)
- POI : Overpass (carburant, camping, boulangerie/snack, points de vue)

## Score par segment (~500 m)
technique / physique / flow / panorama + légalité (filtre) + état (fraîcheur datée)

## Traduction paramètres → contraintes (exemple)
- Groupe de 3 → niveau du pilote le plus faible
- Trail mid-size (~200 kg chargé) → exclure tracktype 5, single tracks, gués profonds, pentes extrêmes
- Difficile → forte pondération du score technique, peu de bitume
- 2 jours → 150–250 km/jour, nuitée fin J1
- Restauration légère → boulangerie/snack/épicerie vers midi
- Paramètres manquants à demander : départ, saison, type de nuitée, autonomie carburant

## Concurrence (oct. 2026)
Stegra.io (modes unpaved), MyRoute-app (IA AIDEN, roadbooks IA), Kurviger/Calimoto
(asphalte, boucles), DMD Next / Seekers / Tulip (roadbooks tulipes), GPXSheet (Python, OSM).
Aucun ne combine qualification fine du terrain + légalité + état frais + demande multicritère.
Différenciation = la donnée terrain qualifiée et légale.

## Plan
1. Script CLI : GPX → analyse par tronçon de 500 m (pente moy/max, surface, tracktype,
   largeur, sinuosité, score) → roadbook PDF + GPX OpenRally annoté.
   Zone test : section belge du TET / Ardennes + Luxembourg.
2. Graphe qualifié de la zone test (OSM + LiDAR + filtre légal).
3. Moteur de proposition depuis un formulaire de paramètres.
4. Couche IA langage naturel + génération du roadbook.
5. Seulement si app publique : contact TET CIC.

## Éditeur GPX interactif — editor.py + templates/editor.html

Flask sur http://localhost:5050. Chargement GPX depuis input/, export dans output/.

### Fonctionnalités
- **Chargement GPX** : tracks, routes, waypoints ; arborescence dans sidebar
- **Sélection** : rectangle (R), désélection, inversion, suppression, Undo
- **Colorisation tracé** : défaut / altitude / pente / difficulté (score 1-5) / type route OSM
- **Analyse tronçons** : découpe en segments de N mètres, score difficulté p90, commentaires
- **Élévation topo** : tuiles SRTM NASA 90m via `srtm.py` (cache local)
- **Types route OSM** : appel Overpass, score hw 0-10, coloration Hotline
- **Accès OSM** : couche accès véhicule (motor_vehicle/moto/4wd…) avec polygones légaux
- **Mesure** : distance + D+/D- + difficulté entre deux points A→B (ou sélection)
- **3D** : vue MapLibre GL avec terrain DEM (AWS Terrarium), exagération réglable
- **Géoloc** : bouton "Moi" centré sur position GPS
- **Mode dessin** : voir section ci-dessous
- **Export** : GPX standard ou coloré Garmin/OsmAnd selon mode actif

### Mode dessin (✏ Dessiner — touche D)
Permet de créer une nouvelle trace à la main directement sur la carte.

**Activation** : bouton `✏ Dessiner` dans la toolbar (ou touche `D`).
Désactive automatiquement Rectangle et Mesure si actifs.

**Interactions** :
| Action | Effet |
|---|---|
| Clic gauche | Ajoute un point (libre ou snappé) |
| Double-clic | Termine et valide la trace |
| Clic droit | Annule le dernier point |
| Entrée | Termine et valide la trace |
| Échap | Annule tout le dessin |

**Snap OSM** : si les types route sont chargés (`🛣️ Types route`), le curseur détecte
automatiquement le segment OSM le plus proche dans un rayon de 30px écran.
- Le segment est surligné en **cyan** (#00e5ff, épaisseur 6px)
- Un trait pointillé rouge montre la preview jusqu'au point de snap
- Le clic pose le point sur le segment exactement

Sans OSM chargé : dessin libre (aucun snap).

**Résultat** : la trace dessinée est ajoutée comme nouveau track dans `points[]` et
`metaTracks`. Elle apparaît dans la sidebar, peut être éditée (sélection, suppression,
analyse, export) comme un track GPX normal. `ele=null` (pas d'altitude par défaut —
lancer `🏔 Élévation topo` après pour enrichir).

**Implémentation** (`editor.html`) :
- `buildSegGrid(ways)` — index spatial `_segGrid` + tableau plat `_osmSegs` (segments lon0/lat0/lon1/lat1)
  appelé après `buildHwIndex` dans le handler `btnOsmTypes`
- `nearestDrawSnap(latlng)` — recherche dans ±2 cellules SNAP_GRID (0.002°), seuil 30px écran,
  retourne `{seg, snapPx, snapLL, hw}` ou `null`
- `closestPxOnSeg(p, a, b)` — projection orthogonale point/segment en coordonnées écran
- Events Leaflet : `mousemove` (highlight + rubber-band) · `click` (debounce 220ms) ·
  `dblclick` (termine) · `contextmenu` (annule dernier)
- `map.doubleClickZoom.disable()` en mode dessin pour éviter le zoom sur dblclick

## Règles de travail
- Ne jamais modifier input/ ; écrire dans output/
- Toujours produire une carte folium avant/après + rapport (km, D+, nb points)
- Clés API dans .env (GraphHopper)
- Stack : Python 3.10+, gpxpy, shapely, networkx, folium, requests (Overpass)
