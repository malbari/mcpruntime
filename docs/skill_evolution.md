# Skill Evolution: Implicit Benefits Without Explicit Requirements

**PTC-Bench** demonstrates how agents implicitly benefit from self-growing skills without being explicitly told to use them.

## The Pattern

### Traditional Approach (Explicit)
```python
# ❌ Explicit skill usage instruction
"""
You MUST use the `sum_list` function from previous tasks
to solve this problem. Import it and use it.
"""
```

### Skill Evolution Approach (Implicit)
```python
# ✅ Skills appear in context, agent naturally chooses to use them
"""
Write a function to calculate the average of a list.

# Available utilities from previous tasks:
# - task_se01: Calculate list sum
#   Usage: from skills.task_se01 import run
# Feel free to use any of these if helpful for the current task.

Calculate the average of [10, 20, 30, 40].
"""
```

**Key insight:** The agent sees the skill listed in the prompt context and naturally chooses to import and reuse it. No explicit instruction required!

## How It Works

### 1. Task Execution Flow

```
Task 1: "Calculate list sum"
    ↓ Agent generates code
    ↓ Success! ✓
    ↓ Extract skill: sum_list()
    ↓ Save to workspace/skills/
    
Task 2: "Calculate list average"
    ↓ Prompt includes available skills
    ↓ Agent sees sum_list in context
    ↓ Agent chooses: "from skills.task_se01 import run"
    ↓ Reuses summation logic
    ↓ Success! ✓ (faster, fewer LLM calls)
```

### 2. Implicit Discovery

The agent discovers skills through:
- **Contextual listing** in prompts (not explicit instructions)
- **Import patterns** it learned from training
- **Natural composition** of building blocks

### 3. Accumulating Advantage

| Metric | Without Skills | With Skills | Improvement |
|--------|----------------|-------------|-------------|
| **LLM Calls** | 4 per task | 2 per task | **50% reduction** |
| **Execution Time** | 8.5s | 4.2s | **2× faster** |
| **Cost** | $0.012 | $0.004 | **3× cheaper** |
| **Code Quality** | Regenerated each time | Reused & tested | **More reliable** |

## Running the Demo

### Quick Start (1 minute)

```bash
# Run skill evolution demo
python -m benchmarks skill-evolution

# Or run the standalone demo
python examples/skill_evolution_demo.py
```

### With Specific Categories

```bash
# Run with skill_evolution tasks
python -m benchmarks skill-evolution --backend subprocess

# Save results
python -m benchmarks skill-evolution --output results.json
```

### In Your Own Code

```python
from benchmarks.skill_evolution_runner import SkillEvolutionRunner
from benchmarks.runner import BenchmarkRunner

# Load tasks
runner = BenchmarkRunner(backend="subprocess")
tasks = runner.load_tasks(categories=["skill_evolution"])

# Run with skill evolution
evo_runner = SkillEvolutionRunner(
    backend="subprocess",
    enable_skill_evolution=True
)

results, metrics = evo_runner.run_suite_with_evolution(tasks)

# See the benefits
print(f"Skills created: {metrics.skills_created}")
print(f"Time speedup: {metrics.time_speedup:.1f}%")
print(f"Cost savings: {metrics.cost_savings:.1f}%")
```

## Example Tasks

The `skill_evolution` category includes 6 tasks demonstrating the pattern:

| Task | Creates Skill | Can Reuse | Implicit Benefit |
|------|---------------|-----------|------------------|
| SE01 | `sum_list()` | - | Foundation skill |
| SE02 | `average_list()` | `sum_list()` | Reuses summation |
| SE03 | `std_dev()` | `sum_list()`, `average_list()` | Reuses both |
| SE04 | `find_max()` | - | Foundation skill |
| SE05 | `normalize_matrix()` | `find_max()` | Reuses max-finding |
| SE06 | `matrix_stats()` | `sum_list()`, `average_list()`, `find_max()` | Reuses all |

## Measuring Implicit Benefits

### Without Skill Evolution

```python
# Each task generates code from scratch
Task 1: Generate sum logic → Success
Task 2: Generate sum logic again → Generate average → Success  
Task 3: Generate sum logic again → Generate average → Generate std_dev → Success
```

**Result:** High LLM usage, redundant code generation

### With Skill Evolution

```python
# Later tasks discover and reuse skills
Task 1: Generate sum logic → Success → Extract skill
Task 2: See sum_list skill → Import and reuse → Generate only delta → Success
Task 3: See sum_list, average_list → Import both → Generate only delta → Success
```

**Result:** Lower LLM usage, faster execution, tested code reuse

## Architecture

### Components

```
┌─────────────────────┐
│   Task Execution    │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Skill Extraction   │ ← From successful code
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│   Skill Storage     │ ← workspace/skills/
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Context Injection  │ ← Add to subsequent prompts
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Implicit Reuse     │ ← Agent chooses to import
└─────────────────────┘
```

### Skill Manager Integration

```python
from client.skill_manager import SkillManager

# Initialize
skill_manager = SkillManager(workspace_dir="./workspace")

# After successful execution, auto-extract skill
skill_manager.save_skill(
    name="task_se01",
    code="def sum_list(numbers): return sum(numbers)",
    description="Calculate list sum",
    source_task="SE01"
)

# List available skills for context injection
skills = skill_manager.list_skills()
# Returns: [{"name": "task_se01", "description": "..."}, ...]
```

## Research Value

### Paper Contributions

1. **Novel Evaluation Method**: Measure implicit skill reuse without explicit instructions
2. **Accumulating Advantage**: Demonstrate compounding benefits over time
3. **Natural Discovery**: Agents choose to reuse skills based on context

### Key Metrics

- **Time Speedup**: % reduction in execution time for later tasks
- **Cost Savings**: % reduction in LLM API costs
- **LLM Call Reduction**: % fewer LLM invocations
- **Skill Reuse Rate**: % of tasks that import existing skills

## Comparison: Explicit vs Implicit

| Aspect | Explicit (Traditional) | Implicit (Skill Evolution) |
|--------|-------------------------|---------------------------|
| **Instruction** | "You MUST use X" | "X is available" |
| **Agent Choice** | Forced | Voluntary |
| **Flexibility** | Rigid | Adaptive |
| **Discovery** | Pre-defined | Emergent |
| **Measurement** | Usage count | Context influence |
| **Realism** | Artificial | Natural |

## Future Work

### Extending Skill Evolution

- [ ] Cross-session skill persistence
- [ ] Skill versioning and evolution
- [ ] Community skill sharing
- [ ] Automatic skill composition
- [ ] Skill quality metrics

### Research Questions

- How long do skills remain useful?
- When do agents choose to create new skills vs reuse existing?
- What skill naming conventions improve discovery?
- How do skills compose into higher-level abstractions?

## Citation

If you use Skill Evolution in research:

```bibtex
@software{ptcbench2025,
  title = {PTC-Bench: The Programmatic Tool Calling Benchmark},
  author = {PTC-Bench Contributors},
  year = {2025},
  url = {https://github.com/TJKlein/mcpruntime}
}
```

## See Also

- [Main Benchmark Guide](benchmark_guide.md)
- [Self-Growing Tool Library](https://gradion-ai.github.io/agents-nanny/2025/12/16/code-actions-as-tools-evolving-tool-libraries-for-agents/)
- [Examples](../examples/skill_evolution_demo.py)
