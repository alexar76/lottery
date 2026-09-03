## Base mainnet (8453)

Redeployed **2026-07-26** from `0x1218ff36C5d2e3B6A565CdB1A8B1AcCFc606Ad0a`.
Full journal + every tx: [`docs/onchain-journal.md`](https://github.com/alexar76/aicom/blob/main/docs/onchain-journal.md).
Canonical registry: [`config/deployments/base-mainnet.json`](https://github.com/alexar76/aicom/blob/main/config/deployments/base-mainnet.json).

| Contract | Address | Explorer |
|---|---|---|
| AIAgentLottery | `0x701A7bd8487cd4d2EcE0E252Dbc0E67dF70a9554` | https://basescan.org/address/0x701A7bd8487cd4d2EcE0E252Dbc0E67dF70a9554 |
| AIMarketEscrow | `0x0606983cbEc6D0C12a0B750f72Ceb6032c72C25D` | https://basescan.org/address/0x0606983cbEc6D0C12a0B750f72Ceb6032c72C25D |
| AIMarketCapabilityNFT | `0x544dcdd8B01A7ee1444bf89A5381aA981735a281` | https://basescan.org/address/0x544dcdd8B01A7ee1444bf89A5381aA981735a281 |
| AgentCollateralVault | `0x1BF39f659bd47bf0a15294B9e4760C327113AbD9` | https://basescan.org/address/0x1BF39f659bd47bf0a15294B9e4760C327113AbD9 |
| AgentListingRegistry | `0xab6E20aE29A4c7C10C6131Da9721aE98201B6600` | https://basescan.org/address/0xab6E20aE29A4c7C10C6131Da9721aE98201B6600 |
| AgentLendingPool | `0x36446D8393a39027D1242C1C277FdD9227232298` | https://basescan.org/address/0x36446D8393a39027D1242C1C277FdD9227232298 |
| PulseAMM | `0xED2792499757dd6d40504b2522f2E99559fc5D22` | https://basescan.org/address/0xED2792499757dd6d40504b2522f2E99559fc5D22 |
| AgentAuditPool | `0x96005B0E70ce1F1E0C0977067216aC45043e689b` | https://basescan.org/address/0x96005B0E70ce1F1E0C0977067216aC45043e689b |

> Redeployed **2026-08-22** for the security-audit fixes (collateral double-pledge; self-triggerable default). The addresses these replaced held no funds and are superseded — see [`docs/onchain-journal.md`](https://github.com/alexar76/aicom/blob/main/docs/onchain-journal.md) §2d.
> Canonical machine-readable source: `config/deployments/base-mainnet.json`.

| PulseDistributor | `0x325aC681FDd14c23DE074c15ac2Ed07702e38596` | https://basescan.org/address/0x325aC681FDd14c23DE074c15ac2Ed07702e38596 |
| PlonkVerifier (ZK) | `0x1914D8a04dd65c6d8C888B98A31757F79B8e85c5` | https://basescan.org/address/0x1914D8a04dd65c6d8C888B98A31757F79B8e85c5 |

- owner/admin/treasury/operator/oracle-signer: `0x1218ff36C5d2e3B6A565CdB1A8B1AcCFc606Ad0a`
- native-ETH tickets · ticket 0.000003 ETH · prize/opex/operator 80/12/8 · off-chain VDF
- entry window 30s · minDrawDelay 15s (demo redeploy; prior live set used 120s/30s)
