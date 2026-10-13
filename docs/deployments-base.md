## Base mainnet (8453)

Redeployed **2026-09-11** (lottery) from `0x1218ff36C5d2e3B6A565CdB1A8B1AcCFc606Ad0a`.
Full journal + every tx: [`docs/onchain-journal.md`](https://github.com/alexar76/aicom/blob/main/docs/onchain-journal.md).
Canonical registry: [`config/deployments/base-mainnet.json`](https://github.com/alexar76/aicom/blob/main/config/deployments/base-mainnet.json).

| Contract | Address | Explorer |
|---|---|---|
| AIAgentLottery | `0xEcB3A01b44C5b78210F72768C446c3E4E6175af4` | https://basescan.org/address/0xEcB3A01b44C5b78210F72768C446c3E4E6175af4 |
| AIMarketEscrow | `0xa4cb6ef73B982B847fB06Ec75540d05D0311B2Eb` | https://basescan.org/address/0xa4cb6ef73B982B847fB06Ec75540d05D0311B2Eb |
| AIMarketCapabilityNFT | `0x544dcdd8B01A7ee1444bf89A5381aA981735a281` | https://basescan.org/address/0x544dcdd8B01A7ee1444bf89A5381aA981735a281 |
| AgentCollateralVault | `0xdAa073EDCA17328188Afe5A83394Fc7b5E42081c` | https://basescan.org/address/0xdAa073EDCA17328188Afe5A83394Fc7b5E42081c |
| AgentListingRegistry | `0x3636A636262940Ff4E49aC1BCf34b958F589acC9` | https://basescan.org/address/0x3636A636262940Ff4E49aC1BCf34b958F589acC9 |
| AgentLendingPool | `0x51a61d25b799C17A012eB671e3EDe2569E2d9C3d` | https://basescan.org/address/0x51a61d25b799C17A012eB671e3EDe2569E2d9C3d |
| PulseAMM | `0x0A70AA84903ecB2E0aF5c435AFd9EDd178559E47` | https://basescan.org/address/0x0A70AA84903ecB2E0aF5c435AFd9EDd178559E47 |
| AgentAuditPool | `0xE0C711Ef82F9C97eefBF4C0e715de1b09F8a6160` | https://basescan.org/address/0xE0C711Ef82F9C97eefBF4C0e715de1b09F8a6160 |

> Redeployed **2026-10-13** from the source the 2026-10-08 live-vs-source audit found newer than the chain (a price counts for as long as it held, a baseline needs three samples, collateral is refused before the registry is set). The 2026-08-22 set it replaces held no funds and is superseded — see [`docs/onchain-journal.md`](https://github.com/alexar76/aicom/blob/main/docs/onchain-journal.md) §9 (and §2d for 08-22).
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
