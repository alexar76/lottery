## Base mainnet (8453)

Redeployed **2026-07-26** from `0x1218ff36C5d2e3B6A565CdB1A8B1AcCFc606Ad0a`.
Full journal + every tx: [`docs/onchain-journal.md`](../../docs/onchain-journal.md).
Canonical registry: [`config/deployments/base-mainnet.json`](../../config/deployments/base-mainnet.json).

| Contract | Address | Explorer |
|---|---|---|
| AIAgentLottery | `0x701A7bd8487cd4d2EcE0E252Dbc0E67dF70a9554` | https://basescan.org/address/0x701A7bd8487cd4d2EcE0E252Dbc0E67dF70a9554 |
| AIMarketEscrow | `0x0606983cbEc6D0C12a0B750f72Ceb6032c72C25D` | https://basescan.org/address/0x0606983cbEc6D0C12a0B750f72Ceb6032c72C25D |
| AIMarketCapabilityNFT | `0x544dcdd8B01A7ee1444bf89A5381aA981735a281` | https://basescan.org/address/0x544dcdd8B01A7ee1444bf89A5381aA981735a281 |
| AgentCollateralVault | `0xA29d019F3B706B83C19f36E9BaCD83d22100fF45` | https://basescan.org/address/0xA29d019F3B706B83C19f36E9BaCD83d22100fF45 |
| AgentListingRegistry | `0x04B8Ed69768b567F66c7473f1Ad53748D78a627D` | https://basescan.org/address/0x04B8Ed69768b567F66c7473f1Ad53748D78a627D |
| AgentLendingPool | `0x0ee6599bE35F9AbaFAB4c2182301a15016265B32` | https://basescan.org/address/0x0ee6599bE35F9AbaFAB4c2182301a15016265B32 |
| PulseAMM | `0x96201B1A9eFC563293A1579dAaaDb038f728BFc9` | https://basescan.org/address/0x96201B1A9eFC563293A1579dAaaDb038f728BFc9 |
| AgentAuditPool | `0x84991b78d3874e080aeDe1A4F7746c60eBe4039c` | https://basescan.org/address/0x84991b78d3874e080aeDe1A4F7746c60eBe4039c |
| PulseDistributor | `0x325aC681FDd14c23DE074c15ac2Ed07702e38596` | https://basescan.org/address/0x325aC681FDd14c23DE074c15ac2Ed07702e38596 |
| PlonkVerifier (ZK) | `0x1914D8a04dd65c6d8C888B98A31757F79B8e85c5` | https://basescan.org/address/0x1914D8a04dd65c6d8C888B98A31757F79B8e85c5 |

- owner/admin/treasury/operator/oracle-signer: `0x1218ff36C5d2e3B6A565CdB1A8B1AcCFc606Ad0a`
- native-ETH tickets · ticket 0.000003 ETH · prize/opex/operator 80/12/8 · off-chain VDF
- entry window 30s · minDrawDelay 15s (demo redeploy; prior live set used 120s/30s)
