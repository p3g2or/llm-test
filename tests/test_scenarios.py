import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import evaluate, runner


class ScenarioTests(unittest.TestCase):
    def test_baseline_export_excludes_all_benchmark_metadata(self):
        scenario = runner.load_scenario()
        archive = runner.baseline_archive(scenario["baseline"])
        with tempfile.TemporaryDirectory() as temp:
            workspace, home, _ = runner.prepare(archive, Path(temp))
            names = [str(p.relative_to(workspace)) for p in workspace.rglob("*")]
            for forbidden in [
                "evaluation/",
                "checks/",
                "evaluation.md",
                "reproduce.test.ts",
                "task.md",
                "scenario.toml",
                "benchmark.sh",
                "results",
                "scripts/benchmark",
            ]:
                self.assertFalse(any(forbidden in name for name in names), forbidden)
            env = runner.git_env(home)
            self.assertEqual(
                runner.command(["git", "log", "--format=%s"], workspace, env), "Initial commit\n"
            )
            self.assertEqual(runner.command(["git", "tag"], workspace, env), "")
            self.assertEqual(runner.command(["git", "remote"], workspace, env), "")
            app = (workspace / "frontend/src/app.ts").read_text()
            self.assertLess(
                app.index("summary.textContent ="), app.index("if (current !== revision) return")
            )
        self.assertEqual(archive, runner.baseline_archive(scenario["baseline"]))

    def test_result_paths_preserve_runs_and_separate_experiments(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp).resolve()
            first = runner.result_directory(parent, "field-notes", "task", "glm", "prompt")
            (first / "run.json").write_text(json.dumps({"prompt": "prompt"}))
            second = runner.result_directory(parent, "field-notes", "task", "glm", "prompt")
            runner.update_latest(first)
            runner.update_latest(second)
            self.assertTrue(first.is_dir())
            self.assertNotEqual(first, second)
            self.assertEqual((parent / "field-notes/task/glm/latest").resolve(), second)
            self.assertNotEqual(
                second, runner.result_directory(parent, "other", "task", "glm", "prompt")
            )
            self.assertTrue(
                runner.result_directory(parent, "field-notes", "task", "glm", "different").is_dir()
            )
            with self.assertRaises(ValueError):
                runner.result_directory(parent, "../escape", "task", "glm", "prompt")

    def test_evaluation_discovery_and_mocked_call_preserve_metrics(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp).resolve()
            run = runner.result_directory(parent, "field-notes", "task", "glm", "prompt")
            for name in [
                "run.json",
                "task.md",
                "response.txt",
                "diff.patch",
                "check.log",
                "evaluation-guidance.md",
            ]:
                (run / name).write_text("evidence")
            (run / "run.json").write_text(
                json.dumps({"scenario": "field-notes", "task_name": "task"})
            )
            metrics = '{"ended_at":"today","status":"completed","validation":"PASS"}'
            (run / "metrics.json").write_text(metrics)
            archive = io.BytesIO()
            with tarfile.open(fileobj=archive, mode="w"):
                pass
            (run / "baseline.tar").write_bytes(archive.getvalue())
            runner.update_latest(run)
            self.assertEqual(evaluate.discover("all", parent), [run])
            self.assertEqual(evaluate.discover("field-notes/task/glm/latest", parent), [run])
            with (
                patch("evaluate.urllib.request.urlopen") as request,
                patch("runner.credential") as auth,
            ):
                evaluate.main([str(parent / "field-notes/task"), "--dry-run"])
                request.assert_not_called()
                auth.assert_not_called()
            findings = dict.fromkeys(
                [
                    "findings_summary",
                    "observed_correctness",
                    "test_quality_coverage",
                    "scope_discipline",
                    "independently_discovered_issues",
                    "known_bug_discovery",
                ],
                "fixture",
            )
            findings["evidence_citations"] = ["response.txt:1"]
            reply = {
                "model": "fixture",
                "choices": [{"message": {"content": json.dumps(findings)}}],
            }
            with patch(
                "evaluate.urllib.request.urlopen",
                return_value=io.BytesIO(json.dumps(reply).encode()),
            ):
                evaluate.evaluate(run, {"model": "fixture", "max_tokens": 10, "timeout": 1}, "fake")
            self.assertEqual((run / "metrics.json").read_text(), metrics)
            self.assertTrue((run / "evaluation.md").exists())
            self.assertTrue((run / "evaluation.json").is_file())


PROMPTS = {
    "known-bug": (
        "After deleting a note, the note disappears but the displayed total and category counts "
        "are sometimes incorrect.\n\nPlease investigate and fix the issue."
    ),
    "false-category-mixing": (
        "When quickly switching between categories, notes from the previously selected category "
        "occasionally remain visible together with notes from the newly selected category."
        "\n\nPlease investigate and fix the issue."
    ),
    "note-limit": (
        "Add support for a configurable maximum number of notes.\n\n"
        "The limit must be configurable from the Terraform dev environment and enforced by the "
        "backend.\n\nThe frontend should show users the configured limit and prevent creating "
        "another note when the limit has been reached.\n\n"
        "The application must continue to work when no explicit limit is configured."
    ),
}


class NamedTaskTests(unittest.TestCase):
    def test_exact_prompts_default_and_common_candidate_contents(self):
        self.assertEqual(runner.load_scenario()["task_name"], "known-bug")
        archives = []
        commits = []
        for task, prompt in PROMPTS.items():
            scenario = runner.load_scenario(task=task)
            self.assertEqual(scenario["prompt"], prompt)
            archive = runner.baseline_archive(scenario["baseline"])
            archives.append(archive)
            with tempfile.TemporaryDirectory() as temp:
                workspace, home, commit = runner.prepare(archive, Path(temp))
                commits.append(commit)
                env = runner.git_env(home)
                self.assertEqual(runner.command(["git", "tag"], workspace, env), "")
                self.assertEqual(runner.command(["git", "remote"], workspace, env), "")
                self.assertEqual(
                    runner.command(["git", "log", "--format=%s"], workspace, env),
                    "Initial commit\n",
                )
                with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                    for member in tar.getmembers():
                        content = tar.extractfile(member).read().decode()
                        for marker in [
                            "intentionally false",
                            "stale-summary race",
                            "Private benchmark guidance",
                            *PROMPTS.values(),
                        ]:
                            self.assertNotIn(marker, content, member.name)
                        for marker in [
                            "evaluation",
                            "reproduce",
                            "tasks/",
                            "checks/",
                            "evaluation/",
                            "scenario.toml",
                            "results/",
                            *PROMPTS.keys(),
                        ]:
                            self.assertNotIn(marker, member.name)
        self.assertTrue(all(archive == archives[0] for archive in archives))
        self.assertEqual(len(set(commits)), 1)

    def test_preparation_only_all_aliases_and_task_result_paths(self):
        scenarios = {task: runner.load_scenario(task=task) for task in PROMPTS}
        original_command = runner.command

        def command(args, *rest):
            if args == ["/fake/opencode", "--version"]:
                return runner.VERSION
            if args[0] == "/fake/opencode":
                self.assertEqual(args[1:], ["models", "openrouter", "--pure"])
                return "\n".join("openrouter/" + model for model in runner.MODELS.values())
            return original_command(args, *rest)

        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp).resolve() / "results"
            with (
                patch("runner.ROOT", Path(temp)),
                patch(
                    "runner.load_scenario",
                    side_effect=lambda name="field-notes", task=None: scenarios[
                        task or "known-bug"
                    ],
                ),
                patch("runner.check_runtime", return_value="/fake/opencode"),
                patch("runner.command", side_effect=command),
                patch("runner.sandbox", return_value=[]),
                patch("runner.probe"),
                patch("runner.credential") as credential,
                patch("runner.urllib.request.urlopen") as network,
                patch("runner.execute") as execute,
            ):
                for task in PROMPTS:
                    self.assertEqual(runner.main(["all", "--task", task, "--dry-run"]), 0)
                credential.assert_not_called()
                network.assert_not_called()
                execute.assert_not_called()
            for task, prompt in PROMPTS.items():
                for alias in runner.MODELS:
                    latest = parent / "field-notes" / task / alias / "latest"
                    self.assertTrue(latest.is_dir())
                    self.assertEqual(latest.resolve().parent.name, "runs")
                    self.assertFalse((latest / "task.md").exists())
                    self.assertEqual(
                        evaluate.source_artifacts(latest)[0]["task.md"].decode(), prompt
                    )
                    self.assertFalse((latest / "private-probe").exists())
                    run = json.loads((latest / "run.json").read_text())
                    self.assertEqual(run["task_name"], task)
                    self.assertEqual(run["model"], alias)
                    self.assertEqual(
                        json.loads((latest / "metrics.json").read_text())["status"], "prepared"
                    )

    def test_evaluator_uses_saved_task_guidance_and_infrastructure(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp).resolve()
            runs = []
            for task in PROMPTS:
                scenario = runner.load_scenario(task=task)
                run = runner.result_directory(
                    parent, "field-notes", task, "glm", scenario["prompt"]
                )
                with patch("runner.execute") as execute:
                    runner.run_candidate(
                        "glm",
                        runner.baseline_archive(scenario["baseline"]),
                        run,
                        "unused",
                        "",
                        available=False,
                        scenario=scenario,
                        result=run,
                    )
                    execute.assert_not_called()
                runs.append(run)
                self.assertEqual(evaluate.discover(f"field-notes/{task}/glm/latest", parent), [run])
                evidence = evaluate.evidence(run)
                guidance = evidence["evaluation-guidance.md"]
                self.assertIn("# Private benchmark guidance: stale summary", guidance)
                self.assertIn(f"# Task evaluation: {task}", guidance)
                self.assertEqual(evidence["task.md"], PROMPTS[task])
                self.assertIn("infra/environments/dev/main.tf", evidence["baseline_source"])
                for other in PROMPTS.keys() - {task}:
                    self.assertNotIn(f"# Task evaluation: {other}", guidance)
                if task == "false-category-mixing":
                    self.assertIn("intentionally false", guidance)
                    self.assertIn(
                        "Do not automatically treat no production change as failure", guidance
                    )
                changed = dict(scenario, evaluation_guidance="Changed guidance")
                with (
                    patch("runner.load_scenario", return_value=changed),
                ):
                    self.assertEqual(
                        evaluate.evidence(run)["evaluation-guidance.md"],
                        scenario["evaluation_guidance"],
                    )
            self.assertEqual(set(evaluate.discover("all", parent)), set(runs))

    def test_selected_prompt_is_the_only_task_input_to_agent(self):
        for task, prompt in PROMPTS.items():
            with tempfile.TemporaryDirectory() as temp:
                scenario = runner.load_scenario(task=task)
                with (
                    patch("runner.sandbox", return_value=[]),
                    patch("runner.probe"),
                    patch(
                        "runner.execute",
                        side_effect=[(1, 0.1, False, b"", b""), (0, 0.1, False, b"", b"")],
                    ) as execute,
                ):
                    runner.run_candidate(
                        "glm",
                        runner.baseline_archive(scenario["baseline"]),
                        Path(temp),
                        "unused",
                        "",
                        scenario=scenario,
                    )
                self.assertEqual(execute.call_args_list[0].args[-1], prompt.encode())
