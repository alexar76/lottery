"""Unified multi-chain network selection + health-checked RPC failover (EVM **and** Solana).

This is the single source of truth for *which chain the ecosystem talks to* and *how it
reaches it reliably*. The AIMarket stack is multi-chain: the same escrow + lottery exist
as EVM contracts (Base/Ethereum/Arbitrum — `contracts/evm`, `lottery/contracts`,
`acex/contracts/evm`) **and** as Solana programs (`contracts/solana`). At runtime exactly
one network is active; our live demo deployment is on **Base**.

Two responsibilities:

1. **Network registry + selection.** A preset per network (EVM or Solana) carrying its
   kind, chain-id / cluster, a *priority-ordered* RPC list, native token, explorer, and our
   deployed contract/program addresses. The active network is chosen by env var, defaulting
   to **Base with our demo contracts**. Any other EVM network can be added purely via env
   (no code change): set ``AIMARKET_CHAIN``, ``AIMARKET_CHAIN_KIND=evm``,
   ``AIMARKET_CHAIN_ID`` and ``AIMARKET_RPC_<ID>``.

2. **Health-checked RPC failover.** Both EVM and Solana speak JSON-RPC 2.0 over HTTP, so a
   single :class:`RpcPool` serves both — only the health probe differs (``eth_chainId`` vs
   ``getHealth``). The pool always prefers the **highest-priority endpoint that is healthy**
   (so a working default wins), fails over to the next on error, and *re-probes* a demoted
   endpoint after a cooldown so it **returns to the preferred default once it recovers**.
   Every call is bounded by a short timeout, so an offline environment fails fast instead
   of hanging.

The module is dependency-free (stdlib ``urllib`` transport, injectable for tests) so it can
be vendored verbatim into standalone services (e.g. alien-monitor) and imported directly by
``aimarket_hub`` consumers (the hub, and web/backend which already imports ``aimarket_hub``).

Environment contract
--------------------
``AIMARKET_CHAIN`` / ``AIMARKET_NETWORK``  active network id (default ``base``).
``AIMARKET_TESTNET`` = 1|true              use the testnet variant of the active network.
``AIMARKET_RPC_<ID>``                       comma-separated RPC URLs, **priority order**, e.g.
                                            ``AIMARKET_RPC_BASE="https://my.node,https://backup"``.
                                            Tried ahead of the built-in public presets (deduped),
                                            so your node becomes the preferred default.
``AIMARKET_CHAIN_KIND`` / ``AIMARKET_CHAIN_ID``  define an ad-hoc EVM network not in the presets.
``AIMARKET_ADDR_<ID>_<NAME>``               override/add a contract address for a network, e.g.
                                            ``AIMARKET_ADDR_BASE_ESCROW=0x...``.
``AIMARKET_RPC_TIMEOUT``                     per-call timeout seconds (default 6).
``AIMARKET_RPC_COOLDOWN``                    seconds a failed endpoint is skipped before re-probe
                                            (default 30).
``AIMARKET_RPC_USER_AGENT``                  User-Agent sent to RPC providers (default
                                            ``aimarket-chain-net/1.0``). Needed because many public
                                            RPCs (Cloudflare-fronted) 403 the default urllib UA.

Back-compat: the legacy single-URL vars (``BASE_RPC_URL``, ``ETHEREUM_RPC_URL``,
``ARBITRUM_RPC_URL``, ``SOLANA_RPC_URL`` and the web layer's
``AIFACTORY_PAYMENT_RPC_{BASE,ETHEREUM,ARBITRUM,SOLANA}``) are still honoured as a
*lower-priority* source, so existing deployments keep working and simply gain failover.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)

# ── chain kinds ──────────────────────────────────────────────────────────────
EVM = "evm"
SOLANA = "solana"

DEFAULT_NETWORK = "base"

# Transport: (url, json_body, timeout_s) -> decoded JSON dict. Injectable for tests.
Transport = Callable[[str, dict, float], dict]


class ChainNetError(RuntimeError):
    """Base error for the chain-net layer."""


class AllEndpointsDown(ChainNetError):
    """Every RPC endpoint for the network failed health/transport — fail closed, do not hang."""


class RpcError(ChainNetError):
    """The RPC node returned a JSON-RPC ``error`` object (a node-level, non-transport failure)."""


# ═════════════════════════════════════════════════════════════════════════════
# Network registry
# ═════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class NetworkSpec:
    id: str
    kind: str                       # EVM | SOLANA
    display_name: str
    chain_id: Optional[int]         # EVM numeric chainId; None for Solana
    cluster: Optional[str]          # Solana cluster ("mainnet-beta"); None for EVM
    rpc_urls: tuple[str, ...]       # priority-ordered; index 0 is the preferred default
    native_symbol: str
    explorer_tx: str                # "{}"-formatted url for a tx, "" if unknown
    addresses: dict[str, str] = field(default_factory=dict)  # NAME -> address/program-id
    testnet: bool = False

    @property
    def is_evm(self) -> bool:
        return self.kind == EVM

    @property
    def is_solana(self) -> bool:
        return self.kind == SOLANA

    def explorer_url(self, tx_hash: str) -> str:
        return self.explorer_tx.format(tx_hash) if self.explorer_tx else ""


# Our live Base deployment (owner 0x1218…Ad0a). Canonical record: docs/onchain-journal.md.
# These are the "demo contracts" the default network ships with; overridable via
# AIMARKET_ADDR_BASE_<NAME>. This module is the single programmatic source of truth.
_BASE_ADDRESSES: dict[str, str] = {
    "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "AIAgentLottery": "0xbda3e32331822d525d5e7c7b51ed76132e84db61",
    "AIMarketEscrow": "0x3Df85a639EAB8B50DD14f09bdeB46D5FeF163017",
    "AIMarketCapabilityNFT": "0xA9Af496fD4A1Dc594029Aa8Ea2dbd236Fd255033",
    "AgentCollateralVault": "0x82566bE7Bfd6764b53F24b1eD45378bd3f1c9394",
    "AgentListingRegistry": "0x62a27eDca2ff1b3D8096c4dEBb64401c252feCA8",
    "AgentLendingPool": "0x01280fb29AAF3410Fb9129ee34b459325c51af1a",
    "PulseAMM": "0xf78Eb43147356e66345c20c7d7299c3c54faaC5d",
    "AgentAuditPool": "0xee3e560D6fe9Df842433A8121d45037e125d5C01",
    "PulseDistributor": "0x37F17f2B733d9D801C7f03f6A6D1E5cA8898775e",
    "PlonkVerifier": "0xb11af6f387aCD57E6AECDa222D0108e6380ACf65",
}

# Built-in presets. RPC lists are public endpoints in rough reliability order; index 0 is the
# preferred default (matches what the codebase used historically). Backups exist so a single
# provider outage does not take the ecosystem offline.
_PRESETS: dict[str, NetworkSpec] = {
    "base": NetworkSpec(
        id="base", kind=EVM, display_name="Base", chain_id=8453, cluster=None,
        rpc_urls=(
            "https://mainnet.base.org",
            "https://base-rpc.publicnode.com",
            "https://base.llamarpc.com",
            "https://base.drpc.org",
            "https://1rpc.io/base",
        ),
        native_symbol="ETH",
        explorer_tx="https://basescan.org/tx/{}",
        addresses=dict(_BASE_ADDRESSES),
    ),
    "ethereum": NetworkSpec(
        id="ethereum", kind=EVM, display_name="Ethereum", chain_id=1, cluster=None,
        rpc_urls=(
            "https://eth.llamarpc.com",
            "https://ethereum-rpc.publicnode.com",
            "https://cloudflare-eth.com",
            "https://eth.drpc.org",
            "https://1rpc.io/eth",
        ),
        native_symbol="ETH",
        explorer_tx="https://etherscan.io/tx/{}",
    ),
    "arbitrum": NetworkSpec(
        id="arbitrum", kind=EVM, display_name="Arbitrum One", chain_id=42161, cluster=None,
        rpc_urls=(
            "https://arb1.arbitrum.io/rpc",
            "https://arbitrum-one-rpc.publicnode.com",
            "https://arbitrum.llamarpc.com",
            "https://1rpc.io/arb",
        ),
        native_symbol="ETH",
        explorer_tx="https://arbiscan.io/tx/{}",
    ),
    "solana": NetworkSpec(
        id="solana", kind=SOLANA, display_name="Solana", chain_id=None, cluster="mainnet-beta",
        rpc_urls=(
            "https://api.mainnet-beta.solana.com",
            "https://solana-rpc.publicnode.com",
            "https://1rpc.io/sol",
        ),
        native_symbol="SOL",
        explorer_tx="https://solscan.io/tx/{}",
        # Solana escrow/lottery programs exist in contracts/solana but are not part of the
        # live Base demo; set AIMARKET_ADDR_SOLANA_<NAME> when deployed.
    ),
}

# Testnet variants (chain-id / cluster + RPC) used when AIMARKET_TESTNET is set. Mirrors the
# web payment layer's existing mainnet→sepolia/devnet switch.
_TESTNET: dict[str, dict[str, Any]] = {
    "base": {"chain_id": 84532, "display_name": "Base Sepolia",
             "rpc_urls": ("https://sepolia.base.org", "https://base-sepolia-rpc.publicnode.com")},
    "ethereum": {"chain_id": 11155111, "display_name": "Sepolia",
                 "rpc_urls": ("https://rpc.sepolia.org", "https://ethereum-sepolia-rpc.publicnode.com")},
    "arbitrum": {"chain_id": 421614, "display_name": "Arbitrum Sepolia",
                 "rpc_urls": ("https://sepolia-rollup.arbitrum.io/rpc",)},
    "solana": {"cluster": "devnet", "display_name": "Solana Devnet",
               "rpc_urls": ("https://api.devnet.solana.com",)},
}

# Legacy single-URL env vars to fold in as lower-priority backups (back-compat).
_LEGACY_RPC_ENV: dict[str, tuple[str, ...]] = {
    "base": ("BASE_RPC_URL", "AIFACTORY_PAYMENT_RPC_BASE"),
    "ethereum": ("ETHEREUM_RPC_URL", "AIFACTORY_PAYMENT_RPC_ETHEREUM"),
    "arbitrum": ("ARBITRUM_RPC_URL", "AIFACTORY_PAYMENT_RPC_ARBITRUM"),
    "solana": ("SOLANA_RPC_URL", "AIFACTORY_PAYMENT_RPC_SOLANA"),
}


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _env_bool(name: str) -> bool:
    return _env(name).lower() in ("1", "true", "yes", "on")


def _float_env(name: str, default: float) -> float:
    """Parse a float env var, falling back (with a warning) on a malformed value rather than
    crashing pool construction."""
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        _log.warning("invalid %s=%r — using default %s", name, raw, default)
        return default


def redact_url(url: str) -> str:
    """Host-only form of an RPC URL, dropping any embedded API key / userinfo / path / query —
    safe to put in error messages and logs."""
    try:
        p = urllib.parse.urlsplit(url)
        host = p.hostname or "?"
        return f"{p.scheme}://{host}" + (f":{p.port}" if p.port else "")
    except Exception:  # noqa: BLE001
        return "<rpc-endpoint>"


def _split_urls(raw: str) -> list[str]:
    return [u.strip() for u in raw.replace("\n", ",").split(",") if u.strip()]


def _dedupe(urls: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        key = u.rstrip("/")
        if key and key not in seen:
            seen.add(key)
            out.append(u)
    return tuple(out)


def _resolve_rpc_urls(net_id: str, preset_urls: tuple[str, ...]) -> tuple[str, ...]:
    """Priority order (deduped, order-preserving):
    1. AIMARKET_RPC_<ID> — the new explicit list, your preferred default first.
    2. Legacy single-URL vars (BASE_RPC_URL, AIFACTORY_PAYMENT_RPC_BASE, …) — these are also
       explicit operator config, so they outrank the public presets.
    3. Built-in public presets — pure backups, so the ecosystem is never fully offline.
    """
    ordered: list[str] = []
    ordered += _split_urls(_env(f"AIMARKET_RPC_{net_id.upper()}"))
    for legacy in _LEGACY_RPC_ENV.get(net_id, ()):
        v = _env(legacy)
        if v:
            ordered.append(v)
    ordered += list(preset_urls)
    return _dedupe(ordered)


def _resolve_addresses(net_id: str, preset_addrs: dict[str, str]) -> dict[str, str]:
    """Preset demo addresses, overlaid with AIMARKET_ADDR_<ID>_<NAME> env overrides."""
    addrs = dict(preset_addrs)
    prefix = f"AIMARKET_ADDR_{net_id.upper()}_"
    for key, val in os.environ.items():
        if key.startswith(prefix) and (val or "").strip():
            addrs[key[len(prefix):]] = val.strip()
    return addrs


def network(net_id: Optional[str] = None, *, testnet: Optional[bool] = None) -> NetworkSpec:
    """Resolve a fully-configured :class:`NetworkSpec` (presets + env overrides).

    ``net_id`` defaults to ``AIMARKET_CHAIN``/``AIMARKET_NETWORK`` then ``base``.
    ``testnet`` defaults to the ``AIMARKET_TESTNET`` env flag.
    Unknown ids are allowed if defined ad-hoc via ``AIMARKET_CHAIN_KIND``/``AIMARKET_CHAIN_ID``.
    """
    if net_id is None:
        net_id = _env("AIMARKET_CHAIN") or _env("AIMARKET_NETWORK") or DEFAULT_NETWORK
    net_id = net_id.strip().lower()
    if testnet is None:
        testnet = _env_bool("AIMARKET_TESTNET")

    base_spec = _PRESETS.get(net_id)
    if base_spec is None:
        # Ad-hoc network defined purely via env (the "extensible without code change" path).
        kind = (_env("AIMARKET_CHAIN_KIND") or EVM).lower()
        chain_id_raw = _env("AIMARKET_CHAIN_ID")
        if kind == EVM and chain_id_raw and not chain_id_raw.isdigit():
            _log.warning("ignoring non-numeric AIMARKET_CHAIN_ID=%r for network %r", chain_id_raw, net_id)
        base_spec = NetworkSpec(
            id=net_id, kind=kind, display_name=net_id.title(),
            chain_id=int(chain_id_raw) if (kind == EVM and chain_id_raw.isdigit()) else None,
            cluster=(_env("AIMARKET_CHAIN_CLUSTER") or "mainnet-beta") if kind == SOLANA else None,
            rpc_urls=(), native_symbol=_env("AIMARKET_CHAIN_SYMBOL") or ("SOL" if kind == SOLANA else "ETH"),
            explorer_tx="",
        )

    spec = base_spec
    if testnet and net_id in _TESTNET:
        t = _TESTNET[net_id]
        spec = replace(
            spec,
            display_name=t.get("display_name", spec.display_name),
            chain_id=t.get("chain_id", spec.chain_id),
            cluster=t.get("cluster", spec.cluster),
            rpc_urls=tuple(t.get("rpc_urls", spec.rpc_urls)),
            testnet=True,
        )

    return replace(
        spec,
        rpc_urls=_resolve_rpc_urls(net_id, spec.rpc_urls),
        addresses=_resolve_addresses(net_id, spec.addresses),
    )


def active_network(*, testnet: Optional[bool] = None) -> NetworkSpec:
    """The currently-selected network (from env), default Base + demo contracts."""
    return network(None, testnet=testnet)


def supported_networks() -> list[str]:
    return list(_PRESETS.keys())


# ═════════════════════════════════════════════════════════════════════════════
# Transport (stdlib default, injectable)
# ═════════════════════════════════════════════════════════════════════════════

# Many public RPC providers (Cloudflare-fronted: base.org, llamarpc, publicnode, drpc, 1rpc…)
# reject the default ``Python-urllib/x.y`` User-Agent with HTTP 403. Send a real UA so the
# health probes and calls actually reach the node. Overridable via AIMARKET_RPC_USER_AGENT.
_DEFAULT_USER_AGENT = "aimarket-chain-net/1.0"


def user_agent() -> str:
    """The User-Agent to send to RPC providers (consumers using web3/httpx should set this too)."""
    return os.getenv("AIMARKET_RPC_USER_AGENT") or _DEFAULT_USER_AGENT


def _urllib_transport(url: str, body: dict, timeout: float) -> dict:
    data = json.dumps(body).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": user_agent(),
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed scheme http(s))
        return json.loads(resp.read().decode("utf-8"))


# ═════════════════════════════════════════════════════════════════════════════
# RPC pool with health-checked failover
# ═════════════════════════════════════════════════════════════════════════════

class _Endpoint:
    __slots__ = ("url", "healthy", "cooldown_until", "fails")

    def __init__(self, url: str) -> None:
        self.url = url
        self.healthy = True            # optimistic; first failure demotes it
        self.cooldown_until = 0.0      # monotonic time before which we skip it
        self.fails = 0

    def mark_ok(self) -> None:
        self.healthy = True
        self.cooldown_until = 0.0
        self.fails = 0

    def mark_fail(self, cooldown: float, now: float) -> None:
        self.healthy = False
        self.fails += 1
        self.cooldown_until = now + cooldown


class RpcPool:
    """Priority-ordered JSON-RPC pool with health-aware failover for EVM **and** Solana.

    ``call``/``run`` always try the highest-priority *eligible* endpoint first (eligible =
    healthy, or cooled-down and due for a re-probe), so a working preferred default is always
    chosen and a recovered default is reclaimed after its cooldown. Transport/RPC failures
    demote an endpoint and fail over to the next; if all are down, raises
    :class:`AllEndpointsDown` (fast — bounded by ``timeout`` per endpoint, no hanging).
    """

    def __init__(
        self,
        spec: NetworkSpec,
        *,
        transport: Optional[Transport] = None,
        timeout: Optional[float] = None,
        cooldown: Optional[float] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        # Only http(s) endpoints reach the transport — a hard guard against an env-supplied
        # file:// / gopher:// URL turning a health probe into a local-file/SSRF read.
        usable = [u for u in spec.rpc_urls if u.lower().startswith(("http://", "https://"))]
        dropped = [u for u in spec.rpc_urls if u not in usable]
        if dropped:
            _log.warning("ignoring non-http(s) RPC URL(s) for %r: %s",
                         spec.id, [redact_url(u) for u in dropped])
        if not usable:
            raise ChainNetError(
                f"network {spec.id!r} has no usable http(s) RPC URLs configured "
                f"(set AIMARKET_RPC_{spec.id.upper()})"
            )
        self.spec = spec
        self._transport = transport or _urllib_transport
        self._timeout = timeout if timeout is not None else _float_env("AIMARKET_RPC_TIMEOUT", 6.0)
        self._cooldown = cooldown if cooldown is not None else _float_env("AIMARKET_RPC_COOLDOWN", 30.0)
        self._clock = clock
        self._endpoints = [_Endpoint(u) for u in usable]

    # ── endpoint selection ────────────────────────────────────────────────
    def _candidates(self) -> list[_Endpoint]:
        """Priority order, dropping endpoints still inside their cooldown. If every endpoint
        is cooling down, return them all (a forced retry beats giving up)."""
        now = self._clock()
        live = [e for e in self._endpoints if e.healthy or now >= e.cooldown_until]
        return live or list(self._endpoints)

    # ── core call paths ───────────────────────────────────────────────────
    def run(self, fn: Callable[[str], Any]) -> Any:
        """Run ``fn(url)`` against endpoints in priority order, failing over on exception.

        ``fn`` MUST raise only on transport/connection failure (to trigger failover) and
        return normally for a valid answer — including legitimate "not found" results, which
        must be modelled as return values, not exceptions, or they would be retried needlessly.
        """
        last_err: Optional[Exception] = None
        for ep in self._candidates():
            try:
                result = fn(ep.url)
            except Exception as exc:  # noqa: BLE001 — any transport error fails over
                ep.mark_fail(self._cooldown, self._clock())
                last_err = exc
                continue
            ep.mark_ok()
            return result
        raise AllEndpointsDown(
            f"all {len(self._endpoints)} RPC endpoint(s) for {self.spec.id!r} failed; "
            f"last error: {last_err}"
        )

    def call(self, method: str, params: Optional[list] = None) -> Any:
        """Make a JSON-RPC 2.0 call with failover; returns the ``result`` field.

        Raises :class:`RpcError` if a node returns a JSON-RPC ``error`` (this does NOT fail
        over — the request reached a node and was rejected on its merits)."""
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}

        def _do(url: str) -> Any:
            resp = self._transport(url, body, self._timeout)
            if not isinstance(resp, dict):
                # Not a JSON-RPC object → a broken/wrong endpoint. Treat as a transport
                # failure so the pool fails over instead of returning garbage to the caller.
                raise ChainNetError(f"malformed RPC reply (expected object, got {type(resp).__name__})")
            if resp.get("error"):
                # A node-level rejection — surface it without burning the whole pool.
                raise RpcError(f"{method}: {resp['error']}")
            return resp.get("result")

        # RpcError must propagate (not be treated as transport failure), so run a thin loop
        # that fails over on transport errors only.
        last_err: Optional[Exception] = None
        for ep in self._candidates():
            try:
                result = _do(ep.url)
            except RpcError:
                ep.mark_ok()  # the node answered; it's healthy, the *request* was bad
                raise
            except Exception as exc:  # noqa: BLE001
                ep.mark_fail(self._cooldown, self._clock())
                last_err = exc
                continue
            ep.mark_ok()
            return result
        raise AllEndpointsDown(
            f"all {len(self._endpoints)} RPC endpoint(s) for {self.spec.id!r} failed; "
            f"last error: {last_err}"
        )

    # ── health ─────────────────────────────────────────────────────────────
    def _probe_method(self) -> tuple[str, list]:
        return ("getHealth", []) if self.spec.is_solana else ("eth_chainId", [])

    def healthy_url(self) -> Optional[str]:
        """Return the highest-priority endpoint that responds to a health probe, marking
        states along the way; ``None`` if every endpoint is down. Use to gate work (e.g. a
        live feed) so it degrades to "offline" instead of hanging when no node is reachable."""
        method, params = self._probe_method()
        for ep in self._candidates():
            try:
                self._transport(ep.url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, self._timeout)
            except Exception:  # noqa: BLE001
                ep.mark_fail(self._cooldown, self._clock())
                continue
            ep.mark_ok()
            return ep.url
        return None

    def health(self) -> dict:
        """Full health report across all endpoints (for diagnostics / monitor surfacing)."""
        method, params = self._probe_method()
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        endpoints = []
        any_ok = False
        for ep in self._endpoints:
            ok = False
            detail = ""
            try:
                resp = self._transport(ep.url, body, self._timeout)
                if not isinstance(resp, dict):
                    detail = f"malformed reply ({type(resp).__name__})"  # non-object → unhealthy
                elif resp.get("error"):
                    detail = str(resp.get("error"))
                else:
                    ok = True
                    detail = "ok"
            except Exception as exc:  # noqa: BLE001
                detail = f"{type(exc).__name__}: {exc}"
            if ok:
                any_ok = True
                ep.mark_ok()
            else:
                ep.mark_fail(self._cooldown, self._clock())
            endpoints.append({"url": ep.url, "healthy": ok, "detail": detail})
        return {
            "network": self.spec.id,
            "kind": self.spec.kind,
            "chain_id": self.spec.chain_id,
            "cluster": self.spec.cluster,
            "healthy": any_ok,
            "endpoints": endpoints,
        }


def pool_for(net_id: Optional[str] = None, *, testnet: Optional[bool] = None, **kw: Any) -> RpcPool:
    """Convenience: build an :class:`RpcPool` for a network id (default active network)."""
    return RpcPool(network(net_id, testnet=testnet), **kw)
