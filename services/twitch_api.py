import time
import aiohttp

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
HELIX_STREAMS = "https://api.twitch.tv/helix/streams"

class TwitchAPI:
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: str | None = None
        self._expires_at: float = 0.0

    async def _get_token(self, session: aiohttp.ClientSession) -> str:
        if self._token and time.time() < (self._expires_at - 60):
            return self._token

        params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
        }
        async with session.post(TOKEN_URL, params=params, timeout=20) as r:
            data = await r.json()
            if r.status != 200:
                raise RuntimeError(f"Twitch token error {r.status}: {data}")

            self._token = data["access_token"]
            expires_in = int(data.get("expires_in", 3600))
            self._expires_at = time.time() + expires_in
            return self._token

    def _invalidate_token(self) -> None:
        self._token = None
        self._expires_at = 0.0

    async def get_stream(self, session: aiohttp.ClientSession, streamer_login: str) -> dict | None:
        token = await self._get_token(session)
        headers = {"Client-ID": self.client_id, "Authorization": f"Bearer {token}"}
        params = {"user_login": streamer_login}

        async with session.get(HELIX_STREAMS, headers=headers, params=params, timeout=20) as r:
            data = await r.json()

            if r.status == 401:
                self._invalidate_token()
                token = await self._get_token(session)
                headers["Authorization"] = f"Bearer {token}"

                async with session.get(HELIX_STREAMS, headers=headers, params=params, timeout=20) as r2:
                    data2 = await r2.json()
                    if r2.status != 200:
                        raise RuntimeError(f"Twitch helix error {r2.status}: {data2}")
                    items = data2.get("data", [])
                    return items[0] if items else None

            if r.status != 200:
                raise RuntimeError(f"Twitch helix error {r.status}: {data}")

            items = data.get("data", [])
            return items[0] if items else None

    async def get_streams(self, session: aiohttp.ClientSession, streamer_logins: list[str]) -> dict[str, dict]:
        if not streamer_logins:
            return {}

        token = await self._get_token(session)
        headers = {"Client-ID": self.client_id, "Authorization": f"Bearer {token}"}

        params = []
        for login in streamer_logins[:100]:
            params.append(("user_login", login))

        async with session.get(HELIX_STREAMS, headers=headers, params=params, timeout=20) as r:
            data = await r.json()

            if r.status == 401:
                self._invalidate_token()
                token = await self._get_token(session)
                headers["Authorization"] = f"Bearer {token}"

                async with session.get(HELIX_STREAMS, headers=headers, params=params, timeout=20) as r2:
                    data2 = await r2.json()
                    if r2.status != 200:
                        raise RuntimeError(f"Twitch helix error {r2.status}: {data2}")
                    items = data2.get("data", [])
                    out = {}
                    for it in items:
                        login = (it.get("user_login") or "").lower()
                        if login:
                            out[login] = it
                    return out

            if r.status != 200:
                raise RuntimeError(f"Twitch helix error {r.status}: {data}")

            items = data.get("data", [])
            out = {}
            for it in items:
                login = (it.get("user_login") or "").lower()
                if login:
                    out[login] = it
            return out