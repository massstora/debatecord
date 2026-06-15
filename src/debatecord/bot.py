from __future__ import annotations

import logging

import discord
from discord import app_commands

from .config import BotConfig
from .room import DebateRoom

log = logging.getLogger(__name__)


class DebatecordBot(discord.Client):
    def __init__(self, config: BotConfig) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.voice_states = True
        super().__init__(intents=intents)
        self.config = config
        self.tree = app_commands.CommandTree(self)
        self.rooms = {room.voice_channel_id: DebateRoom(self, room) for room in config.rooms}

    async def setup_hook(self) -> None:
        guild = discord.Object(id=self.config.guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def on_ready(self) -> None:
        log.info("Logged in as %s", self.user)
        for room in self.rooms.values():
            await room.setup()

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        channel_ids = {
            state.channel.id
            for state in (before, after)
            if state.channel is not None and state.channel.id in self.rooms
        }
        for channel_id in channel_ids:
            await self.rooms[channel_id].on_voice_state_update(member, before, after)

    def room_for_interaction(self, interaction: discord.Interaction) -> DebateRoom | None:
        if not isinstance(interaction.user, discord.Member):
            return None
        voice = interaction.user.voice
        if voice is None or voice.channel is None:
            return None
        room = self.rooms.get(voice.channel.id)
        if room is None or not room.is_room_text_channel(interaction.channel_id):
            return None
        return room


def _room_or_reply(bot: DebatecordBot, interaction: discord.Interaction) -> DebateRoom | None:
    room = bot.room_for_interaction(interaction)
    return room


def register_commands(bot: DebatecordBot) -> None:
    @bot.tree.command(name="getmic", description="Join this room's mic queue.")
    async def getmic(interaction: discord.Interaction) -> None:
        room = _room_or_reply(bot, interaction)
        if room is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Use this command in the text channel for the debate voice room you are in.",
                ephemeral=True,
            )
            return
        message = await room.add_to_queue(interaction.user)
        await interaction.response.send_message(message, ephemeral=True)

    @bot.tree.command(name="dropmic", description="Leave the mic queue or end your mic turn.")
    async def dropmic(interaction: discord.Interaction) -> None:
        room = _room_or_reply(bot, interaction)
        if room is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Use this command in the text channel for the debate voice room you are in.",
                ephemeral=True,
            )
            return
        message = await room.drop_from_queue(interaction.user)
        await interaction.response.send_message(message, ephemeral=True)

    @bot.tree.command(name="micstatus", description="Show the current speaker and queue.")
    async def micstatus(interaction: discord.Interaction) -> None:
        room = _room_or_reply(bot, interaction)
        if room is None:
            await interaction.response.send_message(
                "Use this command in a managed debate room text channel.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(await room.status(), ephemeral=True)

    @bot.tree.command(name="skipmic", description="Room admin: skip the current speaker.")
    async def skipmic(interaction: discord.Interaction) -> None:
        room = _room_or_reply(bot, interaction)
        if room is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Use this command in a managed debate room text channel.",
                ephemeral=True,
            )
            return
        message = await room.skip(interaction.user)
        await interaction.response.send_message(message, ephemeral=True)

    @bot.tree.command(name="clearmic", description="Room admin: clear the room mic queue.")
    async def clearmic(interaction: discord.Interaction) -> None:
        room = _room_or_reply(bot, interaction)
        if room is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Use this command in a managed debate room text channel.",
                ephemeral=True,
            )
            return
        message = await room.clear(interaction.user)
        await interaction.response.send_message(message, ephemeral=True)


def run_bot(config: BotConfig) -> None:
    bot = DebatecordBot(config)
    register_commands(bot)
    bot.run(config.token)

