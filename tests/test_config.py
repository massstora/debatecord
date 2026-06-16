from __future__ import annotations

import pytest

from debatecord.config import load_config


def test_load_config_from_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
token = "file-token"
guild_id = 123

[[rooms]]
voice_channel_id = 456
text_channel_id = 789
mic_seconds = 90
pickup_seconds = 5
silence_timeout_seconds = 3
instruction_interval_seconds = 600
force_ptt = true
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.token == "file-token"
    assert config.guild_id == 123
    assert len(config.rooms) == 1
    assert config.rooms[0].voice_channel_id == 456
    assert config.rooms[0].text_channel_id == 789
    assert config.rooms[0].mic_seconds == 90
    assert config.rooms[0].pickup_seconds == 5
    assert config.rooms[0].silence_timeout_seconds == 3
    assert config.rooms[0].instruction_interval_seconds == 600
    assert config.rooms[0].force_ptt is True


def test_env_token_overrides_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "env-token")
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
token = "file-token"
guild_id = 123

[[rooms]]
voice_channel_id = 456
text_channel_id = 789
""".strip(),
        encoding="utf-8",
    )

    assert load_config(config_file).token == "env-token"


def test_requires_at_least_one_room(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "env-token")
    config_file = tmp_path / "config.toml"
    config_file.write_text("guild_id = 123", encoding="utf-8")

    with pytest.raises(ValueError, match=r"At least one \[\[rooms\]\] entry"):
        load_config(config_file)
