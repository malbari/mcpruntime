"""
Skill Evolution Demo: Implicit Benefits Without Explicit Requirements

This demo shows how tasks naturally benefit from self-growing skills:
1. Early tasks create foundational skills (summation, max-finding)
2. Later tasks see these skills in context and choose to reuse them
3. No explicit instruction to "use skills" - agent discovers and imports naturally
4. Measurable speedup: fewer LLM calls, lower cost, faster execution

Run: python examples/skill_evolution_demo.py
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmarks.skill_evolution_runner import run_skill_evolution_demo
from benchmarks.runner import BenchmarkRunner


def main():
    print("="*70)
    print("🎓 SKILL EVOLUTION DEMO")
    print("="*70)
    print("""
This demo shows how tasks implicitly benefit from self-growing skills:

1️⃣  First tasks: Create foundational skills (sum, max, etc.)
2️⃣  Later tasks: See available skills in context, naturally reuse them
3️⃣  Result: Fewer LLM calls, lower cost, faster execution

Key insight: The agent is NOT explicitly told to "use skills".
Skills appear in the prompt context, and the agent naturally chooses
to import and reuse them. This is the "accumulating advantage" pattern.
""")
    
    # Load skill evolution tasks
    runner = BenchmarkRunner(backend="subprocess", n_runs=1)
    tasks = runner.load_tasks(categories=["skill_evolution"])
    
    if not tasks:
        print("❌ No skill_evolution tasks found!")
        print("   Make sure benchmarks/tasks/skill_evolution/tasks.json exists")
        return
    
    print(f"\n📋 Loaded {len(tasks)} tasks:")
    for i, task in enumerate(tasks, 1):
        print(f"   {i}. {task.id}: {task.name}")
        if "foundation" in task.tags:
            print(f"      └─ Creates foundational skill")
        elif "reuse" in task.tags:
            print(f"      └─ Can reuse previous skills")
    
    print("\n" + "="*70)
    print("🚀 RUNNING WITH SKILL EVOLUTION ENABLED")
    print("="*70)
    print("Skills will be:\n  • Extracted from successful tasks\n  • Made available to subsequent tasks\n  • Implicitly reused when beneficial\n")
    
    # Run with skill evolution
    input("Press Enter to start the demo...")
    print()
    
    metrics = run_skill_evolution_demo(tasks, backend="subprocess")
    
    # Detailed breakdown
    print("\n" + "="*70)
    print("📊 DETAILED BREAKDOWN")
    print("="*70)
    
    print("\nTask-by-task results:")
    print(f"{'Task':<8} {'Success':<8} {'Time':<10} {'Skills':<8} {'Notes'}")
    print("-"*60)
    
    for tm in metrics.task_results:
        task_num = tm['task_number']
        success = "✅" if tm['success'] else "❌"
        time_val = f"{tm['total_time']:.2f}s"
        skills = tm['skills_available']
        notes = ""
        
        if task_num == 1:
            notes = "(Baseline - no skills)"
        elif skills > 0:
            if tm.get('new_skill_created'):
                notes = f"(+New skill, {skills-1} available)"
            else:
                notes = f"(Can reuse {skills} skills)"
        
        print(f"{tm['task_id']:<8} {success:<8} {time_val:<10} {skills:<8} {notes}")
    
    # Key insights
    print("\n" + "="*70)
    print("💡 KEY INSIGHTS")
    print("="*70)
    
    if metrics.time_speedup > 0:
        print(f"\n⏱️  TIME: Later tasks were {metrics.time_speedup:.1f}% faster")
        print("   Why? Agents reused skills instead of regenerating logic")
    
    if metrics.cost_savings > 0:
        print(f"\n💰 COST: {metrics.cost_savings:.1f}% savings from skill reuse")
        print("   Why? Fewer LLM calls needed when reusing existing skills")
    
    if metrics.llm_call_reduction > 0:
        print(f"\n🤖 LLM CALLS: {metrics.llm_call_reduction:.1f}% reduction")
        print("   Why? Skill reuse means less code generation per task")
    
    print(f"\n📚 SKILL CATALOG ({metrics.skills_created} skills):")
    for skill in metrics.skill_catalog[:5]:  # Show first 5
        print(f"   • {skill['name']}: {skill.get('description', 'No description')}")
    
    print("\n" + "="*70)
    print("✨ DEMO COMPLETE")
    print("="*70)
    print("""
The agent never received explicit instructions like:
   ❌ "Use skills from previous tasks"
   ❌ "Import the sum_list function"
   ❌ "Check available utilities"

Instead, skills were simply listed in the prompt context:
   ✓ "# Available utilities from previous tasks:"
   ✓ "# - task_se01: Calculate list sum"
   ✓ "#   Usage: from skills.task_se01 import run"

The agent naturally chose to import and reuse them - this is
implicit skill evolution at work!
""")


if __name__ == "__main__":
    main()
