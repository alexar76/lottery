"""Unit tests for economy_draw helpers split out of economy.py."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from ailottery_relayer.economy_draw import advance_to_close, close_and_draw


def test_advance_to_close_fast_forwards_on_anvil():
    engine = SimpleNamespace(
        cfg=SimpleNamespace(fast_forward=True, poll_interval=60),
        chain=SimpleNamespace(
            get_round=MagicMock(side_effect=[
                {"entriesClose": 100},
                {"entriesClose": 100, "status": 1},
            ]),
            block=MagicMock(return_value={"timestamp": 40}),
            fast_forward=MagicMock(),
        ),
    )
    out = advance_to_close(engine, 1)
    engine.chain.fast_forward.assert_called_once_with(61)
    assert out["status"] == 1


def test_close_and_draw_cancels_empty_round():
    sent = []

    def _send(fn, key):
        sent.append((fn, key))
        return {"status": 1}

    engine = SimpleNamespace(
        chain=SimpleNamespace(
            participants_count=lambda rid: 0,
            send=_send,
        ),
        fn=SimpleNamespace(cancelRound=lambda rid: f"cancel:{rid}"),
        operator_key="0xoperator",
        _event=MagicMock(),
    )

    assert close_and_draw(engine, 7) is False
    assert sent == [("cancel:7", "0xoperator")]
    engine._event.assert_called_once_with("operator", "cancel", "round 7", 0)
