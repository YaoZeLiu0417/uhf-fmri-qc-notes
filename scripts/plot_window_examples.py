"""Render caller-selected, private PPG windows without reading source files."""
from pathlib import Path
from textwrap import fill

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
import numpy as np


CATEGORIES = {
    "clear": "Clear-waveform candidate", "清晰": "Clear-waveform candidate",
    "clipping": "ADC clipping", "削顶": "ADC clipping",
    "disagreement": "Detector disagreement", "检测分歧": "Detector disagreement",
}


def render_examples(examples, out):
    """Save three selected windows as a PNG and return its Path.

    time_s and both detector_*_times arrays use the same recording-time seconds;
    start_time is the window's zero. Arrays must contain the selected raw window.
    fs is the declared positive sampling rate; plotting does not resample data.
    category is clear, clipping, or disagreement (Chinese aliases accepted).
    source/run_id are ignored. The caller must supply an anonymous explanation.
    This function neither selects cases nor establishes physiological truth.
    """
    examples = list(examples)
    if len(examples) != 3:
        raise ValueError("Provide exactly three selected examples")
    titles = [CATEGORIES[example["category"]] for example in examples]
    if len(set(titles)) != 3:
        raise ValueError("Provide one clear, one clipping, and one disagreement example")
    output = Path(out)
    if output.suffix.lower() != ".png":
        output = output.with_name(output.name + ".png")
    fonts = {font.name for font in font_manager.fontManager.ttflist}
    family = "Microsoft YaHei" if "Microsoft YaHei" in fonts else "DejaVu Sans"
    with plt.rc_context({"font.family": family, "axes.unicode_minus": False}):
        fig, axes = plt.subplots(3, 1, figsize=(12, 10), dpi=180)
        try:
            for index, (ax, example, title) in enumerate(zip(axes, examples, titles)):
                time = np.asarray(example["time_s"], dtype=float)
                raw = np.asarray(example["raw"], dtype=float)
                fs, start = float(example["fs"]), float(example["start_time"])
                if (time.ndim != 1 or raw.shape != time.shape or len(time) < 2
                        or not np.isfinite(time).all() or not np.isfinite(raw).all()
                        or not (np.diff(time) > 0).all()):
                    raise ValueError("Each window needs matching finite raw values and increasing sample times")
                if not np.isfinite(fs) or fs <= 0 or not np.isfinite(start) or start > time[0] + 1e-9:
                    raise ValueError("Use a positive fs and a window start no later than the first sample")
                if np.any((raw < 0) | (raw > 4095)):
                    raise ValueError("Raw PPG values must lie in the declared 0–4095 ADC range")
                ax.plot(time - start, raw, color="#28251D", lw=1.0, zorder=2)
                for key, marker, color, size in (
                    ("detector_a_times", "o", "#01696F", 46),
                    ("detector_b_times", "x", "#A84B2F", 35),
                ):
                    events = np.asarray(example[key], dtype=float)
                    if events.ndim != 1 or not np.isfinite(events).all():
                        raise ValueError("Detector times must be finite one-dimensional arrays")
                    events = events[(events >= time[0]) & (events <= time[-1])]
                    style = {"facecolors": "none", "edgecolors": color} if marker == "o" else {"color": color}
                    ax.scatter(events - start, np.interp(events, time, raw),
                               marker=marker, s=size, linewidths=1.25, zorder=4, **style)
                for bound in (0, 4095):
                    ax.axhline(bound, color="#8A9297", ls="--", lw=0.85, zorder=1)
                ax.set(xlim=(0, time[-1] - start), ylim=(-160, 4255),
                       yticks=[0, 1024, 2048, 3072, 4095],
                       ylabel="PPG (uncalibrated ADC units)", xlabel="Time from window start (s)")
                ax.set_title(f"Example {chr(65 + index)}  |  {title}", loc="left", fontsize=13, weight="bold", pad=38)
                ax.text(0, 1.035, fill(str(example.get("explanation", "")), width=110),
                        transform=ax.transAxes, va="bottom", fontsize=9, color="#49565C")
                ax.spines[["top", "right"]].set_visible(False)
                ax.grid(axis="y", color="#E7EBED", lw=0.5)
                ax.tick_params(labelsize=9)
            handles = [
                Line2D([], [], color="#28251D", lw=1, label="Raw PPG"),
                Line2D([], [], color="#01696F", marker="o", mfc="none", ls="none", label="Detector A (offline)"),
                Line2D([], [], color="#A84B2F", marker="x", ls="none", label="Detector B (offline)"),
                Line2D([], [], color="#8A9297", ls="--", label="ADC boundaries: 0 / 4095"),
            ]
            fig.suptitle("Offline PPG window examples", y=0.975, fontsize=17, weight="bold")
            fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, 0.94), ncol=4, frameon=False, fontsize=9)
            fig.subplots_adjust(left=0.095, right=0.975, top=0.82, bottom=0.12, hspace=0.9)
            fig.text(0.5, 0.037, "Algorithm agreement is not independent ECG truth. Offline comparison only.",
                     ha="center", fontsize=10, color="#49565C")
            output.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(output, dpi=180, metadata={"Title": "Anonymous offline PPG examples"})
        finally:
            plt.close(fig)
    return output
