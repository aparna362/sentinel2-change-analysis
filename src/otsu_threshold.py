"""Why Otsu threshold fails for change detection.

Otsu's method finds the threshold that maximises between-class variance.
It assumes the histogram has TWO peaks (bimodal): one for unchanged pixels
and one for changed pixels, with a clear valley between them.

The Sentinel-2 change magnitude histogram is near-UNIMODAL — dominated by
one large hump of unchanged/noise pixels shifted by atmospheric drift.
Otsu has no clear valley to find, picks roughly the middle of the
distribution, and flags ~48% of the scene. That is clearly wrong for a
21-day dry-season period over a mine where most of the scene did not change.

Run:    python src/otsu_threshold.py
Output: outputs/otsu_threshold.png
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


def _otsu_with_curve(values: np.ndarray, n_bins: int = 512):
    """Return (threshold, bin_centers, between_class_variance_array)."""
    counts, edges = np.histogram(values, bins=n_bins)
    centers = (edges[:-1] + edges[1:]) / 2.0
    total = float(counts.sum())
    total_mean = (counts * centers).sum() / total
    best_t, best_bcv, w0, m0s = centers[0], 0.0, 0.0, 0.0
    bcv_vals = []
    for i in range(len(counts)):
        w0 += counts[i] / total
        if 0 < w0 < 1:
            w1 = 1 - w0
            m0s += counts[i] * centers[i] / total
            m0 = m0s / w0
            m1 = (total_mean - w0 * m0) / w1
            bcv = w0 * w1 * (m0 - m1) ** 2
            bcv_vals.append(bcv)
            if bcv > best_bcv:
                best_bcv = bcv
                best_t = centers[i]
        else:
            bcv_vals.append(0.0)
    return float(best_t), centers, np.array(bcv_vals)


def _robust_threshold(values: np.ndarray, k: float = THRESHOLD_K) -> float:
    median = np.median(values)
    mad = np.median(np.abs(values - median))
    return float(median + k * 1.4826 * mad)


def main():
    print("otsu_threshold.py — loading stacks...")
    with rasterio.open(STACK_PATHS[DATE_BEFORE]) as s:
        before = s.read().astype(np.float32) / REFLECTANCE_SCALE
    with rasterio.open(STACK_PATHS[DATE_AFTER]) as s:
        after = s.read().astype(np.float32) / REFLECTANCE_SCALE

    valid = np.all(before > 0, axis=0) & np.all(after > 0, axis=0)
    mag   = np.sqrt(np.sum((after - before) ** 2, axis=0)).astype(np.float32)
    mag[~valid] = 0.0
    v = mag[valid]

    t_cva              = _robust_threshold(v)
    t_otsu, ctrs, bcv  = _otsu_with_curve(v)

    pct_cva  = 100.0 * (v > t_cva).sum()  / len(v)
    pct_otsu = 100.0 * (v > t_otsu).sum() / len(v)

    print(f"  CVA  threshold = {t_cva:.4f}  ->  {pct_cva:.2f}% pixels flagged")
    print(f"  Otsu threshold = {t_otsu:.4f}  ->  {pct_otsu:.2f}% pixels flagged")

    binary_cva  = ((mag > t_cva)  & valid)
    binary_otsu = ((mag > t_otsu) & valid)
    CLIP = float(np.percentile(v, 99.5))

    # ── figure: 3 rows x 2 cols ───────────────────────────────────────────────
    fig = plt.figure(figsize=(17, 14))
    fig.patch.set_facecolor("#111111")
    gs = fig.add_gridspec(3, 2, hspace=0.44, wspace=0.28,
                          left=0.07, right=0.97, top=0.90, bottom=0.05)
    ax_hist     = fig.add_subplot(gs[0, :])
    ax_bcv      = fig.add_subplot(gs[1, 0])
    ax_zoom     = fig.add_subplot(gs[1, 1])
    ax_cva_map  = fig.add_subplot(gs[2, 0])
    ax_otsu_map = fig.add_subplot(gs[2, 1])

    DARK = "#1c1c1c"
    for ax in fig.axes:
        ax.set_facecolor(DARK)
        ax.tick_params(colors="#cccccc", labelsize=9)
        for sp in ax.spines.values():
            sp.set_edgecolor("#444")

    # Panel 1 — full histogram
    bins = np.linspace(0, CLIP, 220)
    ax_hist.hist(v[v <= CLIP], bins=bins, color="#4a90d9",
                 alpha=0.8, density=True, label="Pixel magnitude distribution")
    ax_hist.axvline(t_cva,  color="#2ecc71", lw=2.5, ls="-",
                    label=f"CVA  (median + 3·MAD) = {t_cva:.4f}  ->  {pct_cva:.1f}% flagged")
    ax_hist.axvline(t_otsu, color="#e74c3c", lw=2.5, ls="--",
                    label=f"Otsu                  = {t_otsu:.4f}  ->  {pct_otsu:.1f}% flagged")
    ax_hist.axvspan(t_cva,  CLIP, alpha=0.13, color="#2ecc71")
    ax_hist.axvspan(t_otsu, CLIP, alpha=0.08, color="#e74c3c")
    ylim = ax_hist.get_ylim()
    ax_hist.annotate(
        "Single dominant hump\n(no bimodal valley for\nOtsu to split on)",
        xy=(np.percentile(v, 25), ylim[1] * 0.50),
        xytext=(np.percentile(v, 58), ylim[1] * 0.72),
        color="white", fontsize=9.5,
        arrowprops=dict(arrowstyle="->", color="#aaaaaa", lw=1.5),
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#333", edgecolor="#666", alpha=0.92),
    )
    ax_hist.set_xlabel("Change magnitude (reflectance units)", color="#cccccc", fontsize=11)
    ax_hist.set_ylabel("Density", color="#cccccc", fontsize=11)
    ax_hist.set_title(
        "Change magnitude histogram is UNIMODAL  —  Otsu needs BIMODAL",
        color="white", fontsize=13, fontweight="bold", pad=8
    )
    ax_hist.legend(fontsize=10, facecolor="#222", labelcolor="white",
                   edgecolor="#555", loc="upper right")

    # Panel 2 — between-class variance curve
    mask_c = ctrs <= CLIP
    ax_bcv.plot(ctrs[mask_c], bcv[mask_c], color="#e67e22", lw=1.8,
                label="Between-class variance")
    ax_bcv.axvline(t_otsu, color="#e74c3c", lw=2, ls="--",
                   label=f"Otsu peak = {t_otsu:.4f}")
    ax_bcv.axvline(t_cva,  color="#2ecc71", lw=2, ls="-",
                   label=f"CVA = {t_cva:.4f}")
    peak_idx = np.abs(ctrs - t_otsu).argmin()
    ax_bcv.annotate(
        "Flat, gradual peak\n(no sharp valley)",
        xy=(t_otsu, bcv[peak_idx]),
        xytext=(t_otsu + 0.015, bcv.max() * 0.55),
        color="white", fontsize=8.5,
        arrowprops=dict(arrowstyle="->", color="#aaa"),
        bbox=dict(boxstyle="round,pad=0.3", facecolor="#333", edgecolor="#666", alpha=0.85),
    )
    ax_bcv.set_title(
        "Otsu between-class variance\n(flat peak  ->  unreliable split)",
        color="white", fontsize=10, fontweight="bold"
    )
    ax_bcv.set_xlabel("Threshold candidate", color="#cccccc", fontsize=9)
    ax_bcv.set_ylabel("Between-class variance", color="#cccccc", fontsize=9)
    ax_bcv.legend(fontsize=8.5, facecolor="#222", labelcolor="white", edgecolor="#555")

    # Panel 3 — zoomed histogram
    lo_z = max(0, min(t_cva, t_otsu) * 0.4)
    hi_z = min(CLIP, max(t_cva, t_otsu) * 2.2)
    vz   = v[(v >= lo_z) & (v <= hi_z)]
    ax_zoom.hist(vz, bins=np.linspace(lo_z, hi_z, 100),
                 color="#4a90d9", alpha=0.8, density=True)
    ax_zoom.axvline(t_cva,  color="#2ecc71", lw=2, ls="-",  label=f"CVA = {t_cva:.4f}")
    ax_zoom.axvline(t_otsu, color="#e74c3c", lw=2, ls="--", label=f"Otsu = {t_otsu:.4f}")
    ax_zoom.set_title("Zoomed: around threshold region", color="white",
                      fontsize=10, fontweight="bold")
    ax_zoom.set_xlabel("Change magnitude", color="#cccccc", fontsize=9)
    ax_zoom.set_ylabel("Density", color="#cccccc", fontsize=9)
    ax_zoom.legend(fontsize=8.5, facecolor="#222", labelcolor="white", edgecolor="#555")

    # Panel 4 — CVA binary map
    rgb = np.full((*binary_cva.shape, 3), 0.07, dtype=np.float32)
    rgb[binary_cva] = [0.18, 0.80, 0.44]
    ax_cva_map.imshow(rgb)
    ax_cva_map.set_title(
        f"CVA  |  threshold = {t_cva:.4f}  |  {pct_cva:.1f}% flagged\n"
        "Change on mine workings only   [CORRECT]",
        color="#2ecc71", fontsize=10, fontweight="bold"
    )
    ax_cva_map.set_xticks([]); ax_cva_map.set_yticks([])
    ax_cva_map.legend(handles=[
        mpatches.Patch(color=[0.18, 0.80, 0.44], label="Changed"),
        mpatches.Patch(color=[0.07, 0.07, 0.07], label="Unchanged / nodata"),
    ], loc="lower right", fontsize=8, facecolor="#222", labelcolor="white", edgecolor="#555")

    # Panel 5 — Otsu binary map
    rgb2 = np.full((*binary_otsu.shape, 3), 0.07, dtype=np.float32)
    rgb2[binary_otsu] = [0.91, 0.30, 0.24]
    ax_otsu_map.imshow(rgb2)
    ax_otsu_map.set_title(
        f"Otsu  |  threshold = {t_otsu:.4f}  |  {pct_otsu:.1f}% flagged\n"
        "Half the scene flagged — mostly illumination drift   [FAILED]",
        color="#e74c3c", fontsize=10, fontweight="bold"
    )
    ax_otsu_map.set_xticks([]); ax_otsu_map.set_yticks([])
    ax_otsu_map.legend(handles=[
        mpatches.Patch(color=[0.91, 0.30, 0.24], label="'Changed' (mostly false positives)"),
        mpatches.Patch(color=[0.07, 0.07, 0.07], label="Unchanged / nodata"),
    ], loc="lower right", fontsize=8, facecolor="#222", labelcolor="white", edgecolor="#555")

    fig.suptitle(
        "WHY OTSU THRESHOLD FAILS FOR CHANGE DETECTION\n"
        "Otsu requires a bimodal histogram. Change magnitude is unimodal "
        f"-> Otsu flags {pct_otsu:.0f}% of the scene  vs  CVA's correct {pct_cva:.1f}%",
        color="white", fontsize=13, fontweight="bold", y=0.975
    )

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUTS_DIR / "otsu_threshold.png"
    fig.savefig(out, dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  -> {out}")


if __name__ == "__main__":
    main()
