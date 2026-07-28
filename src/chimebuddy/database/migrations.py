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
)