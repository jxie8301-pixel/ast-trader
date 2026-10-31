"""schema_validator —— 契约层校验器。

借鉴上游 `scripts/verdict_block.py` 的做法：`Draft202012Validator` +
`referencing.Registry` 把 `core/schemas/` 下全部 schema 注册，使跨文件
`$ref` 按**文件名**解析（`common.schema.json#/$defs/judgment`）。

**与上游的差别（不照抄）**：
· 上游只校验节点 md **顶部的 YAML 块**，因为它的产物是 markdown 研报；
  本项目没有 md 中间产物，决断卡与 AI 输出都是 dict，所以直接校验 dict。
· 上游把校验埋在 `manifest.save()` 里；这里做成独立的**叶子层**模块，
  lint 与 AI 协处理器都可调用，不产生反向依赖。

**刻意不写死业务阈值**：仓位上限、涨跌幅门槛等属于 `config.py` 与 Lint R12
的职责。把它们再抄一份进 Schema 就构成阈值双写 —— 那本身就是对「数字唯一
出处」的违反，改了一处漏一处。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"

__all__ = [
    "SchemaError", "SchemaNotFoundError",
    "available_schemas", "load_schema", "validate", "validate_or_raise",
    "SCHEMA_DIR",
]


class SchemaError(ValueError):
    """契约校验失败。调用方应据此降级/弃权，而不是抛出后中断整条流水线。"""


class SchemaNotFoundError(SchemaError):
    """请求的 schema 不存在（名字拼错 / 文件未放对目录）。"""


def available_schemas() -> tuple[str, ...]:
    """列出 `core/schemas/` 下全部 schema 文件名（如 `decision_card.schema.json`）。"""
    if not SCHEMA_DIR.is_dir():
        return ()
    return tuple(sorted(p.name for p in SCHEMA_DIR.glob("*.schema.json")))


@lru_cache(maxsize=1)
def _registry() -> Registry:
    """把目录下全部 schema 注册进一个 Registry，供跨文件 `$ref` 解析。

    以**文件名**为资源 key —— 与 schema 里的 `$id` 保持一致，
    因此 `$ref: "common.schema.json#/$defs/x"` 能被正确解析。
    """
    pairs: list[tuple[str, Resource]] = []
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        pairs.append((path.name, Resource.from_contents(data, default_specification=DRAFT202012)))
    return Registry().with_resources(pairs)


@lru_cache(maxsize=None)
def load_schema(schema_name: str) -> dict[str, Any]:
    """按文件名加载 schema（可传 `decision_card` 或 `decision_card.schema.json`）。"""
    name = schema_name if schema_name.endswith(".schema.json") else f"{schema_name}.schema.json"
    path = SCHEMA_DIR / name
    if not path.is_file():
        raise SchemaNotFoundError(
            f"未找到 schema: {schema_name}（可用: {', '.join(available_schemas())}）"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _json_path(err: Any) -> str:
    """把校验错误的定位路径渲染成 `$.a.b[0]` 形式，便于直接定位到字段。"""
    out = "$"
    for part in err.absolute_path:
        out += f"[{part!r}]" if isinstance(part, int) else f".{part}"
    return out


def validate(payload: Any, schema_name: str) -> list[str]:
    """校验 `payload`，返回**错误列表**；空列表表示合法。

    刻意返回 `list[str]` 而非抛异常：调用方（lint / AI 守卫）通常是「收集全部
    问题后一起报」，而不是「遇到第一个就炸」。需要中断语义时用
    `validate_or_raise`。
    """
    schema = load_schema(schema_name)
    validator = Draft202012Validator(schema, registry=_registry())
    errors = []
    for err in sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path)):
        path = _json_path(err)
        errors.append(f"{path}: {err.message}")
    return errors


def validate_or_raise(payload: Any, schema_name: str) -> None:
    """校验失败即抛 `SchemaError`，错误信息含全部违规项。"""
    errors = validate(payload, schema_name)
    if errors:
        raise SchemaError(
            f"契约校验未通过（{schema_name}），共 {len(errors)} 项:\n  - "
            + "\n  - ".join(errors)
        )
