from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tomllib


@dataclass(frozen=True, slots=True)
class RoomConfig:
    voice_channel_id: int
    text_channel_id: int
    mic_seconds: int = 180
    pickup_seconds: int = 10
    force_ptt: bool = False


@dataclass(frozen=True, slots=True)
class BotConfig:
    token: str
    guild_id: int
    rooms: tuple[RoomConfig, ...]


def load_config(path: str | Path) -> BotConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    token = os.environ.get("DISCORD_TOKEN") or data.get("token")
    if not token:
        raise ValueError("Missing Discord bot token in DISCORD_TOKEN or config token")

    rooms = tuple(RoomConfig(**room) for room in data.get("rooms", []))
    if not rooms:
        raise ValueError("At least one [[rooms]] entry is required")

    return BotConfig(token=token, guild_id=int(data["guild_id"]), rooms=rooms)

