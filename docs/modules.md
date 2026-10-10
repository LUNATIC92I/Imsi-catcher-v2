# Documentation des modules

Toute la logique métier est indépendante de l'interface graphique : elle est testable en
isolation et utilisable depuis la ligne de commande. L'IHM (`gui/`) et la CLI (`cli.py`)
passent par `services.Lab`, qui applique les permissions et journalise chaque opération.

## `core` — fondations

| Fichier | Contenu |
|---|---|
| `models.py` | `CellObservation`, `SpectrumSweep`, `Provenance`, `Indicator`, `Alert`, `ConfidenceLevel`, `Severity`, `Technology`, `PositionKind`. Aucun champ pour des identifiants d'abonnés. `Provenance` (source, méthode, `is_simulation`, paramètres de collecte) est obligatoire pour toute donnée. |
| `units.py` | dBm↔mW, moyenne énergétique (domaine linéaire), puissance de canal (somme des bins), plancher de bruit, kTB, ARFCN GSM / UARFCN / EARFCN / NR-ARFCN → MHz (DL). |
| `timeutils.py` | Normalisation UTC (ISO 8601, epoch s/ms, dates naïves interprétées dans le fuseau déclaré), contrôles de plausibilité (futur, année < 2000). |
| `geo.py` | Haversine, décalage local, rayon maximal plausible par technologie. |

## `storage` — persistance

`Database` (SQLite via SQLAlchemy 2) : tables `observations`, `sweeps` (spectres en binaire
float64), `alerts`, `reports` (avec SHA-256), `audit_log`, `imported_files`, `datasets`.
Les horodatages naïfs sont **refusés** à l'écriture ; les dates relues sont en UTC.
Fichier par défaut : `~/.lunatic_imsi_lab/lab.sqlite` (variable `LUNATIC_DATA_DIR`).

## `importers` — connecteur d'import

`import_csv_text`, `import_json_text`, `import_file` produisent des `CellObservation` et un
`ImportReport` (lignes importées / rejetées, motifs, avertissements, colonnes supprimées).

Colonnes reconnues (alias insensibles à la casse) :

| Champ | Alias |
|---|---|
| horodatage *(obligatoire)* | `timestamp`, `time`, `datetime`, `date`, `ts` |
| technologie *(obligatoire)* | `technology`, `tech`, `rat`, `network_type` (`2G/GSM`, `3G/UMTS/WCDMA`, `4G/LTE`, `5G/NR`) |
| MCC / MNC | `mcc`, `mnc` |
| LAC / TAC | `area_code`, `lac`, `tac` |
| identifiant de cellule | `cell_id`, `cid`, `ci`, `eci`, `nci` |
| canal | `channel`, `arfcn`, `uarfcn`, `earfcn`, `nrarfcn` (fréquence calculée si absente) |
| fréquence | `frequency_mhz`, `freq_mhz` |
| code physique | `pci`, `psc`, `bsic` |
| puissance | `rssi_dbm`, `rssi`, `rsrp`, `rscp`, `dbm` (plage plausible −160…0 dBm) |
| qualité | `quality_db`, `rsrq`, `ecno`, `sinr` |
| position | `latitude`/`lat`, `longitude`/`lon`, `position_kind`/`gps_fix` (`GPS` sinon « estimée ») |
| cellule de service | `serving`, `is_serving`, `registered` |
| paramètres diffusés | colonnes `bcast_<nom>` ou objet JSON `broadcast` |

**Filtre de confidentialité** : les colonnes `imsi`, `imei`, `imeisv`, `tmsi`, `msisdn`, `supi`,
`suci`, `guti`, `iccid`, `phone`… (et leurs variantes `*_imsi`, `imsi_*`) sont retirées
**avant** toute lecture des valeurs ; un mappage vers ces colonnes est refusé.
Un fichier marqué `is_simulation=true` reste une SIMULATION à l'import.

**Profils de mappage** (`profiles.py`) : `{"label", "columns": {champ: colonne},
"constants": {champ: valeur}}`. Profils intégrés `auto`, `nr-3gpp`, `lte-only`, `gsm-only` ;
profils personnalisés dans la configuration (`import_profiles`, admin) ou fichier JSON.
Les constantes ne remplacent jamais une colonne présente. `preview_file` indique, sans
importer, la colonne retenue pour chaque champ, les constantes, les colonnes supprimées ou
ignorées et les champs obligatoires manquants.

`importers/service.py` enchaîne : permission → `security.files.protect_import` (extension,
taille, lien symbolique, copie en lecture seule nommée par SHA-256) → analyse → stockage →
audit.

## `radio` — analyse radio

- `spectrum.py` : `detect_emissions` (zones contiguës au-dessus du plancher, centroïde
  énergétique, largeur occupée, puissance de canal, SNR, bande configurée),
  `compare_sweeps` (rééchantillonnage, émissions nouvelles / disparues / modifiées),
  `waterfall`, `band_power_series`, `detect_power_variations` (z-score robuste médiane/MAD
  par émission ; vide si < 5 balayages).
- `receivers.py` : interface `Receiver` **sans aucune méthode d'émission** ;
  `SimulatedReceiver` ; `SoapyReceiver` (flux `SOAPY_SDR_RX` uniquement, PSD de Welch,
  balayage par pas de 80 % de la bande échantillonnée, IQ non conservés, suppression de la
  raie DC par interpolation (`suppress_dc`, `dc_bins` bins de part et d'autre), unité dBFS
  tant qu'aucun offset d'étalonnage n'est fourni).

## `detection` — moteur heuristique

`Baseline` : profils de cellules connues (canaux, PCI, puissances, positions GPS, paramètres
diffusés) et index secondaires.

| Règle | Indicateur | Poids |
|---|---|---|
| R01 | Cellule absente de la référence (plus fort si signal ≥ −70 dBm) | 0,30 / 0,45 |
| R02 | Identifiant connu avec LAC/TAC, canal ou PCI différent | 0,30 (+0,05/motif) |
| R03 | LAC/TAC jamais vu pour l'opérateur (0,15 si cellule connue réidentifiée) | 0,30 |
| R04 | ≥ 3 sauts ≥ 12 dB entre mesures rapprochées, ou excès ≥ 20 dB vs référence | 0,20–0,30 |
| R05 | Transition de service 4G/5G → 2G (plus forte si cellule 2G inconnue) | 0,15 / 0,35 |
| R06 | Cellule éphémère à signal fort ; qualité des horodatages | 0,20 ; 0,05 |
| R07 | Même cellule observée à des distances improbables (÷2 si position estimée) | 0,30 |
| R08 | Paramètres diffusés modifiés ; liste de voisines vide | 0,20 ; 0,25 |
| R09 | Canal + code physique d'une cellule connue repris par une autre identité | 0,25 |
| R10 | Variation spectrale inhabituelle (module radio) | 0,15–0,20 |

Seuils (`RuleConfig`) : configurables et validés (plages admissibles `RULE_PARAM_LIMITS`),
rayons plausibles par technologie pour R07, profils d'environnement `RULE_PROFILES`
(`urbain`, `fixe`, `vehicule`, `rural`), règles
désactivables. Modification via `Lab.update_rules` (permission `configure_rules`,
administrateur), persistée dans la configuration et journalisée (avant / après). Les seuils,
le profil et les règles désactivées figurent dans chaque `AnalysisResult` et rapport.
Le plafond d'un indicateur isolé et les pondérations ne sont **pas** configurables.

Agrégation (`engine.py`) par cellule : score = 1 − Π(1 − wᵢ) sur les règles **distinctes** ;
**plafond de 0,40** si une seule règle ; ×0,5 si référence absente/courte ou observations
< 10. Un fait unique n'est compté qu'une fois (une cellule réidentifiée sous un autre LAC
ne déclenche pas R01/R09). Chaque `Alert` porte : identifiant reproductible, dates, mesures
sources, règles, priorité 0–100, score et niveau de confiance (le plus élevé est « Élevée
(à confirmer) » — il n'existe pas de niveau « confirmé »), explications, faux positifs
possibles et vérifications recommandées. Évaluation globale : `INSUFFICIENT_DATA`,
`NO_INDICATOR`, `ISOLATED_INDICATORS` ou `CONVERGENT_INDICATORS`.

## `simulation` — laboratoire virtuel

`simulate(SimulationParams)` génère une référence et une période d'observation
reproductibles (graine) : propagation simplifiée, masquage corrélé AR(1), sélection de
cellule « comme un terminal » (génération la plus récente au-dessus de −105 dBm).
Scénarios : `normal`, `coverage_change`, `power_variation`, `parameter_change`,
`inconsistent`, `synthetic_anomaly`. Chaque résultat inclut la **vérité terrain**
(`GroundTruth`) pour évaluer le moteur. `SpectrumScenario` produit des spectres
synthétiques (porteuses LTE/GSM, apparition d'émission, sauts). Aucune de ces fonctions
n'émet de signal : elles produisent des tableaux de nombres.

## `correlation` — corrélation et export

`build_timeline`, `group_alerts`, `compare_with_baseline` (statut nouvelle / connue /
absente, **persistante** si visible ≥ 50 % des intervalles de 5 min, sinon **ponctuelle**,
écart de puissance à la référence), `summarize_cells`, `serving_changes`, exports
`export_csv` / `export_json` / `alerts_to_csv` (source, méthode, paramètres de collecte et
marquage SIMULATION sur chaque ligne). `frames.py` : `to_dataframe`, `cell_statistics`,
`resample_power` (pandas, moyennes énergétiques).

## `mapping` — cartographie hors ligne

Projection locale en km (Matplotlib), marqueurs distincts GPS (●) / estimé (▲), cercles
pour les points liés à une alerte, export GeoJSON. Seules les positions **de l'équipement
de mesure** sont représentées.

## `reports` — rapports

`build_report` assemble 10 sections (périmètre, équipements et sources, période,
paramètres, observations radio = faits, anomalies = résultats d'analyse, règles, limites,
hypothèses et hypothèses alternatives, recommandations) et un avertissement permanent.
`render_html` (fichier autonome, images intégrées) et `render_pdf` (ReportLab, police
DejaVu embarquée, bandeau et filigrane SIMULATION le cas échéant). Les empreintes SHA-256
des rapports sont enregistrées.

## `security`

- `rbac.py` : rôles `viewer` (consultation), `analyst` (import, analyse, simulation,
  capture, export, rapports), `admin` (+ configuration, suppression, audit).
- `auth.py` : comptes locaux (`UserStore`) — empreintes PBKDF2-HMAC-SHA256 salées
  (600 000 itérations), politique de mot de passe (≥ 10 caractères, sans le nom), verrouillage
  5 min après 5 échecs, premier compte obligatoirement administrateur, impossibilité de
  désactiver le dernier administrateur. `Lab` refuse tout utilisateur non authentifié dès
  qu'un compte existe ; `Lab.login` journalise réussites et échecs. Permission
  `manage_users` (administrateur).
- `audit.py` : journal chaîné SHA-256 ; `verify()` localise la première entrée altérée.
- `files.py` : protection des imports, contrôle d'intégrité, écrasement avant suppression.
- `deletion.py` : suppression d'un jeu (admin, motif ≥ 5 caractères, confirmation par le
  nom exact, fichiers importés écrasés, action journalisée).

## `gui`

`main_window.py` (navigation, sélection jeu/référence, tâches de fond `QThreadPool`,
notifications), `theme.py` (graphite / argent / bleu électrique), `widgets.py` (tableaux
triables et filtrables, canevas Matplotlib interactif), `pages/` (une page par fonction).
