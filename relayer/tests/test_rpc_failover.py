"""RPC endpoint rotation: a rate-limited endpoint must hand off, not end the call.

Measured against the live free Base endpoints from the relayer host on 2026-09-11.
"""
def test_a_403_rate_limit_rotates_instead_of_raising():
    """publicnode rate-limits with 403 Forbidden, not 429.

    `_retryable` only knew about 429, so the provider raised on the first 403 and the
    other ten endpoints in the list were never tried — the relayer reported "agent X
    work seat failed: 403 Client Error" while healthy endpoints sat unused.
    """
    import requests

    from ailottery_relayer.rpc import _retryable

    for status, text in (
        (403, "403 Client Error: Forbidden for url: https://base-rpc.publicnode.com/"),
        (408, "408 Client Error: Request Timeout for url: https://base.drpc.org/"),
        (413, "413 Client Error: Payload Too Large for url: https://mainnet.base.org/"),
        (429, "429 Client Error: Too Many Requests for url: https://x/"),
    ):
        assert _retryable(requests.HTTPError(text)) is True, status


def test_the_fallback_list_has_no_known_dead_endpoints():
    """Measured from the relayer host 2026-09-11; these answered nothing at all."""
    from ailottery_relayer.rpc import LIVE_FALLBACKS

    dead = (
        "llamarpc",            # HTTP 525
        "onfinality",          # HTTP 429 on every call
        "lava.build",          # HTTP 410
        "omniatech",           # HTTP 521
        "0xrpc.io",            # HTTP 404
        "subquery",            # DNS failure
    )
    joined = " ".join(LIVE_FALLBACKS)
    for host in dead:
        assert host not in joined, f"{host} is dead from the relayer host"
    assert len(LIVE_FALLBACKS) >= 8, "rotation needs real breadth to survive a 403"


def test_rotation_walks_the_whole_list_before_giving_up():
    """One 403 must not end the call while other endpoints are untried."""
    import requests

    from ailottery_relayer.rpc import FailoverHTTPProvider

    urls = [f"https://rpc{i}.example" for i in range(4)]
    provider = FailoverHTTPProvider(urls)
    seen: list[str] = []

    def fake_make_request(method, params):
        seen.append(provider.endpoint_uri)
        if len(seen) < 4:
            raise requests.HTTPError("403 Client Error: Forbidden for url: x")
        return {"jsonrpc": "2.0", "id": 1, "result": "0x1"}

    # Patch the PARENT's make_request, which FailoverHTTPProvider delegates to.
    import web3.providers.rpc as rpc_mod

    original = rpc_mod.HTTPProvider.make_request
    rpc_mod.HTTPProvider.make_request = staticmethod(fake_make_request)
    try:
        out = provider.make_request("eth_chainId", [])
    finally:
        rpc_mod.HTTPProvider.make_request = original

    assert out["result"] == "0x1"
    assert len(set(seen)) == 4, f"did not rotate across the list: {seen}"
