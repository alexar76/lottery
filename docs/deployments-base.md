## Base mainnet (8453)

Redeployed **2026-09-11** (lottery) from `0x1218ff36C5d2e3B6A565CdB1A8B1AcCFc606Ad0a`.
Full journal + every tx: [`docs/onchain-journal.md`](../../docs/onchain-journal.md).
Canonical registry: [`config/deployments/base-mainnet.json`](../../config/deployments/base-mainnet.json).

| Contract | Address | Explorer |
|---|---|---|
| AIAgentLottery | `0xEcB3A01b44C5b78210F72768C446c3E4E6175af4` | https://basescan.org/address/0xEcB3A01b44C5b78210F72768C446c3E4E6175af4 |
| AIMarketEscrow | `0x12Db8FAC81E5999D2f2087B79e38951571562CF2` | https://basescan.org/address/0x12Db8FAC81E5999D2f2087B79e38951571562CF2 |
| AIMarketCapabilityNFT | `0x544dcdd8B01A7ee1444bf89A5381aA981735a281` | https://basescan.org/address/0x544dcdd8B01A7ee1444bf89A5381aA981735a281 |
| AgentCollateralVault | `0x1BF39f659bd47bf0a15294B9e4760C327113AbD9` | https://basescan.org/address/0x1BF39f659bd47bf0a15294B9e4760C327113AbD9 |
| AgentListingRegistry | `0xab6E20aE29A4c7C10C6131Da9721aE98201B6600` | https://basescan.org/address/0xab6E20aE29A4c7C10C6131Da9721aE98201B6600 |
| AgentLendingPool | `0x36446D8393a39027D1242C1C277FdD9227232298` | https://basescan.org/address/0x36446D8393a39027D1242C1C277FdD9227232298 |
| PulseAMM | `0xED2792499757dd6d40504b2522f2E99559fc5D22` | https://basescan.org/address/0xED2792499757dd6d40504b2522f2E99559fc5D22 |
| AgentAuditPool | `0x96005B0E70ce1F1E0C0977067216aC45043e689b` | https://basescan.org/address/0x96005B0E70ce1F1E0C0977067216aC45043e689b |

> Redeployed **2026-08-22** for the security-audit fixes (collateral double-pledge; self-triggerable default). The addresses these replaced held no funds and are superseded — see [`docs/onchain-journal.md`](../../docs/onchain-journal.md) §2d.
> Canonical machine-readable source: `config/deployments/base-mainnet.json`.

| PulseDistributor | `0x325aC681FDd14c23DE074c15ac2Ed07702e38596` | https://basescan.org/address/0x325aC681FDd14c23DE074c15ac2Ed07702e38596 |
| PlonkVerifier (ZK) | `0x1914D8a04dd65c6d8C888B98A31757F79B8e85c5` | https://basescan.org/address/0x1914D8a04dd65c6d8C888B98A31757F79B8e85c5 |

- owner/admin/treasury/operator/oracle-signer: `0x1218ff36C5d2e3B6A565CdB1A8B1AcCFc606Ad0a`
- native-ETH tickets · ticket 0.000003 ETH · prize/opex/operator 80/12/8 · off-chain VDF
- entry window **86400s** (relayer `setEntryWindow` after CREATE; CREATE default was 30s) · minDrawDelay 15s · **paid tickets OFF** (`paidTicketsEnabled=false`); default door is `enterFromWork`
- LIVE address above carries the **participant-bound** WorkSeat ABI:
  `participantSeated(uint256,bytes32)` answers, so a federated work seat issued by
  another Hub can actually be consumed on-chain and the relayer serves `/work-seat`.
- superseded 2026-09-10: `0x291b6eCB45121fEDE86BF769aC0eaa6AdED38350` (0 ETH, no work-seat ABI)
- superseded 2026-09-11: `0x5F3D1b3f21a9db715666060c587aEB049a06daE7` (0 ETH). It was deployed on 2026-09-10 from a **stale
  contracts tree** on the deploy host (`src/AIAgentLottery.sol` dated 2026-06-16), so it
  shipped `paidTicketsEnabled` and the wallet-only `enterFromWork` but **no**
  `participantSeated` — `eth_call` on that selector reverts with no data. The federated
  door could not work on-chain at all. Replacement deploy tx: `0x158cedf49f9c152b697ccae2553a04bbf37ef1251609a6d685089bd0671fef96`
  (block 51158648); every constructor parameter and role was read off the superseded
  contract first and reproduced bit for bit.
