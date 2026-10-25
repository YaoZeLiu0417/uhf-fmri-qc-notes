"""Figures shared by the scripts (matplotlib, Agg backend)."""
import os, numpy as np
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
TEAL, RUST, INK = "#01696F", "#A84B2F", "#28251D"

def plot_beats(x, fs, ref_idx, det_idx, out, title, window_s=20, start_s=None):
    t = np.arange(len(x)) / fs
    if start_s is None: start_s = t[-1] / 2
    m = (t >= start_s) & (t < start_s + window_s)
    fig, ax = plt.subplots(2, 1, figsize=(11, 5.5), gridspec_kw={"height_ratios": [2, 1]})
    ax[0].plot(t[m], x[m], lw=0.8, color=INK)
    for r in ref_idx[(ref_idx / fs >= start_s) & (ref_idx / fs < start_s + window_s)]: ax[0].axvline(r / fs, color=TEAL, lw=1.2, alpha=0.8)
    for d in det_idx[(det_idx / fs >= start_s) & (det_idx / fs < start_s + window_s)]: ax[0].axvline(d / fs, color=RUST, lw=1.0, ls="--", alpha=0.9)
    ax[0].set_title(title); ax[0].set_ylabel("signal (a.u.)")
    ax[0].plot([], [], color=TEAL, label="comparison reference"); ax[0].plot([], [], color=RUST, ls="--", label="offline detection"); ax[0].legend(loc="upper right", frameon=False)
    ax[1].plot(ref_idx[1:] / fs / 60, 60 / (np.diff(ref_idx) / fs), color=TEAL, lw=0.8, label="reference pulse rate")
    ax[1].plot(det_idx[1:] / fs / 60, 60 / (np.diff(det_idx) / fs), color=RUST, lw=0.6, alpha=0.7, label="detected pulse rate")
    ax[1].set_xlabel("time (min)"); ax[1].set_ylabel("pulses / min"); ax[1].legend(frameon=False, ncol=2)
    for a in ax: a.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); os.makedirs(os.path.dirname(out) or ".", exist_ok=True); fig.savefig(out + ".png", dpi=130); plt.close(fig)

def plot_qc(panels, rvt_t, rvt_v, out, title):
    fig, ax = plt.subplots(len(panels) + 1, 1, figsize=(11, 2.6 * (len(panels) + 1))); ax = np.atleast_1d(ax)
    for k, (lab, c, v) in enumerate(panels):
        ax[k].plot(c / 60, v, color=TEAL, lw=1.2); ax[k].set_ylabel(lab); ax[k].spines[["top", "right"]].set_visible(False)
    if rvt_t is not None: ax[-1].plot(rvt_t / 60, rvt_v, color=RUST, lw=0.8); ax[-1].set_ylabel("RVT (a.u.)")
    ax[-1].set_xlabel("time (min)"); ax[-1].spines[["top", "right"]].set_visible(False)
    fig.suptitle(title); fig.tight_layout(); os.makedirs(os.path.dirname(out) or ".", exist_ok=True); fig.savefig(out + ".png", dpi=130); plt.close(fig)
