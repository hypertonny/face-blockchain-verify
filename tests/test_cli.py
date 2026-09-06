"""CLI conformance: prog names, --version, exit codes. Offline-safe."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def run(tool, *args):
    return subprocess.run([PY, os.path.join(HERE, tool), *args],
                          capture_output=True, text=True, timeout=60)


def test_versions():
    for tool in ("pipeline.py", "verify.py", "bench.py",
                 "deploy_polygon.py"):
        r = run(tool, "--version")
        assert r.returncode == 0 and "1.0.0" in r.stdout, (tool, r)


def test_help_names_progs():
    for tool, prog in (("pipeline.py", "pipeline"), ("verify.py", "verify"),
                       ("bench.py", "bench"),
                       ("deploy_polygon.py", "deploy_polygon")):
        r = run(tool, "--help")
        assert r.returncode == 0 and f"usage: {prog}" in r.stdout, tool


def test_usage_errors_exit_2():
    assert run("pipeline.py").returncode == 2
    assert run("verify.py").returncode == 2
    r = run("pipeline.py", "--image", "samples/elon_musk.jpg",
            "--out", "/tmp/opencode/fbv-t", "--no-upload", "--skip-chain")
    assert r.returncode == 2 and "no-upload" in r.stderr
    r = run("pipeline.py", "--image", "http://127.0.0.1/x.jpg",
            "--out", "/tmp/opencode/fbv-t", "--skip-chain")
    assert r.returncode == 2 and "non-public" in r.stderr


def test_compile_help():
    r = subprocess.run(
        [PY, os.path.join(HERE, "contracts", "compile_contracts.py"),
         "--help"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "usage: compile_contracts" in r.stdout


def test_fbv_dispatcher():
    r = run("fbv.py", "--help")
    assert r.returncode == 0 and "usage: fbv" in r.stdout and "deploy" in r.stdout
    r = run("fbv.py", "--version")
    assert r.returncode == 0 and r.stdout.strip() == "fbv 1.0.0"
    r = run("fbv.py", "run", "--version")
    assert r.returncode == 0 and "fbv run 1.0.0" in r.stdout
    r = run("fbv.py", "unknown")
    assert r.returncode == 2 and "unknown command" in r.stderr
