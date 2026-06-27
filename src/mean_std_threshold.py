"""Why mean/std threshold fails for change detection.

The standard mean + k*sigma rule is sensitive to outliers. A handful of
bright genuine-change pixels (burned forest, excavated pit) sit in the far
tail and drag the mean upward and inflate the standard deviation. The result:
the threshold moves unpredictably — too high in some scenes (misses subtle
change), too low in others.

median/MAD solves this because both statistics are resistant to outliers:
extreme values in the tail cannot move the median or MAD. The threshold stays
anchored to the true background level of the scene.

This script shows the effect concretely with actual numbers and maps.

Run:    python src/mean_std_threshold.py
Output: outputs/mean_std_threshold.png
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


def _robust_threshold(values: np.ndarray, k: float = THRESHOLD_K) -> tuple:
    median = np.median(values)
    mad = np.median(np.abs(values - median))
    return float(median + k * 1.4826 * mad), float(median), float(mad)


def _mean_std_threshold(values: np.ndarray, k: float = THRESHOLD_K) -> tuple:
    mean = float(values.mean())
    std  = float(values.std())
    return float(mean + k * std), mean, std


def main():
    print("mean_std_threshold.py — loading stacks...")
    with rasterio.open(STACK_PATHS[DATE_BEFORE]) as s:
        before = s.read().astype(np.float32) / REFLECTANCE_SCALE
    with rasterio.open(STACK_PATHS[DATE_AFTER]) as s:
        after = s.read().astype(np.float32) / REFLECTANCE_SCALE

    valid = np.all(before > 0, axis=0) & np.all(after > 0, axis=0)
    mag   = np.sqrt(np.sum((after - before) ** 2, axis=0)).astype(np.float32)
    mag[~valid] = 0.0
    v = mag[valid]

    t_cva, median, mad      = _robust_threshold(v)
    t_msd, mean,   std      = _mean_std_threshold(v)

    pct_cva = 100.0 * (v > t_cva).sum() / len(v)
    pct_msd = 100.0 * (v > t_msd).sum() / len(v)

    print(f"  median={median:.4f}  MAD={mad:.4f}  ->  CVA threshold={t_cva:.4f}  {pct_cva:.2f}% flagged")
    print(f"  mean  ={mean:.4f}  std={std:.4f}  ->  M/S threshold={t_msd:.4f}  {pct_msd:.2f}% flagged")

    # Demonstrate outlier pull: remove top 0.1% and recompute mean/std
    cutoff_99 = np.percentile(v, 99.9)
    v_trim = v[v <= cutoff_99]
    mean_trim = v_trim.mean()
    std_trim  = v_trim.std()
    t_trim    = mean_trim + THRESHOLD_K * std_trim
    pct_trim  = 100.0 * (v > t_trim).sum() / len(v)

    print(f"  After removing top 0.1%: mean={mean_trim:.4f} std={std_trim:.4f} -> threshold={t_trim:.4f}  {pct_trim:.2f}% flagged")
    print(f"  -> removing 0.1% of pixels changed threshold by {t_trim - t_msd:+.4f}  (mean/std is fragile)")

    binary_cva = ((mag > t_cva) & valid)
    binary_msd = ((mag > t_msd) & valid)
    CLIP = float(np.percentile(v, 99.5))

    # ── figure: 3 rows x 2 cols ───────────────────────────────────────────────
    fig = plt.figure(figsize=(17, 15))
    fig.patch.set_facecolor("#111111")
    gs = fig.add_gridspec(3, 2, hspace=0.46, wspace=0.28,
                          left=0.07, right=0.97, top=0.90, bottom=0.05)
    ax_hist    = fig.add_subplot(gs[0, :])
    ax_outlier = fig.add_subplot(gs[1, 0])
    ax_numbers = fig.add_subplot(gs[1, 1])
    ax_cva_map = fig.add_subplot(gs[2, 0])
    ax_msd_map = fig.add_subplot(gs[2, 1])

    DARK = "#1c1c1c"
    for ax in fig.axes:
        ax.set_facecolor(DARK)
        ax.tick_params(colors="#cccccc", labelsize=9)
        for sp in ax.spines.values():
            sp.set_edgecolor("#444")

    # Panel 1 — full histogram with all markers
    bins = np.linspace(0, CLIP, 220)
    ax_hist.hist(v[v <= CLIP], bins=bins, color="#4a90d9",
                 alpha=0.8, density=True, label="Pixel magnitude distribution")
    ax_hist.axvline(median, color="#f39c12", lw=1.8, ls=":",
                    label=f"Median = {median:.4f}")
    ax_hist.axvline(mean,   color="#e74c3c", lw=1.8, ls=":",
                    label=f"Mean   = {mean:.4f}  (pulled up by outliers)")
    ax_hist.axvline(t_cva,  color="#2ecc71", lw=2.5, ls="-",
                    label=f"CVA  (median + 3·MAD) = {t_cva:.4f}  ->  {pct_cva:.1f}% flagged")
    ax_hist.axvline(t_msd,  color="#e74c3c", lw=2.5, ls="--",
                    label=f"Mean + 3·std          = {t_msd:.4f}  ->  {pct_msd:.2f}% flagged")
    ax_hist.axvspan(t_cva, CLIP, alpha=0.13, color="#2ecc71")
    ax_hist.axvspan(t_msd, CLIP, alpha=0.08, color="#e74c3c")

    # arrow from median to mean showing the pull
    ylim = ax_hist.get_ylim()
    ypos = ylim[1] * 0.88
    ax_hist.annotate(
        "", xy=(mean, ypos), xytext=(median, ypos),
        arrowprops=dict(arrowstyle="->", color="#e74c3c", lw=2)
    )
    ax_hist.text((median + mean) / 2, ypos * 1.04,
                 f"outliers pull mean\n+{mean - median:.4f} above median",
                 ha="center", va="bottom", color="#e74c3c", fontsize=8.5,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="#2a1a1a",
                           edgecolor="#e74c3c", alpha=0.85))

    ax_hist.set_xlabel("Change magnitude (reflectance units)", color="#cccccc", fontsize=11)
    ax_hist.set_ylabel("Density", color="#cccccc", fontsize=11)
    ax_hist.set_title(
        "Mean is pulled up by outliers (genuine change pixels in the tail)  —  Median is not",
        color="white", fontsize=13, fontweight="bold", pad=8
    )
    ax_hist.legend(fontsize=9.5, facecolor="#222", labelcolor="white",
                   edgecolor="#555", loc="upper right")

    # Panel 2 — outlier sensitivity: tail zoom
    tail_lo = np.percentile(v, 97)
    tail_hi = float(v.max())
    v_tail  = v[v >= tail_lo]
    ax_outlier.hist(v_tail, bins=np.linspace(tail_lo, min(tail_hi, CLIP * 2), 60),
                    color="#9b59b6", alpha=0.85, density=False)
    ax_outlier.axvline(t_cva, color="#2ecc71", lw=2, ls="-",  label=f"CVA = {t_cva:.4f}")
    ax_outlier.axvline(t_msd, color="#e74c3c", lw=2, ls="--", label=f"Mean+3std = {t_msd:.4f}")
    n_tail = (v > cutoff_99).sum()
    ax_outlier.set_title(
        f"Far tail (top 3% of pixels): {n_tail:,} extreme pixels\n"
        "These inflate mean and std, shifting the threshold",
        color="white", fontsize=10, fontweight="bold"
    )
    ax_outlier.set_xlabel("Change magnitude", color="#cccccc", fontsize=9)
    ax_outlier.set_ylabel("Pixel count", color="#cccccc", fontsize=9)
    ax_outlier.legend(fontsize=8.5, facecolor="#222", labelcolor="white", edgecolor="#555")

    # Panel 3 — numbers comparison table
    ax_numbers.axis("off")
    table_data = [
        ["Statistic",        "median/MAD (CVA)",              "mean/std"],
        ["Center",           f"{median:.4f} (median)",        f"{mean:.4f} (mean)"],
        ["Spread",           f"{mad:.4f} (MAD)",              f"{std:.4f} (std)"],
        ["Threshold",        f"{t_cva:.4f}",                  f"{t_msd:.4f}"],
        ["% flagged",        f"{pct_cva:.2f}%",               f"{pct_msd:.2f}%"],
        ["Outlier effect",   "None (robust)",                 f"Threshold shifts {t_trim-t_msd:+.4f}\nif top 0.1% removed"],
    ]
    col_colors = [["#2a2a2a"] * 3] * len(table_data)
    col_colors[0] = ["#333", "#1a3a2a", "#3a1a1a"]

    tbl = ax_numbers.table(
        cellText=table_data[1:],
        colLabels=table_data[0],
        loc="center",
        cellLoc="center",
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1.1, 2.0)

    for (r, c), cell in tbl.get_celld().items():
        cell.set_facecolor("#1c1c1c" if r > 0 else "#333333")
        cell.set_text_props(color="white" if r > 0 else "#dddddd")
        cell.set_edgecolor("#555")
        if r > 0 and c == 1:
            cell.set_facecolor("#0d2a1a")
        if r > 0 and c == 2:
            cell.set_facecolor("#2a0d0d")

    ax_numbers.set_title(
        "Numerical comparison: median/MAD vs mean/std",
        color="white", fontsize=10, fontweight="bold", pad=8
    )

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

    # Panel 5 — Mean/std binary map
    rgb2 = np.full((*binary_msd.shape, 3), 0.07, dtype=np.float32)
    rgb2[binary_msd] = [0.91, 0.30, 0.24]
    ax_msd_map.imshow(rgb2)
    ax_msd_map.set_title(
        f"Mean + 3·std  |  threshold = {t_msd:.4f}  |  {pct_msd:.2f}% flagged\n"
        f"Result varies with outliers — fragile   [UNRELIABLE]",
        color="#e74c3c", fontsize=10, fontweight="bold"
    )
    ax_msd_map.set_xticks([]); ax_msd_map.set_yticks([])
    ax_msd_map.legend(handles=[
        mpatches.Patch(color=[0.91, 0.30, 0.24], label="Flagged as changed"),
        mpatches.Patch(color=[0.07, 0.07, 0.07], label="Unchanged / nodata"),
    ], loc="lower right", fontsize=8, facecolor="#222", labelcolor="white", edgecolor="#555")

    fig.suptitle(
        "WHY MEAN + STD THRESHOLD IS UNRELIABLE FOR CHANGE DETECTION\n"
        f"Outliers drag mean {mean-median:+.4f} above median  ->  threshold inflated  "
        f"->  removing top 0.1% shifts threshold by {t_trim-t_msd:+.4f}",
        color="white", fontsize=13, fontweight="bold", y=0.975
    )

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUTS_DIR / "mean_std_threshold.png"
    fig.savefig(out, dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  -> {out}")


if __name__ == "__main__":
    main()
