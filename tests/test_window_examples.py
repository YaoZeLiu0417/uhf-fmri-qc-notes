"""Known plotting coordinates and anonymous synthetic output."""
import struct

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.text import Text
import numpy as np

from scripts.plot_window_examples import render_examples


def test_three_anonymous_windows_interpolate_markers_and_save_png(tmp_path, monkeypatch):
    examples = [
        dict(category=category, source="PRIVATE_SOURCE_ID", run_id="PRIVATE_RUN_ID",
             time_s=np.array([100, 101, 102]), raw=np.array(raw), fs=1, start_time=100,
             detector_a_times=np.array([99, 100.25, 103]), detector_b_times=np.array([100.5]),
             explanation="Known synthetic example; not participant data.")
        for category, raw in [("clear", [1000, 2000, 3000]),
                              ("clipping", [1000, 4095, 4095]),
                              ("disagreement", [1000, 2500, 1000])]
    ]
    closed = []
    original_close = plt.close

    def record_close(figure=None):
        if isinstance(figure, Figure):
            closed.append(figure)
        original_close(figure)

    monkeypatch.setattr(plt, "close", record_close)
    output = render_examples(examples, tmp_path / "synthetic_windows")
    assert output.suffix == ".png"
    with output.open("rb") as stream:
        header = stream.read(24)
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    assert min(struct.unpack(">II", header[16:24])) >= 1600
    fig = closed[-1]
    assert len(fig.axes) == 3 and not plt.fignum_exists(fig.number)
    np.testing.assert_allclose(fig.axes[0].collections[0].get_offsets(), [[0.25, 1250]])
    np.testing.assert_allclose(fig.axes[0].collections[1].get_offsets(), [[0.5, 1500]])
    labels = " ".join(item.get_text() for item in fig.findobj(match=Text))
    assert "PRIVATE_SOURCE_ID" not in labels and "PRIVATE_RUN_ID" not in labels
    assert "not independent ECG truth" in labels
