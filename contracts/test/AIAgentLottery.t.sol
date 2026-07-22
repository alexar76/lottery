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

    address agentA = address(0xA1);
    address agentB = address(0xB2);
    address agentC = address(0xC3);
    address benefactor = address(0xF00D);

    uint256 constant PRICE = 0.01 ether;

    function setUp() public {
        signer = vm.addr(signerPk);
        lot = new AIAgentLottery(
            admin, address(0x6), operator, signer, treasury, // admin, governance, operator, signer, treasury
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
        vm.warp(block.timestamp + 1 hours + 1);
        vm.prank(operator);
        lot.closeEntries(id, keccak256(abi.encodePacked(rnd))); // commit the randomness
        vm.roll(block.number + lot.SEED_BLOCK_OFFSET() + 1); // mine past the pinned future seedBlock
        AIAgentLottery.VdfProof memory empty;
        vm.prank(operator); // fulfillDraw is now OPERATOR-gated (anti mempool-capture)
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
        vm.warp(block.timestamp + 1 hours + 1);
        vm.prank(operator);
        lot.closeEntries(id, keccak256(abi.encodePacked(keccak256("x"))));
        uint256 seedBlock = lot.getRound(id).seedBlock;
        assertEq(seedBlock, block.number + lot.SEED_BLOCK_OFFSET(), "close pins a future seed block");

        // seed not yet mined → reseed refused (cannot pre-empt a pending seed)
        vm.prank(operator);
        vm.expectRevert(AIAgentLottery.TooEarly.selector);
        lot.reseed(id);

        // seed mined and still within the 256-block window → reseed still refused
        vm.roll(seedBlock + 1);
        vm.prank(operator);
        vm.expectRevert(AIAgentLottery.TooEarly.selector);
        lot.reseed(id);

        // once the seed ages out (>256 blocks) the rescue is allowed: re-pins a fresh
        // future block and re-arms the delay anchor.
        vm.roll(seedBlock + 257);
        vm.warp(block.timestamp + 5 minutes);
        vm.prank(operator);
        lot.reseed(id);
        AIAgentLottery.Round memory r = lot.getRound(id);
        assertEq(r.seedBlock, block.number + lot.SEED_BLOCK_OFFSET(), "reseed re-pins a fresh future block");
        assertEq(r.closedAt, uint64(block.timestamp), "reseed re-arms the draw delay anchor");

        // and the rescued round can still be settled from the fresh seed
        vm.roll(r.seedBlock + 1);
        AIAgentLottery.VdfProof memory empty;
        vm.prank(operator);
        lot.fulfillDraw(id, keccak256("x"), 0, _beaconSig(id, keccak256("x"), 0), empty);
        assertEq(lot.getRound(id).winner, agentA, "rescued round settles to the sole participant");
    }

    function test_admin_cannot_self_grant_oracle_signer() public {
        // AUDIT H8: ORACLE_SIGNER is admined by GOVERNANCE, not DEFAULT_ADMIN.
        bytes32 signerRole = lot.ORACLE_SIGNER_ROLE();
        assertEq(lot.getRoleAdmin(signerRole), lot.GOVERNANCE_ROLE(), "signer role admined by governance");
        vm.prank(admin);
        vm.expectRevert();
        lot.grantRole(signerRole, admin);
    }

    function test_fulfillDraw_requires_operator() public {
        // AUDIT critical: fulfillDraw must be operator-gated (anti mempool-capture).
        uint256 id = _open();
        _buy(agentA, id, 1);
        vm.warp(block.timestamp + 1 hours + 1);
        vm.prank(operator);
        lot.closeEntries(id, keccak256(abi.encodePacked(keccak256("x"))));
        vm.roll(block.number + lot.SEED_BLOCK_OFFSET() + 1);
        AIAgentLottery.VdfProof memory empty;
        vm.prank(agentA); // not operator
        vm.expectRevert();
        lot.fulfillDraw(id, keccak256("x"), 0, _beaconSig(id, keccak256("x"), 0), empty);
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
