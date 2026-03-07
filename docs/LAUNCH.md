# 🚀 Launch Guide for PTC-Bench

Quick reference for announcing PTC-Bench and getting visibility.

**Important:** Numbers shown are *expected* based on benchmark design. Run `python -m benchmarks run --approach both` to measure actual results.

## One-Line Pitches

**For Twitter/X:**
```
🏆 A benchmark for comparing code-first vs JSON-first tool calling.

89 tasks • PTC vs FC • Run in 60 seconds • Empirical answers to "when use which?"

Expected: PTC 2–4× faster for multi-step workflows

→ github.com/TJKlein/mcpruntime
```

**For Hacker News:**
```
Show HN: PTC-Bench – benchmark comparing code-first vs JSON-first tool calling

We built 89 tasks comparing Programmatic Tool Calling (agents generate code that 
calls tools) vs traditional Function Calling (JSON tool calls). 

Design predicts: PTC 2–4× faster for multi-step, but FC wins on simple tasks.

Benchmark: github.com/TJKlein/mcpruntime

Try it: python -m benchmarks run --profile quick
```

**For LinkedIn:**
```
Released PTC-Bench: a systematic benchmark comparing code-first vs JSON-first 
tool calling for AI agents.

Based on benchmark design: For multi-step workflows (3–5 tools), PTC is expected 
to be 2–4× faster and 3–6× cheaper than FC. But FC wins for simple single-tool tasks.

Run it yourself: github.com/TJKlein/mcpruntime
```

**For Papers/Research:**
```
PTC-Bench: A Runtime-First Benchmark Suite for Comparing Programmatic Tool Calling 
vs Traditional Function Calling in LLM Agents

A systematic evaluation framework with 89 tasks comparing code-first (PTC) vs 
JSON-first (FC) agent paradigms. Design predicts PTC achieves 2–4× speedup and 
3–6× cost reduction for multi-step workflows, with trade-offs analyzed.

Code & data: github.com/TJKlein/mcpruntime
Citation: See docs/benchmark_guide.md#citation
```

## Key Numbers (Expected from Benchmark Design)

| Metric | Expected Value | Reason |
|--------|----------------|--------|
| **Speedup** | 2–4× | PTC: 1 LLM call vs FC: 4+ calls for multi-step |
| **Cost savings** | 3–6× | Fewer LLM calls (1 vs 4+) |
| **Success rate (multi-step)** | 92% vs 70% | PTC handles orchestration in code |
| **Tasks** | 89 | Across 7 categories |
| **Time to run** | ~60s | Quick profile (baseline mode) |

**Run it yourself:** `python -m benchmarks run --approach both`

See [full methodology →](benchmark_guide.md)

## Visual Assets

### Static Charts
| Asset | File | Best For |
|-------|------|----------|
| **Main comparison** | `assets/ptc_vs_fc_comparison.png` | Twitter, blog posts |
| **Speedup chart** | `assets/ptc_speedup.png` | HN, technical audiences |
| **Radar chart** | `assets/multi_metric_radar.png` | Papers, presentations |
| **Backend perf** | `assets/backend_performance.png` | Infra discussions |
| **Streaming** | `assets/streaming_comparison.png` | Docs, comparisons |

### Animated GIFs (for engagement)
| Asset | File | Best For |
|-------|------|----------|
| **Streaming demo** | `assets/streaming_demo.gif` (76K) | Twitter, demos, engagement |
| **Speedup animation** | `assets/speedup_animation.gif` (79K) | LinkedIn, "PTC wins" message |
| **Comparison build** | `assets/benchmark_comparison.gif` (632K) | Presentations, blog posts |
| **Radar pulse** | `assets/radar_animated.gif` (110K) | Presentations, looping |

All assets: `assets/` (PNG + SVG + GIF)

## Quick Links to Reference

**Don't duplicate content—link to it:**

| Topic | Link |
|-------|------|
| Full methodology | `docs/benchmark_guide.md` |
| Interpreting results | `benchmarks/RESULTS.md` |
| Skill evolution demo | `docs/skill_evolution.md` |
| Interactive dashboard | `dashboard.py` |
| Citation info | `docs/benchmark_guide.md#citation` |

## 60-Second Try-It-Now

```bash
# One line, no setup, ~60 seconds
pip install mcp-agent-runtime
python -m benchmarks run --backend subprocess --profile quick
```

Or with LLM:
```bash
export OPENAI_API_KEY=...
python -m benchmarks run --backend opensandbox --approach both --output results.md
```

## Where to Post

**High-impact channels:**
- [ ] Hacker News (Show HN)
- [ ] r/LocalLLaMA 
- [ ] Twitter/X thread
- [ ] LinkedIn technical post
- [ ] Papers with Code
- [ ] arXiv (as tech report)

**Timing:** Post Tuesday–Thursday, 9am–12pm EST for max visibility.

## Citation (Ready to Copy)

```bibtex
@software{ptcbench2025,
  title = {PTC-Bench: The Programmatic Tool Calling Benchmark},
  author = {PTC-Bench Contributors},
  year = {2025},
  url = {https://github.com/TJKlein/mcpruntime}
}
```

See [docs/benchmark_guide.md](benchmark_guide.md#citation) for full citation options.

## Checklist Before Launch

- [ ] Hero numbers visible in README first screen (marked as "expected")
- [ ] All visual assets generated (`assets/*.png`, `assets/*.gif`)
- [ ] Animated GIFs created (`python assets/create_gifs.py`)
- [ ] Quick run (`--profile quick`) works in fresh environment
- [ ] Dashboard runs (`streamlit run dashboard.py`)
- [ ] Citation info correct
- [ ] Claims clearly marked as "expected" or "measured"

## Post-Launch Tracking

Monitor these for 48 hours after posting:
- GitHub stars (baseline → 24h → 48h → 1 week)
- HN upvotes and comments
- Twitter/X impressions and engagement
- Benchmark runs (if you add telemetry)

## FAQ for Launch

**Q: Is this just another agent framework?**  
A: No—it's a benchmark for comparing two agent paradigms (PTC vs FC). Results are based on benchmark design; run it yourself to measure actual performance.

**Q: Why should I care about PTC vs FC?**  
A: Based on benchmark design: Wrong choice = potentially 4× slower, 6× more expensive for multi-step workflows. Benchmark helps decide when to use each.

**Q: Are the claims proven or expected?**  
A: Numbers are *expected* based on benchmark design (1 LLM call vs 4+). Run `--approach both` to measure actual results with your LLM provider.

**Q: Can I run this myself?**  
A: Yes—`python -m benchmarks run --profile quick` runs in 60 seconds, no API key needed for baseline mode. Use `--approach both --llm-provider openai` for LLM comparison.

**Q: Is this published?**  
A: Code is open source. Working paper coming. Citation: see docs/benchmark_guide.md#citation

---

**Questions?** Open an issue or see [docs/benchmark_guide.md](benchmark_guide.md)
