from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str | Path = ".env", *, override: bool = False) -> Path | None:
    """从 .env 文件加载环境变量；默认不覆盖当前进程已有变量。"""
    env_path = Path(path).resolve()
    if not env_path.exists():
        return None

    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        parsed = _parse_env_line(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        if override or key not in os.environ:
            os.environ[key] = value
    return env_path


def _parse_env_line(raw_line: str) -> tuple[str, str] | None:
    """解析一行最小 .env 语法，支持 KEY=VALUE、export KEY=VALUE 和引号包裹的值。"""
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[len("export ") :].strip()
    if "=" not in line:
        return None

    key, value = line.split("=", 1)
    key = key.strip()
    if not key:
        return None

    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value
