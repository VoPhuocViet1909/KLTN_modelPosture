"""
Kiểm tra dữ liệu theo JSON Schema trong thư mục schemas/ (dùng chung với backend Spring ở giai đoạn 3).

Không cần cài thêm thư viện: tự kiểm tra tập con JSON Schema mà các file schema dùng
(type, enum, const, required, properties, additionalProperties, items, minimum, maximum, minLength, maxItems,
format date-time / uuid, allOf, if/then, $ref tới file khác trong schemas/).

  from schema import validate
  errors = validate("event", ev)        # [] nếu hợp lệ
"""
import json
import os
import re
import uuid
from datetime import datetime

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemas")
_cache = {}

_TYPES = {
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "null": lambda v: v is None,
}


def load(name):
    name = name if name.endswith(".json") else f"{name}.schema.json"
    if name not in _cache:
        with open(os.path.join(SCHEMA_DIR, name), encoding="utf-8") as f:
            _cache[name] = json.load(f)
    return _cache[name]


def _fmt_ok(fmt, v):
    if not isinstance(v, str):
        return True
    if fmt == "date-time":
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
            return bool(re.match(r"^\d{4}-\d{2}-\d{2}T", v))
        except ValueError:
            return False
    if fmt == "uuid":
        try:
            uuid.UUID(v)
            return True
        except ValueError:
            return False
    return True


def _check(s, v, path, errs):
    if "$ref" in s:
        return _check(load(s["$ref"]), v, path, errs)
    for sub in s.get("allOf", []):
        _check(sub, v, path, errs)
    if "if" in s:
        probe = []
        _check(s["if"], v, path, probe)
        if not probe and "then" in s:
            _check(s["then"], v, path, errs)
    t = s.get("type")
    if t is not None:
        ts = t if isinstance(t, list) else [t]
        if not any(_TYPES[x](v) for x in ts):
            errs.append(f"{path}: cần kiểu {t}, nhận {type(v).__name__}")
            return
    if "const" in s and v != s["const"]:
        errs.append(f"{path}: phải bằng {s['const']!r}")
    if "enum" in s and v not in s["enum"]:
        errs.append(f"{path}: {v!r} không thuộc {s['enum']}")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in s and v < s["minimum"]:
            errs.append(f"{path}: {v} < {s['minimum']}")
        if "maximum" in s and v > s["maximum"]:
            errs.append(f"{path}: {v} > {s['maximum']}")
    if isinstance(v, str):
        if "minLength" in s and len(v) < s["minLength"]:
            errs.append(f"{path}: chuỗi rỗng")
        if "format" in s and not _fmt_ok(s["format"], v):
            errs.append(f"{path}: sai định dạng {s['format']}")
    if isinstance(v, dict):
        for k in s.get("required", []):
            if k not in v:
                errs.append(f"{path}: thiếu '{k}'")
        props = s.get("properties", {})
        for k, val in v.items():
            if k in props:
                _check(props[k], val, f"{path}.{k}", errs)
            elif isinstance(s.get("additionalProperties"), dict):
                _check(s["additionalProperties"], val, f"{path}.{k}", errs)
    if isinstance(v, list):
        if "maxItems" in s and len(v) > s["maxItems"]:
            errs.append(f"{path}: quá {s['maxItems']} phần tử")
        if "items" in s:
            for i, it in enumerate(v):
                _check(s["items"], it, f"{path}[{i}]", errs)


def validate(name, value):
    """Trả về danh sách lỗi (rỗng nếu hợp lệ)."""
    errs = []
    _check(load(name), value, "$", errs)
    return errs
