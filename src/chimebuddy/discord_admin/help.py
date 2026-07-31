from enum import StrEnum

import discord


class HelpLanguage(StrEnum):
    ENGLISH = "en"
    HUNGARIAN = "hu"


def preferred_help_language(
    locale,
) -> HelpLanguage:
    locale_text = str(locale or "").casefold()

    if locale_text.startswith("hu"):
        return HelpLanguage.HUNGARIAN

    return HelpLanguage.ENGLISH


def build_help_embed(
    language: HelpLanguage,
) -> discord.Embed:
    selected = HelpLanguage(language)

    if selected is HelpLanguage.HUNGARIAN:
        return _build_hungarian_help_embed()

    return _build_english_help_embed()


def _build_english_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Welcome to ChimeBuddy",
        description=(
            "ChimeBuddy is a Twitch automation bot controlled "
            "through a private Discord administration panel.\n\n"
            "The project is currently in a limited testing phase, "
            "so features and wording may still change."
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="Getting started",
        value=(
            "1. Use the onboarding panel to connect Twitch.\n"
            "2. Authorize the broadcaster account you want to use.\n"
            "3. Check the displayed account and submit your request.\n"
            "4. After approval, use your private broadcaster channel."
        ),
        inline=False,
    )
    embed.add_field(
        name="Your broadcaster panel",
        value=(
            "**Refresh status** reloads current service information.\n"
            "**Pause / Resume** temporarily stops or starts ChimeBuddy "
            "without deleting your settings.\n"
            "**Title triggers** manages automatic messages based on "
            "your Twitch stream title.\n"
            "**Reconnect Twitch** appears when authorization must be "
            "renewed."
        ),
        inline=False,
    )
    embed.add_field(
        name="Title triggers",
        value=(
            "A trigger checks whether your stream title contains or "
            "exactly matches an expression. When it activates, "
            "ChimeBuddy posts your configured chat message and can pin "
            "it. The message is cleaned up when the trigger deactivates."
        ),
        inline=False,
    )
    embed.add_field(
        name="Privacy and safety",
        value=(
            "Authorization tokens are never displayed in Discord. "
            "Do not share Twitch activation codes with anyone. "
            "Sensitive administration responses are private, and your "
            "broadcaster channel is visible only to you and the developer."
        ),
        inline=False,
    )
    embed.add_field(
        name="Need assistance?",
        value=(
            "Write in your private broadcaster channel or contact the "
            "ChimeBuddy developer. When reporting a problem, include what "
            "you pressed and the safe error message you received—never "
            "send access tokens."
        ),
        inline=False,
    )
    embed.set_footer(
        text="Choose a language below • ChimeBuddy closed beta"
    )
    return embed


def _build_hungarian_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Üdvözöl a ChimeBuddy!",
        description=(
            "A ChimeBuddy egy Twitch automatizációs bot, amelyet egy "
            "privát Discord adminisztrációs panelen kezelhetsz.\n\n"
            "A projekt jelenleg korlátozott tesztelési fázisban van, "
            "ezért a funkciók és a szövegek még változhatnak."
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="Első lépések",
        value=(
            "1. A beléptetőpanelen keresztül csatlakoztasd a Twitch-fiókodat.\n"
            "2. A használni kívánt közvetítői fiókkal engedélyezd a botot.\n"
            "3. Ellenőrizd a megjelenített fiókot, majd küldd el a kérelmedet.\n"
            "4. Jóváhagyás után használd a privát közvetítői csatornádat."
        ),
        inline=False,
    )
    embed.add_field(
        name="A közvetítői paneled",
        value=(
            "Az **Állapot frissítése** betölti a szolgáltatás aktuális adatait.\n"
            "A **Szüneteltetés / Folytatás** ideiglenesen leállítja vagy "
            "elindítja a ChimeBuddyt a beállításaid törlése nélkül.\n"
            "A **Címaktiválók** a Twitch-közvetítés címe alapján kezeli az "
            "automatikus üzeneteket.\n"
            "A **Twitch újracsatlakoztatása** akkor jelenik meg, amikor az "
            "engedélyt meg kell újítani."
        ),
        inline=False,
    )
    embed.add_field(
        name="Címaktiválók",
        value=(
            "Az aktiváló ellenőrzi, hogy a közvetítés címe tartalmazza-e, "
            "vagy pontosan megegyezik-e a megadott kifejezéssel. Aktiváláskor "
            "a ChimeBuddy elküldi a beállított chatüzenetet, és igény szerint "
            "rögzíti is. Kikapcsoláskor az üzenetet eltávolítja."
        ),
        inline=False,
    )
    embed.add_field(
        name="Adatvédelem és biztonság",
        value=(
            "A hitelesítési tokenek soha nem jelennek meg a Discordon. "
            "A Twitch aktiválási kódodat ne oszd meg senkivel. Az érzékeny "
            "adminisztrációs válaszok privátak, a közvetítői csatornádat pedig "
            "csak te és a fejlesztő láthatja."
        ),
        inline=False,
    )
    embed.add_field(
        name="Segítségre van szükséged?",
        value=(
            "Írj a privát közvetítői csatornádba, vagy keresd meg a ChimeBuddy "
            "fejlesztőjét. Hibajelentéskor írd le, mire kattintottál, és add meg "
            "a kapott biztonságos hibaüzenetet—hozzáférési tokent soha ne küldj."
        ),
        inline=False,
    )
    embed.set_footer(
        text="Válassz nyelvet lent • ChimeBuddy zárt béta"
    )
    return embed


class HelpLanguageSelect(discord.ui.Select):
    def __init__(
        self,
        language: HelpLanguage,
    ) -> None:
        selected = HelpLanguage(language)
        super().__init__(
            placeholder="Language / Nyelv",
            min_values=1,
            max_values=1,
            options=(
                discord.SelectOption(
                    label="English",
                    value=HelpLanguage.ENGLISH.value,
                    emoji="🇬🇧",
                    default=(
                        selected is HelpLanguage.ENGLISH
                    ),
                ),
                discord.SelectOption(
                    label="Magyar",
                    value=HelpLanguage.HUNGARIAN.value,
                    emoji="🇭🇺",
                    default=(
                        selected is HelpLanguage.HUNGARIAN
                    ),
                ),
            ),
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        view = self.view

        if not isinstance(view, HelpLanguageView):
            return

        await view.controller.change_language(
            interaction,
            HelpLanguage(self.values[0]),
            requested_by_user_id=(
                view.requested_by_user_id
            ),
        )


class HelpLanguageView(discord.ui.View):
    def __init__(
        self,
        *,
        controller: "DiscordHelpController",
        language: HelpLanguage,
        requested_by_user_id: int,
    ) -> None:
        super().__init__(timeout=900)
        self.controller = controller
        self.requested_by_user_id = int(
            requested_by_user_id
        )
        self.add_item(HelpLanguageSelect(language))

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id == self.requested_by_user_id:
            return True

        await interaction.response.send_message(
            "Open your own private help message with `/help`.",
            ephemeral=True,
        )
        return False


class DiscordHelpController:
    """Renders private bilingual help messages."""

    async def show_help(
        self,
        interaction: discord.Interaction,
    ) -> None:
        language = preferred_help_language(
            getattr(interaction, "locale", None)
        )
        await interaction.response.send_message(
            embed=build_help_embed(language),
            view=self.create_view(
                language,
                requested_by_user_id=interaction.user.id,
            ),
            ephemeral=True,
        )

    async def change_language(
        self,
        interaction: discord.Interaction,
        language: HelpLanguage,
        *,
        requested_by_user_id: int,
    ) -> None:
        await interaction.response.edit_message(
            embed=build_help_embed(language),
            view=self.create_view(
                language,
                requested_by_user_id=requested_by_user_id,
            ),
        )

    def create_view(
        self,
        language: HelpLanguage,
        *,
        requested_by_user_id: int,
    ) -> HelpLanguageView:
        return HelpLanguageView(
            controller=self,
            language=language,
            requested_by_user_id=requested_by_user_id,
        )
