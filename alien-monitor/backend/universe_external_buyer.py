"""
External AI Buyer — autonomous agent that purchases from the Hub.

Uses real Hub REST API: search → channel/open → invoke → channel/close.
Selection uses diversity-aware scoring across capability categories.

This is NOT a mock — it exercises the real Hub, ChannelLedger, and
payment infrastructure. The only synthetic element is the wallet funding
(handled by UniverseFundingStream).
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from universe import VirtualUniverse

# Search intents for diverse purchasing
SEARCH_INTENTS = [
    "translation service",
    "code review tool",
    "data analysis",
    "market research",
    "content generation",
    "security audit",
    "API integration",
    "document summarization",
    "fraud detection",
    "SEO optimization",
    "customer support",
    "legal document review",
    "sentiment analysis",
    "image generation",
    "workflow automation",
]

CATEGORY_KEYWORDS = {
    "translate": ["translat", "language", "multilingual"],
    "code": ["code", "dev", "programming", "api", "software"],
    "data": ["data", "analytics", "analysis", "statistics"],
    "content": ["content", "writing", "generate", "creative"],
    "security": ["security", "audit", "compliance", "fraud"],
    "marketing": ["marketing", "seo", "landing", "sales"],
    "legal": ["legal", "contract", "document", "review"],
    "finance": ["finance", "trading", "market", "pricing"],
    "agent": ["agent", "assistant", "bot", "automation"],
    "infra": ["infra", "deploy", "monitor", "cloud"],
}


def _infer_category(name: str, description: str) -> str:
    blob = f"{name} {description}".lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in blob:
                return cat
    return "general"


class ExternalAIBuyer:
    """Autonomous AI agent that buys capabilities from the AIMarket Hub."""

    def __init__(self, hub_url: str = "http://127.0.0.1:9083"):
        self.hub_url = hub_url.rstrip("/")
        self.rounds_completed = 0
        self.purchase_history: list[dict] = []
        self.preferred_categories: set[str] = set()
        self.budget_range = (80.0, 200.0)

    def execute_round(self, vu: VirtualUniverse) -> dict:
        budget = round(random.uniform(*self.budget_range), 2)
        intent = random.choice(SEARCH_INTENTS)

        events: list[dict] = []
        purchases = 0

        try:
            matches = self._search(vu, intent, budget)
            if not matches:
                return {"purchases": 0, "events": []}

            selected = self._select(matches, budget)
            if not selected:
                return {"purchases": 0, "events": []}

            channel_id = self._open_channel(budget)
            if not channel_id:
                return {"purchases": 0, "events": []}

            for item in selected:
                try:
                    result = self._invoke(item, channel_id)
                    if result:
                        purchases += 1
                        cat = _infer_category(item.get("name", ""), item.get("description", ""))
                        self.preferred_categories.add(cat)
                        self.purchase_history.append({
                            "capability_id": item.get("capability_id", ""),
                            "name": item.get("name", ""),
                            "price_usd": item.get("price_per_call_usd", 0),
                            "category": cat,
                            "ts": datetime.now(timezone.utc).isoformat(),
                        })
                        if len(self.purchase_history) > 300:
                            self.purchase_history = self.purchase_history[-300:]
                        if len(self.purchase_history) > 500:
                            self.purchase_history = self.purchase_history[-500:]
                        events.append({
                            "type": "buyer_purchase",
                            "agent": "ExternalAI",
                            "action": "invoke",
                            "target": item.get("capability_id", ""),
                            "amount": item.get("price_per_call_usd", 0),
                            "token": "USDT",
                            "id": f"buyer_{self.rounds_completed}_{purchases}",
                            "ts": datetime.now(timezone.utc).isoformat(),
                        })
                except Exception as exc:
                    print(f"[Buyer] Invoke failed for {item.get('name', '?')}: {exc}")

            self._close_channel(channel_id)

        except Exception as exc:
            print(f"[Buyer] Round failed: {exc}")

        self.rounds_completed += 1
        return {"purchases": purchases, "events": events}

    def _search(self, vu: VirtualUniverse, intent: str, budget: float) -> list[dict]:
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.get(
                    f"{self.hub_url}/ai-market/v2/search",
                    params={"intent": intent, "budget": budget, "limit": 12},
                )
                if r.status_code == 200:
                    data = r.json()
                    return data.get("matches") or data.get("results") or []
                print(f"[Buyer] Search HTTP {r.status_code}")
                return []
        except httpx.ConnectError:
            return []
        except Exception as exc:
            print(f"[Buyer] Search error: {exc}")
            return []

    def _select(self, matches: list[dict], budget: float) -> list[dict]:
        scored = []
        for m in matches:
            price = float(m.get("price_per_call_usd") or m.get("routed_price_usd") or 5.0)
            if price <= 0:
                continue
            trust = float(m.get("trust_score") or 0.5)
            name = str(m.get("name") or m.get("capability_id") or "")
            desc = str(m.get("description") or "")
            cat = _infer_category(name, desc)
            diversity = 1.5 if cat not in self.preferred_categories else 1.0
            score = (1.0 / price) * max(trust, 0.1) * diversity
            scored.append((score, price, m))

        scored.sort(key=lambda x: x[0], reverse=True)

        selected = []
        spent = 0.0
        for _, price, match in scored:
            if spent + price > budget:
                continue
            if len(selected) >= 6:
                break
            selected.append(match)
            spent += price

        return selected

    def _open_channel(self, budget: float) -> str | None:
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.post(
                    f"{self.hub_url}/ai-market/v2/channel/open",
                    json={
                        "deposit_usd": budget,
                        "tx_hash": f"buyer-{int(time.time())}-{random.randint(1000, 9999)}",
                    },
                )
                if r.status_code == 200:
                    data = r.json()
                    ch = data.get("channel") if isinstance(data.get("channel"), dict) else {}
                    return ch.get("channel_id") or data.get("channel_id")
                print(f"[Buyer] Channel open HTTP {r.status_code}: {r.text[:200]}")
                return None
        except Exception as exc:
            print(f"[Buyer] Channel open error: {exc}")
            return None

    def _invoke(self, item: dict, channel_id: str) -> dict | None:
        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.post(
                    f"{self.hub_url}/ai-market/v2/invoke",
                    json={
                        "product_id": item.get("product_id", ""),
                        "capability_id": item.get("capability_id", ""),
                        "source_hub": item.get("source_hub", "local"),
                        "input": {"task": "external_ai_purchase", "mode": "uni"},
                    },
                    headers={"X-Payment-Channel": channel_id},
                )
                if r.status_code == 200:
                    return r.json()
                print(f"[Buyer] Invoke HTTP {r.status_code}")
                return None
        except Exception as exc:
            print(f"[Buyer] Invoke error: {exc}")
            return None

    def _close_channel(self, channel_id: str) -> None:
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.post(
                    f"{self.hub_url}/ai-market/v2/channel/close",
                    json={"channel_id": channel_id},
                )
                if r.status_code != 200:
                    print(f"[Buyer] Channel close HTTP {r.status_code}")
        except Exception as exc:
            print(f"[Buyer] Channel close error: {exc}")
