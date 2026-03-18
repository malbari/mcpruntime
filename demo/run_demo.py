#!/usr/bin/env python3
"""
MCPRuntime — Demo batch
=======================

Esegue tutti i prompt definiti in ``test-prompts.txt`` usando il PTC Agent.
Questo file contiene **solo** logica di demo/test; tutta la logica dell'agent
è in ``ptc_agent.py`` (riutilizzabile da server web o chat conversazionale).
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Silence HuggingFace/sentence-transformers noise before any import triggers them
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# ── Bootstrap path ─────────────────────────────────────────────────────────
_DEMO_DIR = Path(__file__).parent.resolve()
_ROOT = _DEMO_DIR.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_DEMO_DIR / ".env")

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("demo")
logging.getLogger("mcp.client.streamable_http").setLevel(logging.WARNING)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logging.getLogger("transformers").setLevel(logging.ERROR)

# ── Config ───────────────────────────────────────────────────────────────────
TEST_PROMPTS_FILE = _DEMO_DIR / "test-prompts.txt"
SKILLS_FILE = _DEMO_DIR / "SKILLS.md"
SERVERS_FILE = _DEMO_DIR / "servers.json"

SERVERS_CONFIG: list[dict] = json.loads(SERVERS_FILE.read_text(encoding="utf-8"))["servers"]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_prompts() -> list[str]:
    """Legge test-prompts.txt e restituisce le righe attive (ignora vuote e commenti)."""
    lines = TEST_PROMPTS_FILE.read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]


# ── Main ─────────────────────────────────────────────────────────────────────

async def main() -> None:
    """Cicla su tutti i prompt in test-prompts.txt, separando ogni test con un divisore."""
    from ptc_agent import startup, handle_prompt, shutdown

    prompts = _load_prompts()
    if not prompts:
        logger.warning("Nessun prompt trovato in %s — esco.", TEST_PROMPTS_FILE)
        return

    SEP = "=" * 120

    state = await startup(
        servers_config=SERVERS_CONFIG,
        skills_path=SKILLS_FILE,
    )
    try:
        for idx, prompt in enumerate(prompts, start=1):
            logger.info(SEP)
            logger.info("TEST %d/%d: %s", idx, len(prompts), prompt)
            logger.info(SEP)
            result = await handle_prompt(state, prompt)
            if result and result.strip():
                print("\n" + result.strip() + "\n", flush=True)
            logger.info("Fine TEST %d/%d", idx, len(prompts))
    finally:
        shutdown(state)
        logger.info(SEP)
        logger.info("Demo completata — %d prompt eseguiti.", len(prompts))
        logger.info(SEP)


if __name__ == "__main__":
    asyncio.run(main())
