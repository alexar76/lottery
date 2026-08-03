// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.28;

import {Test} from "forge-std/Test.sol";
import {AIAgentLottery} from "../src/AIAgentLottery.sol";

contract AIAgentLotteryTest is Test {
    AIAgentLottery lot;

    address admin = address(0xA11CE);
    address operator = address(0x0B);
    address treasury = address(0x7);
    uint256 signerPk = 0xBEEF;
    address signer;

    address governance = address(0x6);
    address agentA = address(0xA1);
    address agentB = address(0xB2);
    address agentC = address(0xC3);
    address benefactor = address(0xF00D);
    address bystander = address(0xDEAD5); // holds no role at all

    uint256 constant PRICE = 0.01 ether;

    function setUp() public {
        signer = vm.addr(signerPk);
        lot = new AIAgentLottery(
            admin, governance, operator, signer, treasury, // admin, governance, operator, signer, treasury
            address(0), // native ETH
            PRICE,
            8000, 1200, 800, // prize/opex/operator
            1 hours, // entry window
            0, // min draw delay
            false, // onchainVdf off for this suite
            0 // admin transfer delay
        );
        vm.deal(agentA, 10 ether);
        vm.deal(agentB, 10 ether);
        vm.deal(agentC, 10 ether);
        vm.deal(benefactor, 10 ether);
    }

    function _open() internal returns (uint256 id) {
        vm.prank(operator);
        id = lot.openRound();
    }

    /// @dev the on-chain commitment for a randomness value.
    function _commit(bytes32 rnd) internal pure returns (bytes32) {
        return keccak256(abi.encodePacked(rnd));
    }

    /// @dev move past the pinned seed's blockhash window AND the rescue cooldown.
    ///      Every jump is ABSOLUTE (derived from round state): the optimizer is allowed
    ///      to treat `block.timestamp`/`block.number` as constant within a call, so a
    ///      relative `block.timestamp + x` read in a test body can silently use a
    ///      pre-warp value.
    function _ageOutSeed(uint256 id) internal returns (uint256 atBlock, uint256 atTime) {
        atBlock = lot.getRound(id).seedBlock + lot.BLOCKHASH_WINDOW() + 1;
        atTime = uint256(lot.getRound(id).closedAt) + lot.RESEED_COOLDOWN();
        vm.roll(atBlock);
        vm.warp(atTime);
    }

    /// @dev close entries for `id` at the earliest legal moment (absolute warp).
    function _close(uint256 id, bytes32 rnd) internal {
        vm.warp(uint256(lot.getRound(id).entriesClose) + 1);
        vm.prank(operator);
        lot.closeEntries(id, _commit(rnd));
    }

    function _buy(address who, uint256 id, uint256 count) internal {
        vm.prank(who);
        lot.buyTickets{value: PRICE * count}(id, count);
    }

    function _beaconSig(uint256 roundId, bytes32 platonRandom, uint256 vdfT) internal view returns (bytes memory) {
        return _beaconSig(roundId, platonRandom, vdfT, signerPk);
    }

    function _beaconSig(uint256 roundId, bytes32 platonRandom, uint256 vdfT, uint256 pk)
        internal
        view
        returns (bytes memory)
    {
        AIAgentLottery.VdfProof memory empty;
        bytes32 proofHash =
            keccak256(abi.encode(empty.g, empty.y, empty.pi, empty.l, empty.N, empty.T, keccak256(bytes(empty.seed))));
        bytes32 structHash = keccak256(
            abi.encode(
                keccak256("DrawBeacon(uint256 roundId,bytes32 platonRandom,uint256 vdfT,bytes32 proofHash)"),
                roundId,
                platonRandom,
                vdfT,
                proofHash
            )
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(pk, _typed(structHash));
        return abi.encodePacked(r, s, v);
    }

    function _voucherSig(address agent, uint256 roundId, uint16 repBps, uint64 expiry) internal view returns (bytes memory) {
        bytes32 structHash = keccak256(
            abi.encode(
                keccak256("ReputationVoucher(address agent,uint256 roundId,uint16 repBonusBps,uint64 expiry)"),
                agent, roundId, repBps, expiry
            )
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(signerPk, _typed(structHash));
        return abi.encodePacked(r, s, v);
    }

    function _typed(bytes32 structHash) internal view returns (bytes32) {
        bytes32 domain = keccak256(
            abi.encode(
                keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
                keccak256("AIAgentLottery"),
                keccak256("1"),
                block.chainid,
                address(lot)
            )
        );
        return keccak256(abi.encodePacked("\x19\x01", domain, structHash));
    }

    function _draw(uint256 id, bytes32 rnd) internal {
        _close(id, rnd); // commits the randomness
        vm.roll(lot.getRound(id).seedBlock + 1); // mine past the pinned future seedBlock
        AIAgentLottery.VdfProof memory empty;
        vm.prank(operator);
        lot.fulfillDraw(id, rnd, 0, _beaconSig(id, rnd, 0), empty);
    }

    function test_full_lifecycle_and_splits() public {
        uint256 id = _open();
        _buy(agentA, id, 1);
        _buy(agentB, id, 1);
        _buy(agentC, id, 1);
        // benefactor funds the prize pool directly (uni-mode external funding)
        vm.prank(benefactor);
        lot.fund{value: 1 ether}(id, 1 ether);

        uint256 ticketRevenue = PRICE * 3;
        _draw(id, keccak256("rnd-1"));

        AIAgentLottery.Round memory r = lot.getRound(id);
        assertEq(uint8(r.status), uint8(AIAgentLottery.Status.Settled));
        // splits now apply to TOTAL income (tickets + funding): opex 12%, operator 8%, prize = remainder (80%).
        uint256 income = ticketRevenue + 1 ether;
        uint256 expectOpex = (income * 1200) / 10000;
        uint256 expectOperator = (income * 800) / 10000;
        uint256 expectPrize = income - expectOpex - expectOperator;
        assertEq(r.prizePool, expectPrize, "prize");
        assertEq(lot.opexAccrued(), expectOpex, "opex");
        assertEq(lot.operatorAccrued(), expectOperator, "operator");
        assertTrue(r.winner == agentA || r.winner == agentB || r.winner == agentC, "winner is a participant");

        // winner claims (pull payment)
        uint256 balBefore = r.winner.balance;
        vm.prank(r.winner);
        lot.claimPrize(id);
        assertEq(r.winner.balance, balBefore + expectPrize, "prize paid");

        // treasury withdraws opex to pay oracle/agent services off-chain
        vm.prank(treasury);
        lot.withdrawOpex(treasury, expectOpex);
        assertEq(treasury.balance, expectOpex, "opex withdrawn");
    }

    function test_reputation_voucher_boosts_weight() public {
        uint256 id = _open();
        // agentA gets a +50% reputation voucher → weight 1.5x for 2 tickets = 3
        uint64 expiry = uint64(block.timestamp + 1 days);
        vm.prank(agentA);
        lot.buyTicketsWithVoucher{value: PRICE * 2}(id, 2, 5000, expiry, _voucherSig(agentA, id, 5000, expiry));
        _buy(agentB, id, 2); // flat weight 2
        // total weight = 3 + 2 = 5
        // (not asserting the winner, just that the boosted path works and accrues weight)
        assertEq(lot.participantsCount(id), 2);
    }

    function test_cancel_and_refund() public {
        uint256 id = _open();
        _buy(agentA, id, 2);
        uint256 paid = PRICE * 2;
        vm.prank(operator);
        lot.cancelRound(id);
        uint256 before = agentA.balance;
        vm.prank(agentA);
        lot.refund(id);
        assertEq(agentA.balance, before + paid, "refunded");
    }

    function test_access_control() public {
        vm.expectRevert();
        lot.openRound(); // not operator
        uint256 id = _open();
        vm.expectRevert();
        lot.cancelRound(id); // not operator
    }

    function test_bad_beacon_signature_rejected() public {
        uint256 id = _open();
        _buy(agentA, id, 1);
        vm.warp(block.timestamp + 1 hours + 1);
        vm.prank(operator);
        lot.closeEntries(id, keccak256(abi.encodePacked(keccak256("DIFFERENT")))); // commit the revealed value
        vm.roll(block.number + lot.SEED_BLOCK_OFFSET() + 1);
        AIAgentLottery.VdfProof memory empty;
        bytes memory badSig = _beaconSig(id, keccak256("a"), 0);
        vm.prank(operator);
        vm.expectRevert(AIAgentLottery.BadSignature.selector);
        lot.fulfillDraw(id, keccak256("DIFFERENT"), 0, badSig, empty); // payload mismatch → recovers wrong addr
    }

    function test_pause_blocks_entries() public {
        uint256 id = _open();
        vm.prank(admin);
        lot.pause();
        vm.prank(agentA);
        vm.expectRevert();
        lot.buyTickets{value: PRICE}(id, 1);
    }

    function test_weighted_winner_is_deterministic() public {
        // single participant always wins
        uint256 id = _open();
        _buy(agentA, id, 1);
        _draw(id, keccak256("x"));
        assertEq(lot.getRound(id).winner, agentA);
    }

    function test_sponsor_funding_refundable_on_cancel() public {
        // AUDIT high: sponsor funding to a cancelled round must be recoverable.
        uint256 id = _open();
        _buy(agentA, id, 1);
        vm.prank(benefactor);
        lot.fund{value: 1 ether}(id, 1 ether);
        vm.prank(operator);
        lot.cancelRound(id);
        uint256 before = benefactor.balance;
        vm.prank(benefactor);
        lot.refund(id);
        assertEq(benefactor.balance, before + 1 ether, "sponsor funding refunded");
    }

    function test_reveal_must_match_commitment() public {
        // AUDIT C4: commit-reveal — a platonRandom different from the committed one is rejected.
        uint256 id = _open();
        _buy(agentA, id, 1);
        vm.warp(block.timestamp + 1 hours + 1);
        vm.prank(operator);
        lot.closeEntries(id, keccak256(abi.encodePacked(keccak256("committed"))));
        vm.roll(block.number + lot.SEED_BLOCK_OFFSET() + 1);
        AIAgentLottery.VdfProof memory empty;
        vm.prank(operator);
        vm.expectRevert(AIAgentLottery.BadReveal.selector);
        lot.fulfillDraw(id, keccak256("grinded"), 0, _beaconSig(id, keccak256("grinded"), 0), empty);
    }

    function test_reseed_is_rescue_only_not_a_reroll() public {
        // AUDIT C4/H5: reseed must NOT let the operator observe the pending outcome and
        // pick a fresh blockhash. It is a rescue, allowed only once the pinned seedBlock
        // has aged past the 256-block window, and it re-pins to a fresh FUTURE block and
        // re-arms the draw delay.
        uint256 id = _open();
        _buy(agentA, id, 1);
        bytes32 rnd2 = keccak256("x2");
        uint256 closeBlock = block.number;
        _close(id, keccak256("x"));
        uint256 seedBlock = lot.getRound(id).seedBlock;
        assertEq(seedBlock, closeBlock + lot.SEED_BLOCK_OFFSET(), "close pins a future seed block");

        // seed not yet mined → reseed refused (cannot pre-empt a pending seed)
        vm.prank(operator);
        vm.expectRevert(AIAgentLottery.TooEarly.selector);
        lot.reseed(id, _commit(rnd2));

        // seed mined and still within the 256-block window → reseed still refused
        vm.roll(seedBlock + 1);
        vm.prank(operator);
        vm.expectRevert(AIAgentLottery.TooEarly.selector);
        lot.reseed(id, _commit(rnd2));

        // once the seed ages out (>256 blocks) AND the cooldown has passed the rescue is
        // allowed: re-pins a fresh future block and re-arms the delay anchor.
        (uint256 atBlock, uint256 atTime) = _ageOutSeed(id);
        vm.prank(operator);
        lot.reseed(id, _commit(rnd2));
        AIAgentLottery.Round memory r = lot.getRound(id);
        assertEq(r.seedBlock, atBlock + lot.SEED_BLOCK_OFFSET(), "reseed re-pins a fresh future block");
        assertEq(r.closedAt, uint64(atTime), "reseed re-arms the draw delay anchor");

        // and the rescued round can still be settled from the fresh seed
        vm.roll(r.seedBlock + 1);
        AIAgentLottery.VdfProof memory empty;
        vm.prank(operator);
        lot.fulfillDraw(id, rnd2, 0, _beaconSig(id, rnd2, 0), empty);
        assertEq(lot.getRound(id).winner, agentA, "rescued round settles to the sole participant");
    }

    function test_reseed_rejected_without_fresh_entropy() public {
        // FINDING #10: a rescue that reuses the ALREADY-REVEALED-to-the-operator
        // commitment is a free re-roll of the same beacon against a new blockhash.
        // The rescue must bring a never-before-used commitment (⇒ a fresh
        // ORACLE_SIGNER beacon), and the old randomness must no longer settle.
        uint256 id = _open();
        _buy(agentA, id, 1);
        bytes32 rnd = keccak256("stale");
        bytes32 fresh = keccak256("fresh");
        _close(id, rnd);
        _ageOutSeed(id);

        vm.prank(operator);
        vm.expectRevert(AIAgentLottery.StaleCommitment.selector);
        lot.reseed(id, _commit(rnd));

        // a zero commitment is unrevealable — refuse rather than brick the round
        vm.prank(operator);
        vm.expectRevert(AIAgentLottery.BadReveal.selector);
        lot.reseed(id, bytes32(0));

        vm.prank(operator);
        lot.reseed(id, _commit(fresh));
        assertEq(lot.reseedCount(id), 1, "rescue is counted");
        AIAgentLottery.Round memory r = lot.getRound(id);
        assertEq(r.seedCommitment, _commit(fresh), "rescue re-commits fresh entropy");

        // the stale beacon cannot settle the rescued round any more
        vm.roll(r.seedBlock + 1);
        AIAgentLottery.VdfProof memory empty;
        vm.expectRevert(AIAgentLottery.BadReveal.selector);
        lot.fulfillDraw(id, rnd, 0, _beaconSig(id, rnd, 0), empty);
        lot.fulfillDraw(id, fresh, 0, _beaconSig(id, fresh, 0), empty);
        assertEq(lot.getRound(id).winner, agentA);

        // and a used commitment can never be re-committed on this round
        assertTrue(lot.commitmentUsed(id, _commit(rnd)), "close commitment recorded");
        assertTrue(lot.commitmentUsed(id, _commit(fresh)), "rescue commitment recorded");
    }

    function test_reseed_refused_before_cooldown() public {
        // Even with the seed hash expired, a rescue waits out RESEED_COOLDOWN — so
        // re-rolls can never be sampled at the pace of the blockhash window itself
        // (~8.5 min on a 2s chain).
        uint256 id = _open();
        _buy(agentA, id, 1);
        _close(id, keccak256("c"));
        uint64 closedAt = lot.getRound(id).closedAt;

        vm.roll(lot.getRound(id).seedBlock + lot.BLOCKHASH_WINDOW() + 1);
        vm.warp(uint256(closedAt) + lot.RESEED_COOLDOWN() - 1);
        vm.prank(operator);
        vm.expectRevert(AIAgentLottery.TooEarly.selector);
        lot.reseed(id, _commit(keccak256("c2")));

        vm.warp(uint256(closedAt) + lot.RESEED_COOLDOWN());
        vm.prank(operator);
        lot.reseed(id, _commit(keccak256("c2")));
        assertEq(lot.reseedCount(id), 1);
    }

    function test_reseed_capped_then_round_is_only_cancellable() public {
        // Bounded re-rolls: after MAX_RESEEDS the operator's only remaining move is a
        // cancel, which refunds tickets and sponsor funding.
        uint256 id = _open();
        _buy(agentA, id, 2);
        uint256 paid = PRICE * 2;
        vm.prank(benefactor);
        lot.fund{value: 1 ether}(id, 1 ether);
        _close(id, keccak256("k0"));

        for (uint16 i = 1; i <= lot.MAX_RESEEDS(); i++) {
            _ageOutSeed(id);
            vm.prank(operator);
            lot.reseed(id, _commit(keccak256(abi.encodePacked("k", i))));
            assertEq(lot.reseedCount(id), i, "rescue counter");
        }

        _ageOutSeed(id);
        vm.prank(operator);
        vm.expectRevert(AIAgentLottery.ReseedLimit.selector);
        lot.reseed(id, _commit(keccak256("k-last")));

        vm.prank(operator);
        lot.cancelRound(id);
        uint256 aBefore = agentA.balance;
        uint256 bBefore = benefactor.balance;
        vm.prank(agentA);
        lot.refund(id);
        vm.prank(benefactor);
        lot.refund(id);
        assertEq(agentA.balance, aBefore + paid, "tickets refunded after a capped-out round");
        assertEq(benefactor.balance, bBefore + 1 ether, "sponsor funding refunded too");
    }

    function test_stalled_round_settles_from_a_third_party() public {
        // FINDING #10: the operator must not be able to withhold a settlement. Once a
        // valid ORACLE_SIGNER beacon exists, ANY address can settle the round.
        uint256 id = _open();
        _buy(agentA, id, 1);
        bytes32 rnd = keccak256("stalled");
        _close(id, rnd);
        vm.roll(lot.getRound(id).seedBlock + 1);

        AIAgentLottery.VdfProof memory empty;
        vm.prank(bystander); // no OPERATOR_ROLE, no ORACLE_SIGNER_ROLE
        lot.fulfillDraw(id, rnd, 0, _beaconSig(id, rnd, 0), empty);

        assertEq(uint8(lot.getRound(id).status), uint8(AIAgentLottery.Status.Settled), "third party settled it");
        assertEq(lot.getRound(id).winner, agentA);
    }

    function test_operator_cannot_cancel_a_round_whose_outcome_is_already_visible() public {
        // FINDING #10 (residual found in review): permissionless settlement is worthless
        // if the operator can nullify it. `cancelRound` accepted any Drawing round, so an
        // operator that disliked the (already computable) winner could refund everyone —
        // instantly, for free, with no cooldown and no cap — or simply front-run a
        // participant's fulfillDraw in the mempool. That is an UNBOUNDED re-roll lever
        // next to the bounded MAX_RESEEDS one.
        uint256 id = _open();
        _buy(agentA, id, 1);
        _buy(agentB, id, 1);
        bytes32 rnd = keccak256("visible");
        _close(id, rnd);
        vm.roll(lot.getRound(id).seedBlock + 1);
        assertTrue(blockhash(lot.getRound(id).seedBlock) != bytes32(0), "winner is computable now");

        vm.prank(operator);
        vm.expectRevert(AIAgentLottery.TooEarly.selector);
        lot.cancelRound(id);

        // the round remains settleable by anyone, which is the whole point
        AIAgentLottery.VdfProof memory empty;
        vm.prank(bystander);
        lot.fulfillDraw(id, rnd, 0, _beaconSig(id, rnd, 0), empty);
        assertEq(uint8(lot.getRound(id).status), uint8(AIAgentLottery.Status.Settled));
    }

    function test_operator_can_still_cancel_a_round_nobody_could_settle() public {
        // The gate must not remove the honest exit: before the seed is mined, after it
        // has aged out, and for a round with no participants at all, cancelling is the
        // only sane move and carries no information advantage.
        uint256 id = _open();
        _buy(agentA, id, 1);
        _close(id, keccak256("pre-mine"));
        vm.prank(operator);
        lot.cancelRound(id); // seed pinned 4 blocks ahead, hash does not exist yet
        assertEq(uint8(lot.getRound(id).status), uint8(AIAgentLottery.Status.Cancelled));

        uint256 id2 = _open();
        _buy(agentB, id2, 1);
        _close(id2, keccak256("aged"));
        _ageOutSeed(id2);
        vm.prank(operator);
        lot.cancelRound(id2); // hash gone for good → nobody can settle it
        assertEq(uint8(lot.getRound(id2).status), uint8(AIAgentLottery.Status.Cancelled));

        uint256 id3 = _open(); // nobody bought a ticket → no winner to observe
        _close(id3, keccak256("empty"));
        vm.roll(lot.getRound(id3).seedBlock + 1);
        vm.prank(operator);
        lot.cancelRound(id3);
        assertEq(uint8(lot.getRound(id3).status), uint8(AIAgentLottery.Status.Cancelled));
    }

    function test_pausing_cannot_withhold_a_settlement() public {
        // FINDING #10 (residual found in review): `fulfillDraw` was the only Pausable
        // gate on the settle path — closeEntries, reseed, claimPrize and refund never
        // were. So pausing did not stop the round, it only stopped the SETTLEMENT: the
        // admin could freeze a round whose winner it disliked until the seed expired,
        // then unpause and let the operator reseed. Settling an already-closed round
        // pays nobody (the prize is pull-based), so it stays open while paused.
        uint256 id = _open();
        _buy(agentA, id, 1);
        bytes32 rnd = keccak256("paused");
        _close(id, rnd);
        vm.roll(lot.getRound(id).seedBlock + 1);

        vm.prank(admin);
        lot.pause();

        AIAgentLottery.VdfProof memory empty;
        vm.prank(bystander);
        lot.fulfillDraw(id, rnd, 0, _beaconSig(id, rnd, 0), empty);
        assertEq(lot.getRound(id).winner, agentA, "a pause cannot freeze a settleable round");

        // new money is still refused while paused — that is what pausing is for
        vm.prank(agentB);
        vm.expectRevert();
        lot.buyTickets{value: PRICE}(id, 1);

        uint256 before = agentA.balance;
        vm.prank(agentA);
        lot.claimPrize(id);
        assertEq(agentA.balance, before + lot.getRound(id).prizePool, "prize claimable while paused");
    }

    function test_settlement_still_requires_an_oracle_signed_beacon() public {
        // Permissionless does not mean unauthenticated: a beacon signed by anyone other
        // than ORACLE_SIGNER is refused no matter who submits it.
        uint256 id = _open();
        _buy(agentA, id, 1);
        bytes32 rnd = keccak256("forged");
        _close(id, rnd);
        vm.roll(lot.getRound(id).seedBlock + 1);

        AIAgentLottery.VdfProof memory empty;
        vm.prank(bystander);
        vm.expectRevert(AIAgentLottery.BadSignature.selector);
        lot.fulfillDraw(id, rnd, 0, _beaconSig(id, rnd, 0, 0xC0FFEE), empty);
    }

    function test_winner_is_independent_of_the_submission_block() public {
        // The whole reason permissionless settlement is safe: the word is a pure
        // function of (roundId, blockhash(seedBlock), platonRandom). Mixing
        // block.prevrandao made it a function of the SUBMISSION block, i.e. a re-roll
        // lever for whoever submits.
        uint256 id = _open();
        _buy(agentA, id, 1);
        _buy(agentB, id, 1);
        bytes32 rnd = keccak256("determinism");
        _close(id, rnd);
        uint256 seedBlock = lot.getRound(id).seedBlock;
        vm.roll(seedBlock + 1);
        bytes32 bh = blockhash(seedBlock);
        assertTrue(bh != bytes32(0), "seed hash available");

        vm.prevrandao(bytes32(uint256(0xBADC0DE))); // arbitrary submission-block entropy
        AIAgentLottery.VdfProof memory empty;
        vm.prank(bystander);
        lot.fulfillDraw(id, rnd, 0, _beaconSig(id, rnd, 0), empty);

        assertEq(
            lot.getRound(id).randomWord,
            uint256(keccak256(abi.encodePacked(id, bh, rnd))),
            "randomWord fixed by the pinned seed, not by the submitting block"
        );
    }

    function test_draw_delay_bound_is_derived_from_declared_block_time() public {
        // FINDING #10: the old `<= 1 hours` bound was L1-shaped arithmetic. The settle
        // window is SEED_LIFETIME_BLOCKS blocks ⇒ ~520s on a 2s chain, so the bound must
        // come from the declared block time, not a wall-clock literal.
        assertEq(lot.secondsPerBlock(), lot.DEFAULT_SECONDS_PER_BLOCK(), "defaults to the 2s L2 target");
        assertEq(lot.SEED_LIFETIME_BLOCKS(), lot.SEED_BLOCK_OFFSET() + lot.BLOCKHASH_WINDOW());
        assertEq(
            lot.maxDrawDelay(),
            uint64((lot.SEED_LIFETIME_BLOCKS() * lot.DEFAULT_SECONDS_PER_BLOCK()) / lot.DRAW_DELAY_HEADROOM())
        );
        uint64 bound = lot.maxDrawDelay(); // read BEFORE pranking (a view call eats the prank)
        assertEq(bound, 260, "260 blocks * 2s / 2 = 260s");

        vm.prank(admin);
        lot.setMinDrawDelay(bound); // exactly at the bound is fine
        assertEq(lot.minDrawDelay(), 260);

        vm.prank(admin);
        vm.expectRevert("drawDelay > seed window");
        lot.setMinDrawDelay(bound + 1);

        // the value the old bound happily accepted:
        vm.prank(admin);
        vm.expectRevert("drawDelay > seed window");
        lot.setMinDrawDelay(1 hours);
    }

    function test_constructor_rejects_a_draw_delay_that_would_brick_rounds() public {
        vm.expectRevert("drawDelay > seed window");
        new AIAgentLottery(
            admin, governance, operator, signer, treasury, address(0), PRICE, 8000, 1200, 800, 1 hours, 1 hours, false, 0
        );
    }

    function test_delay_past_the_window_expires_every_seed() public {
        // Why the bound matters: a 1h delay on a 2s chain means waiting ~1800 blocks,
        // and the pinned seed hash is gone after SEED_LIFETIME_BLOCKS (260). The round
        // would be undrawable on arrival — every single time — forcing a rescue loop.
        uint256 blocksInAnHour = uint256(1 hours) / lot.DEFAULT_SECONDS_PER_BLOCK();
        assertGt(blocksInAnHour, lot.SEED_LIFETIME_BLOCKS(), "1h of 2s blocks outlives the seed");

        uint256 id = _open();
        _buy(agentA, id, 1);
        bytes32 rnd = keccak256("expired");
        _close(id, rnd);
        // an hour of 2s blocks later — exactly where a 1h draw delay would put the
        // relayer — the pinned seed's hash is already unreachable
        vm.roll(lot.getRound(id).seedBlock + blocksInAnHour);
        vm.warp(uint256(lot.getRound(id).closedAt) + 1 hours);

        AIAgentLottery.VdfProof memory empty;
        vm.expectRevert(AIAgentLottery.BlockhashUnavailable.selector);
        lot.fulfillDraw(id, rnd, 0, _beaconSig(id, rnd, 0), empty);
    }

    function test_block_time_change_revalidates_the_draw_delay() public {
        vm.prank(admin);
        lot.setMinDrawDelay(260);

        // a FASTER chain shrinks the window: refuse the change while the configured
        // delay would no longer fit (fail closed — lower the delay first)
        vm.prank(governance);
        vm.expectRevert("drawDelay > seed window");
        lot.setSecondsPerBlock(1);
        assertEq(lot.secondsPerBlock(), 2, "rejected change must not take effect");

        // a slower (L1-like) chain widens it
        vm.prank(governance);
        lot.setSecondsPerBlock(12);
        assertEq(lot.maxDrawDelay(), 1560, "260 blocks * 12s / 2");
        vm.prank(admin);
        lot.setMinDrawDelay(1500);

        // even there, an hour is past the window
        vm.prank(admin);
        vm.expectRevert("drawDelay > seed window");
        lot.setMinDrawDelay(1 hours);

        // and the block-time model is GOVERNANCE's, not the operator's or admin's
        vm.prank(admin);
        vm.expectRevert();
        lot.setSecondsPerBlock(4);
        vm.prank(governance);
        vm.expectRevert("blockTime out of range");
        lot.setSecondsPerBlock(0);
    }

    function test_stalled_round_cancellable_by_anyone_and_fully_refunded() public {
        // A round the operator never settles, never rescues and never cancels must not
        // hold entries hostage.
        uint256 id = _open();
        _buy(agentA, id, 2);
        uint256 paid = PRICE * 2;
        vm.prank(benefactor);
        lot.fund{value: 1 ether}(id, 1 ether);
        _close(id, keccak256("never-published"));
        uint64 closedAt = lot.getRound(id).closedAt;

        vm.warp(uint256(closedAt) + lot.STALL_CANCEL_DELAY() - 1);
        vm.prank(bystander);
        vm.expectRevert(AIAgentLottery.TooEarly.selector);
        lot.cancelStalledRound(id);

        vm.warp(uint256(closedAt) + lot.STALL_CANCEL_DELAY());
        vm.prank(bystander);
        lot.cancelStalledRound(id);
        assertEq(uint8(lot.getRound(id).status), uint8(AIAgentLottery.Status.Cancelled));

        uint256 aBefore = agentA.balance;
        uint256 bBefore = benefactor.balance;
        vm.prank(agentA);
        lot.refund(id);
        vm.prank(benefactor);
        lot.refund(id);
        assertEq(agentA.balance, aBefore + paid, "tickets refunded");
        assertEq(benefactor.balance, bBefore + 1 ether, "funding refunded");
    }

    function test_stall_cancel_cannot_touch_a_settled_or_open_round() public {
        uint256 id = _open();
        _buy(agentA, id, 1);
        vm.warp(uint256(lot.getRound(id).openedAt) + lot.STALL_CANCEL_DELAY() + 1);
        vm.expectRevert(AIAgentLottery.WrongStatus.selector);
        lot.cancelStalledRound(id); // still Open, entries are the operator's to close

        _draw(id, keccak256("s"));
        vm.warp(uint256(lot.settledAt(id)) + lot.STALL_CANCEL_DELAY() + 1);
        vm.expectRevert(AIAgentLottery.WrongStatus.selector);
        lot.cancelStalledRound(id); // Settled — a paid-out round is never cancellable
    }

    function test_unclaimed_prize_is_recycled_into_a_later_round() public {
        // MINOR: an unclaimed prize used to be stranded in the contract forever. It is
        // now forfeited after UNCLAIMED_PRIZE_TTL and can only ever become a later
        // round's prize — no operator/treasury path to it.
        uint256 id1 = _open();
        _buy(agentA, id1, 1);
        _draw(id1, keccak256("p1"));
        uint256 stranded = lot.getRound(id1).prizePool;
        assertGt(stranded, 0);

        vm.expectRevert(AIAgentLottery.TooEarly.selector);
        lot.forfeitUnclaimedPrize(id1); // TTL not reached

        vm.warp(uint256(lot.settledAt(id1)) + lot.UNCLAIMED_PRIZE_TTL());
        vm.prank(bystander); // permissionless
        lot.forfeitUnclaimedPrize(id1);
        assertEq(lot.unclaimedPool(), stranded, "prize parked for the players, not withdrawn");

        // the lapsed winner can no longer claim, and the forfeit is not repeatable
        vm.prank(agentA);
        vm.expectRevert(AIAgentLottery.AlreadyClaimed.selector);
        lot.claimPrize(id1);
        vm.expectRevert(AIAgentLottery.AlreadyClaimed.selector);
        lot.forfeitUnclaimedPrize(id1);

        // next round's prize absorbs it in full (already taxed once — not taxed again)
        uint256 id2 = _open();
        _buy(agentB, id2, 1);
        _draw(id2, keccak256("p2"));
        uint256 income = PRICE;
        uint256 expectPrize = income - (income * 1200) / 10000 - (income * 800) / 10000 + stranded;
        assertEq(lot.getRound(id2).prizePool, expectPrize, "forfeited prize rolled in");
        assertEq(lot.prizeRolledIn(id2), stranded);
        assertEq(lot.unclaimedPool(), 0, "pool drained into the round");

        uint256 before = agentB.balance;
        vm.prank(agentB);
        lot.claimPrize(id2);
        assertEq(agentB.balance, before + expectPrize, "recycled prize is really payable");
    }

    function test_recycled_prize_cannot_be_harvested_by_a_one_ticket_round() public {
        // FINDING (found in review of the unclaimed-prize fix): the pool is free money
        // to whoever wins the absorbing round, and the operator can BE that winner —
        // open a round, buy a single ticket, close entries, take everything. The roll-in
        // is therefore capped at the round's own income, so extracting the pool costs at
        // least as much real capital as it yields, in rounds anyone else can enter.
        uint256 big = _open();
        _buy(agentA, big, 1);
        vm.prank(benefactor);
        lot.fund{value: 4 ether}(big, 4 ether);
        _draw(big, keccak256("big"));
        uint256 stranded = lot.getRound(big).prizePool;
        assertGt(stranded, 3 ether, "a real prize lapses");
        vm.warp(uint256(lot.settledAt(big)) + lot.UNCLAIMED_PRIZE_TTL());
        lot.forfeitUnclaimedPrize(big);
        assertEq(lot.unclaimedPool(), stranded);

        // the operator's cheap harvest attempt: one ticket, nothing else
        vm.deal(operator, 1 ether);
        uint256 grab = _open();
        _buy(operator, grab, 1);
        _draw(grab, keccak256("grab"));
        assertEq(lot.getRound(grab).winner, operator, "sole participant wins, as designed");
        assertEq(lot.prizeRolledIn(grab), PRICE, "roll-in cannot exceed the round's own income");
        uint256 expectPrize = PRICE - (PRICE * 1200) / 10000 - (PRICE * 800) / 10000 + PRICE;
        assertEq(lot.getRound(grab).prizePool, expectPrize, "one ticket does not buy the pool");
        assertEq(lot.unclaimedPool(), stranded - PRICE, "the rest stays pooled for the players");

        // a round that actually carries the pool's weight absorbs the remainder in full
        uint256 real = _open();
        _buy(agentB, real, 1);
        vm.prank(benefactor);
        lot.fund{value: 4 ether}(real, 4 ether);
        _draw(real, keccak256("real"));
        assertEq(lot.prizeRolledIn(real), stranded - PRICE, "remainder rolled in, nothing stranded");
        assertEq(lot.unclaimedPool(), 0);

        uint256 before = agentB.balance;
        vm.prank(agentB);
        lot.claimPrize(real);
        assertEq(agentB.balance, before + lot.getRound(real).prizePool, "recycled prize is payable");
    }

    function test_forfeit_requires_a_settled_round() public {
        uint256 id = _open();
        _buy(agentA, id, 1);
        vm.warp(uint256(lot.getRound(id).openedAt) + lot.UNCLAIMED_PRIZE_TTL() + 1);
        vm.expectRevert(AIAgentLottery.WrongStatus.selector);
        lot.forfeitUnclaimedPrize(id);
    }

    function test_claimed_prize_cannot_be_forfeited() public {
        uint256 id = _open();
        _buy(agentA, id, 1);
        _draw(id, keccak256("claimed"));
        vm.prank(agentA);
        lot.claimPrize(id);
        vm.warp(uint256(lot.settledAt(id)) + lot.UNCLAIMED_PRIZE_TTL() + 1);
        vm.expectRevert(AIAgentLottery.AlreadyClaimed.selector);
        lot.forfeitUnclaimedPrize(id);
        assertEq(lot.unclaimedPool(), 0);
    }

    function test_admin_cannot_self_grant_oracle_signer() public {
        // AUDIT H8: ORACLE_SIGNER is admined by GOVERNANCE, not DEFAULT_ADMIN.
        bytes32 signerRole = lot.ORACLE_SIGNER_ROLE();
        assertEq(lot.getRoleAdmin(signerRole), lot.GOVERNANCE_ROLE(), "signer role admined by governance");
        vm.prank(admin);
        vm.expectRevert();
        lot.grantRole(signerRole, admin);
    }

    function test_closeEntries_still_requires_operator() public {
        // Settlement is permissionless, but closing entries (and pinning the seed) is
        // not — otherwise anyone could cut a round's entry window short.
        uint256 id = _open();
        _buy(agentA, id, 1);
        vm.warp(block.timestamp + 1 hours + 1);
        vm.prank(agentA);
        vm.expectRevert();
        lot.closeEntries(id, _commit(keccak256("x")));
    }

    function test_prize_floor_enforced() public {
        // the lottery owns the opex/prize split, but opex+operator can never push the
        // prize below MIN_PRIZE_BPS (70%) — the guaranteed floor on TOTAL income.
        vm.prank(admin);
        vm.expectRevert(AIAgentLottery.InvalidSplits.selector);
        lot.setSplits(6900, 3000, 100); // prize 69% < 70% floor → reject
        vm.prank(admin);
        vm.expectRevert(AIAgentLottery.InvalidSplits.selector);
        lot.setSplits(6999, 3001, 0); // opex 30.01% > MAX_OPEX_BPS → reject
    }

    function test_valid_high_opex_split_accepted() public {
        // up to 30% opex (with the 70% floor) is allowed — the lottery's own policy.
        vm.prank(admin);
        lot.setSplits(7000, 3000, 0);
        // and opex now draws from donations: fund a no-ticket round and confirm opex accrues from funding
        uint256 id = _open();
        _buy(agentA, id, 1);
        vm.prank(benefactor);
        lot.fund{value: 1 ether}(id, 1 ether);
        _draw(id, keccak256("floor"));
        uint256 income = PRICE + 1 ether;
        assertEq(lot.getRound(id).prizePool, (income * 7000) / 10000, "prize = 70% of total income");
        assertEq(lot.opexAccrued(), (income * 3000) / 10000, "opex = 30% of total income (incl. donation)");
    }
}
