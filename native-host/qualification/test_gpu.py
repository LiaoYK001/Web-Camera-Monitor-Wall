"""Synthetic attribution tests; actual PDH calls live in test_windows_api.py."""
import copy
import unittest

from gpu import Sampler, select


def name(pid=10, engine=0, kind="3D", luid="0x00000000_0x00001234"):
    return f"pid_{pid}_luid_{luid}_phys_0_eng_{engine}_engtype_{kind}"


class FakePdh:
    def __init__(self, rows=None, errors=None):
        self.rows = rows or {}
        self.errors = errors or {}
        self.closed = 0

    def read(self):
        return copy.deepcopy(self.rows), self.errors.copy()

    def close(self):
        self.closed += 1


class GpuTests(unittest.TestCase):
    def test_keeps_devices_and_engines_separate_and_discards_other_processes(self):
        rows, rejected = select({"engines": [(name(), 0, 12.5), (name(engine=1, kind="VideoDecode"), 1, 20.),
                                             (name(luid="0x0_0x9999"), 0, 3.), (name(pid=99), 0, 100.)]},
                                {10: "10:100"})
        self.assertEqual(rejected, 0)
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["engineType"] for r in rows}, {"3D", "VideoDecode"})
        self.assertEqual(len({r["adapterLuid"] for r in rows}), 2)
        self.assertTrue(all(r["identity"] == "10:100" for r in rows))
        self.assertEqual(rows[0]["utilizationPercent"], 12.5)
        self.assertNotIn("total", rows[0])

    def test_memory_is_a_separate_gauge_not_an_engine_total(self):
        instance = "pid_10_luid_0x0_0x1234_phys_0"
        rows, rejected = select({"dedicated": [(instance, 0, 123456)], "shared": [(instance, 0, 65536)]}, {10: "owned"})
        self.assertEqual([r["bytes"] for r in rows], [123456, 65536])
        self.assertEqual(rejected, 0)

    def test_invalid_unknown_and_duplicate_rows_do_not_turn_into_zeros(self):
        values = [(name(), 0, 0.), (name(), 0, 2.), (name(engine=1), 0xC0000BBA, 9.),
                  ("unrecognized-private-instance", 0, 42.), (name(engine=2), 0, float('nan')),
                  (name(engine=3), 0, -1.), (name(engine=4), 0, True)]
        rows, rejected = select({"engines": values}, {10: "owned"})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["utilizationPercent"], 0.)
        self.assertEqual(rejected, 6)
        self.assertEqual(select({}, {10: "owned"}), ([], 0))

    def test_pid_reuse_or_exit_is_not_attributed_to_the_previous_process(self):
        backend = FakePdh({"engines": [(name(), 0, 15.)]})
        sampler = Sampler(backend)
        def processes(identity="10:100", exited=False):
            return [{"pid": 10, "identity": identity, "exited": exited}]
        self.assertEqual(sampler.sample(processes(), lambda _: True)["status"], "priming")
        self.assertEqual(len(sampler.sample(processes(), lambda _: True)["rows"]), 1)
        self.assertEqual(sampler.sample(processes("10:200"), lambda _: True)["rows"], [])
        self.assertEqual(len(sampler.sample(processes("10:200"), lambda _: True)["rows"]), 1)
        self.assertEqual(sampler.sample(processes("10:200"), lambda _: False)["rows"], [])
        self.assertEqual(sampler.sample(processes(exited=True), lambda _: True)["rows"], [])
        sampler.close()
        self.assertEqual(backend.closed, 1)

    def test_missing_counters_stay_unavailable_with_codes_and_no_parity_verdict(self):
        sampler = Sampler(FakePdh(errors={"engines": 0xC0000BB8}))
        process = [{"pid": 10, "identity": "10:100", "exited": False}]
        sampler.sample(process, lambda _: True)
        value = sampler.sample(process, lambda _: True)
        self.assertEqual(value["status"], "unavailable")
        self.assertEqual(value["counterErrors"], {"engines": "0xc0000bb8"})
        self.assertEqual(value["rows"], [])
        self.assertFalse(value["qualified"])
        self.assertTrue(value["coverageIncomplete"])


if __name__ == '__main__':
    unittest.main()
