"""Riot account-v1 / match-v5 client. Server-side only, conservative throttling."""
import asyncio
import os
from urllib.parse import quote
import httpx

class RiotError(Exception):
    pass

class RiotClient:
    def __init__(self, api_key=None, transport=None):
        self.api_key = api_key if api_key is not None else os.getenv("RIOT_API_KEY", "")
        self.delay = max(1.2, float(os.getenv("RIOT_MIN_REQUEST_INTERVAL", "1.4")))
        self._last_call = 0.0
        self._lock = asyncio.Lock()
        self.client = httpx.AsyncClient(timeout=22, transport=transport)

    async def close(self):
        await self.client.aclose()

    async def get(self, url, params=None):
        if not self.api_key:
            raise RiotError("Riot API 키가 설정되지 않았습니다.")
        for trial in range(4):
            async with self._lock:
                loop = asyncio.get_running_loop()
                remaining = self.delay - (loop.time() - self._last_call)
                if remaining > 0:
                    await asyncio.sleep(remaining)
                self._last_call = loop.time()
                try:
                    response = await self.client.get(url, params=params, headers={"X-Riot-Token": self.api_key})
                except httpx.HTTPError as exc:
                    if trial == 3:
                        raise RiotError("Riot 네트워크 요청에 실패했습니다.") from exc
                    await asyncio.sleep(2**trial)
                    continue
            if response.status_code == 429:
                try:
                    retry = float(response.headers.get("Retry-After", "4"))
                except ValueError:
                    retry = 4
                if trial < 3:
                    await asyncio.sleep(min(120, max(2, retry)))
                    continue
                raise RiotError("Riot API 호출 제한(429). 나중에 재시도합니다.")
            if response.status_code in (401,403):
                raise RiotError("Riot API 키가 만료되었거나 권한이 없습니다.")
            if response.status_code == 404:
                raise RiotError("등록한 라이엇 ID 또는 전적을 찾을 수 없습니다.")
            if response.status_code >= 500:
                if trial < 3:
                    await asyncio.sleep(2**trial)
                    continue
                raise RiotError("Riot 서버가 일시적으로 응답하지 않습니다.")
            if response.status_code != 200:
                raise RiotError(f"Riot API 오류: HTTP {response.status_code}")
            return response.json()
        raise RiotError("Riot 응답을 가져오지 못했습니다.")

    async def lookup(self, game_name, tag_line):
        name, tag = quote(game_name, safe=""), quote(tag_line, safe="")
        return await self.get(f"https://asia.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}")

    async def match_ids(self, puuid, start_time, start=0, count=100):
        return await self.get(
            f"https://asia.api.riotgames.com/lol/match/v5/matches/by-puuid/{quote(puuid,safe='')}/ids",
            {"startTime": start_time, "start": start, "count": min(100, count)}
        )

    async def match(self, match_id):
        return await self.get(f"https://asia.api.riotgames.com/lol/match/v5/matches/{quote(match_id, safe='')}")
