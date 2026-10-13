"""HTTP JSON-RPC with retries and comma-separated failover.

Public `mainnet.base.org` 429s under a live relayer loop. A comma-separated
RPC_URL list (and live-mode public fallbacks) keeps reads/txs moving without
inventing a private key-gated endpoint.
"""
from __future__ import annotations

from typing import Iterable, Optional

from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from web3 import Web3
from web3.providers.rpc import HTTPProvider

from .log import get_logger

log = get_logger("rpc")

#: Measured from the relayer host on 2026-09-11, ordered by observed reliability then
#: latency. 100 sequential eth_chainId calls, errors in parentheses:
#:   tenderly 100/100 (54ms) · blockpi 100/100 (77ms) · zan 100/100 (106ms)
#:   blastapi 100/100 (136ms) · publicnode 100/100 (224ms) · 1rpc 100/100 (295ms)
#:   mainnet.base.org 100/100 (299ms) · nodies 98/100 · drpc 93/100 · meowrpc 4/100
#: Dropped as dead from this host: llamarpc (525), onfinality (429), lava (410),
#: base.blockpi.network/v1/rpc/public (521), omniatech (521), 0xrpc (404),
#: subquery (DNS). meowrpc is last because it 429s almost immediately.
#: For eth_getLogs the practical ceiling is ~1000 blocks per request on most of these
#: (publicnode reaches 10k, nobody reaches 100k) — chunk the range in the caller.
LIVE_FALLBACKS = (
    "https://base.gateway.tenderly.co",
    "https://gateway.tenderly.co/public/base",
    "https://base.public.blockpi.network/v1/rpc/public",
    "https://base-rpc.publicnode.com",
    "https://base-mainnet.public.blastapi.io",
    "https://api.zan.top/base-mainnet",
    "https://1rpc.io/base",
    "https://mainnet.base.org",
    "https://base-pokt.nodies.app",
    "https://base.drpc.org",
    "https://base.meowrpc.com",
)

#: Anything here makes the provider try the NEXT endpoint instead of raising.
#:
#: 403 is the one that mattered: `base-rpc.publicnode.com` rate-limits with **403
#: Forbidden**, not 429. Without it here `_retryable` returned False, the provider raised
#: instead of rotating, and the failure surfaced as "agent <name> work seat failed: 403
#: Client Error" with ten other healthy endpoints sitting unused in the list.
#:
#: 408 and 413 are the same story from a different provider: drpc times out with 408 and
#: mainnet.base.org answers a wide eth_getLogs with 413. Neither is worth re-sending to
#: the SAME host, which is why they are not in the urllib3 status_forcelist below — the
#: right move is to move on.
_RETRYABLE = (
    "403",
    "forbidden",
    "408",
    "413",
    "payload too large",
    "429",
    "too many requests",
    "500",
    "502",
    "503",
    "504",
    "timeout",
    "timed out",
    "connection",
    "reset",
)


def parse_rpc_urls(raw: str) -> list[str]:
    urls = [u.strip() for u in (raw or "").split(",") if u.strip()]
    return urls or ["http://chain:8545"]


def with_live_fallbacks(urls: list[str], live: bool) -> list[str]:
    if not live:
        return list(urls)
    out = list(urls)
    seen = {u.rstrip("/") for u in out}
    for fb in LIVE_FALLBACKS:
        if fb not in seen:
            out.append(fb)
            seen.add(fb)
    return out


def _retryable(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(s in msg for s in _RETRYABLE)


def _session() -> Session:
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=0.55,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=16)
    s = Session()
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


class FailoverHTTPProvider(HTTPProvider):
    """Rotate across RPC_URL list when an endpoint 429s or drops."""

    def __init__(self, urls: Iterable[str], request_kwargs: Optional[dict] = None):
        self._urls = [u.rstrip("/") for u in urls if u]
        if not self._urls:
            raise ValueError("no RPC URLs")
        self._i = 0
        super().__init__(
            self._urls[0],
            request_kwargs=request_kwargs or {"timeout": 30},
            session=_session(),
        )

    def _rotate(self) -> None:
        self._i = (self._i + 1) % len(self._urls)
        nxt = self._urls[self._i]
        self.endpoint_uri = nxt
        log.warning("RPC failover → %s", nxt.split("?")[0])

    def make_request(self, method, params):
        last: Optional[BaseException] = None
        attempts = max(3, len(self._urls) * 2)
        for _ in range(attempts):
            try:
                return super().make_request(method, params)
            except Exception as exc:
                last = exc
                if not _retryable(exc) or len(self._urls) < 2:
                    raise
                self._rotate()
        raise last  # type: ignore[misc]


def connect_web3(urls: Iterable[str], timeout: int = 30) -> Web3:
    return Web3(FailoverHTTPProvider(list(urls), request_kwargs={"timeout": timeout}))
