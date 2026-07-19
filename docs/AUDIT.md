# Security Audit — AIAgentLottery + ChronosVDF + BigMath

**Method:** adversarial multi-agent audit (47 agents across 8 attack surfaces —
fund-safety, reentrancy, access control, randomness/MEV, signatures, arithmetic,
DoS/liveness, VDF/bignum — each finding independently verified to refute false
positives), plus Foundry regression tests for every fix. 37 findings confirmed.

> **This is an in-repo review, not a substitute for a professional third-party
> audit.** Do not hold real value on mainnet until the **Residual** items below are
> closed and an external audit + multisig/timelock are in place.

## Verdict on "funds cannot be diverted"

**Original verdict: FALSE as written.** The accounting *segregation* was sound
(opex/operator withdrawals are bounded by their own accrued counters and provably
cannot reach a round's prize pool), **but** the fairness layer was broken — a
malicious/compromised `ORACLE_SIGNER`, an admin who self-grants it, or (originally)
any mempool observer could rig the draw and take the whole pool, and sponsor
funding could be permanently stranded.

**After remediation (this commit):** the *exploitable* breaks are fixed or
materially mitigated and covered by regression tests; the remaining risk is
**operational/centralization** (trusted signer + single admin), explicitly
documented below and gated behind "use a multisig/timelock + m-of-n signers, and
keep value off this until an external audit." Honest current status: **safe for
testnet/demo; not yet for unaudited mainnet value.**

## Findings & remediation

| # | Severity | Finding | Status |
|---|---|---|---|
| C1 | Critical | On-chain VDF unsound — `l` not bound to `hash_to_prime`; `l=1` collapses check to `pi==y` | **Mitigated** — reject `l∈{0,1}`/even/oversized; with the pinned modulus, forging a *chosen* `y` requires an `l`-th root mod N (RSA-hard). Full `hash_to_prime` Miller–Rabin = **Residual**. Regression: `test_reject_l_equals_one_forgery` |
| C2 | Critical | VDF modulus `N` caller-controlled (zero/smooth N accepted; precompile returns 0 for zero-N) | **Fixed** — `N` pinned to the canonical Chronos RSA modulus (`ChronosVDF.CANONICAL_N`); `BigMath.modexp` now rejects a zero-*valued* modulus. Regression: `test_reject_noncanonical_modulus` |
| C3 | Critical | Beacon signed none of `(g,y,pi,l,N)`; `fulfillDraw` permissionless → mempool capture/forge | **Fixed** — `DrawBeacon` now commits `proofHash=keccak256(g,y,pi,l,N,T,seed)`; `fulfillDraw` is `OPERATOR_ROLE`-gated. Regression: `test_fulfillDraw_requires_operator`, `test_bad_beacon_signature_rejected` |
| C4 | Critical | `ORACLE_SIGNER`/`OPERATOR` can grind the draw — `platonRandom` (commit-reveal) **and** the seed block (`reseed` re-picked `block.number` freely with the delay anchored to `closedAt`, so an operator could reseed→wait 1 block→`eth_call fulfillDraw`→reseed if unfavorable→submit) | **Fixed** — (a) **commit-reveal**: operator commits `keccak256(platonRandom)` at `closeEntries` (before the seed block's blockhash/prevrandao exist); `fulfillDraw` rejects any other reveal (`BadReveal`). (b) `closeEntries` now **pins the seed to a fixed FUTURE block** (`block.number + SEED_BLOCK_OFFSET`), so its blockhash is unknown at close and not operator-chooseable. (c) `reseed` is a **rescue only** — refused until the pinned block ages past the 256-block window (`block.number ≤ seedBlock + 256` reverts `TooEarly`), then re-pins another future block and re-arms the draw delay — so a re-roll costs a full >256-block wait against an unpredictable future hash, not a cheap loop. Plus operator-gating + `block.prevrandao` mixed in. m-of-n signers = Residual (defense-in-depth). Regression: `test_reveal_must_match_commitment`, `test_reseed_is_rescue_only_not_a_reroll` |
| H5 | High | Sponsor `fund()` to a later-cancelled round permanently stranded; 256-block blockhash brick | **Fixed** — `fundedBy` ledger + `refund()` returns funding; `reseed()` rescues a `Drawing` round whose pinned seed block has aged out of the 256-block window, re-pinning a fresh **future** block (not a re-roll — see C4) and re-arming the draw delay so the rescue can still settle. Regression: `test_sponsor_funding_refundable_on_cancel`, `test_reseed_is_rescue_only_not_a_reroll` |
| H6 | High | `_buy` credited gross, not received → fee-on-transfer/rebasing under-funds (insolvency) | **Fixed** — `_buy` books the amount actually received (mirrors `fund`) |
| H7 | High | Admin could re-split a round between close and settle, skimming ≤35% of ticket revenue | **Fixed** — splits snapshotted into the `Round` at open and read at settle |
| H8 | High | Single `DEFAULT_ADMIN` administers every role; can self-grant `ORACLE_SIGNER`/`TREASURY` | **Fixed** — adopted `AccessControlDefaultAdminRules`; a **self-administered `GOVERNANCE_ROLE`** is the admin of `ORACLE_SIGNER`/`TREASURY`, so the operational `DEFAULT_ADMIN` cannot self-grant them. Regression: `test_admin_cannot_self_grant_oracle_signer`. (Set GOVERNANCE to a multisig in prod.) |
| M9 | Medium | `renounceRole`/sole-admin footgun (paused contract could freeze) | **Fixed** — `AccessControlDefaultAdminRules` forbids removing the last `DEFAULT_ADMIN` and makes admin transfer 2-step + time-delayed |
| M10 | Medium | `minDrawDelay` anchored to open + unbounded → could brick a round | **Fixed** — anchored to `closedAt`; bounded ≤ 1h in constructor + setter |
| L11 | Low | Operator can cancel any Open/Drawing round (fairness DoS) | **Partial** — funding now refundable; cancel-constraints (no-participants / post-deadline / permissionless refund) = Residual |
| L12 | Low | ReputationVoucher reusable (no nonce/count); cap-before-hash mutation | **Partial** — cap-before-hash replaced with a `require`; per-round nonce/count = Residual |
| L13 | Low | `withdrawOpex/OperatorFee` to arbitrary `to` | **Documented** — bounded by accrued counters (cannot touch prize); fixed-sink/multisig = Residual |
| L14 | Low | Zero `ticketPrice` → free weighted tickets | **Fixed** — `require(ticketPrice>0)` in constructor + setter |
| L15 | Low | Inbound CEI inversion in `_buy/fund` | **Documented** — safe today via `nonReentrant`; latent on guard removal |
| L16 | Low | Pause traps in-flight funds | **Documented** — `cancelRound`+`refund` is the guaranteed paused exit |
| I17 | Info | Beacon has no deadline/nonce (replay contained by state machine) | **Accepted** — optional hardening |
| I18 | Info | Participants array storage-griefing (draw stays O(log n)) | **Accepted** — no draw-DoS |
| I19 | Info | Unbounded modexp exponent length (griefing) | **Mitigated** — `l` now ≤16 bytes |
| ✓ | Info | Opex/operator isolated from prize; no double-claim/refund; outbound CEI + reentrancy correct | **Verified safe** (preserved) |

## Residual — required before any real-value mainnet deployment

The exploitable code paths are now closed in-repo (see the table). What remains is
deeper soundness margin + decentralization + an external sign-off:

1. **VDF soundness, belt-and-suspenders:** implement `l == hash_to_prime(g,y,T)`
   (on-chain SHA-256 transcript + Miller–Rabin) so soundness doesn't lean on the
   pinned-modulus + RSA-hardness argument alone. _Why not yet:_ Chronos derives `l`
   from a **decimal-string** Fiat–Shamir transcript; reproducing that on-chain needs
   a full bignum→decimal conversion (thousands of `DIV` over 2055-bit limbs) per
   verify — prohibitively expensive. Mitigated meanwhile by the pinned canonical `N`
   + degenerate-`l` rejection + the signer-bound `proofHash`.
2. **m-of-n signers + proposer trust:** the trust assumption is now *defense-in-depth*
   only — grinding is blocked by commit-reveal **and** the fixed-future-block seed pin
   with rescue-only `reseed` (C4) — but a single `ORACLE_SIGNER` key should become an
   **m-of-n** threshold before real value. Residual assumption: the seed's unbiasability
   rests on the pinned block's `blockhash` (and mixed `prevrandao`) being outside the
   operator's control. A validator/sequencer that proposes the exact pinned block, or an
   operator colluding with one, retains the standard single-slot influence over that hash
   — treat `blockhash`/`prevrandao` as weak on L2 sequencers and prefer `onchainVdf=true`
   for value. Also note the seed pin lives inside the 256-block `blockhash` window:
   `minDrawDelay` must correspond to fewer than ~256 blocks on the target chain (the
   constructor caps it at 1h and assumes it stays "well under" the window); a delay set
   larger than the window on a fast chain would force perpetual `reseed` rescues — keep
   `MIN_DRAW_DELAY` small (default 60s) relative to block time.
3. **Decentralize admin (operational):** `AccessControlDefaultAdminRules` +
   `GOVERNANCE_ROLE` separation are **in code** (M9/H8 fixed); the remaining step is
   *operational* — point `DEFAULT_ADMIN`/`GOVERNANCE` at a Gnosis Safe multisig +
   `TimelockController`, constrain `withdraw*` to a fixed treasury sink, constrain
   operator cancellation, make the voucher single-use.
4. **External professional audit** of the whole flow.

## Economic-model update (post-audit) — split now draws from total income

The split was reworked so the lottery (not the donor) owns it: **opex is a capped
share of TOTAL income (ticket revenue + donations), not just ticket revenue**, and
donations are no longer 100%→prize. This is deliberate (the lottery is an economic
actor that must fund its own operations), and it is made safe by construction:

- **Guaranteed prize floor.** `_setSplits` enforces `prize ≥ MIN_PRIZE_BPS` (raised to
  **70%**) and `opex ≤ MAX_OPEX_BPS` (**30%**), snapshotted per round — so opex can
  never starve the winner. Regression: `test_prize_floor_enforced`,
  `test_valid_high_opex_split_accepted`.
- **Opex stays segregated.** It accrues to `opexAccrued`, is withdraw-bounded, and is
  provably unable to reach a settled round's `prizePool` (unchanged invariant).
- **The AI Treasurer is constrained by the same wall.** It allocates only the on-chain
  opex bucket; it has no path to the prize pool. Off-chain failures (bad/missing
  Chronos proof on the opt-in `onchainVdf` path) now **fail safe** — the round is
  cancelled (funds refundable) rather than bricked. Fixes the two review criticals
  (decimal-string VDF parsing; `None`-deref guard).

The "funds cannot be diverted" story therefore reads, post-change: **the winner's
floor (≥70% of all income) is guaranteed on-chain; opex (≤30%) is capped, segregated,
and AI-managed; the Hub funds only its bound lottery.**

## Verified-safe (do not regress)

Funding is one-way IN and joins the round's income (refundable to payer/funder only,
after cancel); the prize floor (≥70%) is guaranteed and prizes are pull-payment,
winner-only, once; opex/operator withdrawals are bounded by their own accrued counters
and cannot reach the prize pool; all value-moving functions are `nonReentrant` with
effects-before-interactions.

_Full machine-readable findings: the audit run's output (47 agents) in the
session transcript._
