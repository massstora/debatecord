# Debatecord

Debatecord is a Discord bot for moderated debate voice rooms. Regular users are
server-muted when they enter a managed voice channel, then use a mic queue to
speak. Room admins can speak at any time.

Queue state is kept in memory. Restarting the bot clears all queues.

## Features

- One independent mic queue per configured voice channel.
- Automatic room admin role creation using `<voice-channel-name>-admin`.
- Non-admin users are server-muted when they enter a managed voice channel.
- `/getmic` adds a user to the room's mic queue.
- `/dropmic` removes a user from the queue or ends their current turn.
- The bot unmutes the next queued user when it is their turn.
- The speaker must transmit audio within the pickup window, defaulting to 10
  seconds.
- The mic timer starts only after actual voice transmission is detected.
- If the speaker stops transmitting for the silence timeout, defaulting to 5
  seconds, their turn ends early.
- Remaining-time announcements are posted every 30 seconds.
- Queue updates are announced after speaker and queue changes.
- Users who leave the voice channel are removed from the queue.
- If an admin server-mutes the current speaker, their turn ends.
- If an admin manually unmutes someone outside the queue turn, Debatecord holds
  the queue. That user must transmit within the pickup window or they are muted
  again and the queue resumes.
- Optional Push-to-Talk enforcement per room.
- Optional periodic room instructions explaining `/getmic` and `/dropmic`.

Debatecord uses `discord.py` and `discord-ext-voice-recv` so it can detect real
voice transmission rather than guessing from mute state.

## Requirements

- Python 3.11 or newer
- A Discord bot token
- A Discord server where you can manage bot permissions
- A machine where the bot can run continuously
- Outbound network access and UDP connectivity for Discord voice

A small VPS is the simplest production host. A home server can work too, but the
bot must stay online for queues and timers to work.

## Discord Bot Setup

Create the bot:

1. Go to the Discord Developer Portal.
2. Create a new application named `Debatecord`.
3. Open the application's `Bot` page.
4. Create the bot user.
5. Copy the bot token and keep it private.
6. Enable `SERVER MEMBERS INTENT`.

Generate an invite:

1. Open the application's `OAuth2` page.
2. Use the URL generator.
3. Select these scopes:
   - `bot`
   - `applications.commands`
4. Select these bot permissions:
   - Manage Roles
   - Manage Channels
   - Mute Members
   - Connect
   - View Channels
   - Send Messages
   - Use Slash Commands
5. Open the generated invite URL and add the bot to your server.

After inviting the bot, make sure the bot's highest role is above the room admin
roles it creates. Discord will not let a bot manage roles at or above its own
highest role.

## Discord Room Setup

Create or choose:

- one voice channel for each debate room
- one text channel for each debate room

Commands only work from the configured text channel for the voice room the user
is currently in. For example, if a user is in the `Politics` voice channel,
`/getmic` should be run from the configured `Politics` text channel.

When Debatecord starts, it creates or reuses a role named after the voice
channel:

```text
<voice-channel-name>-admin
```

For a voice channel named `Politics`, the room admin role is:

```text
Politics-admin
```

Give that role to moderators who should be able to speak at all times and use
room admin commands.

## Finding Discord IDs

You need the guild, voice channel, and text channel IDs for `config.toml`.

Enable Developer Mode in Discord:

1. Open Discord settings.
2. Go to `Advanced`.
3. Enable `Developer Mode`.

Then right-click the server or channel and choose `Copy ID`.

## Installation

Clone or copy this project onto the machine that will run the bot.

From the project directory:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

For development tools:

```bash
pip install -e ".[dev]"
ruff check .
pytest
```

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
silence_timeout_seconds = 5
instruction_interval_seconds = 3600
force_ptt = true
```

You may omit `token` from the file and use the `DISCORD_TOKEN` environment
variable instead:

```bash
export DISCORD_TOKEN="put-your-bot-token-here"
```

Room settings:

- `voice_channel_id`: the debate voice channel Debatecord should manage.
- `text_channel_id`: the text channel where room commands and announcements go.
- `mic_seconds`: how long each normal queued speaker may speak after audio is
  detected.
- `pickup_seconds`: how long a user has to start transmitting after being
  unmuted.
- `silence_timeout_seconds`: how long a speaker may stop transmitting before
  Debatecord ends their turn and moves on.
- `instruction_interval_seconds`: how often to post room instructions. Set to
  `0` to disable recurring reminders.
- `force_ptt`: when `true`, Debatecord denies `Use Voice Activity` for
  `@everyone` in the voice channel and allows it for the room admin role. This
  effectively forces Push-to-Talk for regular users.

Multiple rooms can be configured:

```toml
[[rooms]]
voice_channel_id = 222222222222222222
text_channel_id = 333333333333333333
mic_seconds = 180
pickup_seconds = 10
silence_timeout_seconds = 5
instruction_interval_seconds = 3600
force_ptt = true

[[rooms]]
voice_channel_id = 444444444444444444
text_channel_id = 555555555555555555
mic_seconds = 120
pickup_seconds = 10
silence_timeout_seconds = 5
instruction_interval_seconds = 1800
force_ptt = false
```

## Running The Bot

Run with:

```bash
source .venv/bin/activate
debatecord --config config.toml
```

Or:

```bash
./debatecord --config config.toml
```

Useful logging option:

```bash
./debatecord --config config.toml --log-level DEBUG
```

Leave the process running. If the bot stops, queues and active turns are lost.
When it starts again, it will re-check the configured rooms and mute regular
users who should not be speaking.

## Running With systemd

On a VPS, create a dedicated directory such as:

```text
/opt/debatecord
```

Place the project and `config.toml` there, then create a virtual environment and
install the package:

```bash
cd /opt/debatecord
python -m venv .venv
.venv/bin/pip install -e .
```

Create `/etc/systemd/system/debatecord.service`:

```ini
[Unit]
Description=Debatecord Discord bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/debatecord
ExecStart=/opt/debatecord/.venv/bin/debatecord --config /opt/debatecord/config.toml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now debatecord
```

View logs:

```bash
journalctl -u debatecord -f
```

If you prefer to keep the bot token out of `config.toml`, add an environment
file and reference it from the service:

```ini
EnvironmentFile=/etc/debatecord.env
```

Then create `/etc/debatecord.env`:

```text
DISCORD_TOKEN=put-your-bot-token-here
```

## User Commands

Run these commands in the configured room text channel while you are inside that
room's voice channel.

- `/getmic`: join the mic queue.
- `/dropmic`: leave the queue. If you currently have the mic, this ends your
  turn.
- `/micstatus`: show the current speaker, manual floor speaker, and waiting
  queue.

Normal user flow:

1. Join the managed voice channel.
2. Debatecord server-mutes you.
3. Type `/getmic` in the room text channel.
4. Wait for your turn.
5. When Debatecord unmutes you, start speaking within the pickup window.
6. Speak until your time expires, you stop transmitting long enough for the
   silence timeout, or you use `/dropmic`.

## Room Admin Commands

Room admins are users with the `<voice-channel-name>-admin` role or Discord
administrator permission.

- `/skipmic`: end the current queued speaker's turn.
- `/clearmic`: clear the waiting queue.

Admins can also use Discord's native voice controls:

- Server-muting the current speaker ends their turn.
- Disconnecting or moving a speaker out of the voice channel ends their turn.
- Manually unmuting a non-current user gives that user the floor and holds the
  queue.
- If a manually unmuted user does not transmit within the pickup window,
  Debatecord mutes them again and resumes the queue.
- If a manually unmuted user stops transmitting for the silence timeout,
  Debatecord mutes them again and resumes the queue.
- Muting a manually unmuted user releases the hold and resumes the queue.

Admins are exempt from automatic Debatecord muting and can speak at all times.

## Operational Notes

- Debatecord controls voice server mute only. It does not mute text chat.
- Queue state is not saved to disk.
- Restarting the bot clears every room queue.
- If `force_ptt` is enabled, the bot changes channel permissions for `Use Voice
  Activity`.
- A Discord bot can normally only be connected to one voice channel per guild at
  a time. Speaking detection depends on the bot being connected to the voice
  room.
- If permissions are wrong, the most common symptom is that users are not muted
  or the bot cannot create the room admin role.

## Troubleshooting

Slash commands do not show up:

- Make sure the bot was invited with the `applications.commands` scope.
- Restart the bot so it syncs commands.
- Confirm `guild_id` is the server ID, not a channel ID.

Users are not being muted:

- Make sure the bot has `Mute Members`.
- Make sure the bot can see and connect to the voice channel.
- Make sure the bot's role is high enough in the Discord role list.

Room admin role was not created:

- Make sure the bot has `Manage Roles`.
- Move the bot's role higher in the role list.

Push-to-Talk is not enforced:

- Make sure `force_ptt = true`.
- Make sure the bot has `Manage Channels`.
- Check the voice channel permission overrides for `Use Voice Activity`.

The bot starts but does not detect speaking:

- Make sure the bot can connect to the voice channel.
- Make sure the host allows Discord voice UDP traffic.
- Check the logs with `--log-level DEBUG` or `journalctl -u debatecord -f`.

## Security Notes

- Do not commit `config.toml` if it contains your bot token.
- Prefer `DISCORD_TOKEN` or a systemd environment file for production.
- Treat the Discord bot token like a password.
- If a token is leaked, reset it in the Discord Developer Portal.

## License

Debatecord is released under the MIT License. See [LICENSE](LICENSE).
