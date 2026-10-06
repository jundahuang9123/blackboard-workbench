"""One bounded local model job at a time, with restart/cancel handling."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
import uuid
from .store import now, Conflict
from .datasets import Datasets


class Jobs:
    def __init__(self, store, data_dir, upstream=None, python=None, settings=None):
        self.store, self.directory = store, Path(data_dir)
        self.upstream = Path(upstream).resolve() if upstream else None
        self.python = python
        self.settings = settings
        self.lock = threading.Lock()
        self.active = None
        self.process = None
        self.cancelled = set()
        for job in store.jobs():
            if job["status"] in {"queued", "running"}:
                job.update(status="interrupted", message="Server restarted. This job was not automatically resumed.")
                store.save_job(job)

    def setup(self):
        samples = []
        ready = bool(self.upstream and self.python and (self.upstream / "blackboard/codebase/core/blackboard_semantic_mapping.py").is_file())
        if ready:
            base = self.upstream / "datacorpus/vcslam"
            samples = sorted(p.name for p in base.glob("[0-9][0-9][0-9][0-9]") if p.is_dir() and (p / f"{p.name}_samples.json").is_file())
        return {"configured": ready, "upstream": str(self.upstream) if self.upstream else None, "samples": samples}

    def start(self, payload):
        if not self.setup()["configured"]:
            raise ValueError("Start the server with --upstream and --upstream-python to enable model execution.")
        kind = payload.get("kind")
        if kind not in {"pipeline", "custom_pipeline", "discussion"}:
            raise ValueError("Unknown job kind.")
        if self.settings is None:
            from .settings import ModelSettings
            self.settings = ModelSettings(self.directory)
        connection = self.settings.resolve(model=payload.get("model"), provider=payload.get("provider"))
        model = connection["model"]
        timeout = payload.get("timeout", 600)
        max_timeout = 7200 if connection["provider"] in {"ollama", "local"} else 1800
        if not isinstance(timeout, int) or isinstance(timeout, bool) or not 30 <= timeout <= max_timeout:
            raise ValueError(f"Time limit must be between 30 and {max_timeout} seconds.")
        job = {"id": uuid.uuid4().hex, "created": now(), "status": "queued", "kind": kind, "model": model, "provider": connection["provider"], "endpoint": connection["endpoint"], "thinking": connection.get("thinking", "default"), "timeout": timeout, "run_ids": [], "message": "Waiting for worker", "log": ""}
        if kind in {"pipeline", "custom_pipeline"}:
            context_mode = payload.get("context_mode", "shared")
            if context_mode not in {"legacy", "shared"}:
                raise ValueError("Choose shared or legacy ontology context.")
            job["context_mode"] = context_mode
        job["json_output"] = "object-or-array-v1" if connection["provider"] == "ollama" else "prompt"
        cfg = {**job, "upstream": str(self.upstream), "llm": {k: connection[k] for k in ("provider", "model", "endpoint", "thinking")}}
        if kind == "pipeline":
            for key, maximum in [("samples", 5), ("historical", 20)]:
                values = payload.get(key, [])
                allowed = set(self.setup()["samples"])
                if not isinstance(values, list) or len(values) > maximum or any(not isinstance(x, str) or x not in allowed for x in values):
                    raise ValueError(f"Choose at most {maximum} valid {key} IDs.")
                cfg[key] = list(dict.fromkeys(values))
            if not cfg["samples"]:
                raise ValueError("Choose at least one sample.")
            job.update(samples=cfg["samples"], historical=cfg["historical"])
        elif kind == "custom_pipeline":
            folder, metadata = Datasets(self.directory).get(payload.get("dataset_id"))
            cfg["dataset_path"] = str(folder)
            job.update(dataset_id=metadata["id"], dataset_title=metadata["title"], benchmark_available=metadata["benchmark_available"])
        else:
            run = self.store.run(payload.get("run_id"))
            item = next((x for x in run["items"] if x["id"] == payload.get("item_id")), None)
            if item is None or not item["candidates"]:
                raise ValueError("Select an attribute with validated candidates.")
            rounds = payload.get("rounds", 1)
            if not isinstance(rounds, int) or not 1 <= rounds <= 3:
                raise ValueError("Choose one to three discussion rounds.")
            if payload.get("version") != item["version"]:
                raise Conflict("Refresh this attribute before requesting a discussion.")
            cfg["rounds"] = rounds
            cfg["context"] = {"item": item, "history": [e for e in run["events"] if e["item"] == item["id"]], "source_context": run["raw"].get("workbench_context", {"notice": "Original data and documentation were not included in this imported export. Use recorded assessments with that limitation."}), "original_discussions": run["raw"].get("discussions", {})}
            job.update(run_id=run["id"], item_id=item["id"], version=item["version"], rounds=rounds)
        try:
            revision = subprocess.check_output(["git", "-C", str(self.upstream), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            revision = "unknown"
        job["upstream_revision"] = revision
        cfg["upstream_revision"] = revision
        with self.lock:
            if self.active:
                raise Conflict("Another model job is running. Wait or cancel it first.")
            self.active = job["id"]
            self.store.save_job(job)
            threading.Thread(target=self._execute, args=(job, cfg, connection), daemon=True).start()
        return job

    def cancel(self, jid):
        with self.lock:
            if self.active != jid:
                raise ValueError("This job is no longer active.")
            self.cancelled.add(jid)
            if self.process and self.process.poll() is None:
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    def _execute(self, job, cfg, connection=None):
        directory = self.directory / "jobs" / job["id"]
        log_path = directory / "worker.log"
        process = None
        secret = connection.get("api_key", "") if connection else ""
        try:
            directory.mkdir(parents=True)
            cfg["output"] = str(directory / "output")
            Path(cfg["output"]).mkdir()
            config_path = directory / "config.json"
            config_path.write_text(json.dumps(cfg))
            job.update(status="running", message="Starting isolated worker")
            self.store.save_job(job)
            with log_path.open("w") as log:
                environment = os.environ.copy()
                if connection:
                    environment["WORKBENCH_API_KEY"] = secret
                    environment["OPENAIKEY"] = "workbench-provider"
                process = subprocess.Popen([self.python, "-u", str(Path(__file__).with_name("worker.py")), str(config_path)], stdout=log, stderr=log, start_new_session=True, env=environment)
                job["message"] = "Worker running. Follow the stage log below."
                self.store.save_job(job)
                with self.lock:
                    self.process = process
                started = time.monotonic()
                while process.poll() is None:
                    if job["id"] in self.cancelled or time.monotonic() - started > job["timeout"]:
                        try:
                            os.killpg(process.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait()
                        job["status"] = "cancelled" if job["id"] in self.cancelled else "timed_out"
                        break
                    time.sleep(.4)
                    job["log"] = self._log(log_path, (secret,))
                    self.store.save_job(job)
            job["log"] = self._log(log_path, (secret,))
            with self.lock:
                if job["id"] in self.cancelled:
                    job["status"] = "cancelled"
            if job["status"] in {"cancelled", "timed_out"}:
                job["message"] = "Worker stopped. Existing run and review records are unchanged."
            elif process.returncode:
                job.update(status="failed", message="Worker failed. Inspect its log and upstream environment.")
            else:
                if job["kind"] in {"pipeline", "custom_pipeline"}:
                    for result in sorted(Path(cfg["output"]).glob("*/*/*_mapping_results.json")):
                        raw = json.loads(result.read_text())
                        if job["kind"] == "custom_pipeline":
                            title = f"{job['dataset_title']} · {job['model']}"
                            origin = "custom_pipeline"
                        else:
                            sid = result.parent.name
                            base = self.upstream / "datacorpus/vcslam" / sid
                            raw["workbench_context"] = {"data": json.loads((base / f"{sid}_samples.json").read_text()), "documentation": (base / f"{sid}.txt").read_text() if (base / f"{sid}.txt").exists() else "", "historical_ids": cfg["historical"], "upstream_revision": job["upstream_revision"], "model": job["model"], "provider": job.get("provider", "openai"), "endpoint": job.get("endpoint"), "thinking": job.get("thinking", "default"), "json_output": job.get("json_output", "prompt"), "context_mode": job.get("context_mode", "shared")}
                            title, origin = f"SAST {sid} · {job['model']}", "upstream_pipeline"
                        run = self.store.import_run(raw, title, origin)
                        job["run_ids"].append(run["id"])
                    if not job["run_ids"]:
                        raise ValueError("The worker completed without producing SAST result files.")
                else:
                    for line in (Path(cfg["output"]) / "responses.jsonl").read_text().splitlines():
                        self.store.agent_event(job["run_id"], job["item_id"], json.loads(line))
                job.update(status="completed", message="Results saved. Agent proposals require a separate human decision.")
        except Exception as exc:
            message = self.settings.redacted(str(exc), (secret,)) if self.settings else str(exc)
            job.update(status="failed", message=message)
        finally:
            if process and process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            with self.lock:
                self.active = None
                self.process = None
                self.cancelled.discard(job["id"])
            self.store.save_job(job)

    def _log(self, path, extra_keys=()):
        content = path.read_text(errors="replace") if path.exists() else ""
        content = re.sub(r"\x1b\[[0-9;]*m", "", content)
        content = re.sub(r"sk-[A-Za-z0-9_\-]+", "[redacted key]", content)
        for key in ("OPENAIKEY", "OPENAI_API_KEY"):
            if os.environ.get(key):
                content = content.replace(os.environ[key], "[redacted key]")
        if self.settings:
            content = self.settings.redacted(content, extra_keys)
        return content[-8000:]
