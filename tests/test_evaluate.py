"""Offline evaluator tests using saved-run fixtures and mocked model responses."""

import io
import json
import os
import shutil
import tarfile
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from support import evaluate


def assessment(**overrides):
    return {
        **{field: f"Evidence: transcript.jsonl:2 ({field})" for field in evaluate.FIELDS},
        "evidence_citations": ["transcript.jsonl:2", "api-calls.json:3"],
        **overrides,
    }


def synthesis_result(count=1):
    return {"short_decision": "Fixture comparison.", "quality_scores": [80] * count}


def metrics(**overrides):
    return {
        "ended_at": "2026-01-01T00:00:00Z",
        "status": "completed",
        "timeout": False,
        "validation": "PASS",
        "coding_duration_seconds": 120,
        "validation_duration_seconds": 1,
        "actual_cost_usd": 0.05,
        "model": "fixture-model",
        "actual_served_model_id": "fixture-served",
        **overrides,
    }


class EvaluateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.parent = self.root / "results"
        root_patch = patch("runner.ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        self.task = self.parent / "scenario/task"
        self.config = {"backend": "codex", "model": "fixture-evaluator", "timeout": 10}
        prompt = patch("builtins.input", return_value="yes")
        self.confirmation = prompt.start()
        self.addCleanup(prompt.stop)
        terminal = patch("evaluate.sys.stdin.isatty", return_value=True)
        self.interactive = terminal.start()
        self.addCleanup(terminal.stop)
        # Fail closed if a test accidentally reaches a real process or HTTP request.
        for target in ("evaluate.subprocess.Popen", "evaluate.urllib.request.urlopen"):
            mock = patch(target, side_effect=AssertionError("Real model calls are forbidden"))
            mock.start()
            self.addCleanup(mock.stop)

    def saved_run(self, model="model-a", repeat="repeat-1", **changes):
        run = self.task / model / "runs" / repeat
        run.mkdir(parents=True)
        files = {
            "run.json": json.dumps(
                {"scenario": self.task.parent.name, "task_name": self.task.name}
            ),
            "metrics.json": json.dumps(metrics(**changes)),
            "task.md": "Investigate the report.\n",
            "response.txt": "No change needed.\n",
            "diff.patch": "",
            "check.log": "PASS\n",
            "evaluation-guidance.md": "Verify the report independently.\n",
            "transcript.jsonl": '{"text":"escaped\\nnewline\u2028separator"}\n\n{"done":true}\n',
            "api-calls.json": '[\n  {"usage": {"cost": 0.05}}\n]\n',
        }
        for name, text in files.items():
            (run / name).write_text(text)
        with tarfile.open(run / "baseline.tar", "w") as archive:
            data = b"first source line\nsecond source line\n"
            member = tarfile.TarInfo("src/example.py")
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
        evaluate.runner.update_latest(run)
        return run

    def test_explicit_run_rejects_failed_dry_run(self):
        run = self.saved_run(status="failed")
        metadata = json.loads((run / "run.json").read_text())
        (run / "run.json").write_text(json.dumps({**metadata, "dry_run": True}))
        for target in (run, run.parents[1] / "latest"):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "dry-run"):
                evaluate.discover(str(target), self.parent)

    def test_comparison_rejects_different_baselines_or_guidance(self):
        self.saved_run()
        other = self.saved_run(model="model-b")
        for name in ("baseline.tar", "evaluation-guidance.md"):
            path = other / name
            original = path.read_bytes()
            with self.subTest(name=name):
                path.write_bytes(original + b"changed")
                with redirect_stderr(io.StringIO()) as warning:
                    self.assertEqual(
                        len(evaluate.discover_comparison(str(self.task), self.parent)), 2
                    )
                self.assertIn("Warning: comparing different", warning.getvalue())
                path.write_bytes(original)

    def test_openrouter_rejects_invalid_assessment_without_report(self):
        run = self.saved_run()
        incomplete = assessment()
        del incomplete["observed_correctness"]
        invalid_score = assessment(scores={"D": 999, "E": 25, "F": 15, "handoff": 20})
        for findings in (incomplete, invalid_score):
            with (
                self.subTest(findings=findings),
                patch("evaluate.request_assessment", return_value=(findings, {})),
                self.assertRaises(ValueError),
            ):
                evaluate.evaluate(run, {"backend": "openrouter", "timeout": 1}, "fake")
            self.assertFalse((run / "evaluation.json").exists())
            self.assertFalse((run / "evaluation.md").exists())

    def test_shared_artifacts_preserve_evidence_hashes_and_are_read_only(self):
        first = self.saved_run()
        second = self.saved_run(model="model-b")
        before = evaluate.evidence(first)
        names = ("task.md", "evaluation-guidance.md", "baseline.tar")
        originals = {name: (first / name).read_bytes() for name in names}
        for run in (first, second):
            for name in names:
                target = (self.task.parent if name == "baseline.tar" else self.task) / name
                target.write_bytes((run / name).read_bytes())
                (run / name).unlink()
        snapshots = {
            path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in (evaluate.artifact_path(first, name) for name in names)
        }
        self.assertEqual(evaluate.discover_comparison(str(self.task), self.parent), [first, second])
        workspace = self.root / "workspace"
        workspace.mkdir()
        data, manifest = evaluate.prepare_evidence(first, workspace)
        self.assertEqual(data, before)
        for name, raw in originals.items():
            self.assertEqual(manifest["sha256"][name], evaluate.digest(raw))
        self.assertTrue(all(not path.is_symlink() for path in workspace.iterdir()))
        self.assertEqual(
            snapshots,
            {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in snapshots},
        )
        (second / "task.md").write_text("Different prompt")
        with redirect_stderr(io.StringIO()) as warning:
            self.assertEqual(len(evaluate.discover_comparison(str(self.task), self.parent)), 2)
        self.assertIn("different task prompts", warning.getvalue())

    def source_only_run(self, hashes=False, model="model-a"):
        run = self.saved_run(model=model)
        scenario = {
            "prompt": (run / "task.md").read_text().strip(),
            "evaluation_guidance": (run / "evaluation-guidance.md").read_text(),
            "baseline": self.root / "baseline",
        }
        archive = (run / "baseline.tar").read_bytes()
        metadata = {
            "scenario": "scenario",
            "task_name": "task",
            "prompt": scenario["prompt"],
            "archive_sha256": evaluate.digest(archive),
        }
        if hashes:
            metadata["source_sha256"] = {
                "task.md": evaluate.digest(scenario["prompt"].encode()),
                "evaluation-guidance.md": evaluate.digest(scenario["evaluation_guidance"].encode()),
            }
        (run / "run.json").write_text(json.dumps(metadata))
        for name in ("task.md", "evaluation-guidance.md", "baseline.tar"):
            (run / name).unlink()
        return run, scenario, archive

    def test_source_fallback_verifies_inputs_without_modifying_run(self):
        for hashes in (False, True):
            with self.subTest(hashes=hashes):
                self.task = self.parent / str(hashes) / "task"
                run, scenario, archive = self.source_only_run(hashes)
                before = {p.name: p.read_bytes() for p in run.iterdir()}
                workspace = self.root / str(hashes)
                workspace.mkdir()
                with (
                    patch("runner.load_scenario", return_value=scenario) as load,
                    patch("runner.baseline_archive", return_value=archive) as rebuild,
                ):
                    data, manifest = evaluate.prepare_evidence(run, workspace)
                load.assert_called_once_with("scenario", task="task")
                rebuild.assert_called_once_with(scenario["baseline"])
                self.assertEqual(data["task.md"], scenario["prompt"])
                self.assertEqual(manifest["sha256"]["baseline.tar"], evaluate.digest(archive))
                self.assertEqual(
                    manifest["sha256"]["task.md"], evaluate.digest(scenario["prompt"].encode())
                )
                self.assertEqual(
                    "historical identity unverified" in data["source-provenance.txt"], not hashes
                )
                self.assertEqual(before, {p.name: p.read_bytes() for p in run.iterdir()})
                self.assertEqual(list(self.parent.rglob("baseline.tar")), [])

    def test_real_scenario_reconstruction_matches_legacy_archive_without_git(self):
        run = self.saved_run()
        with patch("runner.ROOT", Path(__file__).resolve().parents[1]):
            scenario = evaluate.runner.load_scenario()
        metadata = {
            "scenario": scenario["name"],
            "task_name": scenario["task_name"],
            "prompt": scenario["prompt"],
            # Original Field Notes archive produced by the Git-filtered exporter.
            "archive_sha256": "174d57e74271014da6dbcda8ef44037f7b7bd5cc41079b5d6e3a4d48f58823d7",
        }
        (run / "run.json").write_text(json.dumps(metadata))
        for name in ("task.md", "evaluation-guidance.md", "baseline.tar"):
            (run / name).unlink()
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in run.iterdir()}
        with (
            patch("runner.subprocess.run", side_effect=AssertionError("Git is forbidden")),
            patch("runner.load_scenario", return_value=scenario),
        ):
            data = evaluate.evidence(run)
        self.assertEqual(data["task.md"], scenario["prompt"])
        self.assertIn("historical identity unverified", data["source-provenance.txt"])
        self.assertIn(
            "baseline.tar: current scenario reference; verified", data["source-provenance.txt"]
        )
        self.assertEqual(
            before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in run.iterdir()}
        )

    def test_waiting_reports_immediately_repeats_and_joins_on_every_exit(self):
        for fail in (False, True):
            with self.subTest(exception=fail):
                stopped = threading.Event()
                heartbeats_done = threading.Event()
                intervals = []

                def wait(
                    interval, intervals=intervals, heartbeats_done=heartbeats_done, stopped=stopped
                ):
                    intervals.append(interval)
                    if len(intervals) <= 2:
                        return False
                    heartbeats_done.set()
                    return stopped.wait(5)

                event = Mock(wraps=stopped)
                event.wait.side_effect = wait
                threads = []

                def start_thread(threads=threads, **kwargs):
                    thread = threading.Thread(**kwargs)
                    tracked = Mock(wraps=thread)
                    threads.append((thread, tracked))
                    return tracked

                stream = io.StringIO()
                stderr = Mock(wraps=stream)
                error = RuntimeError("private model failure payload")
                with (
                    patch(
                        "evaluate.threading", Event=Mock(return_value=event), Thread=start_thread
                    ),
                    patch("evaluate.HEARTBEAT_SECONDS", 0.125),
                    patch("evaluate.time.monotonic", side_effect=[100, 115, 130]),
                    redirect_stderr(stderr),
                    redirect_stdout(io.StringIO()) as stdout,
                ):
                    try:
                        with evaluate.waiting("Fixture assessment"):
                            self.assertTrue(
                                stream.getvalue().startswith(
                                    "[evaluate] Fixture assessment: started\n"
                                )
                            )
                            self.assertGreaterEqual(stderr.flush.call_count, 1)
                            self.assertTrue(heartbeats_done.wait(5), "Heartbeat did not repeat")
                            if fail:
                                raise error
                    except RuntimeError as caught:
                        self.assertTrue(fail)
                        self.assertIs(caught, error)
                    else:
                        self.assertFalse(fail, "Context swallowed the exception")
                    finally:
                        # Bound cleanup even if an assertion or a lifecycle regression fails.
                        stopped.set()
                        for thread, _ in threads:
                            thread.join(5)
                event.set.assert_called_once_with()
                self.assertEqual(len(threads), 1)
                thread, tracked = threads[0]
                tracked.start.assert_called_once_with()
                tracked.join.assert_called_once_with()
                self.assertFalse(thread.is_alive())
                self.assertEqual(intervals, [0.125, 0.125, 0.125])
                self.assertEqual(
                    stream.getvalue().splitlines(),
                    [
                        "[evaluate] Fixture assessment: started",
                        "[evaluate] Fixture assessment: still waiting (15s elapsed)",
                        "[evaluate] Fixture assessment: still waiting (30s elapsed)",
                    ],
                )
                self.assertEqual(stderr.flush.call_count, 3)
                self.assertEqual(stdout.getvalue(), "")

    def test_cli_task_reports_plan_and_save_without_logging_model_output(self):
        run = self.saved_run()
        output = self.parent.parent / "evaluations/scenario/task"
        synthesis = synthesis_result()
        private = "PRIVATE_RAW_MODEL_OUTPUT"
        findings = assessment(findings_summary=private)
        events = [{"type": "turn.completed", "raw": private}]
        with (
            patch("evaluate.codex_preflight") as preflight,
            patch("evaluate.runner.credential") as credential,
            patch(
                "evaluate.request_assessment",
                side_effect=[(findings, {"events": events}), (synthesis, {})],
            ) as request,
            redirect_stderr(io.StringIO()) as stderr,
            redirect_stdout(io.StringIO()) as stdout,
        ):
            self.assertEqual(
                evaluate.main(
                    [
                        str(self.task),
                        "--model",
                        "fixture-evaluator",
                        "--timeout",
                        "10",
                    ]
                ),
                0,
            )
        preflight.assert_called_once_with(10)
        credential.assert_not_called()
        self.assertEqual(request.call_count, 2)
        log = stderr.getvalue()
        expected = [
            "Task comparison: 1 runs; backend=codex; "
            "model=fixture-evaluator; timeout=10.0s per session",
            f"Preparing evidence: {run}",
            f"Assessment {run.name} (codex, timeout 10.0s): started",
            f"Assessment {run.name}: response received; validating",
        ]
        positions = [log.index(text) for text in expected]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn(private, log + stdout.getvalue())
        self.assertEqual(stdout.getvalue(), f"Saved task summary: {output / 'comparison.md'}\n")
        saved = json.loads((output / "comparison.json").read_text())["runs"][0]
        self.assertEqual(saved["benchmark_run"], evaluate.run_reference(run))
        self.assertEqual(saved["findings"], findings)
        self.assertNotIn("events", saved)
        self.assertIn(
            "| Model | Quality (0–100) | Time(s) | USD |",
            (output / "comparison.md").read_text(),
        )
        self.assertIn(private, (output / "comparison.md").read_text())

    def test_discovery_selects_only_latest_including_failed_and_timed_out(self):
        self.saved_run()
        runs = [self.saved_run(repeat="repeat-2", status="failed"), self.saved_run("model-b")]
        self.saved_run("model-c")
        runs.append(self.saved_run("model-c", repeat="repeat-2", status="timed-out"))
        self.assertEqual(evaluate.discover("all", self.parent), runs)
        self.assertEqual(evaluate.discover_comparison("scenario/task", self.parent), runs)

    def test_comparison_warns_on_mixed_prompts(self):
        self.saved_run()
        other = self.saved_run("model-b")
        (other / "task.md").write_text("A different prompt.\n")
        with redirect_stderr(io.StringIO()) as warning:
            self.assertEqual(len(evaluate.discover_comparison("scenario/task", self.parent)), 2)
        self.assertIn("different task prompts", warning.getvalue())

    def test_dry_run_prepares_evidence_without_auth_calls_or_reports(self):
        run = self.saved_run()
        output = self.parent.parent / "evaluations/scenario/task"
        for target in (["all"], ["scenario/task"]):
            with (
                self.subTest(target=target),
                patch("evaluate.codex_preflight") as preflight,
                patch("evaluate.runner.credential") as auth,
                patch("evaluate.request_assessment") as request,
                patch("evaluate.prepare_evidence", wraps=evaluate.prepare_evidence) as prepare,
                redirect_stdout(io.StringIO()) as stdout,
            ):
                self.assertEqual(evaluate.main([*target, "--dry-run"]), 0)
                prepare.assert_called_once()
                preflight.assert_not_called()
                auth.assert_not_called()
                request.assert_not_called()
                self.assertIn("evidence files", stdout.getvalue())
                self.assertIn(f"destination={output}", stdout.getvalue())
                self.assertFalse(output.exists())
                self.assertFalse((run / "evaluation.json").exists())
                self.assertFalse((run / "evaluation.md").exists())

    def test_cli_accepts_relative_and_absolute_task_directories(self):
        runs = [self.saved_run(), self.saved_run("model-b")]
        for target in ("scenario/task", str(self.task)):
            with (
                self.subTest(target=target),
                patch("evaluate.compare") as comparison,
                patch("evaluate.evaluate") as single,
                redirect_stdout(io.StringIO()),
            ):
                evaluate.main([target])
                comparison.assert_called_once_with(
                    runs,
                    {
                        "backend": "codex",
                        "model": None,
                        "timeout": 900,
                        "reasoning_effort": "low",
                    },
                    self.parent.parent / "evaluations/scenario/task",
                    None,
                )
                single.assert_not_called()

    def test_cli_noninteractive_cancels_before_auth_or_writes(self):
        self.saved_run()
        self.interactive.return_value = False
        with (
            patch("evaluate.runner.credential") as auth,
            patch("evaluate.request_assessment") as request,
        ):
            self.assertEqual(evaluate.main(["scenario/task"]), 1)
        self.confirmation.assert_not_called()
        auth.assert_not_called()
        request.assert_not_called()
        self.assertFalse((self.parent.parent / "evaluations").exists())

    def test_dry_run_reports_reuse_without_confirmation_or_writes(self):
        run = self.saved_run()
        output = self.parent.parent / "evaluations/scenario/task"
        config = {"backend": "codex", "model": None, "timeout": 900, "reasoning_effort": "low"}
        with (
            patch("evaluate.codex_preflight"),
            patch(
                "evaluate.request_assessment",
                side_effect=[(assessment(), {}), (synthesis_result(), {})],
            ),
        ):
            evaluate.compare([run], config, output)
        before = {p.name: p.read_bytes() for p in output.iterdir()}
        self.saved_run("model-b")
        with (
            patch("evaluate.runner.credential") as auth,
            patch("evaluate.request_assessment") as request,
            redirect_stdout(io.StringIO()) as stdout,
            redirect_stderr(io.StringIO()) as stderr,
        ):
            self.assertEqual(
                evaluate.main(["scenario/task", "--dry-run"]),
                0,
            )
        self.assertIn("1 assessments + 1 synthesis (not called)", stdout.getvalue())
        self.assertIn("reusing 1 assessments", stderr.getvalue())
        self.confirmation.assert_not_called()
        auth.assert_not_called()
        request.assert_not_called()
        self.assertEqual(before, {p.name: p.read_bytes() for p in output.iterdir()})

    def test_cli_rejects_explicit_runs_before_calls(self):
        run = self.saved_run()
        for target in (str(run), str(run.parents[1] / "latest"), "scenario/task/model-a/latest"):
            for flags in ([], ["--dry-run"]):
                with (
                    self.subTest(target=target, flags=flags),
                    patch("evaluate.codex_preflight") as preflight,
                    patch("evaluate.runner.credential") as auth,
                    patch("evaluate.request_assessment") as request,
                    patch("evaluate.compare") as comparison,
                    patch("evaluate.evaluate") as single,
                    self.assertRaisesRegex(ValueError, "not an individual run"),
                ):
                    evaluate.main([target, *flags])
                for mock in (preflight, auth, request, comparison, single):
                    mock.assert_not_called()
        self.assertFalse((self.parent.parent / "evaluations").exists())

    def test_cli_rejects_removed_output_dir_option(self):
        self.saved_run()
        with (
            patch("evaluate.compare") as comparison,
            patch("evaluate.request_assessment") as request,
            redirect_stderr(io.StringIO()) as stderr,
            self.assertRaises(SystemExit) as error,
        ):
            evaluate.main([str(self.task), "--output-dir", str(self.root / "report")])
        self.assertEqual(error.exception.code, 2)
        self.assertIn("unrecognized arguments: --output-dir", stderr.getvalue())
        comparison.assert_not_called()
        request.assert_not_called()

    def test_cli_all_compares_each_distinct_task_separately(self):
        first_task = self.task
        first = [self.saved_run(), self.saved_run("model-b")]
        self.task = self.parent / "scenario/other"
        second = [self.saved_run(), self.saved_run("model-b")]
        with (
            patch("evaluate.compare") as comparison,
            patch("evaluate.evaluate") as single,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(evaluate.main(["all"]), 0)
        self.confirmation.assert_called_once()
        self.assertEqual(comparison.call_count, 2)
        self.assertEqual(
            [(call.args[0], call.args[2]) for call in comparison.call_args_list],
            [
                (runs, self.parent.parent / "evaluations" / task.parent.name / task.name)
                for task, runs in sorted([(first_task, first), (self.task, second)])
            ],
        )
        single.assert_not_called()

    def test_cli_same_task_command_resumes_partial_checkpoint(self):
        runs = [self.saved_run(), self.saved_run("model-b")]
        command = ["scenario/task"]
        output = self.parent.parent / "evaluations/scenario/task"
        synthesis = synthesis_result(2)
        with (
            patch("evaluate.codex_preflight"),
            patch(
                "evaluate.request_assessment",
                side_effect=[(assessment(), {}), RuntimeError("interrupted")],
            ),
        ):
            self.assertEqual(evaluate.main(command), 1)
        checkpoint = json.loads((output / "comparison.json").read_text())
        self.assertEqual(len(checkpoint["runs"]), 1)
        self.assertEqual(checkpoint["status"], "assessing")
        self.assertNotIn("results", checkpoint)
        self.assertFalse((output / "checkpoint.json").exists())
        self.assertFalse((output / "comparison.md").exists())
        with (
            patch("evaluate.codex_preflight"),
            patch(
                "evaluate.request_assessment", side_effect=[(assessment(), {}), (synthesis, {})]
            ) as request,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(evaluate.main(command), 0)
        self.assertEqual(request.call_count, 2)
        result = json.loads((output / "comparison.json").read_text())
        self.assertEqual(
            [item["path"] for item in result["identity"]["runs"]],
            list(map(evaluate.run_reference, runs)),
        )
        self.assertEqual(result["runs"][0], checkpoint["runs"][0])
        self.assertEqual(result["synthesis"], synthesis)
        self.assertTrue((output / "comparison.md").exists())

    def test_cli_handles_changed_task_metadata_without_blocking(self):
        self.saved_run()
        other = self.saved_run("model-b")
        (other / "run.json").write_text(json.dumps({"scenario": "scenario", "task_name": "other"}))
        with patch("evaluate.request_assessment") as request:
            self.assertEqual(evaluate.main([str(self.task), "--dry-run"]), 0)
        request.assert_not_called()

    def test_evidence_preserves_physical_transcript_and_api_line_numbers(self):
        run = self.saved_run()
        workspace = self.root / "workspace"
        workspace.mkdir()
        data, manifest = evaluate.prepare_evidence(run, workspace)
        files = {
            item["source"]: (workspace / item["file"]).read_text() for item in manifest["files"]
        }
        self.assertEqual(
            files["transcript.jsonl"],
            '1: {"text":"escaped\\nnewline\u2028separator"}\n2: \n3: {"done":true}\n',
        )
        self.assertEqual(files["api-calls.json"], '1: [\n2:   {"usage": {"cost": 0.05}}\n3: ]\n')
        self.assertEqual(
            files["baseline.tar:src/example.py"], "1: first source line\n2: second source line\n"
        )
        self.assertEqual(data["transcript.jsonl"], (run / "transcript.jsonl").read_text())
        self.assertEqual(set(manifest["missing"]), {"opencode.log"})
        self.assertEqual(
            manifest["sha256"]["transcript.jsonl"],
            evaluate.digest((run / "transcript.jsonl").read_bytes()),
        )
        self.assertEqual(json.loads((workspace / "manifest.json").read_text()), manifest)

    def test_manifest_records_priorities_utf8_bytes_and_lf_line_counts(self):
        run = self.saved_run()
        (run / "response.txt").write_text("Café\u2028still one physical line\n\nDone.\n")
        workspace = self.root / "workspace"
        workspace.mkdir()
        data, manifest = evaluate.prepare_evidence(run, workspace)
        primary = {
            "task.md",
            "response.txt",
            "diff.patch",
            "metrics.json",
            "check.log",
            "evaluation-guidance.md",
            "source-provenance.txt",
        }
        self.assertEqual(
            {item["source"] for item in manifest["files"] if item["priority"] == "primary"},
            primary,
        )
        for item in manifest["files"]:
            with self.subTest(source=item["source"]):
                source = item["source"]
                text = (
                    data["baseline_source"][source.removeprefix("baseline.tar:")]
                    if source.startswith("baseline.tar:")
                    else data[source]
                )
                self.assertEqual(item["priority"], "primary" if source in primary else "on-demand")
                self.assertEqual(item["bytes"], len(text.encode("utf-8")))
                self.assertEqual(
                    item["lines"], text.count("\n") + int(bool(text) and not text.endswith("\n"))
                )
        entries = {item["source"]: item for item in manifest["files"]}
        self.assertEqual(entries["response.txt"]["lines"], 3)
        self.assertEqual(entries["diff.patch"]["lines"], 0)
        self.assertEqual(json.loads((workspace / "manifest.json").read_text()), manifest)

    def test_openrouter_supplies_only_primary_character_capped_excerpts_and_scope(self):
        run = self.saved_run()
        workspace = self.root / "workspace"
        workspace.mkdir()
        _, manifest = evaluate.prepare_evidence(run, workspace)
        primary = [item for item in manifest["files"] if item["priority"] == "primary"]
        texts = ["é" * 15999, "界" * 16000, "λ" * 16001]
        for item, text in zip(primary, texts, strict=False):
            (workspace / item["file"]).write_text(text)
        (workspace / "unlisted.txt").write_text("PRIVATE_UNLISTED")
        for item in manifest["files"]:
            if item["priority"] == "on-demand":
                # Unavailable files must not even be opened by the tool-free packet builder.
                (workspace / item["file"]).unlink()
        packet = evaluate.openrouter_evidence(workspace)
        self.assertEqual(
            set(packet),
            {
                "manifest.json",
                "review-scope.txt",
                *(item["file"] for item in primary),
            },
        )
        self.assertEqual(json.loads(packet["manifest.json"]), manifest)
        for item, text in zip(primary, texts, strict=False):
            with self.subTest(characters=len(text)):
                suffix = (
                    "\n[TRUNCATED: remaining evidence not supplied]" if len(text) > 16000 else ""
                )
                self.assertEqual(packet[item["file"]], text[:16000] + suffix)
        for item in primary[len(texts) :]:
            self.assertEqual(packet[item["file"]], (workspace / item["file"]).read_text())
        scope = packet["review-scope.txt"]
        for text in (
            "only primary evidence excerpts",
            "unavailable, not reviewed",
            "Do not claim independent source or transcript verification",
            "Disclose these limits",
        ):
            self.assertIn(text, scope)
        for text in ("escaped", "first source line", '"usage"', "PRIVATE_UNLISTED"):
            self.assertNotIn(text, "\n".join(packet.values()))

    def test_openrouter_preserves_synthesis_workspace_without_manifest(self):
        workspace = self.root / "synthesis"
        workspace.mkdir()
        files = {
            "assessment-0000.json": json.dumps({"findings": "é" * 17000}),
            "assessment-0001.json": json.dumps({"rank": 2, "total": 80}),
        }
        for name, text in files.items():
            (workspace / name).write_text(text)
        (workspace / "directory").mkdir()
        self.assertEqual(evaluate.openrouter_evidence(workspace), files)

    def test_single_run_review_preserves_all_six_fields(self):
        findings = assessment()
        markdown = evaluate.assessment_markdown(
            {"benchmark_run": "fixture/run", "findings": findings}
        )
        self.assertEqual(
            markdown,
            "## Run: fixture/run\n\n" + " ".join(findings[field] for field in evaluate.FIELDS),
        )

    def test_subscription_preflight_rejects_api_auth_and_unknown_status(self):
        for status in (
            "Logged in using API key",
            "Logged in using ChatGPT; API_KEY set",
            "Logged in using ChatGPT; API key set",
            "Not logged in",
            "",
        ):
            with (
                self.subTest(status=status),
                patch("evaluate.run_process", return_value=(status, "")),
                self.assertRaisesRegex(ValueError, "subscription login"),
            ):
                evaluate.codex_preflight()
        with patch("evaluate.run_process", return_value=("", "Logged in using ChatGPT")) as process:
            evaluate.codex_preflight(90)
        command, _, _, timeout = process.call_args.args
        self.assertIn('forced_login_method="chatgpt"', command)
        self.assertIn('model_provider="openai"', command)
        self.assertEqual(command[-2:], ["login", "status"])
        self.assertEqual(timeout, 30)

    def test_subscription_environment_removes_api_routing_and_preserves_login_home(self):
        blocked = [
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "openrouter_api_key",
            "AZURE_OPENAI_ENDPOINT",
            "CODEX_API_KEY",
            "CODEX_BASE_URL",
            "CODEX_ACCESS_TOKEN",
            "CODEX_AUTH_JSON",
            "CODEX_MODEL",
            "CHATGPT_BASE_URL",
        ]
        keep = {"CODEX_HOME": "/fixture/login", "PATH": "/fixture/bin", "HOME": "/fixture/home"}
        with patch.dict(os.environ, {**keep, **dict.fromkeys(blocked, "secret")}, clear=True):
            self.assertEqual(evaluate.codex_environment(), keep)

    def test_codex_failure_reports_cause_without_echoing_output(self):
        process = Mock(returncode=1)
        process.communicate.return_value = (
            "",
            "Unsupported reasoning_effort: light; secret-token",
        )
        process.__enter__ = Mock(return_value=process)
        process.__exit__ = Mock(return_value=False)
        with patch("evaluate.subprocess.Popen", return_value=process):
            with self.assertRaises(RuntimeError) as raised:
                evaluate.run_process(["codex"], self.root, {}, 1)
        message = str(raised.exception)
        self.assertIn("reasoning effort support", message)
        self.assertIn("earlier saved assessments are retained", message)
        self.assertNotIn("secret-token", message)

    def test_empty_comparison_can_restart_after_config_change(self):
        output = self.root / "empty-evaluation"
        output.mkdir()
        identity = {"config": {"reasoning_effort": "light"}, "runs": []}
        state = evaluate.load_comparison(output, identity)
        (output / "comparison.json").write_text(json.dumps(state))
        new_identity = {"config": {"reasoning_effort": "low"}, "runs": [{"path": "new"}]}
        resumed = evaluate.load_comparison(output, new_identity)
        self.assertEqual(resumed["identity"], new_identity)
        self.assertEqual(resumed["config"], new_identity["config"])
        self.assertEqual([item["path"] for item in resumed["identity"]["runs"]], ["new"])
        self.assertEqual(resumed["runs"], [])
        self.assertEqual(json.loads((output / "comparison.json").read_text()), state)

    def test_codex_command_pins_subscription_and_safety_flags(self):
        command = evaluate.codex_command(
            self.root, self.root / "output.json", self.root / "schema.json", self.config
        )
        self.assertEqual(command[:2], ["codex", "exec"])
        for flag in (
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--skip-git-repo-check",
            "--json",
        ):
            self.assertIn(flag, command)
        for flag, value in {
            "--sandbox": "read-only",
            "-C": str(self.root),
            "--output-last-message": str(self.root / "output.json"),
            "--output-schema": str(self.root / "schema.json"),
            "--model": "fixture-evaluator",
        }.items():
            self.assertEqual(command[command.index(flag) + 1], value)
        overrides = [command[i + 1] for i, value in enumerate(command) if value == "-c"]
        for value in (
            'forced_login_method="chatgpt"',
            'model_provider="openai"',
            'model_reasoning_effort="low"',
            'approval_policy="never"',
            'web_search="disabled"',
            "project_doc_max_bytes=0",
            "mcp_servers={}",
            "allow_login_shell=false",
            'shell_environment_policy.inherit="none"',
            "skills.include_instructions=false",
            "skills.bundled.enabled=false",
            "memories.use_memories=false",
            "memories.generate_memories=false",
            "features.skip_host_skill_discovery=true",
        ):
            self.assertIn(value, overrides)
        for feature in (
            "apps",
            "plugins",
            "hooks",
            "multi_agent",
            "multi_agent_v2",
            "browser_use",
            "computer_use",
            "image_generation",
            "js_repl",
            "shell_snapshot",
        ):
            self.assertIn(f"features.{feature}=false", overrides)
        self.assertIn("developer_instructions=" + json.dumps(evaluate.SYSTEM), overrides)
        self.assertEqual(command[-1], "-")

    def test_cost_metadata_retains_costs_without_scores(self):
        for cost in (0, 0.05, 3.01):
            self.assertEqual(
                evaluate.cost_metadata(metrics(actual_cost_usd=cost), []),
                {"cost_complete": True, "cost_usd": cost, "cost_lower_bound_usd": 0},
            )
        for cost in (None, -1, True, "0", float("nan"), float("inf")):
            with self.subTest(cost=cost):
                calls = [{"usage": {"cost": 4}}, {"usage": {"cost": -1}}, {"usage": None}, None]
                self.assertEqual(
                    evaluate.cost_metadata(metrics(actual_cost_usd=cost), calls),
                    {"cost_complete": False, "cost_usd": None, "cost_lower_bound_usd": 4},
                )

    def test_compare_saves_compact_state_and_rebuilds_completed_report_without_calls(self):
        runs = [self.saved_run(), self.saved_run(repeat="repeat-2")]
        output = self.root / "comparison"
        synthesis = synthesis_result(2)
        provenance = {"served_model": "fixture-evaluator", "usage": {"output_tokens": 10}}
        snapshots = []

        def request(workspace, config, schema, prompt, key):
            snapshots.append({p.name: p.read_text() for p in workspace.iterdir()})
            self.assertEqual(config, self.config)
            self.assertIsNone(key)
            if schema == evaluate.SYNTHESIS_SCHEMA:
                self.assertEqual(prompt, evaluate.SYNTHESIS_SYSTEM)
            else:
                self.assertEqual(prompt, evaluate.SYSTEM)
            return (synthesis if schema == evaluate.SYNTHESIS_SCHEMA else assessment()), {
                **provenance,
                "events": [{"type": "fixture-event"}],
            }

        with (
            patch("evaluate.codex_preflight") as preflight,
            patch("evaluate.request_assessment", side_effect=request) as model,
        ):
            result = evaluate.compare(runs, self.config, output)
        preflight.assert_called_once_with(10)
        self.assertEqual(model.call_count, 3)
        self.assertIn("manifest.json", snapshots[0])
        self.assertIn("manifest.json", snapshots[1])
        self.assertEqual(set(snapshots[2]), {"assessment-0000.json", "assessment-0001.json"})
        for text in snapshots[2].values():
            packet = json.loads(text)
            self.assertEqual(
                set(packet),
                {
                    "model",
                    "metrics",
                    "findings",
                    "cost_complete",
                    "cost_usd",
                    "cost_lower_bound_usd",
                },
            )
            self.assertEqual(
                packet["metrics"],
                {k: v for k, v in metrics().items() if k in evaluate.METRIC_FIELDS},
            )
            self.assertEqual(
                packet["findings"],
                {k: v for k, v in assessment().items() if k not in {"scores", "score_reasoning"}},
            )
            for excluded in ("scores", "score_reasoning", "rank", "total", "events"):
                self.assertNotIn(f'"{excluded}"', text)
        self.assertEqual(result["state_version"], 1)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["identity"], evaluate.comparison_identity(runs, self.config))
        self.assertNotIn("results", result)
        self.assertEqual(
            [item["path"] for item in result["identity"]["runs"]],
            list(map(evaluate.run_reference, runs)),
        )
        for saved in result["runs"]:
            for name in ("provenance", "scores", "total", "rank", "handoff_cap"):
                self.assertNotIn(name, saved)
        self.assertEqual(result["synthesis"], synthesis)
        self.assertEqual(result["synthesis_provenance"], provenance)
        self.assertEqual(json.loads((output / "comparison.json").read_text()), result)
        markdown = (output / "comparison.md").read_text()
        for text in (
            "# Benchmark comparison",
            "| Model | Quality (0–100) | Time(s) | USD |",
            "| fixture-model | 80 | 120 | $0.0500 |",
            evaluate.comparison_review(assessment()),
            synthesis["short_decision"],
        ):
            self.assertIn(text, markdown)
        for text in (
            "Evaluated:",
            "Latest attempts only:",
            *map(str, runs),
            "api-calls.json:3",
            "## Per-run",
            "## Computed ranking",
            "| Rank |",
            "Total /100",
            "| Cost",
            "| D |",
            "| E |",
            "| F |",
            "Handoff /20",
        ):
            self.assertNotIn(text, markdown)
        for saved, run in zip(result["runs"], runs, strict=True):
            self.assertEqual(saved["benchmark_run"], evaluate.run_reference(run))
            self.assertEqual(saved["findings"], assessment())
            self.assertNotIn("events", saved)
        self.assertEqual(
            set(p.name for p in output.iterdir()),
            {"comparison.json", "comparison.md", ".checkpoint.lock"},
        )
        before = (output / "comparison.json").read_bytes()
        for existing in (None, "Stale report"):
            if existing is None:
                (output / "comparison.md").unlink()
            else:
                (output / "comparison.md").write_text(existing)
            with (
                patch("evaluate.request_assessment") as model,
                patch("evaluate.codex_preflight") as preflight,
            ):
                self.assertEqual(evaluate.compare(runs, self.config, output), result)
            model.assert_not_called()
            preflight.assert_not_called()
            self.assertEqual((output / "comparison.json").read_bytes(), before)
            self.assertEqual((output / "comparison.md").read_text(), markdown)
        with (
            patch("evaluate.request_assessment") as model,
            patch("evaluate.codex_preflight") as preflight,
        ):
            reused = evaluate.compare(runs, {**self.config, "reasoning_effort": "light"}, output)
        self.assertEqual(reused, result)
        self.assertEqual(reused["config"], self.config)
        model.assert_not_called()
        preflight.assert_not_called()

    def test_existing_report_is_backed_up_before_replacement(self):
        output = self.root / "report"
        output.mkdir()
        (output / "comparison.md").write_text("Keep this report.")
        evaluate.save_report(output, "comparison", {}, "Replacement")
        self.assertEqual((output / "comparison.md").read_text(), "Replacement")
        self.assertEqual(
            next((output / "history").glob("*/comparison.md")).read_text(), "Keep this report."
        )

    def test_comparison_failure_saves_canonical_state_but_no_markdown(self):
        run = self.saved_run()
        for name, responses in (
            ("assessment-failure", [RuntimeError("model failed")]),
            ("invalid-assessment", [({}, {})]),
            ("synthesis-failure", [(assessment(), {}), RuntimeError("model failed")]),
            ("invalid-synthesis", [(assessment(), {}), ({}, {})]),
        ):
            output = self.root / name
            with (
                self.subTest(stage=name),
                patch("evaluate.codex_preflight"),
                patch("evaluate.request_assessment", side_effect=responses),
                self.assertRaises((RuntimeError, ValueError)),
            ):
                evaluate.compare([run], self.config, output)
            self.assertFalse((output / "checkpoint.json").exists())
            state = json.loads((output / "comparison.json").read_text())
            self.assertEqual(state["state_version"], 1)
            self.assertEqual(
                state["status"], "synthesizing" if "synthesis" in name else "assessing"
            )
            self.assertEqual(len(state["runs"]), int("synthesis" in name))
            self.assertIsNone(state["synthesis"])
            self.assertIsNone(state["synthesis_provenance"])
            self.assertNotIn("results", state)
            self.assertFalse((output / "comparison.md").exists())
            self.assertFalse((run / "evaluation.json").exists())
            self.assertFalse((run / "evaluation.md").exists())

    def test_assessment_uses_prompt_files(self):
        run = self.saved_run()
        directory = (
            Path(evaluate.__file__).resolve().parents[2] / "scenarios/field-notes/evaluation"
        )
        with patch("evaluate.request_assessment", return_value=(assessment(), {})) as request:
            evaluate.assess(run, self.config)
        expected = (directory / "assessment.md").read_text()
        self.assertEqual(request.call_args.args[3], expected)
        self.assertEqual(evaluate.SYNTHESIS_SYSTEM, (directory / "synthesis.md").read_text())

    def test_comparison_resumes_after_assessment_or_synthesis_failure(self):
        runs = [self.saved_run(), self.saved_run(model="model-b")]
        synthesis = synthesis_result(2)
        for completed in (1, 2):
            output = self.root / f"resume-{completed}"
            with (
                self.subTest(completed=completed),
                patch("evaluate.codex_preflight"),
                patch(
                    "evaluate.request_assessment",
                    side_effect=[(assessment(), {})] * completed + [RuntimeError("interrupted")],
                ),
                self.assertRaisesRegex(RuntimeError, "interrupted|incomplete"),
            ):
                evaluate.compare(runs, self.config, output)
            saved = json.loads((output / "comparison.json").read_text())
            self.assertEqual(len(saved["runs"]), completed)
            self.assertNotIn("evaluator_sha256", saved["identity"])
            self.assertNotIn("runner_sha256", saved["identity"])
            saved["identity"].update(evaluator_sha256="old-code", runner_sha256="old-runner")
            (output / "comparison.json").write_text(json.dumps(saved))
            self.assertEqual(saved["status"], "assessing" if completed == 1 else "synthesizing")
            self.assertFalse((output / "checkpoint.json").exists())
            with (
                patch("evaluate.codex_preflight"),
                patch(
                    "evaluate.request_assessment",
                    side_effect=[(assessment(), {})] * (2 - completed) + [(synthesis, {})],
                ) as request,
            ):
                result = evaluate.compare(runs, self.config, output)
            self.assertEqual(request.call_count, 3 - completed)
            self.assertEqual(result["runs"][:completed], saved["runs"])
            self.assertEqual(result["status"], "completed")
            self.assertTrue((output / "comparison.md").exists())

    def test_comparison_reuses_unchanged_runs_when_selection_changes(self):
        first, last = self.saved_run(), self.saved_run("model-c")
        added = self.saved_run("model-b")
        replacement = self.saved_run(repeat="repeat-2")
        for name, selected, missing in (
            ("add-middle", [first, added, last], [added]),
            ("replace", [replacement, last], [replacement]),
            ("remove", [last], []),
            ("multiple", [replacement, added, last], [replacement, added]),
        ):
            with self.subTest(name=name):
                output = self.root / name
                with (
                    patch("evaluate.codex_preflight"),
                    patch(
                        "evaluate.request_assessment",
                        side_effect=[(assessment(), {})] * 2 + [(synthesis_result(2), {})],
                    ),
                ):
                    original = evaluate.compare([first, last], self.config, output)
                old = {r["benchmark_run"]: r for r in original["runs"]}
                with (
                    patch("evaluate.codex_preflight"),
                    patch("evaluate.assess", wraps=evaluate.assess) as assess,
                    patch(
                        "evaluate.request_assessment",
                        side_effect=[(assessment(), {})] * len(missing)
                        + [(synthesis_result(len(selected)), {})],
                    ) as request,
                ):
                    result = evaluate.compare(selected, self.config, output)
                self.assertEqual(request.call_count, len(missing) + 1)
                self.assertEqual([call.args[0] for call in assess.call_args_list], missing)
                self.assertEqual(
                    [item["path"] for item in result["identity"]["runs"]],
                    list(map(evaluate.run_reference, selected)),
                )
                self.assertEqual(
                    [r["benchmark_run"] for r in result["runs"]],
                    list(map(evaluate.run_reference, selected)),
                )
                for saved in result["runs"]:
                    if saved["benchmark_run"] in old:
                        self.assertEqual(saved, old[saved["benchmark_run"]])
                self.assertEqual(result["state_version"], 1)
                self.assertEqual(result["synthesis"], synthesis_result(len(selected)))
                with patch("evaluate.request_assessment") as request:
                    self.assertEqual(evaluate.compare(selected, self.config, output), result)
                request.assert_not_called()

    def test_updated_comparison_resumes_holes_and_discards_stale_report(self):
        first, last = self.saved_run(), self.saved_run("model-d")
        output = self.root / "update-resume"
        with (
            patch("evaluate.codex_preflight"),
            patch(
                "evaluate.request_assessment",
                side_effect=[(assessment(), {})] * 2 + [(synthesis_result(2), {})],
            ),
        ):
            evaluate.compare([first, last], self.config, output)
        selected = [first, self.saved_run("model-b"), self.saved_run("model-c"), last]
        with (
            patch("evaluate.codex_preflight"),
            patch(
                "evaluate.request_assessment",
                side_effect=[(assessment(), {}), RuntimeError("interrupted")],
            ),
            self.assertRaisesRegex(RuntimeError, "interrupted|incomplete"),
        ):
            evaluate.compare(selected, self.config, output)
        state = json.loads((output / "comparison.json").read_text())
        self.assertEqual(
            [r["benchmark_run"] for r in state["runs"]],
            list(map(evaluate.run_reference, [first, selected[1], last])),
        )
        self.assertIsNone(state["synthesis"])
        self.assertNotIn("evaluated_at", state)
        self.assertFalse((output / "comparison.md").exists())
        with (
            patch("evaluate.codex_preflight"),
            patch("evaluate.assess", wraps=evaluate.assess) as assess,
            patch(
                "evaluate.request_assessment",
                side_effect=[(assessment(), {}), RuntimeError("synthesis interrupted")],
            ),
            self.assertRaisesRegex(RuntimeError, "synthesis interrupted"),
        ):
            evaluate.compare(selected, self.config, output)
        self.assertEqual([call.args[0] for call in assess.call_args_list], [selected[2]])
        with (
            patch("evaluate.codex_preflight"),
            patch("evaluate.assess") as assess,
            patch("evaluate.request_assessment", return_value=(synthesis_result(4), {})) as request,
        ):
            result = evaluate.compare(selected, self.config, output)
        assess.assert_not_called()
        request.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertTrue((output / "comparison.md").exists())

    def test_checkpoint_retains_synthesis_after_publish_failure(self):
        run = self.saved_run()
        output = self.root / "resume"
        synthesis = synthesis_result()
        save = evaluate.save_comparison_file

        def fail_markdown(path, content, key=None):
            if path.suffix == ".md":
                raise OSError("disk error")
            save(path, content, key)

        with (
            patch("evaluate.codex_preflight"),
            patch("evaluate.request_assessment", side_effect=[(assessment(), {}), (synthesis, {})]),
            patch("evaluate.save_comparison_file", side_effect=fail_markdown),
            self.assertRaisesRegex(OSError, "disk error"),
        ):
            evaluate.compare([run], self.config, output)
        saved = json.loads((output / "comparison.json").read_text())
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(saved["synthesis"], synthesis)
        self.assertFalse((output / "comparison.md").exists())
        self.assertFalse((output / "checkpoint.json").exists())
        with (
            patch("evaluate.codex_preflight") as preflight,
            patch("evaluate.request_assessment") as request,
        ):
            self.assertEqual(evaluate.compare([run], self.config, output), saved)
        preflight.assert_not_called()
        request.assert_not_called()
        self.assertTrue((output / "comparison.md").exists())

    def legacy_comparison(self, run, output, final=False):
        output.mkdir()
        with patch("evaluate.request_assessment", return_value=(assessment(), {"events": [1]})):
            result = evaluate.assess(run, self.config)
        result["findings"].update(
            scores={"D": 30},
            score_reasoning="Old scoring",
            quality={"fix_quality": "Old"},
            usable_result=True,
            completed_handoff=True,
            retained_tested_fix=False,
            delivered_work="Old work",
            limitations="Old limits",
        )
        result.update(scores={"D": 30}, total=30, rank=1, handoff_cap=20, completed_handoff=True)
        result["metrics"] = metrics()
        identity = {
            **evaluate.comparison_identity([run], self.config),
            "evaluator_sha256": "legacy",
            "runner_sha256": "legacy-runner",
        }
        synthesis = {
            name: "Legacy finding." for name in evaluate.LEGACY_SYNTHESIS_SCHEMA["properties"]
        }
        synthesis.update(
            success_criteria="Old criteria", delivered_work="Old work", limitations="Old limits"
        )
        provenance = {"served_model": "legacy-evaluator", "events": [2]}
        checkpoint = {
            "identity": identity,
            "results": [result],
            "synthesis": {"findings": synthesis, "provenance": provenance},
        }
        (output / "checkpoint.json").write_text(json.dumps(checkpoint))
        if final:
            (output / "comparison.json").write_text(
                json.dumps(
                    {
                        "runs": [result],
                        "synthesis": synthesis,
                        "synthesis_provenance": provenance,
                        "evaluated_at": "2026-01-01T00:00:00Z",
                        "rubric": "Obsolete rubric",
                        "quality_summary_source": "Obsolete summary source",
                        "legacy_identity": identity,
                    }
                )
            )
            (output / "comparison.md").write_text("Old ranking report")
        return checkpoint

    def test_legacy_completed_conversion_preserves_judgments_without_calls(self):
        run = self.saved_run()
        for final in (False, True):
            with self.subTest(final=final):
                output = self.root / f"legacy-{final}"
                checkpoint = self.legacy_comparison(run, output, final)
                before = {p.name: p.read_bytes() for p in output.iterdir()}
                with (
                    patch("evaluate.codex_preflight") as preflight,
                    patch("evaluate.request_assessment") as request,
                    patch("evaluate.save_comparison_file", side_effect=OSError("save failed")),
                    self.assertRaisesRegex(OSError, "save failed"),
                ):
                    evaluate.compare([run], self.config, output)
                preflight.assert_not_called()
                request.assert_not_called()
                self.assertEqual(
                    {
                        p.name: p.read_bytes()
                        for p in output.iterdir()
                        if p.name != ".checkpoint.lock"
                    },
                    before,
                )

                save = evaluate.save_comparison_file
                publications = []

                def publish(
                    path, content, key=None, *, publications=publications, output=output, save=save
                ):
                    if not publications:
                        self.assertTrue((output / "checkpoint.json").exists())
                        self.assertEqual(path.name, "comparison.json")
                    save(path, content, key)
                    publications.append(path.name)

                with (
                    patch("evaluate.codex_preflight") as preflight,
                    patch("evaluate.request_assessment") as request,
                    patch("evaluate.save_comparison_file", side_effect=publish),
                ):
                    state = evaluate.compare([run], self.config, output)
                preflight.assert_not_called()
                request.assert_not_called()
                self.assertEqual(state["state_version"], 1)
                self.assertEqual(state["status"], "completed")
                for field in ("rubric", "quality_summary_source", "legacy_identity"):
                    self.assertNotIn(field, state)
                self.assertEqual(
                    state["identity"], evaluate.comparison_identity([run], self.config)
                )
                self.assertEqual(
                    [item["path"] for item in state["identity"]["runs"]],
                    [evaluate.run_reference(run)],
                )
                self.assertEqual(
                    state["runs"],
                    [evaluate.compact_assessment(checkpoint["results"][0])],
                )
                self.assertEqual(
                    state["synthesis"],
                    {
                        name: checkpoint["synthesis"]["findings"][name]
                        for name in evaluate.LEGACY_SYNTHESIS_SCHEMA["properties"]
                    },
                )
                self.assertEqual(
                    state["synthesis_provenance"], {"served_model": "legacy-evaluator"}
                )
                self.assertNotIn("results", state)
                self.assertFalse((output / "checkpoint.json").exists())
                self.assertEqual(json.loads((output / "comparison.json").read_text()), state)
                self.assertEqual(
                    (output / "comparison.md").read_text(), evaluate.comparison_markdown(state)
                )

    def test_current_state_projects_old_fields_without_calls_or_text_changes(self):
        run = self.saved_run()
        output = self.root / "current-legacy"
        checkpoint = self.legacy_comparison(run, output)
        saved_run = checkpoint["results"][0]
        exact = {field: f"  Original {field}.\nSecond sentence!  " for field in evaluate.FIELDS}
        saved_run["findings"].update(exact)
        saved_run.update(
            backend="openrouter",
            evaluator_model="historical-evaluator",
            evaluated_at="2025-01-01T00:00:00Z",
            served_model="historical-served",
            usage={"prompt_tokens": 42},
        )
        saved_run["metrics"].update(
            requested_model_id="requested",
            actual_served_models=["served"],
            actual_providers=["provider"],
        )
        state = {
            "state_version": 1,
            "schema_version": evaluate.VERSION,
            "identity": checkpoint["identity"],
            "config": self.config,
            "selection": [str(run)],
            "status": "completed",
            "runs": [saved_run],
            "synthesis": checkpoint["synthesis"]["findings"],
            "synthesis_provenance": {"served_model": "old-synthesis", "usage": {"tokens": 7}},
            "synthesis_policy": "outcome-analysis-v1",
            "evaluated_at": "old-time",
            "rubric": "Obsolete rubric",
            "quality_summary_source": "Obsolete summary source",
            "legacy_identity": checkpoint["identity"],
        }
        (output / "comparison.json").write_text(json.dumps(state))
        with (
            patch("evaluate.request_assessment") as request,
            patch("evaluate.codex_preflight") as preflight,
        ):
            result = evaluate.compare([run], self.config, output)
            self.assertEqual(evaluate.compare([run], self.config, output), result)
        request.assert_not_called()
        preflight.assert_not_called()
        for field in ("rubric", "quality_summary_source", "legacy_identity"):
            self.assertNotIn(field, result)
        self.assertEqual(result["config"], state["config"])
        self.assertEqual(
            [item["path"] for item in result["identity"]["runs"]],
            list(map(evaluate.run_reference, state["selection"])),
        )
        migrated = result["runs"][0]
        self.assertEqual(
            migrated["findings"],
            {**exact, "evidence_citations": saved_run["findings"]["evidence_citations"]},
        )
        self.assertEqual(set(migrated["metrics"]), set(evaluate.METRIC_FIELDS))
        for field in (
            "backend",
            "evaluator_model",
            "evaluated_at",
            "served_model",
            "usage",
            "cost_complete",
            "cost_usd",
            "cost_lower_bound_usd",
        ):
            self.assertEqual(migrated[field], saved_run[field])
        self.assertEqual(set(result["synthesis"]), {"short_decision", "tradeoffs"})
        self.assertEqual(result["synthesis_provenance"], state["synthesis_provenance"])
        self.assertIn(" ".join(exact.values()), (output / "comparison.md").read_text())
        self.assertEqual(json.loads((output / "comparison.json").read_text()), result)

    def test_new_schema_accepts_only_six_fields_and_citations(self):
        self.assertEqual(
            set(evaluate.ASSESSMENT_SCHEMA["properties"]),
            set(evaluate.FIELDS) | {"evidence_citations"},
        )
        self.assertEqual(
            set(evaluate.SYNTHESIS_SCHEMA["properties"]), {"short_decision", "quality_scores"}
        )
        evaluate.validate_schema(assessment(), evaluate.ASSESSMENT_SCHEMA)
        for field in (
            "scores",
            "score_reasoning",
            "quality",
            "delivered_work",
            "limitations",
            "usable_result",
            "completed_handoff",
            "retained_tested_fix",
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                evaluate.validate_schema(assessment(**{field: None}), evaluate.ASSESSMENT_SCHEMA)

    def test_save_comparison_file_atomically_replaces_json_and_markdown(self):
        for suffix, content in (("json", {"status": "completed"}), ("md", "New report\n")):
            with self.subTest(suffix=suffix):
                path = self.root / f"comparison.{suffix}"
                path.write_text("Old content")
                replace = os.replace

                def publish(
                    source,
                    destination,
                    *,
                    path=path,
                    suffix=suffix,
                    content=content,
                    replace=replace,
                ):
                    self.assertEqual(destination, path)
                    self.assertEqual(path.read_text(), "Old content")
                    self.assertEqual(source.parent.parent, path.parent)
                    actual = (
                        json.loads(source.read_text()) if suffix == "json" else source.read_text()
                    )
                    self.assertEqual(actual, content)
                    replace(source, destination)

                with patch("evaluate.os.replace", side_effect=OSError("publish failed")):
                    with self.assertRaisesRegex(OSError, "publish failed"):
                        evaluate.save_comparison_file(path, content)
                self.assertEqual(path.read_text(), "Old content")
                self.assertEqual(list(self.root.glob(".comparison-*")), [])
                with patch("evaluate.os.replace", side_effect=publish) as publication:
                    evaluate.save_comparison_file(path, content)
                publication.assert_called_once()
                self.assertEqual(list(self.root.glob(".comparison-*")), [])

    def test_comparison_report_preserves_reviews_and_maps_scores_before_sorting(self):
        findings = assessment(
            **{field: f"Full {field}. More detail without truncation" for field in evaluate.FIELDS}
        )
        runs = []
        for alias, duration in (("zebra", 120.6), ("Alpha", 10.2)):
            measured = metrics(
                model=alias, coding_duration_seconds=duration, actual_cost_usd=0.123456
            )
            runs.append(
                {"metrics": measured, "findings": findings, **evaluate.cost_metadata(measured, [])}
            )
        report = evaluate.comparison_markdown(
            {
                "runs": runs,
                "evaluated_at": "fixture",
                "synthesis": {"short_decision": "Summary.", "quality_scores": [72, 93]},
            }
        )
        self.assertEqual(
            [line for line in report.splitlines() if line.startswith("| ")],
            [
                "| Model | Quality (0–100) | Time(s) | USD |",
                "| Alpha | 93 | 10 | $0.1235 |",
                "| zebra | 72 | 121 | $0.1235 |",
            ],
        )
        review = " ".join(findings[field] for field in evaluate.FIELDS)
        self.assertEqual(report.count(review), 2)
        self.assertEqual(evaluate.comparison_review(findings), review)
        self.assertLess(report.index("## Alpha"), report.index("## zebra"))
        self.assertNotIn("###", report)
        self.assertNotIn("fixture-served", report)
        self.assertNotIn("api-calls.json:3", report)

    def test_quality_scores_reject_invalid_values_and_wrong_count(self):
        for scores in ([True], [80.5], [-1], [101], ["80"], [], [80, 90]):
            with self.subTest(scores=scores), self.assertRaises(ValueError):
                evaluate.validate_quality_scores({"quality_scores": scores}, [{}])
        for score in (0, 50, 100):
            evaluate.validate_quality_scores({"quality_scores": [score]}, [{}])

    def test_report_omits_old_sections_and_keeps_legacy_summary_without_calls(self):
        result = {
            "runs": [],
            "evaluated_at": "fixture",
            "synthesis": {"short_decision": "Keep this summary.", "tradeoffs": "Old tradeoffs."},
        }
        report = evaluate.comparison_markdown(result)
        self.assertIn("## Summary\n\nKeep this summary.", report)
        for text in ("Success criterion", "Method", "Tradeoffs", "Old tradeoffs."):
            self.assertNotIn(text, report)

    def test_checkpoint_lock_rejects_concurrent_comparison(self):
        run = self.saved_run()
        output = self.root / "locked"
        output.mkdir()
        with (output / ".checkpoint.lock").open("a") as lock:
            evaluate.fcntl.flock(lock, evaluate.fcntl.LOCK_EX | evaluate.fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, "already running"):
                evaluate.compare([run], self.config, output)

    def test_failed_report_staging_preserves_existing_report(self):
        output = self.root / "report"
        output.mkdir()
        (output / "comparison.md").write_text("Original")
        with (
            patch("runner.save", side_effect=OSError("fixture staging failure")),
            self.assertRaises(OSError),
        ):
            evaluate.save_report(output, "comparison", {}, "Replacement")
        self.assertEqual((output / "comparison.md").read_text(), "Original")

    def test_changed_evidence_rebuilds_only_affected_run_and_backs_up_reports(self):
        first, other = self.saved_run(), self.saved_run("model-b")
        output = self.root / "comparison"
        with (
            patch("evaluate.codex_preflight"),
            patch(
                "evaluate.request_assessment",
                side_effect=[(assessment(), {})] * 2 + [(synthesis_result(2), {})],
            ),
        ):
            original = evaluate.compare([first, other], self.config, output)
        old_json = (output / "comparison.json").read_bytes()
        old_md = (output / "comparison.md").read_bytes()
        (other / "response.txt").write_text("Updated evidence")
        with (
            patch("evaluate.codex_preflight"),
            patch("evaluate.assess", wraps=evaluate.assess) as assess_call,
            patch(
                "evaluate.request_assessment",
                side_effect=[(assessment(), {}), (synthesis_result(2), {})],
            ) as request,
        ):
            result = evaluate.compare([first, other], {**self.config, "timeout": 60}, output)
        self.assertEqual(request.call_count, 2)
        self.assertEqual([c.args[0] for c in assess_call.call_args_list], [other])
        self.assertEqual(result["runs"][0], original["runs"][0])
        backup = next((output / "history").iterdir())
        self.assertEqual((backup / "comparison.json").read_bytes(), old_json)
        self.assertEqual((backup / "comparison.md").read_bytes(), old_md)

    def test_completed_cli_needs_no_terminal_confirmation_or_calls(self):
        run = self.saved_run()
        output = self.root / "evaluations/scenario/task"
        with (
            patch("evaluate.codex_preflight"),
            patch(
                "evaluate.request_assessment",
                side_effect=[(assessment(), {}), (synthesis_result(), {})],
            ),
        ):
            evaluate.compare([run], self.config, output)
        (output / "comparison.md").unlink()
        self.interactive.return_value = False
        with (
            patch("evaluate.request_assessment") as request,
            patch("evaluate.codex_preflight") as auth,
        ):
            self.assertEqual(evaluate.main(["scenario/task"]), 0)
        self.confirmation.assert_not_called()
        request.assert_not_called()
        auth.assert_not_called()
        self.assertTrue((output / "comparison.md").is_file())

    def test_unusable_latest_is_skipped_without_choosing_older_success(self):
        good = self.saved_run()
        for kind in ("dry", "unfinished", "missing", "broken", "malformed"):
            self.saved_run(kind)
            latest = self.saved_run(kind, repeat="repeat-2")
            if kind == "dry":
                data = json.loads((latest / "run.json").read_text())
                (latest / "run.json").write_text(json.dumps({**data, "dry_run": True}))
            elif kind == "unfinished":
                (latest / "metrics.json").write_text(json.dumps(metrics(ended_at=None)))
            elif kind == "missing":
                (latest / "run.json").unlink()
            elif kind == "malformed":
                (latest / "run.json").write_text("{broken")
            else:
                link = latest.parents[1] / "latest"
                link.unlink()
                link.symlink_to("absent")
        with redirect_stderr(io.StringIO()) as warning:
            self.assertEqual(evaluate.discover_comparison("scenario/task", self.parent), [good])
        self.assertIn("Skipping", warning.getvalue())

    def test_changed_sources_are_reference_only_and_saved_prompt_wins(self):
        run, scenario, archive = self.source_only_run(hashes=True)
        before = (run / "run.json").read_bytes()
        with (
            patch(
                "runner.load_scenario",
                return_value={
                    **scenario,
                    "prompt": "Changed prompt",
                    "evaluation_guidance": "Changed guidance",
                },
            ),
            patch("runner.baseline_archive", return_value=archive + b"changed"),
            redirect_stderr(io.StringIO()) as warning,
        ):
            data = evaluate.evidence(run)
        self.assertEqual(data["task.md"], scenario["prompt"])
        self.assertIn("CURRENT REFERENCE ONLY", data["source-provenance.txt"])
        self.assertIn("Warning", warning.getvalue())
        self.assertEqual((run / "run.json").read_bytes(), before)

    def test_damaged_state_is_rebuilt_after_preserving_original(self):
        run = self.saved_run()
        output = self.root / "comparison"
        output.mkdir()
        (output / "comparison.json").write_text("{interrupted")
        with (
            patch("evaluate.codex_preflight"),
            patch(
                "evaluate.request_assessment",
                side_effect=[(assessment(), {}), (synthesis_result(), {})],
            ),
        ):
            result = evaluate.compare([run], self.config, output)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            next((output / "history").glob("*/comparison.json")).read_text(), "{interrupted"
        )

    def test_results_directory_option_is_removed(self):
        with self.assertRaises(SystemExit) as error:
            evaluate.main(["scenario/task", "--results-dir", "/tmp/unused"])
        self.assertEqual(error.exception.code, 2)

    def test_failed_assessment_does_not_block_other_runs(self):
        first, second = self.saved_run(), self.saved_run("model-b")
        output = self.root / "comparison"
        with (
            patch("evaluate.codex_preflight"),
            patch(
                "evaluate.request_assessment",
                side_effect=[RuntimeError("provider failed"), (assessment(), {})],
            ) as request,
            self.assertRaisesRegex(RuntimeError, "incomplete"),
        ):
            evaluate.compare([first, second], self.config, output)
        self.assertEqual(request.call_count, 2)
        state = json.loads((output / "comparison.json").read_text())
        self.assertEqual(
            [r["benchmark_run"] for r in state["runs"]], [evaluate.run_reference(second)]
        )
        self.assertIsNone(state["synthesis"])

    def published_comparison(self):
        run = self.saved_run()
        metadata = json.loads((run / "run.json").read_text())
        metadata.update(prompt="Saved task", archive_sha256="a" * 64)
        (run / "run.json").write_text(json.dumps(metadata))
        output = self.root / "evaluations/scenario/task"
        with (
            patch("evaluate.codex_preflight"),
            patch(
                "evaluate.request_assessment",
                side_effect=[(assessment(), {}), (synthesis_result(), {})],
            ),
        ):
            state = evaluate.compare([run], self.config, output)
        shutil.rmtree(self.parent)
        return output, state

    def test_published_comparison_regenerates_without_results_or_model_calls(self):
        output, original = self.published_comparison()
        self.interactive.return_value = False
        for target in ("scenario/task", "all"):
            (output / "comparison.md").unlink()
            with (
                patch("evaluate.request_assessment") as request,
                patch("evaluate.codex_preflight") as auth,
            ):
                self.assertEqual(evaluate.main([target]), 0)
            request.assert_not_called()
            auth.assert_not_called()
            saved = json.loads((output / "comparison.json").read_text())
            self.assertEqual(saved["runs"], original["runs"])
            self.assertEqual(saved["synthesis"], original["synthesis"])
            self.assertNotIn(str(self.root), json.dumps(saved))
            self.assertEqual(saved["runs"][0]["benchmark_inputs"]["baseline_sha256"], "a" * 64)
            self.assertTrue((output / "comparison.md").is_file())
        self.confirmation.assert_not_called()

    def test_published_alias_order_preserves_score_association(self):
        runs = [self.saved_run("qwen"), self.saved_run("qwen-flash")]
        output = self.root / "evaluations/scenario/task"
        synthesis = {"short_decision": "Different scores.", "quality_scores": [90, 70]}
        with (
            patch("evaluate.codex_preflight"),
            patch(
                "evaluate.request_assessment",
                side_effect=[(assessment(), {})] * 2 + [(synthesis, {})],
            ),
        ):
            original = evaluate.compare(runs, self.config, output)
        shutil.rmtree(self.parent)
        with patch("evaluate.request_assessment") as request:
            restored = evaluate.compare([], self.config, output)
        request.assert_not_called()
        self.assertEqual(restored["runs"], original["runs"])
        self.assertEqual(restored["synthesis"], synthesis)

    def test_new_local_model_extends_published_assessments(self):
        output, original = self.published_comparison()
        added = self.saved_run("model-b")
        with (
            patch("evaluate.codex_preflight"),
            patch("evaluate.assess", wraps=evaluate.assess) as assess_call,
            patch(
                "evaluate.request_assessment",
                side_effect=[(assessment(), {}), (synthesis_result(2), {})],
            ) as request,
        ):
            self.assertEqual(evaluate.main(["scenario/task"]), 0)
        self.assertEqual([c.args[0] for c in assess_call.call_args_list], [added])
        self.assertEqual(request.call_count, 2)
        saved = json.loads((output / "comparison.json").read_text())
        self.assertEqual(saved["runs"][0], original["runs"][0])
        self.assertEqual(len(saved["runs"]), 2)

    def test_local_rerun_replaces_published_model(self):
        output, original = self.published_comparison()
        replacement = self.saved_run(repeat="repeat-2")
        with (
            patch("evaluate.codex_preflight"),
            patch(
                "evaluate.request_assessment",
                side_effect=[(assessment(), {}), (synthesis_result(), {})],
            ),
        ):
            result = evaluate.compare([replacement], self.config, output)
        self.assertEqual(len(result["runs"]), 1)
        self.assertNotEqual(
            result["runs"][0]["benchmark_run"], original["runs"][0]["benchmark_run"]
        )

    def test_legacy_absolute_references_survive_checkout_move(self):
        output, original = self.published_comparison()
        saved = json.loads((output / "comparison.json").read_text())
        for run in saved["runs"]:
            run["benchmark_run"] = "/previous-checkout/" + run["benchmark_run"]
        for item in saved["identity"]["runs"]:
            item["path"] = "/previous-checkout/" + item["path"]
        (output / "comparison.json").write_text(json.dumps(saved))
        with patch("evaluate.request_assessment") as request:
            result = evaluate.compare([], self.config, output)
        request.assert_not_called()
        self.assertEqual(result["runs"], original["runs"])

    def test_published_baseline_hash_difference_warns_without_invalidating(self):
        output, original = self.published_comparison()
        saved = json.loads((output / "comparison.json").read_text())
        other = json.loads(json.dumps(saved["runs"][0]))
        other["benchmark_run"] = other["benchmark_run"].replace("model-a", "model-b")
        other["benchmark_inputs"]["baseline_sha256"] = "b" * 64
        saved["runs"].append(other)
        saved["identity"]["runs"].append(
            {**saved["identity"]["runs"][0], "path": other["benchmark_run"]}
        )
        saved["synthesis"] = synthesis_result(2)
        (output / "comparison.json").write_text(json.dumps(saved))
        with patch("evaluate.request_assessment") as request, redirect_stderr(io.StringIO()) as log:
            result = evaluate.compare([], self.config, output)
        request.assert_not_called()
        self.assertEqual(len(result["runs"]), 2)
        self.assertIn("different baseline hashes", log.getvalue())


if __name__ == "__main__":
    unittest.main()
