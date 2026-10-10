# LUNATIC IMSI LAB

Plateforme Python **défensive** de détection et d'analyse des menaces sur les réseaux
cellulaires (2G/3G/4G/5G) : analyse de spectre en réception seule, import d'observations de
cellules issues d'outils de diagnostic autorisés, détection heuristique d'indicateurs
compatibles avec un IMSI catcher, corrélation, cartographie hors ligne et rapports PDF/HTML.

> **Ce que le logiciel ne fait pas, par conception** : aucune émission radio, aucune fausse
> station de base, aucune interception ou collecte d'identifiants d'abonnés ou d'appareils
> (IMSI, IMEI, TMSI, MSISDN…), aucun décodage de trafic, aucun brouillage, aucun suivi de
> personnes. L'outil ne conclut **jamais** à la présence certaine d'un IMSI catcher.

![Statut](https://img.shields.io/badge/tests-158%20réussis-2f8bff) ![Python](https://img.shields.io/badge/python-3.12%2B-c0c7d1)

## Démarrage rapide

```bash
# Linux / macOS
scripts/install.sh          # crée .venv, installe les dépendances, exécute les tests
scripts/run.sh              # lance l'interface graphique

# Windows
scripts\install.bat
scripts\run.bat
```

Sans installation (dépendances déjà présentes) :

```bash
pip install -r requirements.txt
python -m lunatic_imsi_lab gui
```

### Premier essai en mode SIMULATION

```bash
# Scénario synthétique multi-indicateurs, analyse et rapport PDF/HTML
python -m lunatic_imsi_lab simulate --scenario synthetic_anomaly --report --out ./rapports

# Scénario légitime (aucune alerte significative attendue)
python -m lunatic_imsi_lab simulate --scenario normal
```

Dans l'interface : **Laboratoire de simulation → Lancer la simulation et l'analyse**, puis
parcourir le tableau de bord, les anomalies, la chronologie et la carte. Toutes les données
synthétiques portent la mention **SIMULATION** (bandeau rouge, base, exports, rapports).

### Analyser des mesures réelles autorisées

```bash
# 1. Référence : période où l'environnement radio est réputé sain
python -m lunatic_imsi_lab import ref.csv --source "Outil de diagnostic X" \
       --dataset site-A-ref --authorization "AUT-2026-014" --tz Europe/Paris
# 2. Période à analyser
python -m lunatic_imsi_lab import mesures.csv --source "Outil de diagnostic X" \
       --dataset site-A --authorization "AUT-2026-014" --tz Europe/Paris
# 3. Analyse, export et rapport
python -m lunatic_imsi_lab analyze --dataset site-A --baseline site-A-ref \
       --report --export ./export --scope "Site A, bâtiment 2, 3e étage"
```

Format d'import (CSV `,` `;` ou tabulation, ou JSON) : voir
[`docs/modules.md`](docs/modules.md#importers--connecteur-dimport). Les colonnes
d'identifiants personnels éventuellement présentes sont supprimées sans être lues.
Pour un export dont les noms de colonnes ne sont pas reconnus automatiquement, utiliser un
profil de mappage (`--profile nr-3gpp`, `lte-only`, `gsm-only` ou un fichier JSON via
`--profile-file`) et vérifier d'abord l'interprétation avec `preview`.

### Adapter les seuils à l'environnement

```bash
python -m lunatic_imsi_lab --role admin rules --profile fixe          # point fixe en intérieur
python -m lunatic_imsi_lab --role admin rules --set jump_db=15        # ajustement fin
```

Profils : `urbain` (défaut), `fixe`, `vehicule`, `rural`. Le plafond de confiance d'un
indicateur isolé et les pondérations restent fixes.

## Commandes

| Commande | Rôle |
|---|---|
| `gui` | Interface graphique PySide6 |
| `simulate` | Scénario SIMULATION (`normal`, `coverage_change`, `power_variation`, `parameter_change`, `inconsistent`, `synthetic_anomaly`) |
| `import` | Import CSV/JSON protégé (empreinte SHA-256, copie en lecture seule) |
| `analyze` | Détection d'anomalies sur un jeu, avec ou sans référence |
| `datasets` | Liste des jeux de données |
| `delete` | Suppression contrôlée (administrateur, motif + confirmation, journalisée) |
| `audit --verify` | Vérification de l'intégrité du journal d'audit chaîné |
| `generate-synthetic DIR` | Régénère les jeux synthétiques reproductibles |
| `devices` | Détection des récepteurs SoapySDR |
| `preview FICHIER [--profile]` | Aperçu de l'interprétation des colonnes avant import |
| `profiles` | Profils de mappage d'import disponibles |
| `rules [--profile] [--set P=V] [--disable R..]` | Afficher / modifier les seuils de détection (admin) |

Options globales : `--data-dir`, `--user`, `--role {viewer,analyst,admin}`, `-v`.

## Interface graphique

Navigation latérale : tableau de bord · analyseur de spectre · explorateur de cellules ·
anomalies · chronologie / corrélation · cartographie · laboratoire de simulation · console
technique · rapports · règles de détection · équipements & configuration. Tableaux triables et filtrables,
graphiques interactifs (zoom, déplacement, export), notifications dans la barre d'état,
indicateur de progression pour les tâches de fond.

## Arborescence

```
lunatic_imsi_lab/
  core/          modèles, calculs de puissance, canaux↔fréquences, horodatages, géodésie
  storage/       persistance SQLite (SQLAlchemy)
  importers/     connecteur CSV/JSON + filtre de confidentialité
  radio/         analyse spectrale, récepteurs (simulé, SoapySDR — réception seule)
  detection/     référence, règles heuristiques, moteur d'agrégation prudent
  simulation/    laboratoire virtuel (cellules, spectres), jeux de données synthétiques
  correlation/   chronologie, regroupement, comparaison à la référence, export, pandas
  mapping/       cartographie hors ligne, GeoJSON
  reports/       contenu, graphiques, rendu HTML et PDF
  security/      RBAC, audit chaîné, protection des fichiers, suppression contrôlée
  gui/           interface PySide6
  services.py    couche de services partagée IHM / CLI
  cli.py         ligne de commande
data/synthetic/  jeux de données synthétiques reproductibles (SIMULATION)
examples/        exemple de rapport PDF et HTML
docs/            documentation
tests/           tests automatisés (pytest)
```

## Documentation

- [Documentation des modules](docs/modules.md)
- [Guide de configuration des équipements](docs/equipment_guide.md)
- [Autorisations et cadre légal](docs/legal_compliance.md)
- [Bilan des fonctionnalités et limitations](docs/status_and_limitations.md)

## Tests

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

Les tests couvrent les calculs de puissance, les conversions de canaux, l'import et le filtre
de confidentialité, les horodatages, chaque règle de détection, les faux positifs (scénarios
légitimes), les situations de données insuffisantes, la génération de rapports (absence de
conclusion abusive), la sécurité (RBAC, audit, suppression) et l'interface (tests de fumée
hors écran).
