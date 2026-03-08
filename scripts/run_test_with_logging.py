#!/usr/bin/env python3
"""Run a simple OpenSandbox execution with detailed logging."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

log_file = Path('/tmp/test_run.log')
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from client.opensandbox_executor import OpenSandboxExecutor
from config.loader import load_config


def main() -> int:
    logger.info('=' * 60)
    logger.info('Starting OpenSandbox logging test')
    logger.info('=' * 60)

    config = load_config()
    executor = OpenSandboxExecutor(
        execution_config=config.execution,
        guardrail_config=config.guardrails,
        optimization_config=config.optimizations,
    )

    code = """
from pathlib import Path
p = Path('/workspace/test_with_logging.txt')
p.write_text('hello from opensandbox', encoding='utf-8')
print(p.read_text(encoding='utf-8'))
"""

    result, output, error = executor.execute(code)
    logger.info('Result: %s', result)
    logger.info('Output: %s', output)
    logger.info('Error: %s', error)
    logger.info('Full log saved to: %s', log_file)
    return 0 if error is None else 1


if __name__ == '__main__':
    raise SystemExit(main())
