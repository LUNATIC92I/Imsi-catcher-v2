"""Construction du contenu d'un rapport d'analyse (indépendant du format).

Le rapport sépare strictement :

* **Faits observés** — valeurs mesurées ou importées, avec leur source ;
* **Résultats d'analyse** — règles déclenchées et scores calculés ;
* **Hypothèses** — interprétations possibles, toujours accompagnées
  d'hypothèses alternatives légitimes.

Il ne contient jamais d'affirmation d'identification d'un IMSI catcher.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

from lunatic_imsi_lab import APP_NAME, SIMULATION_LABEL, __version__
from lunatic_imsi_lab.core.models import CellObservation, SpectrumSweep
from lunatic_imsi_lab.core.timeutils import utcnow
from lunatic_imsi_lab.detection.engine import AnalysisResult, Assessment
from lunatic_imsi_lab.detection.rules import DEFAULT_RULES
from lunatic_imsi_lab.radio.spectrum import detect_emissions
from lunatic_imsi_lab.reports import charts

DISCLAIMER = (
    "Ce rapport présente des indicateurs heuristiques. Aucun indicateur, ni aucune "
    "combinaison d'indicateurs, ne permet à lui seul d'établir la présence d'un IMSI catcher. "
    "Les phénomènes légitimes (mobilité, maintenance, évolution de couverture, incidents "
    "radio, limites des outils de mesure) peuvent produire des observations similaires.")

LIMITATIONS = [
    "Seuls les paramètres exposés par les outils de diagnostic utilisés sont analysés ; "
    "les couches protocolaires non accessibles ne sont pas évaluées.",
    "La qualité des conclusions dépend de la durée et de la représentativité de "
    "l'environnement de référence.",
    "Les puissances issues d'un récepteur SDR non étalonné sont relatives (dBFS).",
    "Les positions estimées (non GNSS) peuvent comporter des erreurs importantes.",
    "Les seuils des règles sont génériques et doivent être ajustés à l'environnement "
    "radio étudié.",
]


@dataclass
class ReportSection:
    title: str
    paragraphs: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    table: list[list[str]] | None = None   # première ligne = en-têtes
    images: list[tuple[str, bytes]] = field(default_factory=list)  # (légende, PNG)


@dataclass
class ReportContent:
    title: str
    generated_at: datetime
    is_simulation: bool
    assessment: str
    assessment_text: str
    sections: list[ReportSection]
    disclaimer: str = DISCLAIMER

    @property
    def banner(self) -> str:
        return (f"{SIMULATION_LABEL} — DONNÉES SYNTHÉTIQUES, AUCUNE MESURE RÉELLE"
                if self.is_simulation else "MESURES AUTORISÉES")


@dataclass
class ReportInput:
    title: str
    scope: str
    operator: str
    authorization_ref: str
    observations: Sequence[CellObservation]
    analysis: AnalysisResult
    sweeps: Sequence[SpectrumSweep] = ()
    equipment: Sequence[str] = ()
    measurement_parameters: dict | None = None
    include_charts: bool = True


def _fmt(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC") if dt else "n/d"


def build_report(inp: ReportInput) -> ReportContent:
    obs = sorted(inp.observations, key=lambda o: o.timestamp)
    res = inp.analysis
    is_sim = (res.is_simulation or any(o.provenance.is_simulation for o in obs)
              or any(s.provenance.is_simulation for s in inp.sweeps))
    sections: list[ReportSection] = []

    # 1. Périmètre
    sections.append(ReportSection("1. Périmètre de l'analyse", paragraphs=[
        inp.scope or "Périmètre non précisé.",
        f"Opérateur de l'analyse : {inp.operator or 'n/d'}.",
        f"Référence d'autorisation : {inp.authorization_ref or 'NON RENSEIGNÉE'}.",
    ] + ([f"ATTENTION — {SIMULATION_LABEL} : toutes les données de ce rapport sont synthétiques."]
         if is_sim else [])))

    # 2. Équipements et sources
    sources = Counter(o.provenance.label for o in obs)
    methods = sorted({o.provenance.method for o in obs} | {s.provenance.method
                                                             for s in inp.sweeps})
    sections.append(ReportSection("2. Équipements et sources", bullets=(
        [f"Équipement : {e}" for e in inp.equipment]
        + [f"Source : {s} ({n} observations)" for s, n in sources.most_common()]
        + [f"Source spectrale : {s.provenance.label}" for s in inp.sweeps[:1]]
        + [f"Méthodes de collecte : {', '.join(methods) or 'n/d'}"])))

    # 3. Période
    start = obs[0].timestamp if obs else None
    end = obs[-1].timestamp if obs else None
    bs = res.baseline_summary
    sections.append(ReportSection("3. Période d'observation", bullets=[
        f"Observations analysées : {_fmt(start)} → {_fmt(end)}",
        f"Référence : {bs.get('start') or 'n/d'} → {bs.get('end') or 'n/d'} "
        f"({bs.get('observations', 0)} mesures, {bs.get('cells', 0)} cellules)",
    ]))

    # 4. Paramètres de mesure
    params = dict(inp.measurement_parameters or {})
    if obs:
        for k, v in obs[0].provenance.parameters.items():
            params.setdefault(k, v)
    sections.append(ReportSection("4. Paramètres de mesure", table=[["Paramètre", "Valeur"]] + [
        [str(k), str(v)] for k, v in sorted(params.items())][:40]
        if params else None, paragraphs=[] if params else ["Aucun paramètre consigné."]))

    # 5. Faits observés
    per_cell: dict[tuple, list[CellObservation]] = {}
    for o in obs:
        per_cell.setdefault(o.cell_key, []).append(o)
    table = [["Cellule", "Canal", "Fréq. (MHz)", "Obs.", "P. min/méd/max (dBm)", "Première",
              "Dernière"]]
    for key, items in sorted(per_cell.items(), key=lambda kv: -len(kv[1]))[:40]:
        r = sorted(o.rssi_dbm for o in items if o.rssi_dbm is not None)
        table.append([items[0].cell_label, str(items[0].channel),
                      f"{items[0].frequency_mhz:.1f}" if items[0].frequency_mhz else "n/d",
                      str(len(items)),
                      f"{r[0]:.0f} / {r[len(r)//2]:.0f} / {r[-1]:.0f}" if r else "n/d",
                      f"{items[0].timestamp:%H:%M:%S}", f"{items[-1].timestamp:%H:%M:%S}"])
    tech = Counter(o.technology.value for o in obs)
    radio = ReportSection("5. Observations radio (faits observés)", paragraphs=[
        f"{len(obs)} observations, {len(per_cell)} cellules distinctes. Technologies : "
        + (", ".join(f"{t} ({n})" for t, n in tech.most_common()) or "aucune") + "."],
        table=table if len(table) > 1 else None)
    if inp.sweeps:
        last = inp.sweeps[-1]
        ems = detect_emissions(last)
        radio.bullets += [f"Émission à {e.center_mhz:.3f} MHz, largeur ≈ {e.bandwidth_hz/1e3:.0f} "
                          f"kHz, puissance canal {e.channel_power_dbm:.1f}, SNR {e.snr_db:.1f} dB"
                          for e in ems[:15]]
        if inp.include_charts:
            radio.images.append(("Spectre (dernier balayage)", charts.spectrum_png(last, ems)))
    if inp.include_charts and obs:
        radio.images.append(("Puissance par cellule", charts.rssi_png(obs, res.alerts)))
        if any(o.has_position for o in obs):
            radio.images.append(("Carte des points de mesure (cercle : position GPS ; triangle : position estimée)",
                                 charts.map_png(obs, res.alerts)))
    sections.append(radio)

    # 6. Anomalies (résultats d'analyse)
    atable = [["Alerte", "Début", "Règles", "Priorité", "Confiance", "Sévérité"]]
    for a in res.alerts[:50]:
        atable.append([a.alert_id, f"{a.first_seen:%Y-%m-%d %H:%M}", ", ".join(a.rules),
                       str(a.priority), a.confidence.value, a.severity.value])
    anomalies = ReportSection("6. Anomalies relevées (résultats d'analyse)",
                              paragraphs=[f"Évaluation globale : {res.assessment_text}"]
                              + [f"Qualité des données : {q}" for q in res.data_quality],
                              table=atable if res.alerts else None)
    if not res.alerts:
        anomalies.paragraphs.append("Aucune alerte générée.")
    for a in res.alerts[:10]:
        anomalies.bullets.append(f"{a.alert_id} — {a.summary}")
        anomalies.bullets += [f"    • {e}" for e in a.explanation[:6]]
    sections.append(anomalies)

    # 7. Règles déclenchées
    triggered = Counter(r for a in res.alerts for r in a.rules)
    names = {r.rule_id: r.name for r in DEFAULT_RULES}
    names["R10_SPECTRUM_POWER"] = "Variation spectrale inhabituelle"
    sections.append(ReportSection("7. Règles déclenchées", table=[["Règle", "Description",
                                                                   "Alertes"]] + [
        [r, names.get(r, r), str(n)] for r, n in sorted(triggered.items())]
        if triggered else None, paragraphs=[] if triggered else ["Aucune règle déclenchée."]))

    # 8. Limites
    sections.append(ReportSection("8. Limites de l'analyse", bullets=LIMITATIONS
                                  + res.data_quality))

    # 9. Hypothèses
    fps = list(dict.fromkeys(fp for a in res.alerts for fp in a.false_positives))
    hyp = ReportSection("9. Hypothèses et hypothèses alternatives", paragraphs=[
        "Les éléments ci-dessous sont des HYPOTHÈSES, pas des faits établis."])
    if res.assessment == Assessment.CONVERGENT_INDICATORS:
        hyp.bullets.append("Hypothèse à examiner : un équipement radio non autorisé pourrait "
                           "être à l'origine des indicateurs convergents. Cette hypothèse "
                           "n'est pas démontrée par la présente analyse.")
    hyp.bullets += [f"Hypothèse alternative : {fp}" for fp in fps[:20]] or [
        "Aucune anomalie : pas d'hypothèse spécifique à examiner."]
    sections.append(hyp)

    # 10. Recommandations
    recs = list(dict.fromkeys(c for a in res.alerts for c in a.recommended_checks))
    recs += ["Conserver les fichiers sources et leurs empreintes SHA-256 pour toute "
             "investigation ultérieure.",
             "En cas de suspicion persistante, saisir les autorités ou l'opérateur compétents ; "
             "ne pas tenter d'investigation radio active sans habilitation."]
    sections.append(ReportSection("10. Recommandations pour les investigations complémentaires",
                                  bullets=recs[:20]))

    sections.append(ReportSection("Annexe — Génération", bullets=[
        f"{APP_NAME} v{__version__}", f"Généré le {_fmt(utcnow())}"]))
    return ReportContent(title=inp.title, generated_at=utcnow(), is_simulation=is_sim,
                         assessment=res.assessment, assessment_text=res.assessment_text,
                         sections=sections)
