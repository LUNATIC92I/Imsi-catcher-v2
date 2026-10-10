"""Interface en ligne de commande.

Exemples ::

    python -m lunatic_imsi_lab gui
    python -m lunatic_imsi_lab simulate --scenario synthetic_anomaly --report
    python -m lunatic_imsi_lab import mesures.csv --source "Outil X" --dataset site-A
    python -m lunatic_imsi_lab analyze --dataset site-A --baseline site-A-ref --report
    python -m lunatic_imsi_lab generate-synthetic data/synthetic
    python -m lunatic_imsi_lab audit --verify
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from lunatic_imsi_lab import APP_NAME, __version__
from lunatic_imsi_lab.config import AppConfig
from lunatic_imsi_lab.security.rbac import Role, User
from lunatic_imsi_lab.simulation.cells import Scenario, SimulationParams


def _lab(args):
    from lunatic_imsi_lab.services import Lab
    cfg = AppConfig.load(Path(args.data_dir) / "config.json") if args.data_dir else AppConfig.load()
    if args.data_dir:
        cfg.data_dir = args.data_dir
    user = User(args.user or cfg.operator_name, Role(args.role or cfg.operator_role))
    return Lab(cfg, user)


def _print_result(res) -> None:
    print(f"\nÉvaluation : {res.assessment}\n  {res.assessment_text}")
    for q in res.data_quality:
        print(f"  [données] {q}")
    print(f"\n{len(res.alerts)} alerte(s) :")
    for a in res.alerts:
        sim = " [SIMULATION]" if a.is_simulation else ""
        print(f"  {a.alert_id}{sim} prio={a.priority:3d} {a.severity.value:6s} "
              f"confiance={a.confidence.value} règles={','.join(a.rules)}")
        print(f"      {a.summary}")


def cmd_simulate(args) -> int:
    lab = _lab(args)
    params = SimulationParams(scenario=Scenario(args.scenario), seed=args.seed,
                              duration_minutes=args.duration, n_cells=args.cells)
    res = lab.run_simulation(params)
    print(f"[SIMULATION] scénario « {params.scenario.label} » — "
          f"{len(res.baseline)} mesures de référence, {len(res.observations)} observations")
    for e in res.truth.events:
        print(f"  vérité terrain : {e}")
    _print_result(lab.analyze())
    if args.report:
        for p in lab.generate_report(f"Simulation — {params.scenario.label}",
                                     "Évaluation du moteur de détection sur données "
                                     "synthétiques (SIMULATION).", args.out):
            print(f"Rapport : {p}")
    if args.export:
        for p in lab.export(args.export):
            print(f"Export : {p}")
    return 0


def cmd_import(args) -> int:
    lab = _lab(args)
    rep = lab.import_file(args.file, source=args.source, dataset=args.dataset,
                          authorization_ref=args.authorization or "", assume_tz=args.tz)
    print(f"{rep.rows_imported} ligne(s) importée(s), {rep.rows_rejected} rejetée(s).")
    for w in rep.warnings[:20]:
        print(f"  avertissement : {w}")
    for e in rep.errors[:20]:
        print(f"  erreur : {e}")
    return 0 if rep.rows_imported else 1


def cmd_analyze(args) -> int:
    lab = _lab(args)
    lab.load(args.dataset, args.baseline or "")
    if not lab.ws.observations:
        print(f"Aucune observation dans le jeu « {args.dataset} ».", file=sys.stderr)
        return 1
    _print_result(lab.analyze())
    if args.report:
        for p in lab.generate_report(args.title or f"Analyse — {args.dataset}",
                                     args.scope or "", args.out):
            print(f"Rapport : {p}")
    if args.export:
        for p in lab.export(args.export):
            print(f"Export : {p}")
    return 0


def cmd_datasets(args) -> int:
    lab = _lab(args)
    for d in lab.db.list_datasets():
        tag = " [SIMULATION]" if d.is_simulation else ""
        print(f"{d.name}{tag}  {lab.db.count_observations(d.name)} obs.  {d.description}")
    return 0


def cmd_delete(args) -> int:
    lab = _lab(args)
    print(json.dumps(lab.delete_dataset(args.dataset, args.reason, args.confirm), indent=1))
    return 0


def cmd_audit(args) -> int:
    lab = _lab(args)
    if args.verify:
        ok, bad = lab.audit.verify()
        print("Journal d'audit intègre." if ok else f"Journal ALTÉRÉ à l'entrée {bad}.")
        return 0 if ok else 2
    for e in reversed(lab.audit.entries(args.limit)):
        print(f"{e.timestamp:%Y-%m-%d %H:%M:%S} {e.user}({e.role}) {e.action} {e.details}")
    return 0


def cmd_generate_synthetic(args) -> int:
    from lunatic_imsi_lab.simulation.dataset import write_lab_datasets
    for p in write_lab_datasets(args.directory, seed=args.seed):
        print(p)
    return 0


def cmd_devices(args) -> int:
    from lunatic_imsi_lab.radio.receivers import SoapyReceiver
    print("SoapySDR disponible :", SoapyReceiver.module_available())
    for d in SoapyReceiver.enumerate_devices():
        print("  ", d)
    return 0


def cmd_gui(args) -> int:
    from lunatic_imsi_lab.gui.app import run
    return run(data_dir=args.data_dir)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lunatic_imsi_lab",
                                description=f"{APP_NAME} v{__version__} — analyse défensive")
    p.add_argument("--data-dir", help="répertoire de données (défaut ~/.lunatic_imsi_lab)")
    p.add_argument("--user", help="nom de l'opérateur")
    p.add_argument("--role", choices=[r.value for r in Role])
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("gui", help="lancer l'interface graphique")
    s.set_defaults(func=cmd_gui)

    s = sub.add_parser("simulate", help="exécuter un scénario de SIMULATION")
    s.add_argument("--scenario", default="synthetic_anomaly", choices=[x.value for x in Scenario])
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--duration", type=float, default=120.0, help="minutes")
    s.add_argument("--cells", type=int, default=6)
    s.add_argument("--report", action="store_true")
    s.add_argument("--export", help="répertoire d'export CSV/JSON")
    s.add_argument("--out", help="répertoire des rapports")
    s.set_defaults(func=cmd_simulate)

    s = sub.add_parser("import", help="importer des observations (CSV/JSON)")
    s.add_argument("file")
    s.add_argument("--source", required=True, help="outil / équipement d'origine")
    s.add_argument("--dataset", default="default")
    s.add_argument("--authorization", help="référence de l'autorisation de mesure")
    s.add_argument("--tz", help="fuseau des horodatages naïfs (ex. Europe/Paris)")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("analyze", help="analyser un jeu de données")
    s.add_argument("--dataset", required=True)
    s.add_argument("--baseline", help="jeu de données de référence")
    s.add_argument("--report", action="store_true")
    s.add_argument("--title")
    s.add_argument("--scope")
    s.add_argument("--export")
    s.add_argument("--out")
    s.set_defaults(func=cmd_analyze)

    s = sub.add_parser("datasets", help="lister les jeux de données")
    s.set_defaults(func=cmd_datasets)

    s = sub.add_parser("delete", help="suppression contrôlée d'un jeu (admin)")
    s.add_argument("dataset")
    s.add_argument("--reason", required=True)
    s.add_argument("--confirm", required=True, help="répéter le nom du jeu")
    s.set_defaults(func=cmd_delete)

    s = sub.add_parser("audit", help="consulter / vérifier le journal d'audit")
    s.add_argument("--verify", action="store_true")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=cmd_audit)

    s = sub.add_parser("generate-synthetic", help="écrire les jeux synthétiques de laboratoire")
    s.add_argument("directory")
    s.add_argument("--seed", type=int, default=42)
    s.set_defaults(func=cmd_generate_synthetic)

    s = sub.add_parser("devices", help="détecter les récepteurs SoapySDR")
    s.set_defaults(func=cmd_devices)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from lunatic_imsi_lab.security.rbac import PermissionDenied
    try:
        return args.func(args)
    except PermissionDenied as exc:
        print(f"Permission refusée : {exc}", file=sys.stderr)
        return 3
    except (ValueError, FileNotFoundError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
