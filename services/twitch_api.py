import os
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

    async def _get_app_access_token(self, session: aiohttp.ClientSession) -> str:
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials"
        }
        async with session.post(TOKEN_URL, data=payload) as response:
            if response.status == 200:
                data = await response.json()
                self._token = data.get("access_token")
                expires_in = data.get("expires_in", 5184000)
                self._expires_at = time.time() + expires_in
                return self._token

            response_text = await response.text()
            raise Exception(f"Failed to fetch token: {response.status} - {response_text}")

    async def _get_token(self, session: aiohttp.ClientSession) -> str:
        current_time = time.time()

        if self._token and current_time < (self._expires_at -300):
            return self._token
        # Use the App Access Token helper for helix calls
        return await self._get_app_access_token(session)

    async def get_stream(self, session: aiohttp.ClientSession, streamer_login: str) -> dict | None:
        token = await self._get_token(session)
        headers = {"Client-ID": self.client_id, "Authorization": f"Bearer {token}"}
        params = {"user_login": streamer_login}

        async with session.get(HELIX_STREAMS, headers=headers, params=params, timeout=20) as r:
            data = await r.json()
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
            if r.status != 200:
                raise RuntimeError(f"Twitch helix error {r.status}: {data}")

            items = data.get("data", [])
            out = {}
            for it in items:
                login = (it.get("user_login") or "").lower()
                if login:
                    out[login] = it
            return out