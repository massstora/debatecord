from __future__ import annotations

from collections.abc import Callable
import logging

import discord

try:
    from discord.ext import voice_recv
except ImportError:  # pragma: no cover - only happens when dependency is missing.
    voice_recv = None

log = logging.getLogger(__name__)


class SpeakingSink(voice_recv.AudioSink if voice_recv else object):
    """Receives audio and reports when a user transmits voice packets."""

    def __init__(self, on_speaking: Callable[[discord.Member], None]) -> None:
        if voice_recv:
            super().__init__()
        self._on_speaking = on_speaking

    def wants_opus(self) -> bool:
        return True

    def write(self, user: discord.Member | discord.User | None, data: object) -> None:
        if isinstance(user, discord.Member):
            self._on_speaking(user)

    def cleanup(self) -> None:
        pass


def voice_recv_client_cls() -> type[discord.VoiceClient]:
    if voice_recv is None:
        raise RuntimeError(
            "discord-ext-voice-recv is required for speaking detection. "
            "Install project dependencies with `pip install -e .`."
        )
    return voice_recv.VoiceRecvClient


def start_listening(
    voice_client: discord.VoiceClient,
    on_speaking: Callable[[discord.Member], None],
) -> None:
    if voice_recv is None:
        raise RuntimeError("discord-ext-voice-recv is not installed")
    recv_client = voice_client
    if not hasattr(recv_client, "listen"):
        raise RuntimeError("Voice client does not support receiving audio")
    if getattr(recv_client, "is_listening", lambda: False)():
        return
    recv_client.listen(SpeakingSink(on_speaking))  # type: ignore[attr-defined]

