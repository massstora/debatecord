# Debatecord

Debatecord is a Discord bot for moderated debate voice rooms. Regular users are
muted when they enter a managed voice channel, then use a mic queue to speak.
Room admins can speak at any time.

## How It Works

- Each configured voice channel has its own mic queue.
- The bot creates or reuses a room admin role named `<voice-channel-name>-admin`.
- Non-admin users are server-muted when they enter the managed voice channel.
- Users type `/getmic` in the room text channel to join the queue.
- Users type `/dropmic` to leave the queue or end their current turn.
- When a user reaches the front of the queue, Debatecord unmutes them.
- The user must transmit audio within the pickup window, defaulting to 10 seconds.
- Once audio is detected, their mic timer starts.
- The bot posts remaining-time messages every 30 seconds.
- The bot announces the updated mic queue after queue and speaker changes.
- When the timer expires, the user is muted and the next queued user gets the mic.
- If a user leaves the voice channel, they are removed from the queue.
- If the current speaker is server-muted by an admin, their turn ends.
- If an admin manually unmutes someone outside the queue turn, Debatecord holds
  the queue. That user must transmit within the pickup window or they are muted
  again and the queue resumes.

Queue state is kept in memory. Restarting the bot clears all queues.

## Requirements

- Python 3.11+
- A Discord bot token
- A server or VPS where the bot can run continuously
- Bot permissions:
  - Manage Roles
  - Manage Channels
  - Mute Members
  - Connect
  - View Channels
  - Send Messages
  - Use Slash Commands

The bot uses `discord.py` and `discord-ext-voice-recv` so it can detect real
voice transmission rather than guessing from mute state.

## Discord Setup

1. Create an application in the Discord Developer Portal.
2. Add a bot user.
3. Enable the Server Members intent.
4. Invite the bot with the `bot` and `applications.commands` scopes.
5. Grant the permissions listed above.
6. Put the bot's highest role above the room admin roles it needs to manage.

## Configuration

Copy the example config:

```bash
cp config.example.toml config.toml
```

Edit `config.toml`:

```toml
token = "put-your-bot-token-here"
guild_id = 111111111111111111

[[rooms]]
voice_channel_id = 222222222222222222
text_channel_id = 333333333333333333
mic_seconds = 180
pickup_seconds = 10
instruction_interval_seconds = 3600
force_ptt = true
```

You may also omit `token` from the file and use the `DISCORD_TOKEN`
environment variable.

`force_ptt = true` denies the Discord `Use Voice Activity` permission for
`@everyone` in that voice channel and allows it for the room admin role. That
effectively forces Push-to-Talk for regular users.

`instruction_interval_seconds` controls how often Debatecord posts room
instructions explaining `/getmic` and `/dropmic`. Set it to `0` to disable
recurring instruction messages.

## Running Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
debatecord --config config.toml
```

For development tools:

```bash
pip install -e ".[dev]"
ruff check .
```

## Commands

User commands:

- `/getmic` joins the current room's mic queue.
- `/dropmic` leaves the queue or ends your current turn.
- `/micstatus` shows the current speaker and queue.

Room admin commands:

- `/skipmic` ends the current speaker's turn.
- `/clearmic` clears the room queue.

Commands only work from the configured text channel for the voice room the user
is currently in.

## Hosting

Run Debatecord as a long-lived process on a VPS or other always-on server. A
simple `systemd` service is usually enough. The bot needs stable outbound
network access and UDP connectivity for Discord voice.
