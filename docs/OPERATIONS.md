# ChimeBuddy Operations

This guide describes the beta deployment on a Linux
server. The examples assume that the repository is stored
at:

```text
~/bots/chimebuddy-v2
```

The supplied service files use `%h`, so they do not contain
a username. If the repository is stored elsewhere, update
`WorkingDirectory`, `EnvironmentFile`, and `ExecStart` in
all four service files before installing them.

## 1. Prepare the installation

Run these commands from the repository:

```bash
cd ~/bots/chimebuddy-v2
.venv/bin/pip install -e .
chmod 600 .env
mkdir -p var/backups
chmod 700 var var/backups
```

Installing the project again is required after a new
console command is added. It does not remove the virtual
environment or database.

## 2. Test one backup manually

The backup command uses SQLite's online backup API. Twitch
and Discord may remain running while it creates a
consistent snapshot.

```bash
chimebuddy-backup-database
```

A successful result prints:

```text
Backup created: .../var/backups/chimebuddy-....db
SQLite integrity check: ok
Expired backups removed: 0
```

By default, the newest 14 backups are retained. Only files
whose names match `chimebuddy-*.db` inside the configured
backup directory are eligible for retention cleanup.

## 3. Install the user services

User services do not require ChimeBuddy itself to run as
root.

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/chimebuddy-* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now chimebuddy-twitch.service
systemctl --user enable --now chimebuddy-discord.service
systemctl --user enable --now chimebuddy-backup.timer
```

For the services to continue after the SSH session closes,
user lingering must be enabled once:

```bash
sudo loginctl enable-linger "$USER"
```

## 4. Verify the services

```bash
systemctl --user status chimebuddy-twitch.service
systemctl --user status chimebuddy-discord.service
systemctl --user list-timers chimebuddy-backup.timer
```

Both bots should show `active (running)`. The timer output
shows when the next backup is due.

The service manager restarts a bot after an unexpected
failure. A deliberate `systemctl --user stop` does not
trigger a restart.

## 5. Read logs

Follow live Twitch logs:

```bash
journalctl --user -u chimebuddy-twitch.service -f
```

Follow live Discord logs:

```bash
journalctl --user -u chimebuddy-discord.service -f
```

Show important messages from both services since midnight:

```bash
journalctl --user \
  -u chimebuddy-twitch.service \
  -u chimebuddy-discord.service \
  --since today \
  -p warning
```

Show backup history:

```bash
journalctl --user -u chimebuddy-backup.service
```

The system journal handles log retention, so a permanent
`tee -a` process is no longer necessary.

## 6. Deploy an update

```bash
cd ~/bots/chimebuddy-v2
git pull --ff-only
.venv/bin/pip install -e .
systemctl --user restart chimebuddy-twitch.service
systemctl --user restart chimebuddy-discord.service
```

Then verify both service statuses and refresh the private
Discord broadcaster panel.

Database migrations run automatically during startup.
Both processes safely coordinate migration writes.

## 7. Run or inspect a backup

Run the backup service immediately:

```bash
systemctl --user start chimebuddy-backup.service
```

List retained backups:

```bash
ls -lh var/backups/
```

Backups contain OAuth credentials and must be treated as
secrets. Do not upload them to public storage, attach them
to chat messages, or commit them to Git.

## 8. Recovery rule

Never replace the live SQLite database while either bot is
running.

Before restoring a backup:

1. Stop both ChimeBuddy services.
2. Preserve the current database and its `-wal` and `-shm`
   files together in a private recovery directory.
3. Copy the selected verified backup to the exact path in
   `CHIMEBUDDY_DATABASE_PATH`.
4. Give the restored file mode `600`.
5. Start Twitch, then Discord.
6. Inspect both service logs and refresh the Discord panel.

Because restoring the wrong request or credential state can
affect real users, recovery should remain a deliberate,
guided operation rather than an automatic command.

## 9. Beta operational checklist

Before inviting a streamer:

- both services survive an SSH logout;
- both services restart after a simulated process failure;
- the daily backup timer is scheduled;
- at least one backup passes its integrity check;
- the private Discord panel shows current runtime health;
- `.env`, the live database, and backups have restrictive
  permissions;
- the real live-title acceptance test is assigned to the
  first consenting streamer tester.
