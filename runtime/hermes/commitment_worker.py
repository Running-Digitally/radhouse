"""Native cron entry point for the bounded Radhouse commitment-review lane.

No timer, model tools, shared memory or external messaging. Owner configuration
selects the existing native provider; Radhouse supplies and publishes the evidence.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import ssl
import subprocess
import sys
from urllib.parse import urlsplit

import httpx


CONFIG_ENV = "RADHOUSE_COMMITMENT_WORKER_CONFIG"
JOB_NAME = "radhouse-commitment-review-v1"


def research_module():
    spec = importlib.util.spec_from_file_location('radhouse_public_research', Path(__file__).with_name('public_research.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configuration():
    path = Path(os.environ[CONFIG_ENV])
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("worker_config_requires_private_file")
    value = json.loads(path.read_text())
    if set(value) != {"endpoint", "worker_bearer", "model", "provider", "ca_file", "tls_server_name", "hermes_root"}:
        raise ValueError("invalid_worker_config")
    endpoint = urlsplit(value["endpoint"])
    if (endpoint.scheme != "https" or endpoint.hostname not in {"127.0.0.1", "localhost", "::1"} or endpoint.username
            or endpoint.password or endpoint.query or endpoint.fragment or endpoint.path not in {"", "/"}
            or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", value["worker_bearer"])
            or any(not isinstance(value[k], str) or not value[k].strip() or len(value[k]) > 512 for k in ("model", "provider"))
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", value["tls_server_name"])
            or not Path(value["ca_file"]).is_file()
            or not Path(value["hermes_root"]).is_absolute() or not Path(value["hermes_root"]).is_dir()):
        raise ValueError("invalid_worker_config")
    ssl.create_default_context(cafile=value["ca_file"])
    return value


def _guard_installed_runtime(root):
    # These deployed base-overlay guards enforce the empty tool allowlist at
    # dispatch as well as request serialization, including dynamic tool refresh.
    pins = json.loads((Path(__file__).parent / "base-runtime-manifest.json").read_text())
    for name in ("agent/tool_executor.py", "agent/agent_runtime_helpers.py", "agent/agent_init.py"):
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != pins[name]["after_sha256"]:
            raise ValueError("bounded_review_runtime_unqualified")


def native_review(prompt, config):
    root = Path(config["hermes_root"]).resolve()
    _guard_installed_runtime(root)
    sys.path.insert(0, str(root))
    from run_agent import AIAgent
    import run_agent
    if Path(run_agent.__file__).resolve().parent != root:
        raise ValueError("review_runtime_identity_mismatch")
    from hermes_cli.env_loader import load_hermes_dotenv
    load_hermes_dotenv()
    from gateway.run import _resolve_runtime_agent_kwargs_for_provider
    runtime = _resolve_runtime_agent_kwargs_for_provider(config["provider"], config["model"])
    if runtime.get("api_mode") != "chat_completions":
        raise ValueError("review_transport_unqualified")
    # Do not pass native provider overrides capable of installing extra messages,
    # tool schemas or an unreviewed fallback onto the bounded source lane.
    allowed = ("api_key", "base_url", "provider", "requested_provider", "api_mode")
    agent = AIAgent(**{key: runtime[key] for key in allowed if key in runtime},
        model=config["model"], enabled_toolsets=[], disabled_toolsets=["memory", "cronjob", "messaging"],
        skip_context_files=True, load_soul_identity=False, skip_memory=True, skip_background_review=True,
        # Use Hermes' native chat-completions JSON mode. These fixed overrides
        # control syntax only; provider-supplied overrides remain excluded and
        # the application still verifies every field, quotation and citation.
        request_overrides={"response_format": {"type": "json_object"}, "temperature": 0},
        # Leave room for a second bounded call on the local model. The parent
        # process still enforces the independent 240-second wall-clock limit.
        max_iterations=2, max_tokens=2500, run_budget_seconds=180, quiet_mode=True,
        save_trajectories=False, fallback_model=None, session_id="radhouse-review-" + os.urandom(16).hex())
    try:
        agent._allowed_tool_names = frozenset()
        if agent.tools or agent.valid_tool_names or agent._memory_store is not None or agent._memory_manager is not None:
            raise ValueError("review_context_scope_mismatch")
        result = agent.run_conversation(prompt)
        if not isinstance(result, dict) or result.get("failed") or result.get("interrupted"):
            raise ValueError("review_execution_failed")
        output = result.get("final_response")
        if not isinstance(output, str) or not output.strip() or len(output.encode()) > 12000:
            raise ValueError("review_output_invalid")
        if type(json.loads(output)) is not dict:
            raise ValueError("review_output_invalid")
        return output
    finally:
        agent.close()


def isolated_review(prompt, config):
    # Native run budgets are cooperative. This process boundary also bounds a
    # stalled provider call; stdout contains only the result, never native logs.
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "infer"],
        input=prompt, text=True, capture_output=True, timeout=240, check=False)
    if result.returncode or len(result.stdout.encode()) > 12000:
        raise ValueError("review_execution_failed")
    return result.stdout


def run_once(config, *, infer=isolated_review, transport=None, collect=None):
    verify = True if transport is not None else ssl.create_default_context(cafile=config["ca_file"])
    extensions = {"sni_hostname": config.get("tls_server_name", "fixture.test")}
    with httpx.Client(base_url=config["endpoint"], timeout=15, follow_redirects=False, trust_env=False,
                      transport=transport, verify=verify, headers={"Authorization": "Bearer " + config["worker_bearer"]}) as client:
        claim = client.post("/internal/commitment-review/claim", extensions=extensions,
                            headers={'X-Radhouse-Research': 'v1'})
        if claim.status_code == 409 and claim.json().get("error") == "responsibility_paused":
            return "paused"
        claim.raise_for_status()
        if len(claim.content) > 60000:
            raise ValueError("review_claim_too_large")
        value = claim.json()
        if value.get("status") in {"unchanged", "running", "budget_wait"}:
            return value["status"]
        if value.get("status") != "claimed" or not isinstance(value.get("prompt"), str):
            raise ValueError("invalid_review_claim")
        failed = False
        try:
            prompt = value['prompt']
            if value.get('research_requests'):
                collector = collect or research_module().collect_requests
                packet = collector(value['research_requests'], config)
                evidence = client.post('/internal/commitment-review/research', extensions=extensions,
                    json={'review_id': value['review_id'], 'evidence': packet})
                evidence.raise_for_status()
                if len(evidence.content) > 60000:
                    raise ValueError('research_prompt_too_large')
                prompt = evidence.json()['prompt']
            output = infer(prompt, config)
        except Exception:
            failed, output = True, ""
        completion = client.post("/internal/commitment-review/complete", extensions=extensions, json={
            "review_id": value["review_id"], "output": output, "failed": failed})
        completion.raise_for_status()
        status = completion.json().get("status")
        if failed or status not in {"quiet", "ready", "stale"}:
            raise ValueError("review_failed")
        return status


def _install_script(home):
    source = Path(__file__).resolve()
    manifest = source.with_name("base-runtime-manifest.json")
    contents = {source.name: source.read_bytes(), manifest.name: manifest.read_bytes()}
    for name in ('public_research.py', 'research-source-lock.json'):
        contents[name] = source.with_name(name).read_bytes()
    contents['research_contract.py'] = research_module().contract_path().read_bytes()
    revision = hashlib.sha256(b"".join(contents.values())).hexdigest()[:16]
    directory = home / "scripts" / "radhouse-review" / revision
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    if directory.is_symlink() or not directory.resolve().is_relative_to((home / "scripts").resolve()):
        raise ValueError("review_script_directory_invalid")
    for name, data in contents.items():
        path = directory / name
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or path.read_bytes() != data:
                raise ValueError("review_script_needs_reconciliation") from None
        else:
            with os.fdopen(fd,"wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
    return directory / source.name


def _schedule_matches(saved, expected):
    for key, value in expected.items():
        if key == "schedule":
            if saved["schedule"].get("kind") != "interval" or saved["schedule"].get("minutes") != 60:
                return False
        elif saved.get(key) != value:
            return False
    return not any(saved.get(key) for key in ("workdir", "origin", "skills", "context_from", "monitor_script", "monitor_url"))


def provision(*, activate=False):
    """Owner-only provisioning through native storage, not the lossy Jobs API.

    Creates paused and verifies the effective fields. Repeated invocation finds
    the same native job; unexpected/duplicate configuration requires reconciliation.
    """
    import fcntl
    from hermes_constants import get_hermes_home
    from cron import jobs
    home = Path(get_hermes_home())
    home.mkdir(parents=True, exist_ok=True)
    fd = os.open(home / ".radhouse-review-provision.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("review_provision_lock_invalid")
        script = _install_script(home)
        expected = {"name": JOB_NAME, "prompt": "", "schedule": "every 1h", "deliver": "local",
                    "script": str(script), "interpreter": str(Path(sys.executable).absolute()),
                    "enabled_toolsets": [], "no_agent": True, "attach_to_session": False, "failure_deliver": "local"}
        matches = [job for job in jobs.list_jobs(include_disabled=True) if job["name"] == JOB_NAME]
        if len(matches) > 1:
            raise ValueError("review_schedule_needs_reconciliation")
        job = matches[0] if matches else jobs.create_job(**expected, paused=True)
        saved = jobs.get_job(job["id"])
        if not _schedule_matches(saved, expected):
            jobs.pause_job(job["id"])
            raise ValueError("review_schedule_scope_mismatch")
        if activate and not saved["enabled"]:
            jobs.resume_job(job["id"])
        return jobs.get_job(job["id"])
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "infer", "provision", "activate"), nargs="?", default="run")
    args = parser.parse_args()
    try:
        config = configuration()
        sys.path.insert(0, str(Path(config["hermes_root"]).resolve()))
        if args.action == "infer":
            prompt = sys.stdin.read(60001)
            if len(prompt) > 60000:
                raise ValueError("review_prompt_too_large")
            with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                output = native_review(prompt, config)
            print(output)
        elif args.action in {"provision", "activate"}:
            job = provision(activate=args.action == "activate")
            print(json.dumps({"job_id": job["id"], "enabled": job["enabled"], "state": job["state"]}))
        else:
            run_once(config)
            # The durable result is in Radhouse. Cron's local log need not copy it
            # or send a second native-platform message.
            print("[SILENT]")
        return 0
    except Exception:
        print("Radhouse commitment review failed; inspect its coverage status.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
