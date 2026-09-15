"""政策信源配置加载。

配置用 TOML（stdlib tomllib，只读场景够用），避免为配置文件引入 pyyaml。
每个 [[sites]] 是一个站点适配器，加站点只改配置、不改代码。
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LEVELS = frozenset({"national", "province", "city"})
TIERS = frozenset({"requests", "playwright", "rss"})


@dataclass(frozen=True)
class SiteSpec:
    """单个政策信源的抓取配置。"""

    key: str
    name: str
    level: str                      # national | province | city
    region: str                     # 北京 / 浙江 / 全国 ...
    list_url: str
    item_selector: str              # CSS，命中列表项容器
    title_selector: str = "a"       # 相对 item 的 CSS
    title_attr: str = "title"       # 优先取该属性，取不到回退到文本
    url_selector: str = "a"
    url_attr: str = "href"
    date_selector: str = ""         # 留空则从 item 全文里正则提取
    base_url: str = ""              # urljoin 基准，留空则用 list_url
    tier: str = "requests"          # requests | playwright | rss
    enabled: bool = True
    max_items: int = 200
    min_title_length: int = 8       # 过滤导航/装饰性短链接
    title_exclude: tuple[str, ...] = ()   # 标题命中任一子串即丢弃
    note: str = ""

    @property
    def resolve_base(self) -> str:
        return self.base_url or self.list_url


_REQUIRED = ("key", "name", "level", "region", "list_url")
# item_selector 只对 HTML 列表页有意义，rss tier 不需要
_REQUIRED_BY_TIER = {"requests": ("item_selector",), "playwright": ("item_selector",), "rss": ()}


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(p.strip() for p in value.split(",") if p.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(v).strip() for v in value if str(v).strip())
    return ()


def parse_site(raw: dict[str, Any]) -> SiteSpec:
    """把 TOML 里的一张表转成 SiteSpec，缺必填字段或取值非法直接报错。"""
    missing = [k for k in _REQUIRED if not str(raw.get(k, "")).strip()]
    tier_raw = str(raw.get("tier", "requests")).strip().lower()
    missing += [k for k in _REQUIRED_BY_TIER.get(tier_raw, ()) if not str(raw.get(k, "")).strip()]
    if missing:
        raise ValueError(f"站点配置缺少必填字段 {missing}: {raw.get('key', '<无 key>')}")

    level = str(raw["level"]).strip().lower()
    if level not in LEVELS:
        raise ValueError(f"站点 {raw['key']} 的 level={level!r} 非法，应为 {sorted(LEVELS)}")

    tier = tier_raw
    if tier not in TIERS:
        raise ValueError(f"站点 {raw['key']} 的 tier={tier!r} 非法，应为 {sorted(TIERS)}")

    return SiteSpec(
        key=str(raw["key"]).strip(),
        name=str(raw["name"]).strip(),
        level=level,
        region=str(raw["region"]).strip(),
        list_url=str(raw["list_url"]).strip(),
        item_selector=str(raw.get("item_selector", "")).strip(),
        title_selector=str(raw.get("title_selector", "a")).strip() or "a",
        title_attr=str(raw.get("title_attr", "title")).strip(),
        url_selector=str(raw.get("url_selector", "a")).strip() or "a",
        url_attr=str(raw.get("url_attr", "href")).strip() or "href",
        date_selector=str(raw.get("date_selector", "")).strip(),
        base_url=str(raw.get("base_url", "")).strip(),
        tier=tier,
        enabled=_coerce_bool(raw.get("enabled", True), True),
        max_items=_coerce_int(raw.get("max_items", 200), 200),
        min_title_length=_coerce_int(raw.get("min_title_length", 8), 8),
        title_exclude=_coerce_tuple(raw.get("title_exclude")),
        note=str(raw.get("note", "")).strip(),
    )


def load_sources(
    path: str | Path,
    *,
    include_disabled: bool = False,
    only_levels: set[str] | None = None,
    only_keys: set[str] | None = None,
) -> list[SiteSpec]:
    """读取配置文件并按条件筛选站点。

    only_levels / only_keys 为 None 时不做该维度过滤。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"政策信源配置不存在: {p}")

    with p.open("rb") as fh:
        data = tomllib.load(fh)

    raw_sites = data.get("sites")
    if not isinstance(raw_sites, list):
        raise ValueError(f"{p} 里没有 [[sites]] 配置")

    specs: list[SiteSpec] = []
    seen: set[str] = set()
    for raw in raw_sites:
        if not isinstance(raw, dict):
            raise ValueError(f"{p} 里存在非表结构的 [[sites]] 条目: {raw!r}")
        spec = parse_site(raw)
        if spec.key in seen:
            raise ValueError(f"{p} 里站点 key 重复: {spec.key}")
        seen.add(spec.key)
        if not include_disabled and not spec.enabled:
            continue
        if only_levels is not None and spec.level not in only_levels:
            continue
        if only_keys is not None and spec.key not in only_keys:
            continue
        specs.append(spec)
    return specs


def group_by_level(specs: list[SiteSpec]) -> dict[str, list[SiteSpec]]:
    out: dict[str, list[SiteSpec]] = {level: [] for level in ("national", "province", "city")}
    for spec in specs:
        out.setdefault(spec.level, []).append(spec)
    return out
