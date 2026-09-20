"""prompts/ 注册中心与各 agent 模块的防漂移测试。

迁移完成后，提示词的唯一事实源是项目根 prompts/ 目录。这个文件守住三件事：
1. registry 能加载全部 agent，且共享片段已渲染（无 {shared. 残留）；
2. 曾经靠人工同步、实测已漂移的三处文本（ai_relevance 评分标准、read_webpage
   工具说明、关注方向列表）确实单点共享——防止有人把 yml 改回各写一份；
3. 各 .py 的模块级导出（SYSTEM_PROMPT / *_OUTPUT_SCHEMA）与 registry 同源，
   policy_enrich 的 enum 与 .py 常量同步——防止 schema 在两处再次分叉。
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from rss2cubox import prompt_registry as pr

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

ALL_AGENTS = (
    "enrich",
    "global",
    "signal_cluster",
    "prediction",
    "prediction_review",
    "daily_report",
    "policy_triage",
    "policy_enrich",
)


@pytest.fixture(autouse=True)
def _use_repo_prompts(monkeypatch):
    # 测试进程可能被注入 RSS2CUBOX_PROMPTS_DIR（fail-fast 用例会改它）
    monkeypatch.delenv("RSS2CUBOX_PROMPTS_DIR", raising=False)
    pr.reset_cache()
    yield
    pr.reset_cache()

class TestRegistryLoads:
    def test_all_agents_loadable(self):
        for name in ALL_AGENTS:
            agent = pr.get(name)
            assert agent.system_prompt.strip(), name
            assert isinstance(agent.version, int) and agent.version >= 1, name
            schema = agent.output_schema
            assert schema["type"] == "object", name
            assert isinstance(schema.get("properties"), dict), name

    def test_no_unrendered_shared_refs(self):
        for name in ALL_AGENTS:
            assert "{shared." not in pr.get(name).system_prompt, name

    def test_user_instructions_are_nonempty_strings(self):
        for name in ALL_AGENTS:
            for item in pr.get(name).instructions_list:
                assert isinstance(item, str) and item.strip(), name

    def test_shared_fragments_rendered_into_multiple_prompts(self):
        shared = yaml.safe_load((PROMPTS_DIR / "_shared.yaml").read_text(encoding="utf-8"))
        # ai_relevance 评分标准：policy_triage 与 policy_enrich 必须共享同一段
        assert shared["ai_relevance_scale"] in pr.get("policy_triage").system_prompt
        assert shared["ai_relevance_scale"] in pr.get("policy_enrich").system_prompt
        # read_webpage 工具说明：enrich 与 global 共享
        assert shared["read_webpage_note"] in pr.get("enrich").system_prompt
        assert shared["read_webpage_note"] in pr.get("global").system_prompt
        # 关注方向列表：enrich / global / prediction 共享
        for name in ("enrich", "global", "prediction"):
            assert shared["focus_areas"] in pr.get(name).system_prompt, name

    def test_unknown_agent_raises_keyerror(self):
        with pytest.raises(KeyError):
            pr.get("no_such_agent")


class TestModuleExportsStayInSync:
    """各 agent 模块的导出必须与 registry 同源（policy/__init__ re-export 链路也在内）。"""

    def test_enrich(self):
        from rss2cubox.enrich_agent import ENRICH_OUTPUT_SCHEMA, SYSTEM_PROMPT
        assert SYSTEM_PROMPT == pr.get("enrich").system_prompt
        assert ENRICH_OUTPUT_SCHEMA == pr.get("enrich").output_schema

    def test_global(self):
        from rss2cubox.global_agent import GLOBAL_OUTPUT_SCHEMA, SYSTEM_PROMPT
        assert SYSTEM_PROMPT == pr.get("global").system_prompt
        assert GLOBAL_OUTPUT_SCHEMA == pr.get("global").output_schema

    def test_signal_cluster(self):
        from rss2cubox.signal_cluster_agent import SIGNAL_CLUSTER_OUTPUT_SCHEMA, SYSTEM_PROMPT
        assert SYSTEM_PROMPT == pr.get("signal_cluster").system_prompt
        assert SIGNAL_CLUSTER_OUTPUT_SCHEMA == pr.get("signal_cluster").output_schema

    def test_prediction(self):
        from rss2cubox.prediction_agent import SYSTEM_PROMPT, TREND_PREDICTION_OUTPUT_SCHEMA
        assert SYSTEM_PROMPT == pr.get("prediction").system_prompt
        assert TREND_PREDICTION_OUTPUT_SCHEMA == pr.get("prediction").output_schema

    def test_prediction_review(self):
        from rss2cubox.prediction_review_agent import PREDICTION_REVIEW_OUTPUT_SCHEMA, SYSTEM_PROMPT
        assert SYSTEM_PROMPT == pr.get("prediction_review").system_prompt
        assert PREDICTION_REVIEW_OUTPUT_SCHEMA == pr.get("prediction_review").output_schema

    def test_daily_report(self):
        from rss2cubox.daily_report_agent import DAILY_REPORT_OUTPUT_SCHEMA, SYSTEM_PROMPT
        assert SYSTEM_PROMPT == pr.get("daily_report").system_prompt
        assert DAILY_REPORT_OUTPUT_SCHEMA == pr.get("daily_report").output_schema

    def test_policy_triage(self):
        from rss2cubox.policy.triage_agent import SYSTEM_PROMPT, TRIAGE_OUTPUT_SCHEMA
        assert SYSTEM_PROMPT == pr.get("policy_triage").system_prompt
        assert TRIAGE_OUTPUT_SCHEMA == pr.get("policy_triage").output_schema

    def test_policy_enrich(self):
        from rss2cubox.policy.enrich_agent import POLICY_ENRICH_SCHEMA, SYSTEM_PROMPT
        assert SYSTEM_PROMPT == pr.get("policy_enrich").system_prompt
        assert POLICY_ENRICH_SCHEMA == pr.get("policy_enrich").output_schema

    def test_policy_package_reexports(self):
        from rss2cubox.policy import (
            POLICY_ENRICH_SCHEMA,
            POLICY_ENRICH_SYSTEM_PROMPT,
            POLICY_TRIAGE_SYSTEM_PROMPT,
            TRIAGE_OUTPUT_SCHEMA,
        )
        assert POLICY_ENRICH_SYSTEM_PROMPT == pr.get("policy_enrich").system_prompt
        assert POLICY_TRIAGE_SYSTEM_PROMPT == pr.get("policy_triage").system_prompt
        assert POLICY_ENRICH_SCHEMA == pr.get("policy_enrich").output_schema
        assert TRIAGE_OUTPUT_SCHEMA == pr.get("policy_triage").output_schema


class TestSchemaContractGuards:
    """历史踩坑点固化为断言：这些 schema 细节都是实测教训，迁移后不能静默丢失。"""

    def test_policy_triage_reason_not_required(self):
        # reason 必填会让整批 schema 校验重试至死（error_max_structured_output_retries）
        items = pr.get("policy_triage").output_schema["properties"]["results"]["items"]
        assert "reason" not in items["required"]

    def test_policy_enrich_enums_match_py_constants(self):
        from rss2cubox.policy.enrich_agent import (
            INSTRUMENT_TYPES,
            OBLIGATION_LEVELS,
            POLICY_LINEAGES,
            STAGES,
        )

        props = pr.get("policy_enrich").output_schema["properties"]
        assert props["instrument_type"]["enum"] == INSTRUMENT_TYPES
        assert props["stage"]["enum"] == STAGES
        assert props["obligation_level"]["enum"] == OBLIGATION_LEVELS
        # lineage 的 enum 额外含 null（schema 层表达"不属于任何主线"）
        assert props["policy_lineage"]["enum"] == [*POLICY_LINEAGES, None]

    def test_daily_report_anchor_items_share_schema(self):
        schema = pr.get("daily_report").output_schema
        signal_item = schema["properties"]["trends"]["items"]
        assert signal_item is schema["properties"]["weak_signals"]["items"]
        assert signal_item is schema["properties"]["daily_advices"]["items"]

    def test_signal_cluster_status_enum(self):
        items = pr.get("signal_cluster").output_schema["properties"]["clusters"]["items"]
        assert "signal_type" not in items["properties"]  # 程序从 key 前缀解析
        assert set(items["properties"]["status"]["enum"]) == {
            "new", "warming", "bursting", "cooling", "mature", "invalid",
        }

    def test_prediction_time_fields_not_in_schema(self):
        # 模型生成的时间不可信，由 Python 覆写，所以不进 schema
        items = pr.get("prediction").output_schema["properties"]["predictions"]["items"]
        assert "created_at" not in items["properties"]
        assert "target_start_at" not in items["properties"]


class TestParamPriority:
    """运行参数三层优先级：.env 环境变量 > yml params > 代码默认值。"""

    ENV_KEY = "POLICY_TRIAGE_BATCH_SIZE"

    def test_env_overrides_yml(self, monkeypatch):
        monkeypatch.setenv(self.ENV_KEY, "7")
        assert pr.param("policy_triage", "batch_size", 10, env_var=self.ENV_KEY, minimum=1) == 7

    def test_yml_overrides_default(self, monkeypatch):
        monkeypatch.delenv(self.ENV_KEY, raising=False)
        # policy_triage.yaml 写的是 batch_size: 10，与 default 相同；换一个不相等的
        # default 证明返回值来自 yml 而非 default
        assert pr.param("policy_triage", "batch_size", 999) == 10

    def test_fallback_to_code_default(self, monkeypatch):
        monkeypatch.delenv(self.ENV_KEY, raising=False)
        # yml 没写 min_relevance 的 triage 键 → 用代码 default
        assert pr.param("policy_triage", "no_such_key", 42) == 42

    def test_minimum_clamp(self, monkeypatch):
        monkeypatch.setenv(self.ENV_KEY, "0")
        assert pr.param("policy_triage", "batch_size", 10, env_var=self.ENV_KEY, minimum=1) == 1

    def test_bad_env_falls_back_to_yml(self, monkeypatch):
        monkeypatch.setenv(self.ENV_KEY, "not-a-number")
        # 坏 env 值回退 yml（10）而不是崩溃
        assert pr.param("policy_triage", "batch_size", 10, env_var=self.ENV_KEY, minimum=1) == 10

    def test_float_and_bounds(self, monkeypatch):
        monkeypatch.delenv("SIGNAL_CLUSTER_MIN_LINK_COVERAGE", raising=False)
        assert pr.param("signal_cluster", "min_link_coverage", 0.5, minimum=0.0, maximum=1.0) == 0.9

    def test_module_constants_come_from_param(self):
        """模块级常量的定义必须直接是 param(...) 调用（三层解析的唯一入口）。

        不做运行时值比对：模块常量在首次 import 时求值，而 load_dotenv
        （enrich/daily_report 模块级副作用）的注入时机取决于测试执行顺序，
        「import 时的 env 快照」对断言方不可知。源码断言与值域检查不受此影响。
        """
        import inspect

        from rss2cubox import enrich_agent, global_agent
        from rss2cubox.policy import triage_agent

        for mod, name, floor in (
            (triage_agent, "TRIAGE_BATCH_SIZE", 1),
            (enrich_agent, "ENRICH_MAX_WORKERS", 1),
            (global_agent, "GLOBAL_AGENT_TIMEOUT_SECONDS", 60),
        ):
            src = inspect.getsource(mod)
            assert f"{name} = param(" in src, (mod.__name__, name)
            value = getattr(mod, name)
            assert isinstance(value, int) and value >= floor, (mod.__name__, name, value)

    def test_yml_value_reaches_run_json_agent_defaults(self, monkeypatch):
        """_budget 的 default 来自 param(yml)：env 未设置时预算真实生效（不再是 None）。"""
        from rss2cubox.agent_sdk_runner import _budget

        monkeypatch.delenv("POLICY_TRIAGE_MAX_BUDGET_USD", raising=False)
        default = pr.param("policy_triage", "max_budget_usd", 2.0)
        assert default == 2.0
        assert _budget("POLICY_TRIAGE_MAX_BUDGET_USD", default) == 2.0


class TestFailFast:
    """yml 缺字段 / 悬空共享引用 / 非 object schema → 访问即抛异常，不带病运行。"""

    def _write(self, tmp_path: Path, filename: str, content: str) -> None:
        (tmp_path / filename).write_text(content, encoding="utf-8")

    def test_missing_required_field(self, tmp_path, monkeypatch):
        self._write(tmp_path, "bad_agent.yaml", "version: 1\nsystem_prompt: hello\n")
        monkeypatch.setenv("RSS2CUBOX_PROMPTS_DIR", str(tmp_path))
        pr.reset_cache()
        with pytest.raises(ValueError, match="output_schema"):
            pr.get("bad_agent")

    def test_dangling_shared_ref(self, tmp_path, monkeypatch):
        self._write(
            tmp_path,
            "bad_agent.yaml",
            "version: 1\nsystem_prompt: |-\n  你好 {shared.nope}\noutput_schema:\n  type: object\n  properties: {}\n",
        )
        monkeypatch.setenv("RSS2CUBOX_PROMPTS_DIR", str(tmp_path))
        pr.reset_cache()
        with pytest.raises(ValueError, match="nope"):
            pr.get("bad_agent")

    def test_non_object_schema_rejected(self, tmp_path, monkeypatch):
        self._write(
            tmp_path,
            "bad_agent.yaml",
            "version: 1\nsystem_prompt: hi\noutput_schema:\n  type: string\n",
        )
        monkeypatch.setenv("RSS2CUBOX_PROMPTS_DIR", str(tmp_path))
        pr.reset_cache()
        with pytest.raises(ValueError, match="object"):
            pr.get("bad_agent")

    def test_invalid_version_rejected(self, tmp_path, monkeypatch):
        self._write(
            tmp_path,
            "bad_agent.yaml",
            "version: 0\nsystem_prompt: hi\noutput_schema:\n  type: object\n  properties: {}\n",
        )
        monkeypatch.setenv("RSS2CUBOX_PROMPTS_DIR", str(tmp_path))
        pr.reset_cache()
        with pytest.raises(ValueError, match="version"):
            pr.get("bad_agent")
