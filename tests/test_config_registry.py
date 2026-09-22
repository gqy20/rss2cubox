"""config.py 注册表的防漂移测试。

这个文件是 B 方案的核心保障：不要求一次性重写 10 个模块的读取方式，
但强制要求「代码里读的每个环境变量都必须在 config.REGISTRY 里登记，
且默认值一致」。否则注册表会在几周内重新和代码脱节，变成第二份过期文档。

之前 cluster 超时 300s 这个值只存在于 signal_cluster_agent.py:135 的代码默认值里，
任何配置文件都看不到它 —— 那正是它长期没人发现的原因。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from rss2cubox import config as cfg_mod

SRC = Path(__file__).resolve().parent.parent / "src" / "rss2cubox"
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

# CI 注入的变量不属于应用配置，不要求登记
CI_INJECTED = {"GITHUB_SHA", "GITHUB_REF_NAME", "GITHUB_EVENT_NAME", "GITHUB_RUN_ID",
               "GITHUB_STEP_SUMMARY", "GITHUB_WORKSPACE", "GITHUB_REPOSITORY"}

# 扫描模式：覆盖项目里所有读环境变量的写法
PATTERNS = [
    # os.getenv("NAME", default) / os.getenv("NAME")
    re.compile(r'''os\.getenv\(\s*["']([A-Z][A-Z0-9_]*)["']\s*(?:,\s*(.+?))?\s*\)'''),
    # sync_pipeline.env_int/env_float("NAME", default)
    re.compile(r'''env_(?:int|float)\(\s*["']([A-Z][A-Z0-9_]*)["']\s*,\s*(.+?)\s*\)'''),
    # _budget("NAME", default)
    re.compile(r'''_budget\(\s*["']([A-Z][A-Z0-9_]*)["']\s*,\s*(.+?)\s*\)'''),
    # _agent_timeout("NAME", default=X, minimum=Y)
    re.compile(r'''_agent_timeout\(\s*["']([A-Z][A-Z0-9_]*)["']\s*,\s*default=([^,)]+)'''),
    # os.environ.get("NAME", default) / os.environ["NAME"]
    re.compile(r'''os\.environ\.get\(\s*["']([A-Z][A-Z0-9_]*)["']\s*(?:,\s*(.+?))?\s*\)'''),
    re.compile(r'''os\.environ\[\s*["']([A-Z][A-Z0-9_]*)["']\s*\]'''),
    # 通过注册表读取：cfg.str("NAME") / cfg.int(...) / cfg.get(...) / cfg.is_overridden(...)
    re.compile(r'''cfg\.(?:str|int|float|bool|csv|get|is_overridden)\(\s*["']([A-Z][A-Z0-9_]*)["']'''),
    # 属性式访问：cfg.NAME
    re.compile(r'''\bcfg\.([A-Z][A-Z0-9_]{2,})\b'''),
    # prompt_registry.param(..., env_var="NAME")：yml 参数的 env 覆盖层入口
    re.compile(r'''env_var\s*=\s*["']([A-Z][A-Z0-9_]*)["']'''),
]

# 前 6 个模式带默认值捕获组，后 4 个（environ / cfg.*）不带
_PATTERNS_WITH_DEFAULT = 6


def _scan() -> dict[str, list[tuple[str, str]]]:
    """返回 {变量名: [(默认值源码, 位置), ...]}"""
    found: dict[str, list[tuple[str, str]]] = {}
    roots = [SRC, SCRIPTS]
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="replace")
            for idx, pattern in enumerate(PATTERNS):
                for m in pattern.finditer(text):
                    name = m.group(1)
                    if idx < _PATTERNS_WITH_DEFAULT and m.lastindex and m.lastindex >= 2:
                        default_src = (m.group(2) or "").strip()
                    else:
                        default_src = ""
                    line = text[: m.start()].count("\n") + 1
                    found.setdefault(name, []).append((default_src, f"{path.name}:{line}"))
    return found


def _normalize(default_src: str, kind: str):
    """把源码里的默认值字面量转成可与注册表比较的 Python 值。"""
    src = default_src.strip()
    if not src or src == "None":
        return None
    # 形如 max(1, int(os.getenv(...))) 之类的表达式无法静态比较，跳过
    if not re.fullmatch(r'[-+]?[\d.]+|"[^"]*"|\'[^\']*\'|True|False|None', src):
        return "__expr__"
    try:
        value = ast.literal_eval(src)
    except (ValueError, SyntaxError):
        return "__expr__"
    if kind == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if kind == "int":
        return int(float(value))
    if kind == "float":
        return float(value)
    if kind == "csv":
        if not isinstance(value, str):
            return value
        return [p.strip() for p in value.split(",") if p.strip()]
    return value


SCANNED = _scan()


class TestRegistryCompleteness:
    def test_every_env_var_in_code_is_registered(self) -> None:
        """代码里读的每个变量都必须登记，否则它在任何配置文件里都不可见。"""
        unregistered = sorted(
            f"{name}  ({', '.join(loc for _, loc in hits[:2])})"
            for name, hits in SCANNED.items()
            if name not in cfg_mod.REGISTRY and name not in CI_INJECTED
        )
        assert not unregistered, (
            "以下环境变量被代码读取但未在 config.REGISTRY 登记：\n  "
            + "\n  ".join(unregistered)
        )

    def test_no_registered_setting_is_unused(self) -> None:
        """反向检查：登记了却没人读的项是死配置。"""
        unused = sorted(
            name for name in cfg_mod.REGISTRY
            if name not in SCANNED and name not in CI_INJECTED
        )
        assert not unused, f"注册表里这些项没有任何代码读取: {unused}"


class TestDefaultsMatch:
    """注册表的默认值必须与代码里的字面量一致，否则就有两个事实来源。"""

    @pytest.mark.parametrize("name", sorted(n for n in SCANNED if n in cfg_mod.REGISTRY))
    def test_default_matches_code(self, name: str) -> None:
        setting = cfg_mod.REGISTRY[name]
        for default_src, loc in SCANNED[name]:
            if default_src == "":
                continue  # 该读取点未写默认值（如 os.getenv("X") 或 cfg.str("X")）
            expected = _normalize(default_src, setting.kind)
            if expected == "__expr__":
                continue  # 复杂表达式（如 max(1, int(...))）无法静态比较
            actual = setting.default
            # str 类型下 None 与 "" 等价：两者都表示"未配置"
            if setting.kind == "str" and {actual, expected} <= {None, ""}:
                continue
            if setting.kind == "bool" and isinstance(actual, str):
                actual = actual.strip().lower() in ("1", "true", "yes", "on")
            assert actual == expected, (
                f"{name} 的默认值不一致：config.REGISTRY={actual!r} 但 {loc} 写的是 {expected!r}。"
                f"两边必须改成一个值 —— 注册表是事实来源。"
            )


class TestRegistryShape:
    def test_names_unique(self) -> None:
        assert len({s.name for s in cfg_mod.REGISTRY.values()}) == len(cfg_mod.REGISTRY)

    def test_all_groups_declared(self) -> None:
        declared = {g for g, _ in cfg_mod.GROUPS}
        used = {s.group for s in cfg_mod.REGISTRY.values()}
        assert used <= declared, f"未声明的分组: {used - declared}"
        assert declared == used, f"声明了但没有配置项的分组: {declared - used}"

    def test_kinds_are_valid(self) -> None:
        valid = {"bool", "int", "float", "str", "csv"}
        bad = {n: s.kind for n, s in cfg_mod.REGISTRY.items() if s.kind not in valid}
        assert not bad, f"非法 kind: {bad}"

    def test_every_setting_has_help(self) -> None:
        missing = sorted(n for n, s in cfg_mod.REGISTRY.items() if not s.help.strip())
        assert not missing, f"这些配置项没有说明文字: {missing}"

    def test_help_is_not_just_the_name(self) -> None:
        """说明必须提供名字之外的信息，否则等于没写。"""
        lazy = sorted(
            n for n, s in cfg_mod.REGISTRY.items()
            if s.help.strip().lower() in (n.lower(), n.lower().replace("_", " "))
        )
        assert not lazy, f"这些配置项的说明只是重复了名字: {lazy}"

    def test_required_settings_are_registered(self) -> None:
        assert cfg_mod.REQUIRED <= set(cfg_mod.REGISTRY)


class TestCoercion:
    @pytest.mark.parametrize("raw,expected", [
        ("true", True), ("True", True), ("1", True), ("yes", True), ("on", True),
        ("false", False), ("0", False), ("no", False),
        # 空字符串视为未设置（_raw 把 "" 归一化成 None），因此回退默认值 true。
        # 这与各模块现有的 `os.getenv("X", "true").lower() not in ("false","0","no")` 行为一致。
        ("", True),
    ])
    def test_bool(self, monkeypatch: pytest.MonkeyPatch, raw: str, expected: bool) -> None:
        monkeypatch.setenv("ENRICH_AGENT_ENABLED", raw)
        assert cfg_mod.cfg.bool("ENRICH_AGENT_ENABLED") is expected

    @pytest.mark.parametrize("raw,expected", [("500", 500), ("500.0", 500), (" 300 ", 300)])
    def test_int(self, monkeypatch: pytest.MonkeyPatch, raw: str, expected: int) -> None:
        monkeypatch.setenv("MAX_ITEMS_PER_RUN", raw)
        assert cfg_mod.cfg.int("MAX_ITEMS_PER_RUN") == expected

    def test_int_invalid_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """非法值回退默认而不是崩溃，与 sync_pipeline.env_int 的既有行为一致。"""
        monkeypatch.setenv("MAX_ITEMS_PER_RUN", "abc")
        assert cfg_mod.cfg.int("MAX_ITEMS_PER_RUN") == cfg_mod.REGISTRY["MAX_ITEMS_PER_RUN"].default

    def test_float(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FEED_READ_TIMEOUT_SECONDS", "12.5")
        assert cfg_mod.cfg.float("FEED_READ_TIMEOUT_SECONDS") == 12.5

    def test_csv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FEED_SECTIONS_DISABLE", "twitter, bilibili ,,werss")
        assert cfg_mod.cfg.csv("FEED_SECTIONS_DISABLE") == ["twitter", "bilibili", "werss"]

    def test_csv_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FEED_SECTIONS_DISABLE", raising=False)
        assert cfg_mod.cfg.csv("FEED_SECTIONS_DISABLE") == []

    def test_unset_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SIGNAL_CLUSTER_MAX_ARTICLES", raising=False)
        assert cfg_mod.cfg.int("SIGNAL_CLUSTER_MAX_ARTICLES") == 200
        assert cfg_mod.cfg.is_overridden("SIGNAL_CLUSTER_MAX_ARTICLES") is False

    def test_is_overridden_detects_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SIGNAL_CLUSTER_MAX_ARTICLES", "100")
        assert cfg_mod.cfg.is_overridden("SIGNAL_CLUSTER_MAX_ARTICLES") is True
        assert cfg_mod.cfg.int("SIGNAL_CLUSTER_MAX_ARTICLES") == 100

    def test_attribute_access(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAX_ITEMS_PER_SOURCE", "42")
        assert cfg_mod.cfg.MAX_ITEMS_PER_SOURCE == 42

    def test_unknown_attribute_raises(self) -> None:
        with pytest.raises(AttributeError):
            _ = cfg_mod.cfg.NOT_A_REAL_SETTING

    def test_unregistered_name_still_readable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未登记的变量仍能读到原值（迁移期兼容），但会被完整性测试抓住。"""
        monkeypatch.setenv("SOME_UNREGISTERED_THING", "x")
        assert cfg_mod.cfg.get("SOME_UNREGISTERED_THING") == "x"


class TestMissingRequired:
    def test_reports_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in cfg_mod.REQUIRED:
            monkeypatch.delenv(name, raising=False)
        assert set(cfg_mod.cfg.missing_required()) == set(cfg_mod.REQUIRED)

    def test_partially_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in cfg_mod.REQUIRED:
            monkeypatch.setenv(name, "x")
        monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
        assert cfg_mod.cfg.missing_required() == ["ANTHROPIC_MODEL"]

    def test_none_missing_when_all_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in cfg_mod.REQUIRED:
            monkeypatch.setenv(name, "x")
        assert cfg_mod.cfg.missing_required() == []


class TestMasking:
    def test_credentials_are_masked(self) -> None:
        masked = cfg_mod._mask("ANTHROPIC_AUTH_TOKEN", "sk-3dfiTCQOn1qAxIpgVoQnuSuANDiMZJCLnK8wwdujwpz9KZLe")
        # 只保留头 8 尾 4，中间全部隐藏
        assert masked == "sk-3dfiT\u2026KZLe"
        assert "QOn1qAxIpgVoQnuSuANDiMZJCLnK8wwduj" not in masked

    def test_short_credential_fully_masked(self) -> None:
        assert cfg_mod._mask("ANTHROPIC_AUTH_TOKEN", "sk-12345") == "***"

    def test_local_db_url_is_masked(self) -> None:
        """变量名是 DATABASE_URL 而不是 *_DATABASE_URL，敏感词表必须覆盖到。

        回归：最初敏感词表只写了 DATABASE_URL，导致含密码的 DATABASE_URL
        在 make config 输出里原样泄露。
        """
        masked = cfg_mod._mask("DATABASE_URL", "postgresql://postgres:supersecret@localhost:5434/db")
        assert "supersecret" not in masked

    def test_neon_db_url_is_masked(self) -> None:
        masked = cfg_mod._mask(
            "NEON_DATABASE_URL",
            "postgresql://neondb_owner:npg_SECRETVALUE@ep-x.aws.neon.tech/neondb")
        assert "npg_SECRETVALUE" not in masked

    def test_normal_values_not_masked(self) -> None:
        assert cfg_mod._mask("MAX_ITEMS_PER_RUN", 1500) == "1500"


class TestDescribe:
    def test_describe_lists_all_groups(self) -> None:
        out = cfg_mod.describe()
        for _group, label in cfg_mod.GROUPS:
            assert label in out

    def test_describe_does_not_leak_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        secret = "sk-SUPERSECRETVALUE1234567890abcdef"
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", secret)
        assert secret not in cfg_mod.describe(show_help=True)

    def test_describe_with_help_includes_text(self) -> None:
        out = cfg_mod.describe(show_help=True)
        assert "└" in out
