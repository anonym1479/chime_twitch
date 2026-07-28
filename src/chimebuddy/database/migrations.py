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
)