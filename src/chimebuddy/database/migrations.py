from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]


MIGRATIONS = (
    Migration(
        version=1,
        name="create_app_settings",
        statements=(
            """
            CREATE TABLE app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
        ),
    ),
    Migration(
        version=2,
        name="create_identity_and_broadcaster_tables",
        statements=(
            """
            CREATE TABLE twitch_accounts (
                twitch_user_id TEXT PRIMARY KEY,
                login TEXT NOT NULL COLLATE NOCASE,
                display_name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                CHECK (length(trim(twitch_user_id)) > 0),
                CHECK (length(trim(login)) > 0),
                CHECK (length(trim(display_name)) > 0)
            )
            """,
            """
            CREATE UNIQUE INDEX twitch_accounts_login_nocase
            ON twitch_accounts(login COLLATE NOCASE)
            """,
            """
            CREATE TABLE discord_accounts (
                discord_user_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                display_name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                CHECK (length(trim(discord_user_id)) > 0),
                CHECK (length(trim(username)) > 0),
                CHECK (length(trim(display_name)) > 0)
            )
            """,
            """
            CREATE TABLE account_links (
                twitch_user_id TEXT PRIMARY KEY,
                discord_user_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                verification_method TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                verified_at TEXT,
                revoked_at TEXT,

                FOREIGN KEY (twitch_user_id)
                    REFERENCES twitch_accounts(twitch_user_id)
                    ON DELETE CASCADE,

                FOREIGN KEY (discord_user_id)
                    REFERENCES discord_accounts(discord_user_id)
                    ON DELETE CASCADE,

                CHECK (
                    status IN ('pending', 'verified', 'revoked')
                )
            )
            """,
            """
            CREATE INDEX account_links_discord_user_id_idx
            ON account_links(discord_user_id)
            """,
            """
            CREATE TABLE broadcasters (
                twitch_user_id TEXT PRIMARY KEY,
                owner_discord_user_id TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (twitch_user_id)
                    REFERENCES twitch_accounts(twitch_user_id)
                    ON DELETE RESTRICT,

                FOREIGN KEY (owner_discord_user_id)
                    REFERENCES discord_accounts(discord_user_id)
                    ON DELETE RESTRICT,

                CHECK (enabled IN (0, 1))
            )
            """,
            """
            CREATE INDEX broadcasters_owner_discord_user_id_idx
            ON broadcasters(owner_discord_user_id)
            """,
        ),
    ),
        Migration(
        version=3,
        name="create_trigger_tables",
        statements=(
            """
            CREATE TABLE triggers (
                trigger_id INTEGER PRIMARY KEY AUTOINCREMENT,
                broadcaster_twitch_user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'stream_title',
                match_type TEXT NOT NULL DEFAULT 'contains',
                expression TEXT NOT NULL,
                response_message TEXT NOT NULL,
                pin_message INTEGER NOT NULL DEFAULT 1,
                priority INTEGER NOT NULL DEFAULT 100,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (broadcaster_twitch_user_id)
                    REFERENCES broadcasters(twitch_user_id)
                    ON DELETE CASCADE,

                CHECK (source IN ('stream_title')),
                CHECK (match_type IN ('contains', 'exact')),
                CHECK (length(trim(name)) > 0),
                CHECK (length(trim(expression)) > 0),
                CHECK (length(trim(response_message)) > 0),
                CHECK (pin_message IN (0, 1)),
                CHECK (priority >= 0),
                CHECK (enabled IN (0, 1))
            )
            """,
            """
            CREATE UNIQUE INDEX triggers_broadcaster_name_nocase
            ON triggers(
                broadcaster_twitch_user_id,
                name COLLATE NOCASE
            )
            """,
            """
            CREATE INDEX triggers_broadcaster_enabled_priority_idx
            ON triggers(
                broadcaster_twitch_user_id,
                enabled,
                priority
            )
            """,
            """
            CREATE TABLE trigger_runtime_state (
                trigger_id INTEGER PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'inactive',
                last_title TEXT,
                message_id TEXT,
                is_pinned INTEGER NOT NULL DEFAULT 0,
                activated_at TEXT,
                operation_started_at TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_error TEXT,

                FOREIGN KEY (trigger_id)
                    REFERENCES triggers(trigger_id)
                    ON DELETE CASCADE,

                CHECK (
                    status IN (
                        'inactive',
                        'activating',
                        'active',
                        'deactivating',
                        'error'
                    )
                ),
                CHECK (is_pinned IN (0, 1))
            )
            """,
        ),
    ),
    Migration(
        version=4,
        name="create_oauth_credentials",
        statements=(
            """
            CREATE TABLE oauth_credentials (
                twitch_user_id TEXT NOT NULL,
                credential_kind TEXT NOT NULL,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                scopes_json TEXT NOT NULL DEFAULT '[]',
                expires_at INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                PRIMARY KEY (
                    twitch_user_id,
                    credential_kind
                ),

                FOREIGN KEY (twitch_user_id)
                    REFERENCES twitch_accounts(twitch_user_id)
                    ON DELETE CASCADE,

                CHECK (
                    credential_kind IN (
                        'bot',
                        'broadcaster'
                    )
                ),
                CHECK (length(trim(access_token)) > 0),
                CHECK (length(trim(refresh_token)) > 0),
                CHECK (expires_at > 0)
            )
            """,
            """
            CREATE INDEX oauth_credentials_kind_idx
            ON oauth_credentials(credential_kind)
            """,
        ),
    ),
    Migration(
        version=5,
        name="create_discord_onboarding_tables",
        statements=(
            """
            CREATE UNIQUE INDEX
                account_links_discord_user_id_unique_idx
            ON account_links(discord_user_id)
            """,
            """
            CREATE TABLE account_link_sessions (
                session_id TEXT PRIMARY KEY,
                discord_user_id TEXT NOT NULL,
                twitch_user_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                requested_scopes_json TEXT NOT NULL DEFAULT '[]',
                expires_at INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                last_error TEXT,

                FOREIGN KEY (discord_user_id)
                    REFERENCES discord_accounts(discord_user_id)
                    ON DELETE RESTRICT,

                FOREIGN KEY (twitch_user_id)
                    REFERENCES twitch_accounts(twitch_user_id)
                    ON DELETE SET NULL,

                CHECK (length(trim(session_id)) > 0),
                CHECK (expires_at > 0),
                CHECK (
                    status IN (
                        'pending',
                        'authorized',
                        'expired',
                        'cancelled',
                        'failed'
                    )
                )
            )
            """,
            """
            CREATE UNIQUE INDEX
                account_link_sessions_pending_discord_idx
            ON account_link_sessions(discord_user_id)
            WHERE status = 'pending'
            """,
            """
            CREATE INDEX
                account_link_sessions_status_expiry_idx
            ON account_link_sessions(status, expires_at)
            """,
            """
            CREATE TABLE broadcaster_requests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                twitch_user_id TEXT NOT NULL,
                discord_user_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',

                review_guild_id TEXT,
                review_channel_id TEXT,
                review_message_id TEXT,

                decision_reason TEXT,
                requester_message TEXT,
                decided_by_discord_user_id TEXT,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                decided_at TEXT,
                provisioned_at TEXT,

                FOREIGN KEY (twitch_user_id)
                    REFERENCES twitch_accounts(twitch_user_id)
                    ON DELETE RESTRICT,

                FOREIGN KEY (discord_user_id)
                    REFERENCES discord_accounts(discord_user_id)
                    ON DELETE RESTRICT,

                CHECK (
                    status IN (
                        'pending',
                        'approving',
                        'provisioning',
                        'active',
                        'rejected',
                        'blacklisted',
                        'provisioning_failed',
                        'suspended',
                        'reauthorization_required'
                    )
                )
            )
            """,
            """
            CREATE INDEX
                broadcaster_requests_status_created_idx
            ON broadcaster_requests(status, created_at)
            """,
            """
            CREATE UNIQUE INDEX
                broadcaster_requests_open_twitch_idx
            ON broadcaster_requests(twitch_user_id)
            WHERE status IN (
                'pending',
                'approving',
                'provisioning',
                'active',
                'provisioning_failed',
                'suspended',
                'reauthorization_required'
            )
            """,
            """
            CREATE UNIQUE INDEX
                broadcaster_requests_open_discord_idx
            ON broadcaster_requests(discord_user_id)
            WHERE status IN (
                'pending',
                'approving',
                'provisioning',
                'active',
                'provisioning_failed',
                'suspended',
                'reauthorization_required'
            )
            """,
            """
            CREATE TABLE broadcaster_panels (
                twitch_user_id TEXT PRIMARY KEY,
                request_id INTEGER NOT NULL UNIQUE,
                discord_guild_id TEXT NOT NULL,
                discord_channel_id TEXT NOT NULL UNIQUE,
                opening_message_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (twitch_user_id)
                    REFERENCES broadcasters(twitch_user_id)
                    ON DELETE CASCADE,

                FOREIGN KEY (request_id)
                    REFERENCES broadcaster_requests(request_id)
                    ON DELETE RESTRICT,

                CHECK (length(trim(discord_guild_id)) > 0),
                CHECK (length(trim(discord_channel_id)) > 0)
            )
            """,
            """
            CREATE TABLE broadcaster_blacklist (
                blacklist_id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_user_id TEXT,
                twitch_user_id TEXT,
                internal_reason TEXT NOT NULL,
                requester_message TEXT,
                created_by_discord_user_id TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                revoked_at TEXT,
                revoked_by_discord_user_id TEXT,
                revocation_reason TEXT,

                CHECK (
                    discord_user_id IS NOT NULL
                    OR twitch_user_id IS NOT NULL
                ),
                CHECK (
                    length(trim(internal_reason)) > 0
                ),
                CHECK (
                    length(
                        trim(created_by_discord_user_id)
                    ) > 0
                ),
                CHECK (active IN (0, 1))
            )
            """,
            """
            CREATE UNIQUE INDEX
                broadcaster_blacklist_active_discord_idx
            ON broadcaster_blacklist(discord_user_id)
            WHERE
                active = 1
                AND discord_user_id IS NOT NULL
            """,
            """
            CREATE UNIQUE INDEX
                broadcaster_blacklist_active_twitch_idx
            ON broadcaster_blacklist(twitch_user_id)
            WHERE
                active = 1
                AND twitch_user_id IS NOT NULL
            """,
            """
            CREATE TABLE onboarding_request_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT,
                actor_discord_user_id TEXT,
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (request_id)
                    REFERENCES broadcaster_requests(request_id)
                    ON DELETE CASCADE,

                CHECK (length(trim(event_type)) > 0)
            )
            """,
            """
            CREATE INDEX
                onboarding_request_events_request_idx
            ON onboarding_request_events(
                request_id,
                created_at
            )
            """,
        ),
    ),
    Migration(
        version=6,
        name="create_runtime_health_tables",
        statements=(
            """
            CREATE TABLE runtime_health (
                component TEXT NOT NULL,
                subject_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}',
                last_success_at TEXT,
                last_failure_at TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                PRIMARY KEY (component, subject_id),

                CHECK (length(trim(component)) > 0),
                CHECK (length(trim(status)) > 0)
            )
            """,
            """
            CREATE TABLE runtime_error_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                component TEXT NOT NULL,
                subject_id TEXT NOT NULL DEFAULT '',
                error_code TEXT NOT NULL,
                safe_message TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                CHECK (length(trim(component)) > 0),
                CHECK (length(trim(error_code)) > 0),
                CHECK (length(trim(safe_message)) > 0)
            )
            """,
            """
            CREATE INDEX runtime_error_events_subject_created_idx
            ON runtime_error_events(
                subject_id,
                created_at DESC,
                event_id DESC
            )
            """,
        ),
    ),
    Migration(
        version=7,
        name="create_custom_command_tables",
        statements=(
            """
            CREATE TABLE custom_commands (
                command_id INTEGER PRIMARY KEY AUTOINCREMENT,
                broadcaster_twitch_user_id TEXT NOT NULL,
                name TEXT NOT NULL COLLATE NOCASE,
                response_message TEXT NOT NULL,
                permission TEXT NOT NULL DEFAULT 'everyone',
                cooldown_seconds INTEGER NOT NULL DEFAULT 30,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (broadcaster_twitch_user_id)
                    REFERENCES broadcasters(twitch_user_id)
                    ON DELETE CASCADE,

                CHECK (length(trim(name)) > 0),
                CHECK (length(trim(response_message)) > 0),
                CHECK (
                    permission IN (
                        'everyone',
                        'subscriber',
                        'vip',
                        'moderator',
                        'broadcaster'
                    )
                ),
                CHECK (cooldown_seconds >= 0),
                CHECK (enabled IN (0, 1))
            )
            """,
            """
            CREATE UNIQUE INDEX
                custom_commands_broadcaster_name_nocase_idx
            ON custom_commands(
                broadcaster_twitch_user_id,
                name COLLATE NOCASE
            )
            """,
            """
            CREATE INDEX
                custom_commands_broadcaster_enabled_idx
            ON custom_commands(
                broadcaster_twitch_user_id,
                enabled,
                command_id
            )
            """,
        ),
    ),
)
