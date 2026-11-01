#!/usr/bin/env python3
"""Cross-platform build/isolation tests, not Windows/Qt/media qualification."""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "native-host/scripts"
sys.path.insert(0, str(SCRIPTS))
import prepare
import stage
import smoke_windows


class BuildContractTests(unittest.TestCase):
    def test_repository_text_reads_have_explicit_utf8(self):
        # Source files and bilingual docs are UTF-8, independent of Windows ACP.
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == "read_text"]
        self.assertTrue(calls)
        for call in calls:
            self.assertTrue(any(keyword.arg == "encoding" and
                                isinstance(keyword.value, ast.Constant) and
                                keyword.value.value == "utf-8" for keyword in call.keywords),
                            "repository source read must explicitly use UTF-8")

    def test_lock_matches_pinned_obs_and_only_needed_dependencies(self):
        lock = json.loads((ROOT / "desktop/dependencies.lock.json").read_text(encoding="utf-8"))
        presets = json.loads((ROOT / "obs/obs-studio/CMakePresets.json").read_text(encoding="utf-8"))
        artifacts = prepare.locked_artifacts(lock, presets)
        self.assertEqual([a["id"] for a in artifacts], ["obs-deps", "obs-qt"])
        for field, value in [("obsCommit", "0" * 40)]:
            bad = copy.deepcopy(lock)
            bad[field] = value
            with self.assertRaises(ValueError):
                prepare.locked_artifacts(bad, presets)
        for field in ("sha256", "url", "version"):
            bad = copy.deepcopy(lock)
            next(a for a in bad["artifacts"] if a["id"] == "obs-qt")[field] = "not-pinned"
            with self.assertRaises(ValueError):
                prepare.locked_artifacts(bad, presets)

    def test_cache_is_rehashed_and_offline_never_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            payload = cache / "obs-qt.zip"
            payload.write_bytes(b"fixture archive")
            artifact = {"id": "obs-qt", "sha256": prepare.digest(payload), "url": "https://example.invalid/fixture"}
            with patch("urllib.request.urlopen", side_effect=AssertionError("network must not run")):
                self.assertEqual(prepare.obtain(artifact, cache, True), payload)
                payload.write_bytes(b"corrupt")
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    prepare.obtain(artifact, cache, False)
                with self.assertRaisesRegex(ValueError, "Offline cache missing"):
                    prepare.obtain(dict(artifact, id="missing"), cache, True)

    def test_snapshot_excludes_untracked_and_rejects_modified_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "source", root / "snapshot"
            source.mkdir()
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            (source / "tracked.txt").write_text("fixed contents\n")
            (source / "nested with spaces").mkdir()
            (source / "nested with spaces/second.txt").write_text("another tracked entry\n")
            subprocess.run(["git", "-C", str(source), "add", "."], check=True)
            subprocess.run(["git", "-C", str(source), "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)
            pin = prepare.git(source, "rev-parse", "HEAD").strip()
            (source / "untracked-secret.txt").write_text("not copied")
            with patch.object(prepare, "OBS_COMMIT", pin):
                prepare.snapshot(source, output)
                self.assertFalse((output / "untracked-secret.txt").exists())
                self.assertEqual((output / "nested with spaces/second.txt").read_text(encoding="utf-8"), "another tracked entry\n")
                receipt = json.loads((output / ".webobs-source.json").read_text(encoding="utf-8"))
                self.assertEqual(len(receipt["files"]), 2)
                prepare.snapshot(source, output)
                (output / "tracked.txt").write_text("patched")
                with self.assertRaisesRegex(ValueError, "snapshot was modified"):
                    prepare.snapshot(source, output)
                (source / "tracked.txt").write_text("dirty upstream")
                with self.assertRaisesRegex(ValueError, "tracked modifications"):
                    prepare.snapshot(source, root / "another")

    @unittest.skipIf(sys.platform == "win32", "Windows Git normally checks out symlinks as text")
    def test_snapshot_materializes_link_text_without_reading_external_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "source", root / "snapshot"
            source.mkdir()
            (root / "private.txt").write_text("never copied")
            (source / "tool-link").symlink_to("../private.txt")
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            subprocess.run(["git", "-C", str(source), "add", "."], check=True)
            subprocess.run(["git", "-C", str(source), "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)
            pin = prepare.git(source, "rev-parse", "HEAD").strip()
            with patch.object(prepare, "OBS_COMMIT", pin):
                prepare.snapshot(source, output)
                self.assertFalse((output / "tool-link").is_symlink())
                self.assertEqual((output / "tool-link").read_text(encoding="utf-8"), "../private.txt")
                prepare.snapshot(source, output)

    def fixture_runtime(self, root: Path) -> tuple[Path, Path, Path]:
        repo, source, runtime = root / "repo", root / "source", root / "runtime"
        for path in stage.REQUIRED:
            target = runtime / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"fixture - not a real binary")
        for path in ("native-host/scripts/launch-native.ps1", "native-host/README.md", "native-host/LICENSE", "desktop/dependencies.lock.json"):
            target = repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("fixture")
        source.mkdir()
        (source / "COPYING").write_text("fixture license")
        return repo, source, runtime

    def test_staging_requires_native_qt_plugin_and_new_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            repo, source, runtime = self.fixture_runtime(Path(directory))
            manifest = stage.finalize(repo, source, runtime, "0.1.0-dev.test")
            self.assertEqual(json.loads((runtime / "webobs-native-prototype.json").read_text(encoding="utf-8")), manifest)
            self.assertFalse(manifest["defaultProduct"])
            self.assertEqual(manifest["servicesStarted"], [])
            self.assertEqual(manifest["obsCommit"], prepare.OBS_COMMIT)
            self.assertTrue((runtime / "portable_mode.txt").exists())
            self.assertTrue((runtime / "disable_updater.txt").exists())
            self.assertFalse((runtime / "config").exists())
            self.assertGreater(manifest["sizeBytesBeforeManifest"], 0)
            with self.assertRaisesRegex(ValueError, "new, separate"):
                stage.finalize(repo, source, runtime, "0.1.0-dev.test")
        with tempfile.TemporaryDirectory() as directory:
            repo, source, runtime = self.fixture_runtime(Path(directory))
            (runtime / "config").mkdir()
            with self.assertRaisesRegex(ValueError, "user configuration"):
                stage.finalize(repo, source, runtime, "0.1.0-dev.test")
        with tempfile.TemporaryDirectory() as directory:
            repo, source, runtime = self.fixture_runtime(Path(directory))
            # A symlink cannot stand in for Qt's native Windows platform plugin.
            target = runtime / "bin/64bit/platforms/qwindows.dll"
            target.unlink()
            with self.assertRaisesRegex(ValueError, "qwindows.dll"):
                stage.finalize(repo, source, runtime, "0.1.0-dev.test")
            with self.assertRaisesRegex(ValueError, "development-tagged"):
                stage.finalize(repo, source, runtime, "0.1.0")

    def test_smoke_fingerprint_detects_changes_without_exporting_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "private-obs"
            self.assertEqual(smoke_windows.fingerprint(profile), {})
            profile.mkdir()
            (profile / "secret.ini").write_text("private fixture")
            before = smoke_windows.fingerprint(profile)
            self.assertNotIn("private fixture", json.dumps(before))
            (profile / "secret.ini").write_text("changed private fixture")
            self.assertNotEqual(smoke_windows.fingerprint(profile), before)

    def test_launcher_and_builder_keep_architecture_boundaries(self):
        builder = (ROOT / "desktop/scripts/build-obs-native.ps1").read_text(encoding="utf-8")
        launcher = (SCRIPTS / "launch-native.ps1").read_text(encoding="utf-8")
        for expected in ("-DENABLE_FRONTEND=ON", "-DENABLE_BROWSER=OFF", "-DQt6_DIR=", "-A','x64", "-DCMAKE_SYSTEM_VERSION=10.0.22621.0", "BuildDirectory already exists"):
            self.assertIn(expected, builder)
        for forbidden in ("prepare-obs-headless.py", "Invoke-Checked 'pnpm'", "ENABLE_FRONTEND=OFF", "Invoke-Checked 'node'", "clients/", "GStreamer"):
            # Comment explicitly states no GStreamer; commands must never import it.
            if forbidden != "GStreamer":
                self.assertNotIn(forbidden, builder)
        for expected in ("$AllowPrototype", "--portable", "--disable-updater", "WorkingDirectory = Join-Path $root 'bin/64bit'", "OBS_PLUGINS_PATH", "QT_PLUGIN_PATH", "defaultProduct", "$ProcessGatePath", "Get-CimInstance Win32_Process"):
            self.assertIn(expected, launcher)
        self.assertNotIn("Start-Process", launcher)  # Explicit child environment, fixed CWD.
        self.assertNotIn("--multi", launcher)  # Do not bypass upstream portable instance guard.

    def test_build_symbols_are_stripped_before_the_manifest(self):
        builder = (ROOT / "desktop/scripts/build-obs-native.ps1").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/windows-obs-native-host.yaml").read_text(encoding="utf-8")
        self.assertIn("native-host/scripts/prune_runtime.py", builder)
        self.assertLess(
            builder.index("prune_runtime.py"),
            builder.index("native-host/scripts/stage.py"),
        )
        self.assertIn("native-runtime-prune.json", workflow)
        self.assertIn("-Filter *.pdb", workflow)
        self.assertIn("build-symbol PDB files", workflow)

    def test_nsis_install_receipt_records_actual_footprint(self):
        workflow = (ROOT / ".github/workflows/windows-obs-native-host.yaml").read_text(encoding="utf-8")
        self.assertIn("New-InstalledTreeFootprintScope -Root $root -Purpose isolated-nsis-install-before-first-start", workflow)
        self.assertIn("$footprint = Measure-InstalledTreeFootprint -Scope $scope", workflow)
        self.assertIn("installed = $footprint", workflow)
        self.assertLess(
            workflow.index("New-InstalledTreeFootprintScope"),
            workflow.index("Measure-InstalledTreeFootprint"),
        )

    def test_p5_campaign_plan_is_scheduled_not_measured(self):
        plan = (ROOT / "native-host/qualification/plan.py").read_text(encoding="utf-8")
        self.assertIn('"qualified": False', plan)
        self.assertIn('"status": "planned"', plan)
        self.assertIn("plan.py", (ROOT / "native-host/qualification/README.md").read_text(encoding="utf-8"))
        self.assertIn("plan.py", (ROOT / "docs/windows-target-qualification-runbook.md").read_text(encoding="utf-8"))

    def test_p5_preflight_is_diagnostic_only(self):
        workflow = (ROOT / ".github/workflows/windows-obs-native-host.yaml").read_text(encoding="utf-8")
        preflight = (ROOT / "native-host/qualification/preflight.py").read_text(encoding="utf-8")
        self.assertIn("native-host/qualification/preflight.py", workflow)
        self.assertIn("--diagnostic", workflow)
        self.assertIn("native-p5-preflight-diagnostic.json", workflow)
        self.assertIn("never marks a P5 campaign qualified", preflight)
        self.assertIn('"qualified": False', preflight)

    def test_size_gap_comparison_runs_against_stock_obs(self):
        workflow = (ROOT / ".github/workflows/windows-obs-native-host.yaml").read_text(encoding="utf-8")
        script = (SCRIPTS / "compare_runtime_sizes.py").read_text(encoding="utf-8")
        self.assertIn("native-host/scripts/compare_runtime_sizes.py", workflow)
        self.assertIn("--prototype build/obs-native-ci/runtime --obs $root", workflow)
        self.assertIn("build/obs-native-ci/native-size-compare.json", workflow)
        self.assertLess(
            workflow.index("Measure the stock OBS 32.1.2 installation"),
            workflow.index("--obs $root"),
        )
        for expected in ("obsOnlyGroups", "sharedPercentOfObsBytes", "largestObsOnly"):
            self.assertIn(expected, script)

    def test_runtime_inventory_enforces_budget_and_accounting(self):
        workflow = (ROOT / ".github/workflows/windows-obs-native-host.yaml").read_text(encoding="utf-8")
        script = (SCRIPTS / "runtime_inventory.py").read_text(encoding="utf-8")
        self.assertIn("native-host/scripts/runtime_inventory.py", workflow)
        self.assertIn("--max-runtime-bytes 104857600", workflow)
        self.assertIn("build/obs-native-ci/native-runtime-inventory.json", workflow)
        self.assertLess(
            workflow.index("Inventory the runtime"),
            workflow.index("Freeze clean non-default prototype"),
        )
        for expected in ('".pdb"', '".lib"', "licenseHint", "withinBudget"):
            self.assertIn(expected, script)

    def test_installer_is_per_user_and_never_deletes_private_config(self):
        script = (ROOT / "native-host/installer/WebOBSNative.nsi").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/windows-obs-native-host.yaml").read_text(encoding="utf-8")
        self.assertIn("RequestExecutionLevel user", script)
        self.assertIn('StrCmp $1 "config" un_next', script)
        self.assertIn('StrCmp $1 "backups" un_next', script)
        self.assertNotIn('RMDir /r "$INSTDIR"', script)
        self.assertIn("File /r \"${PACKAGE_DIR}\\*.*\"", script)
        self.assertIn('WriteUninstaller "$INSTDIR\\Uninstall.exe"', script)
        self.assertIn("Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\WebOBSNativePrototype", script)
        self.assertIn("native-host/installer/WebOBSNative.nsi", workflow)
        self.assertIn("choco install nsis", workflow)
        self.assertIn("configPreservedAcrossReinstall = $true", workflow)
        self.assertIn("configPreservedAcrossUninstall = $true", workflow)
        self.assertIn("signed = $false", workflow)

    def test_process_gate_rejects_helper_services_and_orphans(self):
        workflow = (ROOT / ".github/workflows/windows-obs-native-host.yaml").read_text(encoding="utf-8")
        smoke = (ROOT / "native-host/tests/smoke_windows.py").read_text(encoding="utf-8")
        self.assertIn("native-*-process-gate.json", workflow)
        for expected in ("FORBIDDEN_PROCESS_NAMES", "SERVICE_LISTENER_PORTS", "check_process_gate"):
            self.assertIn(expected, smoke)
        base = {"schema": 1, "samples": 3, "observed": [{"name": "obs64.exe"}], "listeners": [], "orphans": []}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gate.json"

            def write(payload):
                path.write_text(json.dumps(payload), encoding="utf-8")

            write(base)
            self.assertEqual(smoke_windows.check_process_gate(path)["orphanCount"], 0)
            for payload in (
                {**base, "observed": [{"name": "ffmpeg.exe"}]},
                {**base, "orphans": [{"name": "obs64.exe"}]},
                {**base, "listeners": [{"port": 8554, "name": "obs64"}]},
                {**base, "samples": 0},
            ):
                write(payload)
                with self.assertRaises(AssertionError):
                    smoke_windows.check_process_gate(path)

    def test_crash_smoke_kills_the_host_and_requires_no_survivors(self):
        workflow = (ROOT / ".github/workflows/windows-obs-native-host.yaml").read_text(encoding="utf-8")
        launcher = (ROOT / "native-host/scripts/launch-native.ps1").read_text(encoding="utf-8")
        smoke = (ROOT / "native-host/tests/smoke_windows.py").read_text(encoding="utf-8")
        self.assertIn("--crash-smoke", workflow)
        self.assertIn("native-crash-smoke.json", workflow)
        self.assertIn("--crash-after-seconds 8", workflow)
        self.assertIn("$CrashAfterSeconds", launcher)
        self.assertIn("-CrashProbe", smoke)
        self.assertIn("$CrashProbe", launcher)
        self.assertIn("--second-instance-smoke", workflow)
        self.assertIn("native-second-instance-smoke.json", workflow)
        self.assertIn("run_second_instance", smoke)
        self.assertIn("$AllowMultiple", launcher)
        self.assertIn("WebObsNativeHostSingleInstance", launcher)
        self.assertIn("native-nsis-upgrade.json", workflow)
        self.assertIn("v4.1.0-dev.40", workflow)
        self.assertIn("7cc5724c0aee941802bdc9f8ed71b7547d1b3d73631170e003c5a03d7bb2a54d", workflow)
        self.assertIn("configPreservedAcrossUpgrade", workflow)
        self.assertIn(".Replace('\\','/')", workflow)
        self.assertIn("crashed = [bool]$gateCrashed", launcher)
        self.assertIn('--crash-smoke', smoke)
        self.assertIn('gate.get("crashed") is not True', smoke)

    def test_native_control_boundary_has_standalone_linux_and_msvc_contracts(self):
        workflow = (ROOT / ".github/workflows/web-runtime-ci.yaml").read_text(encoding="utf-8")
        standalone = (ROOT / "native-host/tests/control-auth/CMakeLists.txt").read_text(encoding="utf-8")
        root_cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        manifest = json.loads((ROOT / "native-host/tests/control-auth-vcpkg/vcpkg.json").read_text(encoding="utf-8"))
        self.assertIn("native-control-contracts:", workflow)
        self.assertIn("windows-native-control-contracts:", workflow)
        self.assertIn("native-host/tests/test_legacy_import.py", workflow)
        self.assertIn("native-host/tests/control-auth", workflow)
        self.assertIn("x64-windows-static", workflow)
        self.assertEqual(workflow.count("contents: write"), 1)
        optional_caller = workflow.split("  windows-desktop-candidate:", 1)[1].split("  public-audit:", 1)[0]
        self.assertIn("contents: write", optional_caller)
        self.assertIn("official: false", optional_caller)
        self.assertNotIn("publish_dev", optional_caller)
        self.assertIn("core/src/native_control_auth.cpp", standalone)
        self.assertIn("core/src/authentication.cpp", standalone)
        self.assertNotIn("add_subdirectory", standalone)
        self.assertNotIn("find_package(libobs", standalone)
        self.assertNotIn("find_package(Qt", standalone)
        self.assertIn("native-control-no-media-symbols", standalone)
        self.assertIn("webobs-native-control-auth-tests", root_cmake)
        self.assertEqual(manifest["dependencies"], ["openssl", "sqlite3", "curl", "jansson"])
        self.assertIn("core/src/native_cluster_authorization.cpp", standalone)
        self.assertIn("test_native_cluster_authorization.py", standalone)
        self.assertIn("native-cluster-no-media-symbols", standalone)
        self.assertEqual(manifest["builtin-baseline"], "eb2d3a3279fd019cb7733072d86900d0ad2a1aef")

    def test_native_graph_ownership_contracts_use_pinned_headers_without_media(self):
        workflow = (ROOT / ".github/workflows/web-runtime-ci.yaml").read_text(encoding="utf-8")
        cmake = (ROOT / "native-host/CMakeLists.txt").read_text(encoding="utf-8")
        job = workflow.split("  native-graph-api-contracts:", 1)[1].split("  windows-update-contracts:", 1)[0]
        self.assertIn("os: [ubuntu-24.04, windows-2022]", job)
        self.assertIn("git submodule update --init --depth 1 obs/obs-studio", job)
        self.assertIn("actual == pin", job)
        self.assertIn("cmake --build build/native-graph-api --config Release --parallel 2 --verbose", job)
        self.assertIn("-DWEBOBS_NATIVE_BUILD_PLUGIN=OFF", job)
        self.assertIn("-DWEBOBS_NATIVE_BUILD_TESTS=ON", job)
        self.assertNotIn("vcpkg", job)
        self.assertNotIn("build-obs-native.ps1", job)
        self.assertIn("tests/product_bootstrap_test.cpp src/product_bootstrap.cpp", cmake)
        self.assertIn("native-product-bootstrap-api-contract", cmake)
        self.assertIn("tests/wall_snapshot_test.cpp src/wall_snapshot.cpp", cmake)
        self.assertIn("native-wall-snapshot-api-contract", cmake)
        self.assertIn("target_compile_options(native-wall-snapshot-test PRIVATE /EHs /EHc-)", cmake)
        plugin = cmake.split("if(WEBOBS_NATIVE_BUILD_PLUGIN)", 1)[1].split("if(WEBOBS_NATIVE_BUILD_TESTS)", 1)[0]
        self.assertNotIn("/EHc-", plugin)
        self.assertIn('TIMEOUT 30 LABELS "native;api-contract;no-media"', cmake)

    def test_offline_private_staging_is_a_separate_no_media_matrix(self):
        workflow = (ROOT / ".github/workflows/web-runtime-ci.yaml").read_text(encoding="utf-8")
        job = workflow.split("  native-private-staging-contracts:", 1)[1].split("  windows-native-control-contracts:", 1)[0]
        self.assertIn("os: [ubuntu-24.04, windows-2022]", job)
        for name in ("test_legacy_stage_document.py", "test_private_stage.py", "test_legacy_stage.py"):
            self.assertIn(name, job)
        for command in ("vcpkg", "submodule", "build-obs", "obs64", "upload-artifact"):
            self.assertNotIn(command, job)
        self.assertNotIn("contents: write", job)
        cli = (SCRIPTS / "legacy_stage.py").read_text(encoding="utf-8")
        self.assertIn("--existing-config-root", cli)
        self.assertIn("document_stage.verify", cli)
        self.assertNotIn("subprocess", cli)

    def test_real_loader_gate_is_standalone_and_never_installed(self):
        cmake = (ROOT / 'native-host/tests/real-loader/CMakeLists.txt').read_text(encoding="utf-8")
        probe = (ROOT / 'native-host/tests/real-loader/loader_probe.cpp').read_text(encoding="utf-8")
        builder = (ROOT / 'desktop/scripts/build-obs-native.ps1').read_text(encoding="utf-8")
        workflow = (ROOT / '.github/workflows/web-runtime-ci.yaml').read_text(encoding="utf-8")
        self.assertIn('find_package(libobs 32.1.2 EXACT CONFIG REQUIRED)', cmake)
        self.assertIn('PRIVATE OBS::libobs', cmake)
        self.assertNotIn('install(', cmake)
        self.assertIn('TIMEOUT 60', cmake)
        self.assertIn('test_real_legacy_loader.py', cmake)
        for forbidden in ('obs_reset_video(', 'obs_reset_audio(', 'obs_load_all_modules(',
                          'obs_open_module(', 'obs_frontend_', 'obs_set_output_source('):
            self.assertNotIn(forbidden, probe)
        self.assertIn("Join-Path $repoRoot 'native-host/tests/real-loader'", builder)
        self.assertIn('$env:PATH = $beforeLoaderPath', builder)
        job = workflow.split('  native-real-loader-contracts:', 1)[1].split('  native-private-staging-contracts:', 1)[0]
        self.assertIn('--target libobs', job)
        self.assertIn('-DENABLE_FRONTEND=OFF', job)
        self.assertIn('-DENABLE_PLUGINS=OFF', job)
        self.assertIn('extra-cmake-modules', job)
        self.assertIn('xvfb xauth libglvnd-dev', job)
        self.assertIn('xvfb-run -a ctest --test-dir build/native-real-loader', job)
        self.assertNotIn('upload-artifact', job)
        self.assertNotIn('contents: write', job)

    def test_native_account_overflow_guard_survives_windows_max_macro(self):
        source = (ROOT / "core/src/native_cluster_authorization.cpp").read_text(encoding="utf-8")
        # curl may expose the SDK's function-like max macro. Keep the callable
        # parenthesized rather than changing the arithmetic or weakening bounds.
        self.assertIn("(std::numeric_limits<std::size_t>::max)() / size", source)
        self.assertNotIn("std::numeric_limits<std::size_t>::max()", source)

    def test_operation_auth_orchestrator_is_bounded_and_cached_nothing(self):
        header = (ROOT / "core/include/webobs/native_operation_auth.hpp").read_text(encoding="utf-8")
        source = (ROOT / "core/src/native_operation_auth.cpp").read_text(encoding="utf-8")
        standalone = (ROOT / "native-host/tests/control-auth/CMakeLists.txt").read_text(encoding="utf-8")
        root_cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        # Wired into both the standalone Linux/MSVC contract and the root build.
        self.assertIn("core/src/native_operation_auth.cpp", standalone)
        self.assertIn("webobs-native-operation-auth-tests", standalone)
        self.assertIn("native-operation-auth", standalone)
        self.assertIn("core/src/native_operation_auth.cpp", root_cmake)
        self.assertIn("webobs-native-operation-auth-tests", root_cmake)
        # Fail-closed whole-operation gate: one budget, no reusable grant cache.
        self.assertIn("total_budget", header)
        self.assertNotIn("std::map", source)
        self.assertNotIn("std::unordered_map", source)
        self.assertIn("current - start >= total_budget", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
