"""Deterministic tests for the bounded, process-group-owning subprocess seam.

These drive ``trello_watch._run_subprocess`` with real (sub-second) subprocesses
via ``[sys.executable, "-c", <script>]`` so nested-child cleanup, output
bounding, and the RunResult contract are proven without invoking real ``twf``
or waiting hours. POSIX-only (setsid/killpg).
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from gallery import trello_watch

posix_only = pytest.mark.skipif(os.name != "posix", reason="requires POSIX setsid/killpg")


@pytest.fixture
def run_env(tmp_path, monkeypatch):
    """Point run-logs at the sandbox and return a minimal child env."""
    monkeypatch.setenv("GALLERY_DATA_DIR", str(tmp_path))
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}


def _pid_dead(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        # Still alive but not ours to signal — treat as alive.
        return False
    return False


@posix_only
def test_timeout_reaps_grandchild(tmp_path, run_env):
    pid_file = tmp_path / "pids.txt"
    ready_file = tmp_path / "grandchild-ready"
    grandchild_script = (
        "import signal, time\n"
        "from pathlib import Path\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"Path({str(ready_file)!r}).write_text('ready')\n"
        "time.sleep(30)\n"
    )
    script = f"""
import os, subprocess, sys, time
gc = subprocess.Popen([sys.executable, "-c", {grandchild_script!r}])
deadline = time.monotonic() + 5
while not os.path.exists({str(ready_file)!r}):
    if time.monotonic() >= deadline:
        raise RuntimeError("grandchild did not become ready")
    time.sleep(0.01)
open({str(pid_file)!r}, "w").write(str(os.getpid()) + "\\n" + str(gc.pid) + "\\n")
print("MARKER-BEFORE-HANG", flush=True)
time.sleep(30)
"""
    result = trello_watch._run_subprocess(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=run_env,
        timeout=1,
        grace=0.2,
    )

    assert result.timed_out is True
    assert result.returncode == 124

    pids = [int(line) for line in pid_file.read_text().split()]
    try:
        assert len(pids) == 2
        for pid in pids:
            for _ in range(50):
                if _pid_dead(pid):
                    break
                time.sleep(0.05)
            assert _pid_dead(pid), f"pid {pid} survived group cleanup"
    finally:
        # Never leave a sleeper behind if an assertion exposes a regression.
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@posix_only
def test_partial_log_survives_timeout(tmp_path, run_env):
    script = "import sys, time; print('MARKER-PARTIAL', flush=True); time.sleep(30)"
    result = trello_watch._run_subprocess(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=run_env,
        timeout=0.5,
        grace=0.2,
    )

    assert result.timed_out is True
    assert "MARKER-PARTIAL" in result.output
    assert "timed out after 0.5s" in result.output


@posix_only
def test_interruption_reaps_owned_process_group(tmp_path, run_env, monkeypatch):
    real_popen = trello_watch.subprocess.Popen
    spawned_pid = None

    class InterruptingPopen:
        def __init__(self, *args, **kwargs):
            nonlocal spawned_pid
            self._proc = real_popen(*args, **kwargs)
            self._interrupt = True
            spawned_pid = self._proc.pid

        @property
        def pid(self):
            return self._proc.pid

        @property
        def returncode(self):
            return self._proc.returncode

        def poll(self):
            return self._proc.poll()

        def wait(self, timeout=None):
            if self._interrupt:
                self._interrupt = False
                raise KeyboardInterrupt
            return self._proc.wait(timeout=timeout)

    monkeypatch.setattr(trello_watch.subprocess, "Popen", InterruptingPopen)

    try:
        with pytest.raises(KeyboardInterrupt):
            trello_watch._run_subprocess(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                cwd=tmp_path,
                env=run_env,
                timeout=30,
                grace=0.2,
            )

        assert spawned_pid is not None
        assert _pid_dead(spawned_pid)
    finally:
        if spawned_pid is not None:
            try:
                os.kill(spawned_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@posix_only
def test_interruption_reaps_group_after_direct_child_exits(tmp_path, run_env, monkeypatch):
    pid_file = tmp_path / "pids.txt"
    ready_file = tmp_path / "grandchild-ready"
    grandchild_script = (
        "import signal, time\n"
        "from pathlib import Path\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"Path({str(ready_file)!r}).write_text('ready')\n"
        "time.sleep(30)\n"
    )
    script = f"""
import os, subprocess, sys, time
gc = subprocess.Popen([sys.executable, "-c", {grandchild_script!r}])
deadline = time.monotonic() + 5
while not os.path.exists({str(ready_file)!r}):
    if time.monotonic() >= deadline:
        raise RuntimeError("grandchild did not become ready")
    time.sleep(0.01)
open({str(pid_file)!r}, "w").write(str(os.getpid()) + "\\n" + str(gc.pid) + "\\n")
"""
    real_popen = trello_watch.subprocess.Popen

    class ExitedThenInterruptedPopen:
        def __init__(self, *args, **kwargs):
            self._proc = real_popen(*args, **kwargs)
            self._interrupt = True

        @property
        def pid(self):
            return self._proc.pid

        @property
        def returncode(self):
            return self._proc.returncode

        def poll(self):
            return self._proc.poll()

        def wait(self, timeout=None):
            result = self._proc.wait(timeout=timeout)
            if self._interrupt:
                self._interrupt = False
                raise KeyboardInterrupt
            return result

    monkeypatch.setattr(trello_watch.subprocess, "Popen", ExitedThenInterruptedPopen)

    pids = []
    try:
        with pytest.raises(KeyboardInterrupt):
            trello_watch._run_subprocess(
                [sys.executable, "-c", script],
                cwd=tmp_path,
                env=run_env,
                timeout=30,
                grace=0.2,
            )

        pids = [int(line) for line in pid_file.read_text().split()]
        assert len(pids) == 2
        assert _pid_dead(pids[0]), "direct child should already be reaped"
        for _ in range(50):
            if _pid_dead(pids[1]):
                break
            time.sleep(0.05)
        assert _pid_dead(pids[1]), f"grandchild pid {pids[1]} survived exceptional cleanup"
    finally:
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@posix_only
def test_sigterm_to_watcher_reaps_active_worker(tmp_path):
    pid_file = tmp_path / "worker.pid"
    child_script = (
        "import os, time\n"
        "from pathlib import Path\n"
        f"Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(30)\n"
    )
    wrapper_script = f"""
import sys
from pathlib import Path
from gallery import cli, trello_watch

class FakeWatcher:
    def poll_once(self):
        trello_watch._run_subprocess(
            [sys.executable, "-c", {child_script!r}],
            cwd=Path({str(tmp_path)!r}),
            env={{"PATH": {os.environ.get("PATH", "/usr/bin:/bin")!r}}},
            timeout=30,
            grace=0.2,
        )
        return {{}}

cli.trello_watch.build_watcher = lambda *args, **kwargs: FakeWatcher()
sys.argv = ["portal", "trello-watch", "--repo", {str(tmp_path)!r}, "--once"]
cli.main()
"""
    env = dict(os.environ)
    env["GALLERY_DATA_DIR"] = str(tmp_path / "gallery-data")
    wrapper = subprocess.Popen(
        [sys.executable, "-c", wrapper_script],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
    )
    worker_pid = None
    try:
        deadline = time.monotonic() + 5
        while not pid_file.exists():
            if wrapper.poll() is not None:
                pytest.fail(f"watcher wrapper exited early with {wrapper.returncode}")
            if time.monotonic() >= deadline:
                pytest.fail("worker did not become ready")
            time.sleep(0.01)

        worker_pid = int(pid_file.read_text())
        os.kill(wrapper.pid, signal.SIGTERM)
        assert wrapper.wait(timeout=5) == 128 + signal.SIGTERM
        for _ in range(50):
            if _pid_dead(worker_pid):
                break
            time.sleep(0.05)
        assert _pid_dead(worker_pid), f"worker pid {worker_pid} survived watcher SIGTERM"
    finally:
        if wrapper.poll() is None:
            wrapper.kill()
            wrapper.wait()
        if worker_pid is not None:
            try:
                os.kill(worker_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_output_is_bounded(tmp_path, run_env):
    # Write far more than the tail cap, ending with a unique marker.
    script = (
        "import sys\n"
        "chunk = 'x' * 1000\n"
        "for _ in range(5000):\n"
        "    sys.stdout.write(chunk)\n"
        "sys.stdout.write('END-MARKER')\n"
    )
    result = trello_watch._run_subprocess(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=run_env,
        timeout=30,
        grace=0.2,
    )

    assert result.returncode == 0
    assert result.timed_out is False
    # Bounded by the tail cap (ascii => bytes == chars), plus a small margin.
    assert len(result.output) <= trello_watch.RUN_LOG_TAIL_BYTES + 16
    # It is the END of the stream, not the start.
    assert result.output.endswith("END-MARKER")


def test_normal_exit_captures_output(tmp_path, run_env):
    script = "print('hello from child')"
    result = trello_watch._run_subprocess(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=run_env,
        timeout=30,
        grace=0.2,
    )

    assert result.returncode == 0
    assert result.timed_out is False
    assert "hello from child" in result.output


def test_nonzero_exit_preserved(tmp_path, run_env):
    result = trello_watch._run_subprocess(
        [sys.executable, "-c", "import sys; sys.exit(3)"],
        cwd=tmp_path,
        env=run_env,
        timeout=30,
        grace=0.2,
    )

    assert result.returncode == 3
    assert result.timed_out is False


def test_unlaunchable_command_returns_127(tmp_path, run_env):
    result = trello_watch._run_subprocess(
        [str(tmp_path / "no-such-binary-xyz")],
        cwd=tmp_path,
        env=run_env,
        timeout=30,
        grace=0.2,
    )

    assert result.returncode == 127
    assert "could not start" in result.output
