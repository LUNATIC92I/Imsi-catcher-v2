# Bilan des fonctionnalités opérationnelles et des limitations

Version 0.1.0 — état vérifié par la suite de tests (`python -m pytest`, 173 tests) et par
l'exécution de l'interface en mode hors écran.

Légende : ✅ opérationnel et testé · 🟡 implémenté, non validé sur matériel réel ·
⛔ volontairement exclu.

## Fonctionnalités

| Domaine | Fonction | État | Preuve / remarque |
|---|---|---|---|
| Tableau de bord | État système, équipements, technologies, bandes, puissance, changements de cellule, anomalies, historique des analyses, confiance des alertes, derniers rapports | ✅ | `tests/test_gui.py` |
| Analyse radio | Visualisation du spectre, cascade, émissions (fréquence centrale, largeur, puissance de canal, SNR, bande) | ✅ | `TestSpectrum` |
| | Comparaison de balayages successifs, variations temporelles inhabituelles | ✅ | `test_compare_*`, `test_power_variations` |
| | Enregistrement des balayages | ✅ | `TestDatabase::test_sweeps_roundtrip` |
| | Acquisition SoapySDR (RTL-SDR, Airspy, HackRF/USRP en RX…) | 🟡 | Code de réception présent ; **non testé sur matériel** dans l'environnement de développement (aucun SDR, bindings SoapySDR absents). Le mode « indisponible » est testé. |
| Cellules | Import CSV/JSON (alias, `;`/`,`/tab, virgule décimale, epoch, fuseaux), technologie, CI, MCC/MNC, LAC/TAC, canal→fréquence, puissance, qualité, horodatages, source et méthode | ✅ | `TestImporter` |
| | Filtre des identifiants personnels | ✅ | `test_privacy_filter_drops_identifiers` |
| | Connexion directe à un modem en mode diagnostic | ⛔ | Hors périmètre : l'import passe par les exports d'outils autorisés. |
| Détection | 10 règles (R01–R10), alertes complètes (ID, date, sources, règles, priorité, confiance, explications, faux positifs, vérifications) | ✅ | `TestRules`, `TestEngine` |
| | Plafonnement des indicateurs isolés, prise en compte des données insuffisantes | ✅ | `test_single_indicator_is_capped`, `test_insufficient_*` |
| | Scénarios légitimes sans alerte significative ; anomalie synthétique convergente | ✅ | `TestScenarios` |
| Simulation | 6 scénarios paramétrables, reproductibles (graine), vérité terrain, spectres synthétiques, marquage SIMULATION | ✅ | `test_seed_reproducibility`, `test_all_simulated_data_is_labelled` |
| Corrélation | Chronologie, regroupement, comparaison à la référence, persistant/ponctuel, export CSV/JSON avec provenance | ✅ | `TestCorrelation` |
| Cartographie | Points de mesure, horodatages, niveaux, alertes, GPS vs estimé, hors ligne, GeoJSON | ✅ | `TestMapping` |
| Rapports | PDF et HTML, 10 sections, faits / hypothèses séparés, aucune conclusion abusive | ✅ | `TestReports`, `examples/exemple_rapport.pdf` |
| Sécurité | Journal d'audit chaîné, RBAC, protection des imports, suppression contrôlée | ✅ | `TestRbacAuditDeletion`, `TestFileProtection` |
| Configuration | Seuils de règles validés, profils d'environnement, règles désactivables (admin, audit, rapports) | ✅ | `tests/test_configuration.py` |
| | Profils de mappage d'import, constantes, aperçu des colonnes | ✅ | `TestImportProfiles` |
| | Suppression de la raie DC des récepteurs SDR | ✅ | `TestDcSuppression` (fonction testée ; chaîne SDR non testée sur matériel) |
| Sécurité | Comptes locaux (PBKDF2-SHA256, verrouillage, premier compte admin, dernier admin protégé), connexion obligatoire IHM/CLI, journalisation des connexions | ✅ | `tests/test_auth.py` |
| Configuration | Éditeur graphique des profils d'import ; rayons de cellule R07 réglables | ✅ | `test_profile_editor`, `test_cell_radius_is_configurable` |
| IHM | 12 pages, filtres, tableaux triables, graphiques interactifs, notifications, progression | ✅ | `tests/test_gui.py` (hors écran) |
| Fonctions offensives | Fausse station de base, interception, brouillage, émission, suivi | ⛔ | Exclues par conception ; `test_receive_only_interface`. |

## Limitations connues

### Analyse et détection
- Les règles sont **heuristiques** ; leurs seuils par défaut et les profils
  d'environnement sont génériques et doivent être ajustés à chaque environnement (page
  « Règles de détection » ou commande `rules`). Les rayons de cellule de R07 sont réglables
  par technologie. Les poids ont été
  calibrés sur les scénarios synthétiques, **pas sur des données de terrain**.
- Seuls les paramètres exposés par l'outil source sont analysés. Les indicateurs
  protocolaires (algorithme de chiffrement négocié, demandes d'identité, rejets
  d'enregistrement…) ne sont pas accessibles par l'import d'observations de cellules et ne
  sont **pas** évalués.
- La détection de cellules inconnues dépend entièrement de la qualité de la référence.
- R07 (spatial) ne s'appuie que sur les positions de l'équipement de mesure ; l'outil
  n'estime pas la position des émetteurs.
- Les variations spectrales (R10) ne sont pas rattachées à une cellule précise.

### Radio
- Puissances SDR en dBFS tant qu'un offset d'étalonnage n'est pas saisi ; l'offset dépend
  du gain et de la fréquence.
- Le balayage SoapySDR concatène des fenêtres de 80 % de la bande échantillonnée ; la raie
  DC est interpolée, mais les fréquences images propres à certains récepteurs ne sont pas
  filtrées.
- Les profils de mappage intégrés reposent sur des conventions de nommage génériques
  (3GPP) ; aucun format propriétaire d'outil commercial n'est intégré : le déclarer comme
  profil personnalisé.
- Les conversions EARFCN couvrent les bandes LTE usuelles (1, 2, 3, 4, 5, 7, 8, 12, 13, 20,
  28, 38, 40, 41) ; UARFCN sans décalage de bande ; ARFCN 512–810 interprétés en DCS 1800
  par défaut (option PCS 1900 dans l'API).
- GNU Radio n'est pas utilisé ; PyQtGraph non plus (Matplotlib suffit aux volumes traités).

### Simulation
- Modèle de propagation simplifié (pas de multi-trajets réalistes, pas d'interférences).
  Les scénarios servent à éprouver la logique du moteur, pas à prédire des performances
  réelles de détection.

### Sécurité
- Tant qu'aucun compte n'est créé, l'application fonctionne **sans authentification**
  (rôle issu de la configuration) et l'affiche. Après création du premier compte
  (administrateur), la connexion est obligatoire en IHM comme en ligne de commande.
- Les comptes protègent l'usage de l'application, pas les fichiers : un utilisateur
  disposant des droits du système sur la base SQLite peut la lire ou la modifier
  directement (seule l'altération du journal d'audit serait détectée).
- Le journal d'audit détecte les altérations de la chaîne mais un administrateur système
  peut supprimer la base entière ; exporter régulièrement l'empreinte de la dernière
  entrée si une preuve externe est nécessaire.
- L'écrasement avant suppression est « au mieux » : il n'offre pas de garantie sur SSD,
  systèmes de fichiers journalisés ou copies de sauvegarde. Préférer un chiffrement
  intégral du disque.
- La base n'est pas chiffrée par l'application (SQLCipher nécessiterait une dépendance
  native supplémentaire) : utiliser un chiffrement intégral du disque ou d'un volume dédié.

### Cartographie
- Pas de fond de carte (fonctionnement hors ligne) : projection locale en km. L'export
  GeoJSON permet la superposition dans un SIG hors ligne.

### Interface
- Les opérations longues (dont chaque acquisition SDR) s'exécutent une par une en
  arrière-plan ; en acquisition continue, un balayage plus lent que la période (1,5 s) fait
  sauter les déclenchements intermédiaires.
- Interface en français uniquement (traductions Qt françaises chargées pour les dialogues
  standard).

## Pistes d'évolution
- Étalonnage SDR assisté par fréquence.
- Chiffrement de la base (SQLCipher) en option.
- Constantes de profil d'import autres que la technologie depuis l'éditeur graphique
  (possibles via fichier JSON).
