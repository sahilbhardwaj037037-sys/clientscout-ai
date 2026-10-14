from typing import Protocol


class DiscoveryProvider(Protocol):
    id: str
    async def search(self, query, progress, cache_get, cache_put) -> dict: ...
