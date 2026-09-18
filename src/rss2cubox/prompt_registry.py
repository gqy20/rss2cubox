"""提示词注册中心：从项目根 prompts/ 目录加载 yml 管理的 agent 提示词。

边界原则：「给模型的指令」进 yml（system_prompt / user_instructions / output_schema），
「给模型的数据」留在各 agent 的 _build_prompt 代码里（裁剪、分批、索引/文件拆分）。

- prompts/ 下一个 agent 一个 yml 文件，文件名即 agent 名（不含扩展名）
- _shared.yaml 存放跨 agent 共享片段，system_prompt 里用 {shared.片段名} 引用，
  加载时做精确模式插值（只认 {shared.xxx}，其余花括号不动，JSON 示例不受影响）
- 文件顶层 _defs: 可放 YAML 锚点供 output_schema 内部复用（如 daily_report 的
  signal_item），加载后剔除，不进入运行时 schema
- fail-fast：缺文件、缺字段、悬空共享引用、schema 不是 object → 首次访问即抛异常，
  不带病运行
- cron 每次新进程，改 yml 下次运行生效，无需热更新
- 运行参数经 param() 读取：优先级环境变量（.env） > yml params > 代码默认值
  （默认值与 config.REGISTRY 登记一致，test_config_registry 守护这层同步）
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_SHARED_REF = re.compile(r"\{shared\.([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class AgentPrompt:
    name: str
    version: int
    system_prompt: str
    output_schema: dict[str, Any]
    user_instructions: tuple[str, ...] = ()
    description: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def instructions_list(self) -> list[str]:
        """user_instructions 的 list 视图，供 _build_prompt 的 json.dumps 直接使用。"""
        return list(self.user_instructions)


def prompts_dir() -> Path:
    env = os.getenv("RSS2CUBOX_PROMPTS_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "prompts"


def _render(text: str, shared: dict[str, str], ctx: str) -> str:
    missing = [key for key in _SHARED_REF.findall(text) if key not in shared]
    if missing:
        raise ValueError(f"{ctx}: 引用了 _shared.yaml 里不存在的片段 {missing}")
    return _SHARED_REF.sub(lambda m: shared[m.group(1)], text)


def _load_shared(root: Path) -> dict[str, str]:
    path = root / "_shared.yaml"
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: 顶层必须是「片段名: 文本」的映射")
    shared: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{path}: 片段 {key} 必须是非空文本")
        shared[str(key)] = value
    return shared


_REQUIRED_FIELDS = ("version", "system_prompt", "output_schema")


def _load_agent(path: Path, shared: dict[str, str]) -> AgentPrompt:
    name = path.stem
    ctx = str(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx}: 顶层必须是映射")

    for key in _REQUIRED_FIELDS:
        if key not in raw:
            raise ValueError(f"{ctx}: 缺少必需字段 {key}")

    version = raw["version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError(f"{ctx}: version 必须是正整数，当前值 {version!r}")

    system_prompt = _render(str(raw["system_prompt"]), shared, ctx)
    if not system_prompt.strip():
        raise ValueError(f"{ctx}: system_prompt 不能为空")

    output_schema = raw["output_schema"]
    if not isinstance(output_schema, dict) or output_schema.get("type") != "object":
        raise ValueError(f"{ctx}: output_schema 必须是 type=object 的 JSON Schema")

    instructions_raw = raw.get("user_instructions", [])
    if not isinstance(instructions_raw, list):
        raise ValueError(f"{ctx}: user_instructions 必须是字符串列表")
    instructions = tuple(str(item) for item in instructions_raw)
    if any(not item.strip() for item in instructions):
        raise ValueError(f"{ctx}: user_instructions 存在空条目")

    params_raw = raw.get("params", {})
    if not isinstance(params_raw, dict):
        raise ValueError(f"{ctx}: params 必须是标量映射（仅作文档）")

    return AgentPrompt(
        name=name,
        version=version,
        description=str(raw.get("description", "")),
        system_prompt=system_prompt,
        user_instructions=instructions,
        output_schema=output_schema,
        params=dict(params_raw),
    )


@lru_cache(maxsize=None)
def _load_all() -> dict[str, AgentPrompt]:
    root = prompts_dir()
    if not root.is_dir():
        raise FileNotFoundError(f"prompts 目录不存在: {root}")

    shared = _load_shared(root)
    agents: dict[str, AgentPrompt] = {}
    for path in sorted(root.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        agent = _load_agent(path, shared)
        if agent.name in agents:
            raise ValueError(f"prompts 目录里存在同名 agent: {agent.name}")
        agents[agent.name] = agent
    if not agents:
        raise FileNotFoundError(f"prompts 目录里没有 agent 配置: {root}")
    return agents


def get(name: str) -> AgentPrompt:
    """按名字取一个 AgentPrompt。未知名字直接抛 KeyError，fail-fast。"""
    try:
        return _load_all()[name]
    except KeyError:
        available = ", ".join(sorted(_load_all()))
        raise KeyError(f"未注册的 agent prompt: {name}（可用: {available}）") from None


def reset_cache() -> None:
    """清空加载缓存（测试用）。"""
    _load_all.cache_clear()


_MISSING = object()


def _coerce_like(default: Any, raw: Any) -> Any:
    """把 raw 按 default 的类型转换。bool 判断必须在 int 之前（bool 是 int 子类）。"""
    if isinstance(default, bool):
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        return int(float(str(raw).strip()))
    if isinstance(default, float):
        return float(str(raw).strip())
    return str(raw).strip()


def param(
    agent: str,
    key: str,
    default: Any = None,
    *,
    env_var: str | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
) -> Any:
    """读 agent 运行参数，优先级：环境变量（.env 已注入） > yml params[key] > default。

    - default 即代码字面量（与 config.REGISTRY 登记一致），同时决定返回类型：
      int/float 做数值转换并按 minimum/maximum clamp；bool 按真假词表解析；
      str 原样返回
    - env_var 只走 env 层；_budget/_agent_timeout 系调用方自带 env 特殊语义
      （"0"=禁用等），此时不传 env_var、只用 param 提供 yml 层默认值
    - 坏值（env 或 yml 解析失败）回退下一层，坏配置不把进程搞崩
    """
    value: Any = _MISSING
    if env_var:
        raw = os.environ.get(env_var, "")
        if raw.strip():
            try:
                value = _coerce_like(default, raw)
            except (ValueError, TypeError):
                pass  # 坏 env 值 → 回退 yml / default
    if value is _MISSING:
        raw = get(agent).params.get(key)
        if raw is not None:
            try:
                value = _coerce_like(default, raw)
            except (ValueError, TypeError):
                value = _MISSING
    if value is _MISSING:
        value = default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if minimum is not None:
            value = max(value, type(value)(minimum))
        if maximum is not None:
            value = min(value, type(value)(maximum))
    return value
