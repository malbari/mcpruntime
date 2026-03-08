# Scripts

Development and CI helper scripts. Run them from the repository root.

```bash
python scripts/check_setup.py
python scripts/verify_setup.py
python scripts/run_all_examples.py
python scripts/benchmark_pooling.py -n 5
```

- `check_setup.py`: Verify local Python packages and project modules needed for examples.
- `verify_setup.py`: Verify Docker and the OpenSandbox server are ready.
- `run_all_examples.py` / `run_all_examples.sh`: Run the example suite.
- `run_all_tests.sh`, `run_live_tests.sh`: Test runners.
- `run_test_with_logging.py`, `run_tests_and_save.py`: Test runs with logging or saved output.
- `benchmark_pooling.py`: Sandbox pooling benchmarks.
- `verify_examples.py`: Example verification.
- `debug_trial.sh`: Debug helper.

The canonical test suite is `pytest tests/`; see `CONTRIBUTING.md`.
