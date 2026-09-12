"""Minimal QC for one fMRI run: tSNR map, mean-GM tSNR, framewise displacement, DVARS.
Usage: python qc_tsnr_motion.py bold.nii.gz [--mask mask.nii.gz] [--motion motion.par] --out qc/run01
Motion file: 6 columns (3 rot rad, 3 trans mm) as produced by FSL mcflirt (.par).
"""
import argparse, json, os
import numpy as np, nibabel as nib
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

def tsnr(data):
    m, s = data.mean(-1), data.std(-1)
    return np.where(s > 0, m / np.maximum(s, 1e-6), 0)

def dvars(data, mask):
    d = np.diff(data[mask], axis=-1)
    return np.sqrt((d ** 2).mean(0))

def fd(par, radius=50.0):
    p = np.loadtxt(par)
    rot, trans = p[:, :3] * radius, p[:, 3:]
    return np.abs(np.diff(np.hstack([rot, trans]), axis=0)).sum(1)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("bold"); ap.add_argument("--mask"); ap.add_argument("--motion"); ap.add_argument("--out", required=True)
    a = ap.parse_args(); os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    img = nib.load(a.bold); data = img.get_fdata()
    mask = nib.load(a.mask).get_fdata() > 0 if a.mask else data.mean(-1) > np.percentile(data.mean(-1), 60)
    t = tsnr(data); nib.save(nib.Nifti1Image(t.astype(np.float32), img.affine), a.out + "_tsnr.nii.gz")
    summary = {"n_vol": data.shape[-1], "tsnr_mask_mean": float(t[mask].mean()), "tsnr_mask_median": float(np.median(t[mask])), "dvars_mean": float(dvars(data, mask).mean())}
    fig, ax = plt.subplots(2 if a.motion else 1, 1, figsize=(8, 5), squeeze=False)
    ax[0, 0].plot(dvars(data, mask)); ax[0, 0].set_title("DVARS")
    if a.motion:
        f = fd(a.motion); summary.update({"fd_mean_mm": float(f.mean()), "fd_max_mm": float(f.max()), "frac_fd_gt_0p3": float((f > 0.3).mean())})
        ax[1, 0].plot(f); ax[1, 0].axhline(0.3, ls="--"); ax[1, 0].set_title("Framewise displacement (mm)")
    fig.tight_layout(); fig.savefig(a.out + "_qc.png", dpi=120)
    json.dump(summary, open(a.out + "_summary.json", "w"), indent=2); print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
