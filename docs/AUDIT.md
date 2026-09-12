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
| C3 | Critical | Beacon signed none of `(g,y,pi,l,N)`; `fulfillDraw` permissionless → mempool capture/forge | **Fixed** — `DrawBeacon` now commits `proofHash=keccak256(g,y,pi,l,N,T,seed)`, so a mempool observer can only replay the same beacon and produce the same winner. The operator gate added at the time was **later removed** — it bought no additional security and was itself a withholding lever (see *Fairness rework* below). Regression: `test_bad_beacon_signature_rejected`, `test_settlement_still_requires_an_oracle_signed_beacon` |
| C4 | Critical | `ORACLE_SIGNER`/`OPERATOR` can grind the draw — `platonRandom` (commit-reveal) **and** the seed block (`reseed` re-picked `block.number` freely with the delay anchored to `closedAt`, so an operator could reseed→wait 1 block→`eth_call fulfillDraw`→reseed if unfavorable→submit) | **Fixed** — (a) **commit-reveal**: operator commits `keccak256(platonRandom)` at `closeEntries` (before the seed block's blockhash/prevrandao exist); `fulfillDraw` rejects any other reveal (`BadReveal`). (b) `closeEntries` now **pins the seed to a fixed FUTURE block** (`block.number + SEED_BLOCK_OFFSET`), so its blockhash is unknown at close and not operator-chooseable. (c) `reseed` is a **rescue only** — refused until the pinned block ages past the 256-block window (`block.number ≤ seedBlock + 256` reverts `TooEarly`), then re-pins another future block and re-arms the draw delay — so a re-roll costs a full >256-block wait against an unpredictable future hash, not a cheap loop. The operator gate and the `block.prevrandao` mixing added here were **later removed** as counter-productive (see *Fairness rework*); a rescue now also requires FRESH, never-before-used committed entropy, a cooldown, and is capped at `MAX_RESEEDS`. m-of-n signers = Residual (defense-in-depth). Regression: `test_reveal_must_match_commitment`, `test_reseed_is_rescue_only_not_a_reroll`, `test_reseed_rejected_without_fresh_entropy`, `test_reseed_refused_before_cooldown`, `test_reseed_capped_then_round_is_only_cancellable` |
| H5 | High | Sponsor `fund()` to a later-cancelled round permanently stranded; 256-block blockhash brick | **Fixed** — `fundedBy` ledger + `refund()` returns funding; `reseed()` rescues a `Drawing` round whose pinned seed block has aged out of the 256-block window, re-pinning a fresh **future** block (not a re-roll — see C4) and re-arming the draw delay so the rescue can still settle. Regression: `test_sponsor_funding_refundable_on_cancel`, `test_reseed_is_rescue_only_not_a_reroll` |
| H6 | High | `_buy` credited gross, not received → fee-on-transfer/rebasing under-funds (insolvency) | **Fixed** — `_buy` books the amount actually received (mirrors `fund`) |
| H7 | High | Admin could re-split a round between close and settle, skimming ≤35% of ticket revenue | **Fixed** — splits snapshotted into the `Round` at open and read at settle |
| H8 | High | Single `DEFAULT_ADMIN` administers every role; can self-grant `ORACLE_SIGNER`/`TREASURY` | **Fixed** — adopted `AccessControlDefaultAdminRules`; a **self-administered `GOVERNANCE_ROLE`** is the admin of `ORACLE_SIGNER`/`TREASURY`, so the operational `DEFAULT_ADMIN` cannot self-grant them. Regression: `test_admin_cannot_self_grant_oracle_signer`. (Set GOVERNANCE to a multisig in prod.) |
| M9 | Medium | `renounceRole`/sole-admin footgun (paused contract could freeze) | **Fixed** — `AccessControlDefaultAdminRules` forbids removing the last `DEFAULT_ADMIN` and makes admin transfer 2-step + time-delayed |
| M10 | Medium | `minDrawDelay` anchored to open + unbounded → could brick a round | **Fixed** — anchored to `closedAt`; bounded by `maxDrawDelay()`, **derived from the declared `secondsPerBlock`** rather than the original 1 h literal (which was ~7× the real settle window on a 2 s L2). Regression: `test_draw_delay_bound_is_derived_from_declared_block_time`, `test_constructor_rejects_a_draw_delay_that_would_brick_rounds`, `test_delay_past_the_window_expires_every_seed`, `test_block_time_change_revalidates_the_draw_delay` |
| L11 | Low | Operator can cancel any Open/Drawing round (fairness DoS) | **Fixed** — funding refundable; `cancelRound` now REFUSES a Drawing round whose pinned blockhash is readable (otherwise it was an unlimited, cooldown-free re-roll next to the bounded `reseed` one), and `cancelStalledRound` lets **anyone** cancel + refund after `STALL_CANCEL_DELAY`. Regression: `test_operator_cannot_cancel_a_round_whose_outcome_is_already_visible`, `test_operator_can_still_cancel_a_round_nobody_could_settle`, `test_stalled_round_cancellable_by_anyone_and_fully_refunded` |
| L12 | Low | ReputationVoucher reusable (no nonce/count); cap-before-hash mutation | **Partial** — cap-before-hash replaced with a `require`; per-round nonce/count = Residual |
| L13 | Low | `withdrawOpex/OperatorFee` to arbitrary `to` | **Documented** — bounded by accrued counters (cannot touch prize); fixed-sink/multisig = Residual |
| L14 | Low | Zero `ticketPrice` → free weighted tickets | **Fixed** — `require(ticketPrice>0)` in constructor + setter |
| L15 | Low | Inbound CEI inversion in `_buy/fund` | **Documented** — safe today via `nonReentrant`; latent on guard removal |
| L16 | Low | Pause traps in-flight funds | **Fixed** — pause gates money coming IN only. `fulfillDraw`, `closeEntries`, `reseed`, `cancelStalledRound`, `claimPrize`, `refund` and `withdraw*` are all reachable while paused, so a pause can neither trap entries nor nullify a settleable outcome. Regression: `test_pausing_cannot_withhold_a_settlement`, `test_pause_blocks_entries` |
| L20 | Low | *(follow-up review, not part of the original 37)* An unreachable winner strands the prize in the contract forever | **Fixed** — `forfeitUnclaimedPrize` (permissionless, after `UNCLAIMED_PRIZE_TTL` = 180 d) moves it to `unclaimedPool`, which no role can withdraw and whose only exit is a later round's prize, untaxed and capped at that round's own income. Regression: `test_unclaimed_prize_is_recycled_into_a_later_round`, `test_recycled_prize_cannot_be_harvested_by_a_one_ticket_round`, `test_claimed_prize_cannot_be_forfeited` |
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
   rests on the pinned block's `blockhash` being outside the operator's control. A
   validator/sequencer that proposes the exact pinned block, or an operator colluding
   with one, retains the standard single-slot influence over that hash — treat
   `blockhash` as weak on L2 sequencers and prefer `onchainVdf=true` for value. The
   irreducible operator lever: it alone produces the beacon, so it can compute the
   outcome privately, never publish, and let the round die into a refund — slow, costs a
   full seed window, refunds everyone and earns nothing, but it is the last word on
   whether a round happens at all.
3. **Declared block time is an operational assumption, not a checked one.** The seed
   lives inside a 256-block window, so `maxDrawDelay()` is derived from
   `secondsPerBlock` — which `setSecondsPerBlock` **declares** and no on-chain code can
   verify. A wrong declaration authorises a `minDrawDelay` no seed survives and bricks
   every round into the rescue path. This is a runbook/monitoring obligation: see
   [README.md](README.md) → *The draw window*.
4. **Decentralize admin (operational):** `AccessControlDefaultAdminRules` +
   `GOVERNANCE_ROLE` separation are **in code** (M9/H8 fixed); the remaining step is
   *operational* — point `DEFAULT_ADMIN`/`GOVERNANCE` at a Gnosis Safe multisig +
   `TimelockController`, constrain `withdraw*` to a fixed treasury sink, and make the
   voucher single-use (operator cancellation is now constrained on-chain — L11).
5. **External professional audit** of the whole flow.

## Fairness rework (post-audit) — two of the original fixes were themselves levers

Re-reviewing C3/C4 found that two of their remediations traded one bias for another,
so both were **removed**. Anything still describing them is out of date:

- **`fulfillDraw` is no longer `OPERATOR_ROLE`-gated, and is not Pausable-gated.**
  The winner is a pure function of `(roundId, blockhash(seedBlock), platonRandom)`,
  all three fixed before anyone can act on them, so a mempool observer can only
  replay the same beacon and reproduce the same winner — the gate bought nothing.
  What it *did* buy the operator was a withholding lever: see the outcome, refuse to
  submit, wait for the seed to expire, `reseed`. A pause on settlement was the same
  lever in the admin's hands. Now any holder of a valid beacon can settle.
  Regression: `test_stalled_round_settles_from_a_third_party`,
  `test_pausing_cannot_withhold_a_settlement`.
- **`block.prevrandao` is no longer mixed into the random word.** Commit-reveal
  already pins `platonRandom` and the blockhash is unknown at commit time, so it
  added no entropy against the signer — while making the winner a function of the
  *submission* block, i.e. exactly a re-roll lever (and on OP-stack L2s it is
  inherited from the L1 origin block, identical across many consecutive L2 blocks
  and predictable to the submitter anyway). Dropping it is what makes permissionless
  settlement sound. Regression: `test_winner_is_independent_of_the_submission_block`.

Closing the levers those two removals opened elsewhere: `reseed` now requires a
never-before-used commitment plus a cooldown and is capped (C4), `cancelRound`
refuses a settleable round and `cancelStalledRound` is permissionless (L11), and
unclaimed prizes recycle instead of stranding (L20).

**Off-chain consequence.** The relayer mirrors this ABI by hand, and the rework
changed `reseed(uint256)` → `reseed(uint256,bytes32)` and added five events —
drift that reverts calls and blanks log filters without raising anything locally.
`relayer/tests/test_abi_contract_agreement.py` now derives every selector, topic0
and tuple layout from the compiled artifact and the `.sol` source and asserts the
relayer agrees, so this class of drift cannot silently return.

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
