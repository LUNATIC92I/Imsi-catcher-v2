"""Graphiques Matplotlib réutilisés par l'IHM et les rapports.

Seule l'API objet (``Figure``) est utilisée, sans ``pyplot`` : le module
n'impose donc aucun backend et fonctionne aussi bien hors interface.
"""

from __future__ import annotations

import io
from collections import defaultdict
from typing import Sequence

from matplotlib.figure import Figure

from lunatic_imsi_lab.core.models import Alert, CellObservation, SpectrumSweep
from lunatic_imsi_lab.mapping.maps import prepare_points, render_map

COLORS = ["#2f8bff", "#7ad7f0", "#c0c7d1", "#ffb703", "#8ecae6", "#b388ff", "#06d6a0",
          "#ef476f"]


def _figure(w: float = 7.5, h: float = 3.2) -> Figure:
    return Figure(figsize=(w, h), dpi=110, tight_layout=True)


def fig_to_png(fig: Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    return buf.getvalue()


def _sim_mark(fig: Figure, is_sim: bool) -> None:
    if is_sim:
        fig.text(0.99, 0.98, "SIMULATION", ha="right", va="top", color="#ff4d6d",
                 fontsize=10, fontweight="bold")


def plot_rssi_timeline(ax, observations: Sequence[CellObservation],
                       alerts: Sequence[Alert] = (), max_cells: int = 8) -> None:
    ax.clear()
    per = defaultdict(list)
    for o in observations:
        if o.rssi_dbm is not None:
            per[o.cell_key].append(o)
    keys = sorted(per, key=lambda k: -len(per[k]))[:max_cells]
    for i, k in enumerate(keys):
        obs = sorted(per[k], key=lambda o: o.timestamp)
        ax.plot([o.timestamp for o in obs], [o.rssi_dbm for o in obs], lw=0.9,
                color=COLORS[i % len(COLORS)], label=obs[0].cell_label)
    for a in alerts:
        if a.severity.value in ("MEDIUM", "HIGH"):
            ax.axvspan(a.first_seen, a.last_seen, color="#ff4d6d", alpha=0.12)
    ax.set_ylabel("Puissance (dBm)")
    ax.set_title("Puissance par cellule dans le temps")
    ax.grid(True, alpha=0.25)
    if keys:
        ax.legend(fontsize=6, loc="lower left", ncol=2)


def plot_spectrum(ax, sweep: SpectrumSweep, emissions=()) -> None:
    ax.clear()
    ax.plot(sweep.frequencies_hz / 1e6, sweep.power_dbm, lw=0.7, color="#2f8bff")
    for e in emissions:
        ax.axvspan(e.start_hz / 1e6, e.stop_hz / 1e6, color="#7ad7f0", alpha=0.18)
        ax.annotate(f"{e.center_mhz:.2f}", (e.center_mhz, e.peak_dbm), fontsize=6,
                    color="#c0c7d1", ha="center", va="bottom")
    ax.set_xlabel("Fréquence (MHz)")
    unit = sweep.provenance.parameters.get("unit", "dBm")
    ax.set_ylabel(f"Puissance ({unit}/bin)")
    ax.set_title(f"Spectre — {sweep.timestamp:%Y-%m-%d %H:%M:%S} UTC")
    ax.grid(True, alpha=0.25)


def plot_waterfall(ax, freqs, matrix, times) -> None:
    ax.clear()
    extent = [freqs[0] / 1e6, freqs[-1] / 1e6, len(times), 0]
    im = ax.imshow(matrix, aspect="auto", extent=extent, cmap="magma", interpolation="nearest")
    ax.set_xlabel("Fréquence (MHz)")
    ax.set_ylabel("Balayage n°")
    ax.set_title("Cascade (waterfall)")
    return im


def rssi_png(observations, alerts=()) -> bytes:
    fig = _figure()
    plot_rssi_timeline(fig.add_subplot(111), observations, alerts)
    _sim_mark(fig, any(o.provenance.is_simulation for o in observations))
    return fig_to_png(fig)


def spectrum_png(sweep: SpectrumSweep, emissions=()) -> bytes:
    fig = _figure()
    plot_spectrum(fig.add_subplot(111), sweep, emissions)
    _sim_mark(fig, sweep.provenance.is_simulation)
    return fig_to_png(fig)


def map_png(observations, alerts=()) -> bytes:
    fig = _figure(6.5, 4.8)
    render_map(fig.add_subplot(111), prepare_points(observations, alerts))
    return fig_to_png(fig)
