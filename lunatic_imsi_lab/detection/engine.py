"""Moteur de détection : exécute les règles, agrège les indicateurs en alertes
et produit une évaluation globale prudente.

Principes :

* la confiance d'une alerte combine les poids des règles *distinctes*
  (1 − Π(1 − wᵢ)) ;
* une alerte reposant sur **un seul** indicateur voit sa confiance plafonnée
  au niveau « Faible » ;
* un manque de données (référence vide ou trop courte, peu d'observations)
  réduit la confiance et est signalé ;
* aucun niveau « confirmé » n'existe : l'évaluation la plus forte invite à
  une investigation complémentaire.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from lunatic_imsi_lab.core.models import (Alert, CellObservation, ConfidenceLevel, Indicator,
                                          Severity)
from lunatic_imsi_lab.core.timeutils import utcnow
from lunatic_imsi_lab.detection.baseline import Baseline
from lunatic_imsi_lab.detection.rules import DEFAULT_RULES, Rule, RuleConfig
from lunatic_imsi_lab.radio.spectrum import PowerVariation

SINGLE_INDICATOR_CAP = 0.40
MIN_BASELINE_OBSERVATIONS = 30
MIN_OBSERVATIONS = 10


class Assessment:
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NO_INDICATOR = "NO_INDICATOR"
    ISOLATED_INDICATORS = "ISOLATED_INDICATORS"
    CONVERGENT_INDICATORS = "CONVERGENT_INDICATORS"

    TEXT = {
        INSUFFICIENT_DATA: "Données insuffisantes pour conclure. Étendre la période de "
                           "référence et la collecte avant toute interprétation.",
        NO_INDICATOR: "Aucun indicateur d'anomalie relevé sur la période analysée. Cela ne "
                      "prouve pas l'absence de menace : seuls les phénomènes observables "
                      "par les sources utilisées ont été examinés.",
        ISOLATED_INDICATORS: "Indicateurs isolés relevés. Chacun peut s'expliquer par un "
                             "phénomène légitime (mobilité, maintenance, couverture). Aucune "
                             "conclusion ne peut en être tirée sans vérifications.",
        CONVERGENT_INDICATORS: "Plusieurs indicateurs convergents relevés sur une même "
                               "cellule. Cette situation justifie une investigation "
                               "complémentaire ; elle ne constitue PAS une identification "
                               "d'IMSI catcher.",
    }


@dataclass
class AnalysisResult:
    alerts: list[Alert]
    indicators: list[Indicator]
    assessment: str
    assessment_text: str
    data_quality: list[str] = field(default_factory=list)
    observation_count: int = 0
    baseline_summary: dict = field(default_factory=dict)
    is_simulation: bool = False


def _severity(score: float) -> Severity:
    if score < 0.2:
        return Severity.INFO
    if score < 0.45:
        return Severity.LOW
    if score < 0.7:
        return Severity.MEDIUM
    return Severity.HIGH


def _alert_id(cell_key, rules: Iterable[str], first_seen) -> str:
    raw = f"{cell_key}|{sorted(set(rules))}|{first_seen.isoformat()}"
    return f"ALR-{first_seen:%Y%m%d}-{hashlib.sha1(raw.encode()).hexdigest()[:8].upper()}"


def spectrum_indicators(variations: Sequence[PowerVariation],
                        is_simulation: bool = False) -> list[Indicator]:
    """Convertit des variations spectrales en indicateurs (groupés par fréquence)."""
    groups: dict[int, list[PowerVariation]] = defaultdict(list)
    for v in variations:
        groups[int(round(v.center_hz / 1e5))].append(v)
    out = []
    for _, vs in groups.items():
        f_mhz = vs[0].center_hz / 1e6
        weight = 0.15 if len(vs) < 3 else 0.2
        out.append(Indicator(
            rule_id="R10_SPECTRUM_POWER", rule_name="Variation spectrale inhabituelle",
            timestamp=min(v.timestamp for v in vs), cell_key=("SPECTRUM", round(f_mhz, 1)),
            description=f"Variation de puissance inhabituelle autour de {f_mhz:.2f} MHz",
            technical_details="; ".join(f"{v.timestamp:%H:%M:%S} Δ={v.delta_db:+.1f} dB "
                                        f"(z={v.zscore:+.1f})" for v in vs[:10]),
            weight=weight,
            false_positives=["Variation de charge du trafic", "Évanouissement / obstacle mobile",
                             "Réglage du gain du récepteur", "Émetteur légitime intermittent"],
            recommended_checks=["Vérifier la stabilité du récepteur sur une charge 50 Ω",
                                "Comparer avec un second récepteur"],
            is_simulation=is_simulation))
    return out


class DetectionEngine:
    def __init__(self, rules: Sequence[Rule] | None = None,
                 config: RuleConfig | None = None) -> None:
        self.config = config or RuleConfig()
        self.rules = list(rules) if rules is not None else [r(self.config) for r in DEFAULT_RULES]

    def run(self, observations: Sequence[CellObservation], baseline: Baseline | None = None,
            extra_indicators: Sequence[Indicator] = ()) -> AnalysisResult:
        baseline = baseline or Baseline()
        observations = sorted(observations, key=lambda o: o.timestamp)
        is_sim = any(o.provenance.is_simulation for o in observations)
        indicators: list[Indicator] = list(extra_indicators)
        for rule in self.rules:
            indicators.extend(rule.evaluate(observations, baseline))

        data_quality = []
        if baseline.is_empty:
            data_quality.append("Aucun environnement de référence : les règles comparatives "
                                "(R01, R02, R03, R09) n'ont pas pu être appliquées.")
        elif baseline.observation_count < MIN_BASELINE_OBSERVATIONS:
            data_quality.append(f"Référence courte ({baseline.observation_count} mesures < "
                                f"{MIN_BASELINE_OBSERVATIONS}) : confiance réduite.")
        if len(observations) < MIN_OBSERVATIONS:
            data_quality.append(f"Peu d'observations ({len(observations)} < {MIN_OBSERVATIONS}).")
        quality_factor = 0.5 if data_quality else 1.0

        obs_index = {o.id: o for o in observations}
        groups: dict[object, list[Indicator]] = defaultdict(list)
        for ind in indicators:
            groups[ind.cell_key].append(ind)

        alerts = []
        now = utcnow()
        for cell_key, inds in groups.items():
            best: dict[str, float] = {}
            for i in inds:
                best[i.rule_id] = max(best.get(i.rule_id, 0.0), i.weight)
            prod = 1.0
            for w in best.values():
                prod *= (1.0 - w)
            score = 1.0 - prod
            notes = []
            if len(best) == 1:
                if score > SINGLE_INDICATOR_CAP:
                    notes.append("Confiance plafonnée : un seul type d'indicateur.")
                score = min(score, SINGLE_INDICATOR_CAP)
            score *= quality_factor
            if quality_factor < 1:
                notes.append("Confiance réduite : données ou référence insuffisantes.")
            obs_ids = list(dict.fromkeys(oid for i in inds for oid in i.observation_ids))
            first = min(i.timestamp for i in inds)
            times = [obs_index[o].timestamp for o in obs_ids if o in obs_index] or [first]
            sources = sorted({obs_index[o].provenance.label for o in obs_ids if o in obs_index}
                             or ({"SIMULATION"} if is_sim else {"spectre"}))
            explanation = [f"[{i.rule_id}] {i.description} — {i.technical_details}" for i in inds]
            explanation += notes
            fps = list(dict.fromkeys(fp for i in inds for fp in i.false_positives))
            checks = list(dict.fromkeys(c for i in inds for c in i.recommended_checks))
            if len(best) == 1:
                checks.append("Rechercher d'autres indicateurs indépendants avant toute "
                              "interprétation (un indicateur isolé n'est pas concluant).")
            rules_sorted = sorted(best)
            severity = _severity(score)
            priority = int(round(min(100, 100 * score + 5 * (len(best) - 1))))
            summary = (inds[0].description if len(inds) == 1 else
                       f"{len(best)} règle(s) distincte(s) déclenchée(s) : "
                       + ", ".join(rules_sorted))
            alerts.append(Alert(
                alert_id=_alert_id(cell_key, rules_sorted, first), created_at=now,
                first_seen=min(min(times), first), last_seen=max(times), cell_key=cell_key,
                rules=rules_sorted, priority=priority, confidence_score=score,
                confidence=ConfidenceLevel.from_score(score), severity=severity,
                summary=summary, explanation=explanation, false_positives=fps,
                recommended_checks=checks, observation_ids=obs_ids, sources=sources,
                is_simulation=is_sim or any(i.is_simulation for i in inds), indicators=inds))
        alerts.sort(key=lambda a: (-a.priority, a.first_seen))

        if data_quality and (baseline.is_empty or len(observations) < MIN_OBSERVATIONS):
            assessment = Assessment.INSUFFICIENT_DATA
        elif not alerts or all(a.severity == Severity.INFO for a in alerts):
            assessment = Assessment.NO_INDICATOR
        elif any(a.distinct_rule_count >= 2 and a.confidence_score >= 0.45 for a in alerts):
            assessment = Assessment.CONVERGENT_INDICATORS
        else:
            assessment = Assessment.ISOLATED_INDICATORS
        return AnalysisResult(alerts=alerts, indicators=indicators, assessment=assessment,
                              assessment_text=Assessment.TEXT[assessment],
                              data_quality=data_quality, observation_count=len(observations),
                              baseline_summary=baseline.summary(), is_simulation=is_sim)
