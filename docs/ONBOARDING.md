# ChimeBuddy V2 Onboarding and Discord Panels

## Purpose

ChimeBuddy uses a private Discord server as its administration
interface.

A broadcaster connects their Twitch identity, authorizes the Twitch
application, submits a usage request, and waits for developer approval.

After approval, ChimeBuddy creates a private Discord panel for that
broadcaster.

No public website or open router port is required.

---

## Core identity rule

Internal relationships always use IDs:

- Discord user ID
- Twitch user ID
- Discord guild ID
- Discord channel ID
- Discord role ID

Usernames and display names are cosmetic and may change.

One Discord account may link to only one Twitch account.

One Twitch account may link to only one Discord account.

---

## Public Discord onboarding area

New members initially see:

- Rules
- Link Account

The Link Account channel contains a persistent information panel and a
button:

> Connect Twitch & Request ChimeBuddy

The button starts the combined identity-verification, Twitch
authorization, and usage-request process.

---

## Twitch authorization process

When the user presses the button:

1. ChimeBuddy identifies the Discord user from the interaction.
2. ChimeBuddy verifies that the user is not blacklisted.
3. ChimeBuddy verifies that no linking operation is already active.
4. Twitch Device Code authorization begins.
5. Discord displays the activation URL and code ephemerally.
6. The user signs into the correct Twitch account.
7. Twitch grants the required scopes.
8. ChimeBuddy validates the returned access token.
9. ChimeBuddy obtains the permanent Twitch user ID.
10. Discord and Twitch identities are linked in SQLite.
11. The broadcaster credential is stored securely.
12. The Twitch Linked role is assigned.
13. A pending ChimeBuddy usage request is created.
14. The developer review message is created.

The activation code, access token, refresh token, and client secret must
never appear in public channels or logs.

The linking deadline must use Twitch's returned expiration value.

---

## Discord roles

### Twitch Linked

Means:

- Twitch account ownership was verified.
- Discord and Twitch IDs are linked.

It does not mean that ChimeBuddy is active in the Twitch channel.

### ChimeBuddy Broadcaster

Means:

- The usage request was approved.
- Broadcaster authorization is healthy.
- The private Discord panel was provisioned.
- The broadcaster is enabled in the Twitch worker.

This role may unlock shared broadcaster support areas.

It must not grant access to every private broadcaster panel.

---

## Usage request review

Every completed authorization creates a message in a private developer
review channel.

The review message displays:

- Request ID
- Discord mention and Discord user ID
- Twitch login and Twitch user ID
- Account-link status
- Authorization status
- Granted scopes
- Request timestamp
- Current request status
- Previous request information, if relevant

The review message contains persistent buttons:

- Approve
- Reject
- Blacklist

Only the configured developer Discord user may operate these actions.

The database is the source of truth. The Discord message is only an
interface.

---

## Approve action

Approve opens a modal with an optional note for the requester.

After confirmation:

1. The pending request is claimed atomically.
2. The request enters the approving state.
3. The ChimeBuddy Broadcaster role is assigned.
4. The private Discord panel is provisioned.
5. The Discord panel channel ID is stored.
6. The broadcaster becomes enabled.
7. The request becomes active.
8. The review message is updated.
9. Decision buttons are disabled.
10. The broadcaster is notified in the private panel.
11. A DM notification may also be attempted.

If panel provisioning fails:

- the broadcaster must not become active;
- the failure must be logged;
- the request enters provisioning_failed;
- a developer-only Retry Provisioning action becomes available.

Repeated approval clicks must not create duplicate channels.

---

## Reject action

Reject opens a modal with an optional requester-facing reason.

After confirmation:

- the request becomes rejected;
- no private panel is created;
- the ChimeBuddy Broadcaster role is not assigned;
- the Twitch Linked identity may remain;
- stored broadcaster OAuth credentials are removed;
- the review message is updated;
- decision buttons are disabled;
- a DM notification is attempted;
- the result remains available through /request-status.

A rejected user may request access again unless blacklisted.

---

## Blacklist action

Blacklist requires:

- an internal reason;
- explicit confirmation;
- an optional safe requester-facing message.

Blacklisting applies to both:

- Discord user ID
- Twitch user ID

After confirmation:

- pending requests are blocked;
- active broadcaster access is disabled;
- stored broadcaster OAuth credentials are removed;
- new linking and usage requests are denied;
- an audit record is preserved;
- the review message is updated;
- a safe DM notification may be attempted.

Internal blacklist reasons must never be shown to the requester.

No public blacklist role should be assigned.

Unblocking is a separate developer-only action.

---

## Request statuses

Initial workflow:

- pending
- approving
- provisioning
- active
- rejected
- blacklisted
- provisioning_failed
- suspended
- reauthorization_required

Valid primary path:

pending -> approving -> provisioning -> active

Alternative paths:

pending -> rejected
pending -> blacklisted
provisioning -> provisioning_failed
provisioning_failed -> provisioning
active -> suspended
active -> reauthorization_required

Only valid state transitions may be accepted.

---

## Private panel permissions

The private channel is created under an administration-panel category.

Channel access:

- @everyone: denied
- requesting broadcaster: allowed
- ChimeBuddy Discord bot: allowed
- guild owner: no explicit overwrite required

The shared ChimeBuddy Broadcaster role must not automatically see all
private channels.

Server administrators and the guild owner may still bypass normal
channel restrictions.

---

## Opening broadcaster panel

The first version is read-only.

Example:

ChimeBuddy — anonym_poal

- Status: Active
- Twitch authorization: Healthy
- Twitch identity: anonym_poal
- Title triggers: 1 enabled
- EventSub chat reception: Enabled
- Chat message sending: Enabled
- Pinning: Enabled

Initial controls:

- Refresh
- View Triggers
- View Authorization
- View Errors

Editable controls are added only after ownership and permission checks
are proven reliable.

---

## Twitch activation checklist

Before activation:

- Twitch identity validated
- channel:bot granted
- broadcaster credential stored
- ChimeBuddy moderator status explained or verified
- private Discord panel created
- broadcaster enabled in SQLite
- Twitch worker subscribed to the channel

The broadcaster should be instructed to run:

/mod chimebuddy

Pinning may fail if the bot lacks moderation permission.

---

## Notifications

### Pending

The user receives an ephemeral confirmation and may use
/request-status.

### Approved

The primary notification appears in the newly created private panel.

A DM may also be attempted.

### Rejected

A DM is attempted.

If DMs are unavailable, /request-status still displays the decision.

### Blacklisted

Only a safe requester-facing message may be sent.

Internal reasons remain private.

---

## Reliability requirements

- Persistent buttons use stable custom IDs.
- Persistent views are registered again after restart.
- Only one active link session exists per Discord user.
- Only one pending request exists per linked identity.
- Decision updates use conditional database writes.
- Double-clicking cannot create duplicate panels.
- Deleted Discord messages do not delete database state.
- Missing Discord channels can be recreated.
- Revoked Twitch authorization disables functionality safely.
- OAuth tokens never appear in logs or Discord.
- External Discord operations are retryable.
- Errors are visible to the developer.

---

## Implementation priority

### Phase 1 — Data model

- Onboarding request states
- Link sessions
- Review-message identifiers
- Panel-channel identifiers
- Blacklist entries
- Decision audit data

### Phase 2 — Public linking panel

- Persistent Connect Twitch & Request ChimeBuddy button
- Ephemeral instructions
- Duplicate-session prevention

### Phase 3 — Twitch Device Code integration

- Start authorization
- Poll safely
- Validate Twitch identity
- Store credential
- Link Discord and Twitch IDs
- Assign Twitch Linked role
- Create pending request

### Phase 4 — Developer review queue

- Review message
- Approve modal
- Reject modal
- Blacklist modal
- Persistent decision buttons
- Requester notifications
- /request-status

### Phase 5 — Private panel provisioning

- Create private channel
- Apply permission overwrites
- Assign ChimeBuddy Broadcaster role
- Store panel channel ID
- Read-only opening panel
- Retry failed provisioning

### Phase 6 — Live Twitch reconciliation

- Detect newly enabled broadcasters
- Add EventSub subscriptions without restarting
- Stop handling disabled broadcasters safely
- Report authorization failures

### Phase 7 — Trigger administration

- View triggers
- Safely simulate title matching
- Create triggers
- Edit triggers
- Enable or disable triggers
- Delete triggers
- View trigger runtime errors

### Phase 8 — Additional modules

- Twitch commands
- Moderator and VIP permissions
- Stream information
- Statistics
- Error dashboard
- Future optional modules

---

## Initial success criteria

The onboarding milestone is successful when:

1. A Discord member presses the linking button.
2. They authorize the correct Twitch account.
3. Discord and Twitch IDs are linked.
4. A pending request appears for the developer.
5. The developer approves it.
6. A private panel is created exactly once.
7. The broadcaster receives the correct roles.
8. The Twitch worker begins handling the broadcaster without restart.
9. The broadcaster can view their settings.
10. Other broadcasters cannot view that private panel.