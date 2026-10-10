# Autorisations requises et cadre légal

> Ce document fournit des repères généraux ; il ne constitue pas un avis juridique. Les
> règles varient selon les pays : faire valider chaque campagne de mesure par le service
> juridique ou l'autorité compétente.

## Principes appliqués par le logiciel

| Principe | Mise en œuvre |
|---|---|
| Réception passive uniquement | Aucune méthode d'émission dans `radio/` ; flux SoapySDR `RX` seulement ; test automatisé dédié. |
| Pas de fausse station de base | Le simulateur produit des tableaux de nombres ; il n'émule aucun protocole radio. |
| Pas de données d'abonnés | Aucun champ prévu ; filtre des colonnes IMSI/IMEI/TMSI/MSISDN/SUPI/SUCI à l'import ; aucun décodage de contenu. |
| Pas de suivi de personnes | La carte n'affiche que les positions de l'équipement de mesure. |
| Pas de brouillage | Aucune fonction d'émission. |
| Fonctionnement local | Base SQLite locale, aucune connexion réseau, pas de fond de carte en ligne. |
| Traçabilité | Journal d'audit chaîné, référence d'autorisation enregistrée par jeu de données et dans les rapports, empreintes SHA-256 des fichiers importés et des rapports. |
| Minimisation et suppression | Suppression contrôlée (administrateur, motif, confirmation, écrasement des fichiers importés). |

## Autorisations par type de mesure

| Type de mesure | Autorisations typiquement nécessaires | Points d'attention |
|---|---|---|
| **Spectre (densité de puissance) avec un SDR** | Généralement libre en réception dans de nombreux pays, mais pas partout. | Certaines législations restreignent la réception, l'enregistrement ou la divulgation de communications non destinées au public, même sans décodage. Ne pas conserver d'IQ bruts (désactivé par défaut). |
| **Observations de cellules via un terminal / outil de diagnostic** | Accord de l'opérateur ou du propriétaire de la ligne/du terminal ; licences des outils professionnels. | N'exporter que les paramètres d'infrastructure (cellules), jamais les identifiants des terminaux environnants. |
| **Mesures sur un site tiers** (entreprise, bâtiment) | Mandat écrit du responsable du site précisant le périmètre, la durée et les finalités. | Consigner la référence dans le champ « Autorisation ». |
| **Positions GNSS des points de mesure** | Information des personnes réalisant les mesures (données de localisation du personnel). | Durée de conservation limitée ; minimiser la précision si non nécessaire. |
| **Investigation d'une suspicion d'IMSI catcher** | Ne relève pas d'un particulier ou d'une entreprise : signaler aux autorités compétentes (régulateur des télécommunications, autorité de protection des données, police/justice) et/ou à l'opérateur. | Ne jamais tenter de « contre-mesure » active (émission, brouillage, leurre) : c'est illégal dans la plupart des juridictions. |
| **Émission radio de test** | Licence d'émission / autorisation du régulateur, cage de Faraday. | Hors périmètre : le logiciel ne propose aucune émission. |

## Repères réglementaires (non exhaustifs)

- **Union européenne** : RGPD (les identifiants de cellules associés à des positions et à des
  personnes peuvent constituer des données personnelles), directive ePrivacy
  (confidentialité des communications), législations nationales sur les équipements
  radioélectriques et l'interception (en France : Code des postes et des communications
  électroniques, article 226-3 du Code pénal encadrant les dispositifs d'interception).
- **Autres pays** : se référer au régulateur national des télécommunications (ex. ARCEP,
  ANRT, ARTCI, ART, FCC, ISED) et à l'autorité de protection des données.

## Responsabilités de l'utilisateur

1. Obtenir et consigner les autorisations **avant** la collecte.
2. Utiliser uniquement des équipements et outils dont l'usage est licite dans le pays.
3. Limiter la collecte au périmètre et à la durée nécessaires ; supprimer les données à
   l'issue de la mission (suppression contrôlée).
4. Présenter les résultats comme des **indicateurs**, jamais comme une preuve : les
   rapports du logiciel sont conçus pour cela et ne doivent pas être modifiés pour en
   durcir les conclusions.
5. Ne pas divulguer de données de mesure permettant d'identifier des personnes.
