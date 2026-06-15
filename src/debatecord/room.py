from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
import logging

import discord

from .config import RoomConfig
from .speaking import start_listening, voice_recv_client_cls

log = logging.getLogger(__name__)


@dataclass(slots=True)
class RoomState:
    queue: deque[int] = field(default_factory=deque)
    manual_speaker_ids: set[int] = field(default_factory=set)
    manual_speaker_tasks: dict[int, asyncio.Task[None]] = field(default_factory=dict)
    current_speaker_id: int | None = None
    turn_task: asyncio.Task[None] | None = None
    advance_task: asyncio.Task[None] | None = None
    instruction_task: asyncio.Task[None] | None = None


class DebateRoom:
    def __init__(self, bot: discord.Client, config: RoomConfig) -> None:
        self.bot = bot
        self.config = config
        self.state = RoomState()
        self.admin_role_id: int | None = None
        self._lock = asyncio.Lock()
        self._speaking_event = asyncio.Event()
        self._manual_speaking_events: dict[int, asyncio.Event] = {}

    @property
    def admin_role_name(self) -> str:
        channel = self.voice_channel
        return f"{channel.name}-admin" if channel else f"{self.config.voice_channel_id}-admin"

    @property
    def guild(self) -> discord.Guild | None:
        channel = self.voice_channel
        return channel.guild if channel else None

    @property
    def voice_channel(self) -> discord.VoiceChannel | None:
        channel = self.bot.get_channel(self.config.voice_channel_id)
        return channel if isinstance(channel, discord.VoiceChannel) else None

    @property
    def text_channel(self) -> discord.abc.Messageable | None:
        channel = self.bot.get_channel(self.config.text_channel_id)
        return channel if isinstance(channel, discord.abc.Messageable) else None

    async def setup(self) -> None:
        guild = self.guild
        voice_channel = self.voice_channel
        if guild is None or voice_channel is None:
            log.warning("Room %s is not available yet", self.config.voice_channel_id)
            return

        role = discord.utils.get(guild.roles, name=self.admin_role_name)
        if role is None:
            role = await guild.create_role(
                name=self.admin_role_name,
                reason="Debatecord room admin role",
            )
        self.admin_role_id = role.id

        if self.config.force_ptt:
            await self._apply_ptt_permissions(voice_channel, role)

        await self.reconcile_voice_state()
        self.ensure_instruction_reminders()

    async def _apply_ptt_permissions(
        self, voice_channel: discord.VoiceChannel, admin_role: discord.Role
    ) -> None:
        everyone = voice_channel.guild.default_role
        await voice_channel.set_permissions(
            everyone,
            use_voice_activation=False,
            reason="Debatecord force Push-to-Talk mode",
        )
        await voice_channel.set_permissions(
            admin_role,
            use_voice_activation=True,
            reason="Debatecord room admins may use voice activation",
        )

    def is_admin(self, member: discord.Member) -> bool:
        if member.guild_permissions.administrator:
            return True
        return self.admin_role_id is not None and any(
            role.id == self.admin_role_id for role in member.roles
        )

    def contains_member(self, member: discord.Member) -> bool:
        return (
            member.voice is not None
            and member.voice.channel is not None
            and member.voice.channel.id == self.config.voice_channel_id
        )

    def is_room_text_channel(self, channel_id: int | None) -> bool:
        return channel_id == self.config.text_channel_id

    async def announce(self, message: str) -> None:
        channel = self.text_channel
        if channel is not None:
            await channel.send(message)

    async def announce_queue(self) -> None:
        await self.announce(await self.queue_status_message())

    def instruction_message(self) -> str:
        minutes = self.config.mic_seconds // 60
        seconds = self.config.mic_seconds % 60
        if minutes and seconds:
            timer_text = f"{minutes}m {seconds}s"
        elif minutes:
            timer_text = f"{minutes}m"
        else:
            timer_text = f"{seconds}s"

        return (
            "**Mic queue instructions**\n"
            "Join this voice channel, then use `/getmic` here to enter the mic queue.\n"
            "Use `/dropmic` to leave the queue or give up the mic during your turn.\n"
            f"When your turn starts, begin speaking within {self.config.pickup_seconds} seconds. "
            f"Your mic time is {timer_text}."
        )

    def ensure_instruction_reminders(self) -> None:
        if self.config.instruction_interval_seconds <= 0:
            return
        if self.state.instruction_task is None or self.state.instruction_task.done():
            self.state.instruction_task = asyncio.create_task(self._instruction_reminder_loop())

    async def _instruction_reminder_loop(self) -> None:
        await self.announce(self.instruction_message())
        while self.config.instruction_interval_seconds > 0:
            await asyncio.sleep(self.config.instruction_interval_seconds)
            await self.announce(self.instruction_message())

    async def add_to_queue(self, member: discord.Member) -> str:
        async with self._lock:
            if self.is_admin(member):
                return "Room admins can already speak at any time."
            if not self.contains_member(member):
                return "Join this debate voice channel before using /getmic."
            if member.id == self.state.current_speaker_id:
                return "You already have the mic."
            if member.id in self.state.queue:
                return "You are already in the mic queue."
            self.state.queue.append(member.id)
            position = len(self.state.queue)

        if not await self.is_manual_floor_speaker(member):
            await self.ensure_member_muted(member)
        await self.announce(f"{member.mention} joined the mic queue at position {position}.")
        await self.announce_queue()
        self.ensure_advancing()
        return f"You joined the mic queue at position {position}."

    async def drop_from_queue(self, member: discord.Member) -> str:
        dropped_from_queue = False
        should_end_turn = False
        async with self._lock:
            if member.id in self.state.queue:
                self.state.queue.remove(member.id)
                dropped_from_queue = True
            should_end_turn = member.id == self.state.current_speaker_id

        if dropped_from_queue:
            await self.announce(f"{member.mention} left the mic queue.")
            await self.announce_queue()
            return "You left the mic queue."
        if should_end_turn:
            await self.end_current_turn("speaker dropped the mic")
            return "Your mic turn has ended."
        return "You are not in the mic queue."

    async def status(self) -> str:
        return await self.queue_status_message()

    async def queue_status_message(self) -> str:
        guild = self.guild
        async with self._lock:
            speaker = (
                guild.get_member(self.state.current_speaker_id)
                if guild and self.state.current_speaker_id
                else None
            )
            queued = [guild.get_member(user_id) for user_id in self.state.queue] if guild else []
            manual_speakers = (
                [guild.get_member(user_id) for user_id in self.state.manual_speaker_ids]
                if guild
                else []
            )
        speaker_text = speaker.mention if speaker else "Nobody"
        manual_names = [member.mention for member in manual_speakers if member is not None]
        manual_text = ", ".join(manual_names) if manual_names else "Nobody"
        names = [member.mention for member in queued if member is not None]
        queue_text = ", ".join(names) if names else "empty"
        return (
            "**Mic queue**\n"
            f"Current speaker: {speaker_text}\n"
            f"Manual floor: {manual_text}\n"
            f"Waiting: {queue_text}"
        )

    async def skip(self, actor: discord.Member) -> str:
        if not self.is_admin(actor):
            return "Only room admins can skip the mic."
        await self.end_current_turn(f"skipped by {actor.display_name}")
        return "Skipped the current mic turn."

    async def clear(self, actor: discord.Member) -> str:
        if not self.is_admin(actor):
            return "Only room admins can clear the mic queue."
        async with self._lock:
            self.state.queue.clear()
        await self.announce(f"The mic queue was cleared by {actor.mention}.")
        await self.announce_queue()
        return "Cleared the mic queue."

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        before_here = before.channel is not None and before.channel.id == self.config.voice_channel_id
        after_here = after.channel is not None and after.channel.id == self.config.voice_channel_id

        if before_here and not after_here:
            await self.remove_member(member, "left the voice channel")
            return

        if after_here and member.id == self.state.current_speaker_id and not before.mute and after.mute:
            await self.end_current_turn("speaker was muted")
            return

        if not after_here or self.is_admin(member) or member.id == self.state.current_speaker_id:
            return

        if before.mute and not after.mute:
            await self.start_manual_floor(member)
            return

        if not before.mute and after.mute:
            if await self.end_manual_floor(member, "speaker was muted"):
                return

        if not await self.is_manual_floor_speaker(member):
            await self.ensure_member_muted(member)

    async def remove_member(self, member: discord.Member, reason: str) -> None:
        was_current = False
        was_queued = False
        was_manual = False
        async with self._lock:
            if member.id in self.state.queue:
                self.state.queue.remove(member.id)
                was_queued = True
            if member.id in self.state.manual_speaker_ids:
                self.state.manual_speaker_ids.remove(member.id)
                was_manual = True
            was_current = member.id == self.state.current_speaker_id
        if was_manual:
            await self.announce(f"{member.mention}'s manual floor ended: {reason}.")
            await self.announce_queue()
            self.ensure_advancing()
        if was_queued:
            await self.announce(f"{member.mention} was removed from the mic queue: {reason}.")
            await self.announce_queue()
        if was_current:
            await self.end_current_turn(reason)

    async def reconcile_voice_state(self) -> None:
        channel = self.voice_channel
        if channel is None:
            return
        for member in channel.members:
            if self.is_admin(member):
                continue
            if (
                member.id != self.state.current_speaker_id
                and member.id not in self.state.manual_speaker_ids
            ):
                await self.ensure_member_muted(member)

    async def ensure_member_muted(self, member: discord.Member) -> None:
        if not member.voice or member.voice.mute:
            return
        await member.edit(mute=True, reason="Debatecord room voice control")

    async def ensure_member_unmuted(self, member: discord.Member) -> None:
        if not member.voice or not member.voice.mute:
            return
        await member.edit(mute=False, reason="Debatecord mic turn")

    def ensure_advancing(self) -> None:
        if self.state.advance_task is None or self.state.advance_task.done():
            self.state.advance_task = asyncio.create_task(self._advance_loop())

    async def _advance_loop(self) -> None:
        while True:
            async with self._lock:
                if self.state.current_speaker_id is not None or self.state.manual_speaker_ids:
                    return
                next_id = self._pop_next_valid_user_id()
                if next_id is None:
                    return
                self.state.current_speaker_id = next_id
                self._speaking_event.clear()

            guild = self.guild
            member = guild.get_member(next_id) if guild else None
            if member is None or not self.contains_member(member):
                async with self._lock:
                    if self.state.current_speaker_id == next_id:
                        self.state.current_speaker_id = None
                continue

            await self.ensure_voice_connected()
            await self.ensure_member_unmuted(member)
            await self.announce(
                f"{member.mention} has the mic. Start speaking within "
                f"{self.config.pickup_seconds} seconds."
            )
            await self.announce_queue()

            try:
                await asyncio.wait_for(self._speaking_event.wait(), timeout=self.config.pickup_seconds)
            except asyncio.TimeoutError:
                if not await self._is_current_speaker(member):
                    return
                await self.announce(f"{member.mention} did not take the mic in time. Skipping.")
                await self._finish_member_turn(member, "pickup timeout")
                continue

            if not await self._is_current_speaker(member):
                return
            await self._run_speaker_timer(member)

    def _pop_next_valid_user_id(self) -> int | None:
        guild = self.guild
        while self.state.queue:
            user_id = self.state.queue.popleft()
            member = guild.get_member(user_id) if guild else None
            if member is not None and self.contains_member(member) and not self.is_admin(member):
                return user_id
        return None

    async def ensure_voice_connected(self) -> None:
        channel = self.voice_channel
        if channel is None:
            raise RuntimeError("Managed voice channel is not available")

        voice_client = discord.utils.get(self.bot.voice_clients, guild=channel.guild)
        if voice_client is None:
            voice_client = await channel.connect(cls=voice_recv_client_cls())
        elif voice_client.channel.id != channel.id:
            await voice_client.move_to(channel)

        start_listening(voice_client, self._on_speaking)

    def _on_speaking(self, member: discord.Member) -> None:
        if member.id == self.state.current_speaker_id:
            self.bot.loop.call_soon_threadsafe(self._speaking_event.set)
        if member.id in self.state.manual_speaker_ids:
            self.bot.loop.call_soon_threadsafe(self._set_manual_speaking_event, member.id)

    def _set_manual_speaking_event(self, member_id: int) -> None:
        event = self._manual_speaking_events.get(member_id)
        if event is not None:
            event.set()

    async def _run_speaker_timer(self, member: discord.Member) -> None:
        remaining = self.config.mic_seconds
        await self.announce(f"{member.mention}'s mic timer started: {remaining} seconds.")

        while remaining > 0:
            sleep_for = min(30, remaining)
            await asyncio.sleep(sleep_for)
            remaining -= sleep_for

            if member.id != self.state.current_speaker_id:
                return
            if remaining > 0:
                await self.announce(f"{member.mention} has {remaining} seconds left.")

        await self._finish_member_turn(member, "time expired")

    async def end_current_turn(self, reason: str) -> None:
        guild = self.guild
        async with self._lock:
            current_id = self.state.current_speaker_id
        member = guild.get_member(current_id) if guild and current_id else None
        if member is not None:
            await self._finish_member_turn(member, reason)
        else:
            async with self._lock:
                self.state.current_speaker_id = None
            self.ensure_advancing()

    async def _finish_member_turn(self, member: discord.Member, reason: str) -> None:
        ended = False
        async with self._lock:
            if self.state.current_speaker_id == member.id:
                self.state.current_speaker_id = None
                ended = True
        if not ended:
            return
        if not self.is_admin(member):
            await self.ensure_member_muted(member)
        await self.announce(f"{member.mention}'s mic turn ended: {reason}.")
        await self.announce_queue()
        self.ensure_advancing()

    async def _is_current_speaker(self, member: discord.Member) -> bool:
        async with self._lock:
            return self.state.current_speaker_id == member.id

    async def start_manual_floor(self, member: discord.Member) -> None:
        await self.ensure_voice_connected()
        added = False
        async with self._lock:
            if member.id not in self.state.manual_speaker_ids:
                self.state.manual_speaker_ids.add(member.id)
                event = asyncio.Event()
                self._manual_speaking_events[member.id] = event
                self.state.manual_speaker_tasks[member.id] = asyncio.create_task(
                    self._manual_floor_pickup_timeout(member, event)
                )
                added = True
        if added:
            await self.announce(
                f"{member.mention} was manually unmuted. Holding the mic queue. "
                f"Start speaking within {self.config.pickup_seconds} seconds."
            )
            await self.announce_queue()

    async def end_manual_floor(self, member: discord.Member, reason: str) -> bool:
        return await self._end_manual_floor(member, reason, mute=False)

    async def _end_manual_floor(self, member: discord.Member, reason: str, mute: bool) -> bool:
        removed = False
        task: asyncio.Task[None] | None = None
        async with self._lock:
            if member.id in self.state.manual_speaker_ids:
                self.state.manual_speaker_ids.remove(member.id)
                self._manual_speaking_events.pop(member.id, None)
                task = self.state.manual_speaker_tasks.pop(member.id, None)
                removed = True
        if removed:
            if task is not None and task is not asyncio.current_task():
                task.cancel()
            if mute and not self.is_admin(member):
                await self.ensure_member_muted(member)
            await self.announce(f"{member.mention}'s manual floor ended: {reason}.")
            await self.announce_queue()
            self.ensure_advancing()
        return removed

    async def is_manual_floor_speaker(self, member: discord.Member) -> bool:
        async with self._lock:
            return member.id in self.state.manual_speaker_ids

    async def _manual_floor_pickup_timeout(
        self, member: discord.Member, event: asyncio.Event
    ) -> None:
        try:
            await asyncio.wait_for(event.wait(), timeout=self.config.pickup_seconds)
        except asyncio.TimeoutError:
            await self._end_manual_floor(member, "pickup timeout", mute=True)
        except asyncio.CancelledError:
            raise
