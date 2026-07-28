# ChimeBuddy V2 Architecture

## 1. Objective

ChimeBuddy is a modular Twitch automation bot with a private Discord administration interface.

Its first core workflow is:

1. Read a broadcaster’s current stream title.
2. Compare it with configured title triggers.
3. When a trigger becomes active, send its configured chat message.
4. Pin the message.
5. Avoid sending the same message repeatedly while the trigger remains active.
6. Reset the trigger when the matching expression disappears from the title.

Example:

- Expression: `solo`
- Message: `I am currently playing solo; viewers cannot join.`

Triggers and messages are configured separately for every broadcaster.

## 2. Development Safety

The stable V1 bot remains operational while V2 is developed.

- V1 runs from its existing directory and stable Git branch.
- V2 is developed in a separate Git worktree on `v2-rewrite`.
- V2 uses a separate virtual environment, configuration and development database.
- V1 and V2 must not send messages to the same Twitch channel simultaneously during development.
- V2 testing begins with the developer’s own Twitch channel.
- The stable V1 tag remains the permanent recovery point.

## 3. Runtime Components

ChimeBuddy V2 consists of two separate processes in one project.

### Twitch Worker

Responsible for:

- Twitch authentication and token refresh;
- EventSub connection and reconnection;
- reading Twitch events;
- stream-title monitoring;
- trigger evaluation;
- sending chat messages;
- pinning and unpinning messages;
- Twitch command permission checks.

### Discord Admin Bot

Responsible for:

- private administration panels;
- displaying ChimeBuddy status;
- displaying broadcasters and triggers;
- managing configuration in later stages;
- developer diagnostics;
- sanitized error reports;
- Discord-to-Twitch account linking.

The two processes share application services and one SQLite database.

A failure or restart of the Discord admin bot must not interrupt the Twitch worker.

## 4. Identity

Internal relationships use immutable platform IDs.

Stored identities include:

- Twitch bot user ID;
- Twitch broadcaster user ID;
- Twitch chat user ID;
- Discord user ID;
- Discord guild ID;
- Discord category ID;
- Discord channel ID.

Usernames and display names are stored only for display and may be updated without changing ownership.

## 5. Permission Systems

ChimeBuddy has three independent permission systems.

### Twitch OAuth Authorization

Determines what Twitch permits ChimeBuddy to do through the Twitch API.

Broadcasters initially authorize a common, minimal core scope bundle. Optional future modules may request additional authorization only when enabled.

### Discord Management Permission

Determines who may configure a broadcaster’s ChimeBuddy settings.

Initial access:

- the developer;
- the verified Discord account linked to the Twitch broadcaster.

Discord channel permissions provide privacy, but every administration command must also verify the caller’s Discord ID against the database.

### Twitch Command Permission

Determines who may use commands or actions inside a broadcaster’s Twitch chat.

Policies may allow:

- broadcaster;
- moderators;
- VIPs;
- subscribers;
- everyone;
- explicitly allowed Twitch user IDs.

Policies may also contain explicitly blocked Twitch user IDs.

These rules are stored separately for each broadcaster and command/action.

## 6. Discord Administration Panels

Broadcasters join the ChimeBuddy support Discord server and link their Discord and Twitch identities.

Once approved, the Discord admin bot can create a private channel:

```text
ADMIN PANELS
├── #anonym-poal
├── #liberty-992
└── #b3nde3
```

Initially, only the broadcaster, developer and Discord admin bot can access the channel.

The first Discord panel is read-only and supports:

- application status;
- Twitch connection status;
- token health without exposing tokens;
- monitored broadcaster information;
- configured trigger information;
- recent sanitized errors.

Configuration editing will be added only after the read-only interface is stable.

## 7. Storage

SQLite stores changing application state:

- Twitch accounts;
- Discord accounts;
- verified account links;
- broadcasters;
- OAuth credentials;
- triggers;
- trigger runtime state;
- Twitch command policies;
- command user overrides;
- Discord panel mappings;
- global and broadcaster settings;
- audit events;
- sanitized error events.

The `.env` file stores only deployment secrets and fixed configuration:

- Twitch client ID;
- Twitch client secret;
- Discord bot token;
- developer Discord user ID;
- database path;
- log level.

OAuth tokens must never be printed, returned through Discord, or committed to Git.

The SQLite database and `.env` file must be excluded from Git and protected with restrictive Linux permissions.

## 8. Trigger Rules

Initial trigger behavior:

- title matching is case-insensitive;
- V2 initially supports simple text and phrase matching;
- a trigger fires only when it changes from inactive to active;
- repeated title checks do not resend the message;
- the trigger resets when its expression no longer matches;
- each trigger has an enabled state and priority;
- ChimeBuddy records the ID of every message it sends;
- ChimeBuddy only unpins a message it owns;
- configuration changes become effective without restarting the process.

Regular expressions may be added later with validation and developer-only access.

## 9. V2 First Milestone

### Required Twitch functionality

- load configuration from SQLite;
- import only the necessary working V1 credentials;
- refresh OAuth tokens safely;
- connect and reconnect EventSub;
- monitor the current stream title;
- evaluate configured title triggers;
- send the configured chat message;
- pin the sent message;
- prevent duplicate trigger messages;
- recover from temporary Twitch failures;
- report errors without leaking secrets.

### Required Discord functionality

Owner-only, read-only commands:

- show application status;
- show Twitch and EventSub health;
- show configured broadcasters;
- show a broadcaster’s triggers;
- show recent sanitized errors.

### Acceptance criteria

V2 succeeds when:

- it runs for at least ten continuous hours;
- token refreshes do not produce stale-token errors;
- EventSub reconnects automatically;
- a configured title trigger sends and pins exactly one message;
- repeated checks do not produce duplicate messages;
- the Discord admin bot displays real Twitch worker data from SQLite;
- no unhandled exception terminates the Twitch worker;
- no secret or OAuth token appears in logs or Discord responses.

## 10. Initial Non-Goals

The first milestone does not require:

- public self-service onboarding;
- automatic Twitch OAuth onboarding;
- full broadcaster configuration editing;
- a website;
- open router ports;
- advanced statistics;
- arbitrary Python source-code hot reload;
- migration of every V1 setting;
- support for a large number of broadcasters.

These can be added after the core system is stable.

## 11. Runtime Configuration

Database-backed operational configuration should be changeable without restarting:

- triggers;
- response messages;
- trigger enabled states;
- command permissions;
- broadcaster settings;
- Discord panel mappings.

Python source-code changes still use a controlled systemd service restart.

## 12. Planned Implementation Order

1. Create the V2 project skeleton.
2. Add configuration validation and logging.
3. Add SQLite connection handling and migrations.
4. Add broadcaster, token and trigger repositories.
5. Add the runtime token manager.
6. Add the Twitch API client.
7. Add EventSub lifecycle management.
8. Add stream-title monitoring.
9. Add trigger evaluation.
10. Add chat message sending and pin management.
11. Run a ten-hour Twitch-only stability test.
12. Add the separate Discord admin process.
13. Add owner-only, read-only Discord commands.
14. Add verified Discord-to-Twitch account linking.
15. Add private broadcaster panels.
16. Add safe configuration editing.
17. Migrate additional broadcasters after V2 is proven stable.