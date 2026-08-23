from __future__ import annotations

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from env_loader import load_dotenv


def test_load_dotenv_loads_values_without_overriding_existing_env(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# 注释行会被跳过",
                "DEEPSEEK_API_KEY=from-dotenv",
                "QUOTED_VALUE=\"hello world\"",
                "export EXPORTED_VALUE=enabled",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-process")
    monkeypatch.delenv("QUOTED_VALUE", raising=False)
    monkeypatch.delenv("EXPORTED_VALUE", raising=False)

    loaded_path = load_dotenv(env_file)

    assert loaded_path == env_file.resolve()
    assert os.environ["DEEPSEEK_API_KEY"] == "from-process"
    assert os.environ["QUOTED_VALUE"] == "hello world"
    assert os.environ["EXPORTED_VALUE"] == "enabled"


def test_build_model_adapter_can_read_api_key_from_dotenv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=from-dotenv\n", encoding="utf-8")

    from model import build_model_adapter

    adapter = build_model_adapter({"model": {"provider": "openai_compatible", "name": "demo"}})

    assert adapter.api_key_env == "DEEPSEEK_API_KEY"
    assert adapter.api_key == "from-dotenv"
