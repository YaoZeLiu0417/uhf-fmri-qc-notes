"""Synthetic exports verify timing, source identity and refusal of invalid data."""
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from physio.bids import export_manifest, extract_segment, onset_seconds
from physio.siemens_pmu import load_pmu


class BIDSExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = self.root / "raw"
        self.raw.mkdir()

    def log(self, kind, first=10, last=30, count=2001, flat=False, clock=True):
        samples = np.full(count, 2048) if flat else np.arange(count) % 1000 + 1000
        path = self.raw / f"private-person.{kind}"
        footer = f"LogStartMDHTime: {int(first * 1000)}\nLogStopMDHTime: {int(last * 1000)}\n" if clock else ""
        path.write_text(f"1 2 40 280 5002 LOGVERSION_{kind.upper()} 1 6002 "
                        + " ".join(map(str, samples)) + " 5003\n" + footer, encoding="ascii")
        return path, samples

    def manifest(self, **changes):
        run = {"run_id": "sub-01_ses-pre_task-rest_run-1", "volume_start": 15,
               "duration_seconds": 10, "puls": "raw/private-person.puls"}
        run.update(changes)
        path = self.root / "private-manifest.json"
        path.write_text(json.dumps({"runs": [run]}), encoding="utf-8")
        return path

    def test_different_rates_offsets_and_exact_source_samples(self):
        puls, original = self.log("puls", first=8, last=32, count=2402)
        self.log("resp", first=12, last=29, count=1700)
        rec = load_pmu(str(puls))
        samples, metadata, (low, high) = extract_segment(rec, 15, 10)
        np.testing.assert_array_equal(samples, original[low:high])
        self.assertAlmostEqual(metadata["SamplingFrequency"], 2401 / 24)
        self.assertGreaterEqual(metadata["StartTime"], -5)
        report = export_manifest(self.manifest(resp="raw/private-person.resp"), self.root / "out")
        self.assertEqual(report["exported"], 2)
        values = {x["recording"]: x for x in report["recordings"]}
        self.assertAlmostEqual(values["respiratory"]["StartTime"], -3)
        self.assertAlmostEqual(values["respiratory"]["SamplingFrequency"], 1699 / 17)
        target = next((self.root / "out").rglob("*cardiac_physio.tsv.gz"))
        with gzip.open(target, "rt") as stream:
            np.testing.assert_array_equal(np.loadtxt(stream, dtype=int), samples)
        sidecar = target.with_name(target.name.replace(".tsv.gz", ".json"))
        text = sidecar.read_text()
        self.assertNotIn("private-person", text)
        self.assertNotIn(str(self.raw), text)
        self.assertNotIn("LogStartMDHTime", text)
        self.assertEqual(json.loads(text)["Columns"], ["cardiac"])

    def test_refuses_missing_coverage_flatline_and_clock(self):
        for options, reason in [({"last": 20}, "insufficient_time_coverage"),
                                ({"flat": True}, "constant_signal_during_run"),
                                ({"clock": False}, "missing_mdh_clock")]:
            with self.subTest(reason=reason):
                self.log("puls", **options)
                output = self.root / reason
                report = export_manifest(self.manifest(), output)
                self.assertEqual(report["recordings"][0]["reason"], reason)
                self.assertFalse(list(output.rglob("*physio*")))

    def test_flat_run_cannot_be_rescued_by_samples_outside_fractional_boundaries(self):
        path, _ = self.log("puls", first=0, last=2, count=21, flat=True)
        rec = load_pmu(str(path))
        rec.signal[1] = 1900  # 0.1 s: before run start
        rec.signal[9] = 2100  # 0.9 s: after the first window, exactly at second stop
        for start, duration in ((.15, .7), (.2, .7)):
            with self.subTest(start=start), self.assertRaisesRegex(ValueError, "constant_signal_during_run"):
                extract_segment(rec, start, duration)
        with self.assertRaisesRegex(ValueError, "no_samples_during_run"):
            extract_segment(rec, .11, .01)
        rec.signal[2] = 1900  # 0.2 s is included at the second window's start.
        extract_segment(rec, .2, .7)

    def test_deterministic_gzip_and_no_overwrite(self):
        self.log("puls")
        manifest = self.manifest(volume_start="00:00:15.000")
        for name in ("out1", "out2"):
            self.assertEqual(export_manifest(manifest, self.root / name)["exported"], 1)
        one = next((self.root / "out1").rglob("*.tsv.gz"))
        two = next((self.root / "out2").rglob("*.tsv.gz"))
        self.assertEqual(one.read_bytes(), two.read_bytes())
        before = one.read_bytes()
        self.assertEqual(export_manifest(manifest, self.root / "out1")["recordings"][0]["reason"], "output_exists")
        self.assertEqual(before, one.read_bytes())

    def test_refuses_input_output_overlap_and_ambiguous_clock(self):
        source, _ = self.log("puls")
        original = source.read_bytes()
        with self.assertRaisesRegex(ValueError, "separate"):
            export_manifest(self.manifest(), self.raw / "exports")
        self.assertEqual(source.read_bytes(), original)
        for value in ("120000", "24:00:00", True):
            with self.assertRaises(ValueError):
                onset_seconds(value)


if __name__ == "__main__":
    unittest.main()
