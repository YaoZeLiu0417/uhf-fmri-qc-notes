import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DEFAULT_DATA_ROOT = os.path.join(os.path.dirname(ROOT), "data-physio")

def load_sessions(data_root=None):
    data_root = data_root or os.environ.get("PHYSIO_DATA_ROOT", DEFAULT_DATA_ROOT)
    m = json.load(open(os.path.join(ROOT, "sessions.json")))["sessions"]
    for k, v in m.items():
        for key in ("puls", "resp"):
            if key in v: v[key] = os.path.join(data_root, v[key])
        v["out_dir"] = os.path.join(ROOT, "results", v["role"], k)
    return m
