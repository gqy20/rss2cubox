#!/usr/bin/env python3
"""独立测试 Global Agent 是否能返回带溯源的新格式输出。"""
import asyncio
import json
import os
import sys

# 确保项目路径在 sys.path 中
sys.path.insert(0, "src")

from rss2cubox.global_agent import _run_agent, GLOBAL_OUTPUT_SCHEMA, SYSTEM_PROMPT


MOCK_HIGH_VALUE_ITEMS = [
    {
        "url": "https://openai.com/index/gpt-4o",
        "title": "GPT-4o 发布：原生多模态推理能力大幅提升",
        "hidden_signal": "多模态推理从辅助功能升级为核心竞争力，将改变 AI Agent 的交互范式",
        "core_event": "OpenAI 发布 GPT-4o，支持原生图像和音频理解",
        "reason": "这是今年最重要的模型能力突破之一",
        "importance_score": 5,
        "novelty_score": 5,
        "signal_type": 1,
        "confidence": 5,
        "evidence_strength": 5,
        "tags": ["GPT-4o", "多模态", "OpenAI"],
        "entities": ["OpenAI", "GPT-4o"],
        "cluster_hint": "多模态推理能力突破",
        "actionable": "关注多模态 API 的集成方式变化",
        "market_stage": 4,
    },
    {
        "url": "https://anthropic.com/news/claude-3-5-sonnet",
        "title": "Anthropic 发布 Claude 3.5 Sonnet，编程能力接近 Opus 级别",
        "hidden_signal": "中端模型能力持续压缩，开发者成本结构可能发生根本性变化",
        "core_event": "Anthropic 推出 Claude 3.5 Sonnet，编码基准测试表现优异",
        "reason": "性价比极高的强模型将加速 AI 工具链普及",
        "importance_score": 4,
        "novelty_score": 4,
        "signal_type": 1,
        "confidence": 4,
        "evidence_strength": 4,
        "tags": ["Claude", "Sonnet", "Anthropic"],
        "entities": ["Anthropic", "Claude"],
        "cluster_hint": "中端模型能力跃升",
        "actionable": "评估是否可以将部分工作流迁移到 Claude 3.5 Sonnet",
        "market_stage": 4,
    },
    {
        "url": "https://deepmind.google/blog/alphaFold3",
        "title": "DeepMind AlphaFold 3 预测蛋白质复合物结构",
        "hidden_signal": "蛋白质结构预测从单体到复合物的跨越，将加速药物发现流程",
        "core_event": "Google DeepMind 发布 AlphaFold 3，可预测蛋白质-小分子复合物结构",
        "reason": "对生物制药行业有重大影响",
        "importance_score": 4,
        "novelty_score": 5,
        "signal_type": 6,
        "confidence": 4,
        "evidence_strength": 4,
        "tags": ["AlphaFold", "DeepMind", "生物计算"],
        "entities": ["Google", "DeepMind", "AlphaFold"],
        "cluster_hint": "AI for Science 落地",
        "actionable": "关注 AlphaFold 3 在实际药物设计项目中的应用案例",
        "market_stage": 3,
    },
]

MOCK_HISTORY = {
    "trends": ["开源大模型定价战愈演愈烈", "Agent 框架竞争进入白热化阶段"],
    "weak_signals": ["某开源框架悄然支持多 Agent 编排"],
    "daily_advices": ["关注 MCP 协议的生态进展"],
}


def log_event(level: str, event: str, **fields) -> None:
    ts = fields.pop("ts", None)
    print(f"[{level}] {event} {json.dumps(fields, ensure_ascii=False)[:200]}")


async def main():
    print("=" * 60)
    print("Global Agent 溯溯源格式独立测试")
    print("=" * 60)
    print(f"\n输入: {len(MOCK_HIGH_VALUE_ITEMS)} 条 mock 候选情报")
    print(f"Schema: {json.dumps(GLOBAL_OUTPUT_SCHEMA, ensure_ascii=False)[:300]}")
    print()

    # 捕获原始 stderr 以诊断模型原始输出
    raw_stderr_lines: list[str] = []

    def capture_stderr(line: str) -> None:
        raw_stderr_lines.append(line)
        print(f"[STDERR] {line.strip()}", end="", flush=True)

    result = await _run_agent(
        high_value_items=MOCK_HIGH_VALUE_ITEMS,
        history_signals=MOCK_HISTORY,
        log_event=log_event,
    )

    print("\n" + "=" * 60)
    if result is None:
        print("❌ 结果: Agent 未返回有效报告 (result=None)")
        return False

    # 检查必要字段
    has_trends = bool(result.get("trends"))
    has_weak = bool(result.get("weak_signals"))
    has_advice = bool(result.get("daily_advices"))

    print(f"✅ Agent 返回了结果")
    print(f"   trends:       {len(result.get('trends', []))} 条")
    print(f"   weak_signals: {len(result.get('weak_signals', []))} 条")
    print(f"   daily_advices: {len(result.get('daily_advices', []))} 条")
    print(f"   key_topics:   {result.get('key_topics', [])}")
    print(f"   confidence:   {result.get('confidence_level', 'N/A')}")

    # 关键：检查溯源字段
    all_have_source = True
    source_stats = {"with_source": 0, "total": 0}

    for field in ("trends", "weak_signals", "daily_advices"):
        items = result.get(field, [])
        if not isinstance(items, list):
            print(f"\n⚠️  {field} 不是数组: {type(items)}")
            continue
        for i, item in enumerate(items):
            source_stats["total"] += 1
            if isinstance(item, dict):
                urls = item.get("source_urls", [])
                titles = item.get("source_titles", [])
                if urls:
                    source_stats["with_source"] += 1
                print(f"   [{field}][{i}] text={str(item.get('text', ''))[:50]}")
                print(f"              source_urls={len(urls)} source_titles={len(titles)}")
                if urls:
                    for j, u in enumerate(urls):
                        t = titles[j] if j < len(titles) else "?"
                        print(f"                → [{j}] {t}")
                        print(f"                   {u}")
            elif isinstance(item, str):
                print(f"   [{field}][{i}] (旧格式string) {item[:60]}")
                all_have_source = False

    print("\n" + "-" * 40)
    total = source_stats["total"]
    with_src = source_stats["with_source"]
    print(f"溯源覆盖率: {with_src}/{total} ({100*with_src/max(total,1):.0f}%)")

    if all_have_source and with_src == total:
        print("✅ 全部条目都携带来源链接 — 新格式正常工作")
    elif with_src > 0:
        print(f"⚠️ 部分条目携带来源链接 ({with_src}/{total})")
    else:
        print("❌ 没有条目携带来源链接 — 可能回退到旧格式或模型未遵循指令")

    return result is not None


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
