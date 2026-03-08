#!/usr/bin/env python3
"""Check whether the local environment is ready to run MCPRuntime examples."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def check_package(name: str, import_name: str | None = None) -> tuple[bool, str]:
    import_name = import_name or name
    try:
        importlib.import_module(import_name)
        return True, f"✅ {name}"
    except ImportError as exc:
        return False, f"❌ {name}: {exc}"


def main() -> int:
    print("=" * 60)
    print("Checking MCPRuntime example prerequisites")
    print("=" * 60)
    print()

    required_packages = [
        ("fastmcp", "fastmcp"),
        ("opensandbox", "opensandbox"),
        ("pydantic", "pydantic"),
        ("pyyaml", "yaml"),
        ("typing-extensions", "typing_extensions"),
        ("python-dotenv", "dotenv"),
        ("openai", "openai"),
        ("sentence-transformers", "sentence_transformers"),
        ("numpy", "numpy"),
    ]

    missing: list[str] = []
    for package_name, import_name in required_packages:
        installed, message = check_package(package_name, import_name)
        print(message)
        if not installed:
            missing.append(package_name)

    print()
    print("=" * 60)
    print("Checking project modules")
    print("=" * 60)
    print()

    module_checks = [
        ("mcpruntime", None),
        ("mcpruntime.core", None),
        ("mcpruntime.context", None),
        ("mcpruntime.skills", None),
        ("client.agent_helper", "AgentHelper"),
        ("client.opensandbox_executor", "OpenSandboxExecutor"),
        ("config.loader", "load_config"),
    ]

    for module_name, attr in module_checks:
        try:
            module = importlib.import_module(module_name)
            if attr is not None:
                getattr(module, attr)
            suffix = f'.{attr}' if attr else ''
            print(f"✅ {module_name}{suffix}")
        except (ImportError, AttributeError) as exc:
            suffix = f'.{attr}' if attr else ''
            print(f"❌ {module_name}{suffix}: {exc}")
            missing.append(f"{module_name}{suffix}")

    print()
    print("=" * 60)
    print("Checking repository directories")
    print("=" * 60)
    print()

    root = Path(__file__).resolve().parent.parent
    for rel in ["servers", "workspace", "skills", "examples"]:
        path = root / rel
        print(f"{rel}: {'✅' if path.exists() else '⚠'} {path}")

    print()
    print("=" * 60)
    if missing:
        print(f"❌ Setup incomplete: {len(missing)} issue(s) found")
        print("Install missing packages with:")
        print("  pip install -e .[dev]")
        print("  pip install opensandbox opensandbox-server")
        return 1

    print("✅ All checks passed")
    print("Examples should run once Docker and opensandbox-server are available.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
