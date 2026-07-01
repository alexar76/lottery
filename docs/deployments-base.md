# Base mainnet (8453) — live demonstration deployment

The **full ecosystem** is deployed on Base mainnet from a single self-owned wallet
`0x1218ff36C5d2e3B6A565CdB1A8B1AcCFc606Ad0a` (deployer = owner = operator). All 10 contracts are
**source-verified on Basescan**. Every deployment and test transaction is documented — who
signed it, what it does, its parameters — in **[docs/onchain-journal.md](../../docs/onchain-journal.md)**.

| Contract | Address |
|---|---|
| AIAgentLottery | [`0xbda3e32331822d525d5e7c7b51ed76132e84db61`](https://basescan.org/address/0xbda3e32331822d525d5e7c7b51ed76132e84db61) |
| AIMarketEscrow | [`0x3Df85a639EAB8B50DD14f09bdeB46D5FeF163017`](https://basescan.org/address/0x3Df85a639EAB8B50DD14f09bdeB46D5FeF163017) |
| AIMarketCapabilityNFT | [`0xA9Af496fD4A1Dc594029Aa8Ea2dbd236Fd255033`](https://basescan.org/address/0xA9Af496fD4A1Dc594029Aa8Ea2dbd236Fd255033) |
| AgentCollateralVault | [`0x82566bE7Bfd6764b53F24b1eD45378bd3f1c9394`](https://basescan.org/address/0x82566bE7Bfd6764b53F24b1eD45378bd3f1c9394) |
| AgentListingRegistry | [`0x62a27eDca2ff1b3D8096c4dEBb64401c252feCA8`](https://basescan.org/address/0x62a27eDca2ff1b3D8096c4dEBb64401c252feCA8) |
| AgentLendingPool | [`0x01280fb29AAF3410Fb9129ee34b459325c51af1a`](https://basescan.org/address/0x01280fb29AAF3410Fb9129ee34b459325c51af1a) |
| PulseAMM | [`0xf78Eb43147356e66345c20c7d7299c3c54faaC5d`](https://basescan.org/address/0xf78Eb43147356e66345c20c7d7299c3c54faaC5d) |
| AgentAuditPool | [`0xee3e560D6fe9Df842433A8121d45037e125d5C01`](https://basescan.org/address/0xee3e560D6fe9Df842433A8121d45037e125d5C01) |
| PulseDistributor | [`0x37F17f2B733d9D801C7f03f6A6D1E5cA8898775e`](https://basescan.org/address/0x37F17f2B733d9D801C7f03f6A6D1E5cA8898775e) |
| PlonkVerifier (ZK) | [`0xb11af6f387aCD57E6AECDa222D0108e6380ACf65`](https://basescan.org/address/0xb11af6f387aCD57E6AECDa222D0108e6380ACf65) |

- **Service-economy stablecoin = real Base USDC** `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`
  (whitelisted in the escrow at deploy). No fake token. The **lottery uses native ETH**.
- AIAgentLottery: native-ETH tickets · 0.000003 ETH · prize/opex/operator 80/12/8 · off-chain VDF.
- **ACEX** (vault/registry/lending/amm/auditpool/distributor) is deployed + wired + verified, but
  **not value-tested** — the in-repo audit rated AuditPool TWAP + PulseAMM HIGH, so no real value
  is routed through them.
- A full end-to-end test was run (escrow capability channel, agent↔agent payment, a complete
  lottery round with a signed draw beacon); **all funds returned to `0x1218`** (2.0 USDC + ETH).
  Full per-transaction breakdown: [docs/onchain-journal.md](../../docs/onchain-journal.md).

## Honesty note
This is a **demonstration deployment with small real funds** (~2 USDC + ~0.006 ETH). "$"-pool
figures in any UNI/Anvil showcase are **play-money**, not these Base figures.
