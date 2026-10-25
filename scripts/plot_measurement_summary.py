"""Plot aggregate measurement results without participant-level data."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def plot(summary, output):
    evaluation = summary["offline_ppg_evaluation"]
    broad = evaluation["historical_window"]
    narrow = evaluation["narrower_window_sensitivity"]
    fig, axes = plt.subplots(1, 2, figsize=(12.2, 6.2), gridspec_kw={"width_ratios": [1.2, 1]})
    fig.patch.set_facecolor("#f6f8fb")
    fig.suptitle("Physiological measurement inside MRI", x=.07, ha="left", fontsize=20, weight="bold", color="#132b45")
    fig.text(.07, .88, f'{summary["participants"]} participants | {summary["visits"]} visits | '
             f'{evaluation["recordings"]} evaluated PPG logs | {evaluation["recorded_minutes"]:.1f} whole-log minutes',
             fontsize=11, color="#44556a")
    x = np.arange(2)
    for shift, metrics, color in [(-.18, broad, "#276aa0"), (.18, narrow, "#d08b38")]:
        lo, hi = metrics["matching_window_seconds"]
        values = [metrics["pooled_reference_recall"] * 100, metrics["pooled_detection_ppv"] * 100]
        bars = axes[0].bar(x + shift, values, width=.34, color=color,
                           label=f"{lo*1000:+.0f} to {hi*1000:+.0f} ms")
        axes[0].bar_label(bars, labels=[f"{v:.2f}%" for v in values], padding=4, fontsize=10)
    axes[0].set(xticks=x, xticklabels=["Marker recall", "Detection PPV"], ylim=(0, 112), ylabel="Pooled matched-event proportion (%)")
    axes[0].set_title("A   Agreement depends on the matching window", loc="left", fontsize=11, pad=16)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, ["Matching window: " + label for label in labels],
               loc="center left", bbox_to_anchor=(.065, .835), ncol=2, frameon=False, fontsize=9)
    distributions = broad["per_record_distributions"]
    metrics = [("timing_iqr_ms", "Timing IQR"), ("timing_sd_ms", "Timing SD")]
    for i, (key, label) in enumerate(metrics):
        d = distributions[key]
        axes[1].plot([d["minimum"], d["maximum"]], [i, i], color="#276aa0", linewidth=3)
        axes[1].scatter([d["median"]], [i], color="#132b45", s=60, zorder=3)
        axes[1].annotate(f'{d["minimum"]:.1f} / {d["median"]:.1f} / {d["maximum"]:.1f} ms',
                         (d["minimum"], i), xytext=(0, 17), textcoords="offset points", ha="left", fontsize=10)
    upper = max(distributions[key]["maximum"] for key, _ in metrics) * 1.12
    axes[1].set(yticks=[0, 1], yticklabels=[x[1] for x in metrics], ylim=(-.5, 1.7), xlim=(0, upper), xlabel="Across-record minimum / median / maximum (ms)")
    axes[1].invert_yaxis()
    axes[1].set_title("B   Broad-window timing varies by recording", loc="left", fontsize=11, pad=16)
    axes[1].text(.02, .08, "Matched events only; ranges are not confidence intervals.", transform=axes[1].transAxes, fontsize=9, color="#44556a", wrap=True)
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_facecolor("white")
    offset = distributions["offset_ms_median"]
    fig.text(.07, .16, f'Recording median offsets: {offset["minimum"]:.1f} to {offset["maximum"]:.1f} ms. '
             'The narrower early boundary is -150 ms.', fontsize=10, color="#132b45")
    fig.text(.07, .105, "Reference: scanner PPG markers, not independent ECG truth. Whole-log duration includes non-scan and compromised periods.\n"
             "Offline analysis at 3 T. Offsets are not system latency. Window sensitivity is not a true missed-heartbeat rate.",
             fontsize=9, color="#44556a", linespacing=1.6)
    fig.subplots_adjust(left=.07, right=.98, top=.77, bottom=.3, wspace=.3)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists() or args.out.resolve() == args.summary.resolve():
        parser.error("Choose a new output file")
    plot(json.loads(args.summary.read_text(encoding="utf-8")), args.out)
