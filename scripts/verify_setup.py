#!/usr/bin/env python3
"""Verify that Docker and OpenSandbox are ready for MCPRuntime."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path


DEFAULT_DOMAIN = os.environ.get("OPENSANDBOX_DOMAIN", "localhost:8080")


def print_step(step: str, status: str = "") -> None:
    if status == "✓":
        print(f"✓ {step}")
    elif status == "✗":
        print(f"✗ {step}")
    elif status == "⚠":
        print(f"⚠ {step}")
    else:
        print(f"  {step}")


def check_docker() -> bool:
    try:
        result = subprocess.run(["docker", "ps"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print_step("Docker is running", "✓")
            return True
        print_step("Docker is installed but not running", "✗")
        print("  Start Docker Desktop or the Docker daemon.")
        return False
    except FileNotFoundError:
        print_step("Docker is not installed", "✗")
        print("  Install Docker: https://docs.docker.com/get-docker/")
        return False
    except Exception as exc:
        print_step(f"Error checking Docker: {exc}", "✗")
        return False


def check_python_packages() -> bool:
    missing = []
    for package, import_name in [("opensandbox", "opensandbox"), ("opensandbox-server", "opensandbox")]:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(package)

    if not missing:
        print_step("OpenSandbox Python packages are installed", "✓")
        return True

    print_step("OpenSandbox Python packages are missing", "✗")
    print(f"  Install with: pip install {' '.join(missing)}")
    return False


def check_port_reachable(domain: str) -> bool:
    host, _, port = domain.partition(":")
    port = int(port or "8080")
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def check_opensandbox_server() -> bool:
    if check_port_reachable(DEFAULT_DOMAIN):
        print_step(f"OpenSandbox server is reachable at {DEFAULT_DOMAIN}", "✓")
        return True

    print_step(f"OpenSandbox server is not reachable at {DEFAULT_DOMAIN}", "✗")
    print("  Start it with: opensandbox-server start")
    print("  Configure once with: opensandbox-server init-config ~/.sandbox.toml --example docker")
    return False


def check_workspace_dirs() -> bool:
    root = Path(__file__).resolve().parent.parent
    expected = [root / "workspace", root / "skills", root / "servers"]
    missing = [str(path.relative_to(root)) for path in expected if not path.exists()]
    if not missing:
        print_step("Workspace directories exist", "✓")
        return True

    print_step("Some workspace directories are missing", "⚠")
    print(f"  Missing: {', '.join(missing)}")
    print("  They will be created automatically as needed.")
    return True


def main() -> int:
    print("=" * 60)
    print("MCPRuntime OpenSandbox Verification")
    print("=" * 60)
    print()

    checks = [
        ("[1/4] Checking Docker...", check_docker),
        ("[2/4] Checking Python packages...", check_python_packages),
        ("[3/4] Checking OpenSandbox server...", check_opensandbox_server),
        ("[4/4] Checking workspace layout...", check_workspace_dirs),
    ]

    ok = True
    for title, fn in checks:
        print(title)
        if not fn():
            ok = False
        print()

    print("=" * 60)
    if ok:
        print("✅ ALL CHECKS PASSED")
        print("MCPRuntime is ready to use with OpenSandbox.")
        print()
        print("Try it:")
        print("  python examples/00_simple_api.py")
        print("  python -m benchmarks run --backend opensandbox --profile quick")
        print("=" * 60)
        return 0

    print("❌ SETUP INCOMPLETE")
    print("Fix the issues above, then rerun: python scripts/verify_setup.py")
    print("=" * 60)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
