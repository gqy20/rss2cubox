#!/usr/bin/env python
"""
enrich_agent 和 global_agent 本地测试脚本
用法: python scripts/test_agents.py [--enrich] [--global]
      --enrich  仅测试 enrich_agent
      --global  仅测试 global_agent
      不带参数则两个都测试
"""
import argparse
import os
import sys
import time
from datetime import datetime


def print_header(title: str) -> None:
    print("\n" + "=" * 60)
    print(f"[{datetime.now().isoformat()}] {title}")
    print("=" * 60)


def print_section(title: str) -> None:
    print(f"\n{'─' * 40}")
    print(f"  {title}")
    print(f"{'─' * 40}")


def check_env_vars(vars_to_check: list[str]) -> None:
    """检查环境变量"""
    print("\n[ENV] 检查环境变量...")
    for var in vars_to_check:
        val = os.getenv(var, "(未设置)")
        if "KEY" in var and val and val != "(未设置)":
            val = val[:8] + "..." if len(val) > 8 else "***"
        print(f"  {var}: {val}")


def test_enrich_agent() -> bool:
    """测试 enrich_agent"""
    print_header("enrich_agent 测试")

    check_env_vars([
        "ANTHROPIC_API_KEY",
        "ENRICH_AGENT_ENABLED",
        "ENRICH_MAX_WORKERS",
        "ENRICH_MIN_SCORE",
        "ENRICH_MAX_ITEMS",
        "ENRICH_ITEM_TIMEOUT_SECONDS",
        "ENRICH_MAX_BUDGET_USD",
    ])

    # 导入模块
    print("\n[IMPORT] 导入模块...")
    start = time.perf_counter()
    try:
        from rss2cubox import enrich_agent
        import anyio
        print(f"  ✓ enrich_agent 导入成功 ({time.perf_counter() - start:.2f}s)")
    except ImportError as e:
        print(f"  ✗ 导入失败: {e}")
        return False

    # 显示配置
    print("\n[CONFIG] enrich_agent 配置:")
    print(f"  ENRICH_AGENT_ENABLED: {enrich_agent.ENRICH_AGENT_ENABLED}")
    print(f"  ENRICH_MAX_WORKERS: {enrich_agent.ENRICH_MAX_WORKERS}")
    print(f"  ENRICH_MIN_SCORE: {enrich_agent.ENRICH_MIN_SCORE}")
    print(f"  ENRICH_MAX_ITEMS: {enrich_agent.ENRICH_MAX_ITEMS}")
    print(f"  ENRICH_ITEM_TIMEOUT_SECONDS: {enrich_agent.ENRICH_ITEM_TIMEOUT_SECONDS}")
    print(f"  ENRICH_MAX_BUDGET_USD: {enrich_agent.ENRICH_MAX_BUDGET_USD}")

    # 测试数据
    item = {
        'eid': 'test_enrich_001',
        'url': 'https://arxiv.org/abs/2603.03482',
        'title': 'PERSIST: Persistent 3D Scene Generation',
        'description': 'A new approach to world models with 3D scene persistence.',
    }
    original = {'score': 0.92, 'core_event': 'Initial analysis of PERSIST paper'}

    print("\n[INPUT] 测试输入:")
    print(f"  eid: {item['eid']}")
    print(f"  url: {item['url']}")
    print(f"  title: {item['title']}")

    # 运行测试
    print("\n[RUN] 执行 _enrich_one...")
    run_start = time.perf_counter()
    try:
        result, reason = anyio.run(enrich_agent._enrich_one, item, original)
    except Exception as e:
        print(f"\n[ERROR] 执行异常: {type(e).__name__}: {e}")
        return False

    elapsed = time.perf_counter() - run_start
    print(f"\n[DONE] 完成 (耗时: {elapsed:.2f}s)")
    print(f"  reason: {reason}")

    if result:
        print("\n[OUTPUT] 解析结果:")
        for key in ['core_event', 'hidden_signal', 'actionable', 'score']:
            val = result.get(key, '(空)')
            if isinstance(val, str) and len(val) > 80:
                val = val[:80] + "..."
            print(f"  {key}: {val}")

        has_content = any([result.get('core_event'), result.get('hidden_signal'), result.get('actionable')])
        print("\n✅ enrich_agent 测试通过" if has_content else "\n⚠️ enrich_agent 测试警告 - 结果字段为空")
        return has_content
    else:
        print(f"\n❌ enrich_agent 测试失败 - reason: {reason}")
        return False


def test_global_agent() -> bool:
    """测试 global_agent"""
    print_header("global_agent 测试")

    check_env_vars(["ANTHROPIC_API_KEY", "GLOBAL_AGENT_ENABLE_SKILLS"])

    # 导入模块
    print("\n[IMPORT] 导入模块...")
    start = time.perf_counter()
    try:
        from rss2cubox import global_agent
        import anyio
        print(f"  ✓ global_agent 导入成功 ({time.perf_counter() - start:.2f}s)")
    except ImportError as e:
        print(f"  ✗ 导入失败: {e}")
        return False

    # 显示配置
    print("\n[CONFIG] global_agent 配置:")
    print(f"  GLOBAL_AGENT_ENABLE_SKILLS: {global_agent.GLOBAL_AGENT_ENABLE_SKILLS}")
    print(f"  JINA_MAX_CHARS: {global_agent.JINA_MAX_CHARS}")

    # 测试数据
    high_value_items = [
        {
            "url": "https://arxiv.org/abs/2603.03482",
            "title": "PERSIST: Persistent 3D Scene Generation",
            "hidden_signal": "世界模型从2D时序生成转向3D状态持久化建模",
            "core_event": "Cornell团队提出PERSIST框架实现持久化世界模型",
            "score": 0.94,
        },
        {
            "url": "https://arxiv.org/abs/2603.01234",
            "title": "New Advances in Transformer Architecture",
            "hidden_signal": "Transformer架构持续演进，效率提升显著",
            "core_event": "研究团队发布新型高效Transformer变体",
            "score": 0.91,
        },
        {
            "url": "https://blog.openai.com/new-model-release",
            "title": "OpenAI Releases New Model",
            "hidden_signal": "模型能力边界再次扩展",
            "core_event": "OpenAI发布新一代大语言模型",
            "score": 0.89,
        },
    ]

    print(f"\n[INPUT] 测试输入: {len(high_value_items)} 条高价值情报")
    for i, item in enumerate(high_value_items, 1):
        print(f"  {i}. [{item['score']:.2f}] {item['title'][:50]}...")

    # 运行测试
    print("\n[RUN] 执行 _run_agent...")
    run_start = time.perf_counter()
    try:
        result = anyio.run(global_agent._run_agent, high_value_items)
    except Exception as e:
        print(f"\n[ERROR] 执行异常: {type(e).__name__}: {e}")
        return False

    elapsed = time.perf_counter() - run_start
    print(f"\n[DONE] 完成 (耗时: {elapsed:.2f}s)")

    if result:
        print("\n[OUTPUT] 分析报告:")
        for field, icon in [('trends', '📈'), ('weak_signals', '🔍'), ('daily_advices', '💡')]:
            items = result.get(field, [])
            print(f"\n  {icon} {field} ({len(items)} 条):")
            for i, item in enumerate(items, 1):
                text = item[:70] + "..." if len(item) > 70 else item
                print(f"    {i}. {text}")

        has_content = any([result.get('trends'), result.get('weak_signals'), result.get('daily_advices')])
        print("\n✅ global_agent 测试通过" if has_content else "\n⚠️ global_agent 测试警告 - 结果字段为空")
        return has_content
    else:
        print("\n❌ global_agent 测试失败 - 未获取到有效报告")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="测试 enrich_agent 和 global_agent")
    parser.add_argument("--enrich", action="store_true", help="仅测试 enrich_agent")
    parser.add_argument("--global", dest="global_test", action="store_true", help="仅测试 global_agent")
    args = parser.parse_args()

    # 如果没有指定任何参数，则两个都测试
    test_both = not args.enrich and not args.global_test

    results = {}

    if args.enrich or test_both:
        results["enrich_agent"] = test_enrich_agent()

    if args.global_test or test_both:
        results["global_agent"] = test_global_agent()

    # 汇总结果
    print_header("测试汇总")
    for name, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {name}: {status}")

    all_passed = all(results.values())
    print("\n" + "=" * 60)
    if all_passed:
        print("全部测试通过 ✅")
    else:
        print("部分测试失败 ❌")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
