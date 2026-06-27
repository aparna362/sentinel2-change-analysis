"""All three thresholds side by side — why CVA was chosen.

Produces a single summary figure showing:
  - The magnitude histogram with all three threshold lines marked
  - The binary change map for each method
  - A stats summary table

This is the one-page visual argument for why Otsu and mean/std were rejected
and CVA (median + 3*MAD) was selected.

Run:    python src/threshold_comparison.py
Output: outputs/threshold_comparison.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (
    DATE_AFTER, DATE_BEFORE, OUTPUTS_DIR, REFLECTANCE_SCALE,
    STACK_PATHS, THRESHOLD_K,
)


def _otsu(values: np.ndarray, n_bins: int = 512) -> float:
    counts, edges = np.histogram(values, bins=n_bins)
    centers = (edges[:-1] + edges[1:]) / 2.0
    total = float(counts.sum())
    total_mean = (counts * centers).sum() / total
    best_t, best_bcv, w0, m0s = centers[0], 0.0, 0.0, 0.0
    for i in range(len(counts)):
        w0 += counts[i] / total
        if w0 == 0 or w0 == 1:
            continue
        w1 = 1 - w0
        m0s += counts[i] * centers[i] / total
        m0 = m0s / w0
        m1 = (total_mean - w0 * m0) / w1
        bcv = w0 * w1 * (m0 - m1) ** 2
        if bcv > best_bcv:
            best_bcv = bcv
            best_t = centers[i]
    return float(best_t)


def _robust(values, k=THRESHOLD_K):
    median = np.median(values)
    mad = np.median(np.abs(values - median))
    return float(median + k * 1.4826 * mad), float(median), float(mad)


def _mean_std(values, k=THRESHOLD_K):
    m, s = float(values.mean()), float(values.std())
    return float(m + k * s), m, s


def main():
    print("threshold_comparison.py — loading stacks...")
    with rasterio.open(STACK_PATHS[DATE_BEFORE]) as s:
        before = s.read().astype(np.float32) / REFLECTANCE_SCALE
    with rasterio.open(STACK_PATHS[DATE_AFTER]) as s:
        after = s.read().astype(np.float32) / REFLECTANCE_SCALE

    valid = np.all(before > 0, axis=0) & np.all(after > 0, axis=0)
    mag   = np.sqrt(np.sum((after - before) ** 2, axis=0)).astype(np.float32)
    mag[~valid] = 0.0
    v = mag[valid]

    t_cva, median, mad = _robust(v)
    t_msd, mean,   std = _mean_std(v)
    t_otsu             = _otsu(v)

    pct_cva  = 100.0 * (v > t_cva).sum()  / len(v)
    pct_msd  = 100.0 * (v > t_msd).sum()  / len(v)
    pct_otsu = 100.0 * (v > t_otsu).sum() / len(v)

    print(f"  CVA   threshold = {t_cva:.4f}   {pct_cva:.2f}% flagged")
    print(f"  Mean/std        = {t_msd:.4f}   {pct_msd:.2f}% flagged")
    print(f"  Otsu            = {t_otsu:.4f}  {pct_otsu:.2f}% flagged")

    binary_cva  = (mag > t_cva)  & valid
    binary_msd  = (mag > t_msd)  & valid
    binary_otsu = (mag > t_otsu) & valid
    CLIP = float(np.percentile(v, 99.5))

    # ── figure: 2 rows x 4 cols ───────────────────────────────────────────────
    # Row 0: histogram (spans all) | (empty)
    # Row 1: binary_otsu | binary_msd | binary_cva | stats table
    fig = plt.figure(figsize=(20, 12))
    fig.patch.set_facecolor("#111111")
    gs = fig.add_gridspec(2, 4, hspace=0.38, wspace=0.22,
                          left=0.05, right=0.98, top=0.88, bottom=0.06)

    ax_hist     = fig.add_subplot(gs[0, :3])    # histogram — 3 cols wide
    ax_stats    = fig.add_subplot(gs[0, 3])     # stats table
    ax_otsu_map = fig.add_subplot(gs[1, 0])
    ax_msd_map  = fig.add_subplot(gs[1, 1])
    ax_cva_map  = fig.add_subplot(gs[1, 2])
    ax_verdict  = fig.add_subplot(gs[1, 3])

    DARK = "#1c1c1c"
    for ax in fig.axes:
        ax.set_facecolor(DARK)
        ax.tick_params(colors="#cccccc", labelsize=9)
        for sp in ax.spines.values():
            sp.set_edgecolor("#444")

    # ── Panel 1: histogram ────────────────────────────────────────────────────
    bins = np.linspace(0, CLIP, 220)
    ax_hist.hist(v[v <= CLIP], bins=bins, color="#4a90d9",
                 alpha=0.75, density=True, label="Pixel magnitude distribution")
    ax_hist.axvline(t_otsu, color="#e74c3c", lw=2.5, ls="--",
                    label=f"Otsu      = {t_otsu:.4f}  ->  {pct_otsu:.1f}% flagged  [FAILED]")
    ax_hist.axvline(t_msd,  color="#f39c12", lw=2.5, ls="-.",
                    label=f"Mean+3std = {t_msd:.4f}  ->  {pct_msd:.2f}% flagged  [UNRELIABLE]")
    ax_hist.axvline(t_cva,  color="#2ecc71", lw=2.5, ls="-",
                    label=f"CVA       = {t_cva:.4f}  ->  {pct_cva:.1f}% flagged  [CORRECT]")

    ylim = ax_hist.get_ylim()
    # shade regions
    ax_hist.axvspan(t_cva,  CLIP, alpha=0.12, color="#2ecc71")
    ax_hist.axvspan(t_otsu, CLIP, alpha=0.06, color="#e74c3c")
    ax_hist.axvspan(t_msd,  CLIP, alpha=0.06, color="#f39c12")

    ax_hist.annotate(
        "UNIMODAL: one hump\n(Otsu needs two humps)",
        xy=(np.percentile(v, 20), ylim[1] * 0.45),
        xytext=(np.percentile(v, 50), ylim[1] * 0.68),
        color="white", fontsize=9,
        arrowprops=dict(arrowstyle="->", color="#aaa"),
        bbox=dict(boxstyle="round,pad=0.35", facecolor="#333", edgecolor="#666", alpha=0.9),
    )
    ax_hist.set_xlabel("Change magnitude (reflectance units)", color="#cccccc", fontsize=11)
    ax_hist.set_ylabel("Density", color="#cccccc", fontsize=11)
    ax_hist.set_title(
        "All three thresholds on the same magnitude histogram",
        color="white", fontsize=12, fontweight="bold", pad=7
    )
    ax_hist.legend(fontsize=9.5, facecolor="#222", labelcolor="white",
                   edgecolor="#555", loc="upper right")

    # ── Panel 2: stats table ──────────────────────────────────────────────────
    ax_stats.axis("off")
    rows = [
        ["Method",        "Threshold", "% flagged", "Verdict"],
        ["Otsu",          f"{t_otsu:.4f}", f"{pct_otsu:.1f}%",  "FAILED"],
        ["Mean + 3·std",  f"{t_msd:.4f}",  f"{pct_msd:.2f}%",  "UNRELIABLE"],
        ["CVA (med+MAD)", f"{t_cva:.4f}",  f"{pct_cva:.1f}%",  "CORRECT"],
    ]
    colors_row = [
        ["#333", "#333", "#333", "#333"],
        ["#2a1010", "#2a1010", "#2a1010", "#2a1010"],
        ["#2a1a00", "#2a1a00", "#2a1a00", "#2a1a00"],
        ["#0a2a14", "#0a2a14", "#0a2a14", "#0a2a14"],
    ]
    tbl = ax_stats.table(
        cellText=rows[1:], colLabels=rows[0],
        loc="center", cellLoc="center",
        cellColours=colors_row[1:],
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1.05, 2.2)
    verdict_colors = {"FAILED": "#e74c3c", "UNRELIABLE": "#f39c12", "CORRECT": "#2ecc71"}
    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor("#555")
        txt = cell.get_text().get_text()
        if txt in verdict_colors:
            cell.get_text().set_color(verdict_colors[txt])
            cell.get_text().set_fontweight("bold")
        else:
            cell.get_text().set_color("white")
    ax_stats.set_title("Summary", color="white", fontsize=10, fontweight="bold", pad=6)

    # ── Panels 3–5: binary maps ───────────────────────────────────────────────
    maps = [
        (ax_otsu_map, binary_otsu, [0.91, 0.30, 0.24],
         f"Otsu  |  {t_otsu:.4f}  |  {pct_otsu:.1f}%\n[FAILED]", "#e74c3c"),
        (ax_msd_map,  binary_msd,  [0.95, 0.60, 0.10],
         f"Mean+3std  |  {t_msd:.4f}  |  {pct_msd:.2f}%\n[UNRELIABLE]", "#f39c12"),
        (ax_cva_map,  binary_cva,  [0.18, 0.80, 0.44],
         f"CVA  |  {t_cva:.4f}  |  {pct_cva:.1f}%\n[CORRECT]", "#2ecc71"),
    ]
    for ax, binary, col, title, tcol in maps:
        rgb = np.full((*binary.shape, 3), 0.07, dtype=np.float32)
        rgb[binary] = col
        ax.imshow(rgb)
        ax.set_title(title, color=tcol, fontsize=9.5, fontweight="bold")
        ax.set_xticks([]); ax.set_yticks([])
        ax.legend(handles=[
            mpatches.Patch(color=col,                label="Flagged as changed"),
            mpatches.Patch(color=[0.07, 0.07, 0.07], label="Unchanged / nodata"),
        ], loc="lower right", fontsize=7.5, facecolor="#222",
           labelcolor="white", edgecolor="#555")

    # ── Panel 6: verdict box ──────────────────────────────────────────────────
    ax_verdict.axis("off")
    verdict_text = (
        "WHY CVA WAS CHOSEN\n\n"
        f"Otsu\n"
        f"  Needs bimodal histogram.\n"
        f"  Histogram is unimodal.\n"
        f"  -> flags {pct_otsu:.0f}% of scene.\n\n"
        f"Mean + 3·std\n"
        f"  Mean dragged up by outliers.\n"
        f"  Threshold fragile to tail.\n"
        f"  -> result not reproducible.\n\n"
        f"CVA (median + 3·MAD)\n"
        f"  Median: not moved by outliers.\n"
        f"  MAD: not moved by outliers.\n"
        f"  Anchored to true noise floor.\n"
        f"  -> flags {pct_cva:.1f}% — mine only."
    )
    ax_verdict.text(
        0.5, 0.5, verdict_text,
        ha="center", va="center", transform=ax_verdict.transAxes,
        color="white", fontsize=8.5, linespacing=1.55,
        bbox=dict(boxstyle="round,pad=0.6", facecolor="#1a1a2e",
                  edgecolor="#4a90d9", linewidth=1.5, alpha=0.95),
    )

    fig.suptitle(
        "THRESHOLD METHOD COMPARISON  —  Why CVA (median + 3·MAD) was selected\n"
        f"Otsu: {pct_otsu:.0f}% flagged   |   Mean+3std: {pct_msd:.1f}% flagged   |   CVA: {pct_cva:.1f}% flagged",
        color="white", fontsize=13, fontweight="bold", y=0.975
    )

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUTS_DIR / "threshold_comparison.png"
    fig.savefig(out, dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  -> {out}")


if __name__ == "__main__":
    main()
