"""Best-effort process-level sandbox for executing LLM-generated Python.

Isolation model (documented limitation — see DESIGN.md section 4):
  - Runs in a fresh temp directory containing ONLY the task's declared
    input artifacts, copied in by key. The script cannot see any other
    run's data or any artifact it didn't declare as an input.
  - CPU time, address-space (memory), and wall-clock timeout are limited.
  - Only files matching the task's declared output_keys are lifted out as
    artifacts; anything else the script writes is discarded.
  - This is NOT container-level isolation. A sufficiently adversarial
    script could still escape a subprocess sandbox. Production hardening
    would add nsjail/firejail + a locked network namespace.
"""
import os
import resource
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field


@dataclass
class SandboxResult:
    success: bool
    stdout: str = ""
    stderr: str = ""
    output_files: dict = field(default_factory=dict)  # key -> path (in the temp dir)
    error: str = ""


def _limit_resources(memory_mb: int):
    """Called in the child process (preexec_fn) before exec. POSIX only."""
    def _set():
        mem_bytes = memory_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        except (ValueError, resource.error):
            pass  # some platforms (e.g. macOS) restrict RLIMIT_AS; degrade gracefully
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (25, 25))
        except (ValueError, resource.error):
            pass
    return _set


def run_in_sandbox(
    code: str,
    input_files: dict,          # key -> source path on the host
    expected_output_keys: list,
    timeout_seconds: int = 30,
    memory_mb: int = 256,
) -> SandboxResult:
    workdir = tempfile.mkdtemp(prefix="taskgraph_task_")
    try:
        # Only the declared inputs are visible inside the sandbox.
        for key, src_path in input_files.items():
            dst = os.path.join(workdir, f"input_{key}")
            shutil.copyfile(src_path, dst)

        script_path = os.path.join(workdir, "task_script.py")
        with open(script_path, "w") as f:
            f.write(code)

        env = {
            "PATH": os.environ.get("PATH", ""),
            "TASKGRAPH_WORKDIR": workdir,
        }

        try:
            proc = subprocess.run(
                [sys.executable, script_path],
                cwd=workdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                preexec_fn=_limit_resources(memory_mb) if os.name == "posix" else None,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                success=False,
                error=f"task exceeded {timeout_seconds}s timeout and was killed",
            )

        if proc.returncode != 0:
            return SandboxResult(
                success=False,
                stdout=proc.stdout,
                stderr=proc.stderr,
                error=f"script exited with code {proc.returncode}",
            )

        output_files = {}
        for key in expected_output_keys:
            candidate = os.path.join(workdir, f"output_{key}")
            if os.path.exists(candidate):
                output_files[key] = candidate

        missing = [k for k in expected_output_keys if k not in output_files]
        if missing:
            return SandboxResult(
                success=False,
                stdout=proc.stdout,
                stderr=proc.stderr,
                error=f"task did not produce declared outputs: {missing}",
            )

        return SandboxResult(
            success=True,
            stdout=proc.stdout,
            stderr=proc.stderr,
            output_files=output_files,
        )
    finally:
        # Output files are copied out by the caller (worker.py) via
        # storage.py BEFORE this cleanup would matter in a real deployment;
        # here we leave workdir cleanup to the caller so it can read files
        # first. See worker.py.
        pass


def cleanup_sandbox_dir(any_output_path: str):
    """Call after the worker has copied outputs into persistent storage."""
    workdir = os.path.dirname(any_output_path) if any_output_path else None
    if workdir and os.path.isdir(workdir) and workdir.startswith(tempfile.gettempdir()):
        shutil.rmtree(workdir, ignore_errors=True)
