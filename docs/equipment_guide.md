# Guide de configuration des équipements compatibles

LUNATIC IMSI LAB exploite deux familles de sources, toutes deux **passives** :

1. **Récepteurs SDR** (via SoapySDR) pour la densité spectrale de puissance — aucune
   démodulation, aucun décodage.
2. **Outils de diagnostic cellulaire** (terminaux de test, applications de mesure radio,
   scanners opérateur) dont les exports CSV/JSON sont importés.

> Avant toute mesure réelle, lire [legal_compliance.md](legal_compliance.md).

## 1. Récepteurs SDR (réception seule)

### Matériel pris en charge par SoapySDR (exemples)

| Récepteur | Plage typique | Bande instantanée | Module Soapy | Remarque |
|---|---|---|---|---|
| RTL-SDR (R820T2/R828D) | 24 MHz – 1,7 GHz | ≤ 2,4 MS/s | `soapysdr-module-rtlsdr` | Couvre 700/800/900 MHz et une partie de 1800 MHz. Économique, non étalonné. |
| Airspy R2 / Mini | 24 MHz – 1,8 GHz | 6–10 MS/s | `soapysdr-module-airspy` | Meilleure dynamique. |
| SDRplay RSP | 1 kHz – 2 GHz | ≤ 10 MS/s | `SoapySDRPlay3` | Nécessite l'API SDRplay. |
| HackRF One | 1 MHz – 6 GHz | ≤ 20 MS/s | `soapysdr-module-hackrf` | Utilisé **en réception uniquement** par le logiciel. |
| USRP (B2xx…) | 70 MHz – 6 GHz | ≤ 56 MS/s | `soapysdr-module-uhd` | Utilisé **en réception uniquement**. |

Le code n'ouvre que des flux `SOAPY_SDR_RX` ; aucune fonction d'émission n'est présente
(vérifié par `tests/test_radio_storage.py::TestReceivers::test_receive_only_interface`).
Pour les équipements capables d'émettre, il est recommandé de **ne pas raccorder d'antenne
au port TX** et de conserver un firmware/une configuration par défaut.

### Installation

SoapySDR n'est pas distribué via `pip`. Exemples :

```bash
# Debian / Ubuntu
sudo apt install python3-soapysdr soapysdr-tools soapysdr-module-rtlsdr
# conda-forge (toutes plateformes)
conda install -c conda-forge soapysdr soapysdr-module-rtlsdr
```

Si l'environnement virtuel ne voit pas le module système, créer le venv avec
`python3 -m venv --system-site-packages .venv`.

Vérification :

```bash
SoapySDRUtil --find
python -m lunatic_imsi_lab devices
```

### Déclaration dans l'application

Page **Équipements & configuration** → « Ajouter / modifier un récepteur » :

| Champ | Exemple |
|---|---|
| Nom | `RTL-SDR labo` |
| Pilote | `soapy` |
| Arguments | `driver=rtlsdr` (ou `driver=rtlsdr,serial=00000001`) |
| Échantillonnage | 2,4 MS/s |
| Gain | 30 dB (éviter la saturation : le plancher de bruit doit rester stable) |

Puis **Analyseur de spectre** → choisir le récepteur, la plage (ex. 925–960 MHz) et
« Acquérir un balayage » ou « Acquisition continue ». Les balayages sont enregistrés dans
le jeu de données courant.

### Étalonnage

Sans étalonnage, les valeurs sont des **dBFS** relatifs (indiqué dans les paramètres de
collecte et sur les graphiques). Pour exprimer des dBm :

1. injecter un signal de niveau connu (générateur étalonné, liaison **câblée** avec
   atténuateur, jamais rayonnée) à la fréquence d'intérêt ;
2. relever la puissance de canal mesurée en dBFS ;
3. offset = niveau connu (dBm) − mesure (dBFS) ; le saisir dans le champ « Étalonnage »
   du récepteur (page Équipements). L'offset dépend du gain et de la fréquence : le
   déterminer pour chaque configuration utilisée.

### Bonnes pratiques de mesure

- Position fixe et antenne fixe pour les mesures de référence ; noter l'orientation.
- Vérifier la stabilité sur une charge 50 Ω (plancher de bruit, raies parasites internes).
- Ne pas modifier le gain pendant une série (les variations seraient interprétées comme
  des anomalies de puissance).
- Synchroniser l'horloge (NTP/GNSS) de l'ordinateur et des outils de diagnostic.

## 2. Outils de diagnostic cellulaire

Toute source capable d'exporter, pour chaque mesure, l'horodatage, la technologie, le
MCC/MNC, le LAC/TAC, l'identifiant de cellule, le canal et la puissance convient :
terminaux et logiciels de test radio professionnels, applications de diagnostic réseau
autorisées, scanners de l'opérateur. Le format attendu est décrit dans
[modules.md](modules.md#importers--connecteur-dimport).

Exemple minimal :

```csv
timestamp,technology,mcc,mnc,tac,eci,earfcn,pci,rsrp,rsrq,lat,lon,gps_fix,serving
2026-01-15T10:00:00Z,LTE,208,10,31010,123456,1300,101,-85,-11,48.85,2.35,GPS,1
```

- Indiquer `gps_fix=GPS` uniquement pour les positions issues d'un récepteur GNSS ; toute
  autre position est traitée comme **estimée** (marqueur ▲ et poids réduit des règles
  spatiales).
- Si l'outil exporte des dates sans fuseau, renseigner le fuseau à l'import (`--tz`).
- Les éventuelles colonnes IMSI/IMEI/TMSI/MSISDN sont supprimées à l'import : il est
  préférable de **ne pas les exporter** depuis l'outil source.
- Paramètres diffusés accessibles (ex. nombre de voisines, offsets de resélection,
  temporisateurs) : colonnes `bcast_<nom>`.

## 3. Constituer une référence

La qualité des règles comparatives (R01, R02, R03, R09) dépend de la référence :
plusieurs jours, différentes heures, mêmes emplacements et même équipement que les
mesures analysées. Une référence de moins de 30 mesures est signalée comme courte et réduit
la confiance des alertes.
