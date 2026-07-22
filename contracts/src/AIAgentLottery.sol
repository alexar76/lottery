// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.28;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {AccessControlDefaultAdminRules} from
    "@openzeppelin/contracts/access/extensions/AccessControlDefaultAdminRules.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {ChronosVDF} from "./ChronosVDF.sol";

/**
 * @title AIAgentLottery
 * @notice An economic actor of the AI ecosystem: AI agents buy tickets, an
 *         unbiasable oracle beacon (Platon chaos-VRF + Chronos VDF) draws a
 *         winner, and the pool is split into prize / opex / operator. Reputation
 *         (LUMEN) optionally boosts an agent's odds via a signed voucher. The
 *         contract is mode-agnostic: the same code runs the demo, live, and uni
 *         deployments — the surrounding economy engine drives each mode.
 *
 * Randomness / fairness:
 *   - Entries close and pin the seed to a FIXED future block; the draw binds that
 *     block's `blockhash` (unknown when entries close) ⊕ the committed Platon oracle
 *     randomness. The operator cannot re-pick the block — `reseed` is a rescue that is
 *     refused until the pinned block ages out of the 256-block window — so neither the
 *     operator nor a player can predict or grind the draw.
 *   - The Platon randomness is authenticated by an ORACLE_SIGNER EIP-712 signature
 *     (the relayer verifies the oracle's Ed25519 receipt off-chain, then attests
 *     on-chain with secp256k1). When `onchainVdf` is enabled, the Chronos VDF is
 *     ALSO verified on-chain (ChronosVDF), making unbiasability fully trustless —
 *     the operator cannot have ground the result within the VDF delay.
 *
 * Funds: pull-payment prize claims; opex/operator fees accrue and are withdrawn
 * by the treasury to pay for oracle + agent services off-chain. ReentrancyGuard,
 * Pausable, role-based access; SafeERC20 for ERC-20, native ETH supported when
 * `token == address(0)`.
 *
 * SECURITY/LEGAL: real-money lotteries are regulated. Deploying this for value is
 * the operator's responsibility — see docs/README.md and docs/AUDIT.md. Test on a
 * testnet first; the in-repo audit is not a substitute for a professional one.
 */
contract AIAgentLottery is AccessControlDefaultAdminRules, Pausable, ReentrancyGuard, EIP712 {
    using SafeERC20 for IERC20;

    // ── roles ───────────────────────────────────────────────────────────────
    bytes32 public constant OPERATOR_ROLE = keccak256("OPERATOR_ROLE");
    bytes32 public constant ORACLE_SIGNER_ROLE = keccak256("ORACLE_SIGNER_ROLE");
    bytes32 public constant TREASURY_ROLE = keccak256("TREASURY_ROLE");
    // Administers the money/fairness roles, so the operational DEFAULT_ADMIN
    // cannot self-grant ORACLE_SIGNER / TREASURY (separation of duties).
    bytes32 public constant GOVERNANCE_ROLE = keccak256("GOVERNANCE_ROLE");

    uint16 public constant BPS = 10_000;
    uint16 public constant MAX_OPERATOR_BPS = 1_000; // ≤10% to operator
    uint16 public constant MAX_OPEX_BPS = 3_000; // ≤30% to opex (of TOTAL income)
    uint16 public constant MIN_PRIZE_BPS = 7_000; // ≥70% to players — guaranteed prize floor
    uint16 public constant MAX_REP_BONUS_BPS = 5_000; // reputation can add ≤+50% odds

    // closeEntries pins the seed to this many blocks in the FUTURE, so the seed
    // block's blockhash is unknown when entries close and cannot be re-chosen by the
    // operator later — the draw is not grindable (see closeEntries / reseed).
    uint256 public constant SEED_BLOCK_OFFSET = 4;
    // A pinned seed block whose hash has aged past this window is permanently 0 and
    // can only then be rescued via reseed (never re-rolled while still available).
    uint256 public constant BLOCKHASH_WINDOW = 256;

    enum Status {
        None,
        Open,
        Drawing,
        Settled,
        Cancelled
    }

    struct Participant {
        address agent;
        uint256 weight; // cumulative-friendly: stored as the running total
        uint256 paid; // refundable on cancel
    }

    struct Round {
        Status status;
        uint64 openedAt;
        uint64 entriesClose;
        uint64 closedAt; // timestamp entries were closed — the draw-delay anchor
        uint16 sPrizeBps; // splits SNAPSHOTTED at open — admin can't re-split mid-round
        uint16 sOpexBps;
        uint16 sOperatorBps;
        uint256 seedBlock; // block recorded at closeEntries (blockhash binding)
        bytes32 seedCommitment; // keccak256(platonRandom) committed at close (commit-reveal vs grinding)
        uint256 ticketRevenue; // received from ticket sales (net of any transfer fee)
        uint256 funding; // external benefactor contributions (100% to prize)
        uint256 totalWeight;
        uint256 prizePool; // set on draw
        address winner;
        uint256 randomWord;
        bool prizeClaimed;
    }

    // EIP-712 typed data
    bytes32 private constant REP_VOUCHER_TYPEHASH =
        keccak256("ReputationVoucher(address agent,uint256 roundId,uint16 repBonusBps,uint64 expiry)");
    bytes32 private constant DRAW_BEACON_TYPEHASH =
        keccak256("DrawBeacon(uint256 roundId,bytes32 platonRandom,uint256 vdfT,bytes32 proofHash)");

    // ── config ──────────────────────────────────────────────────────────────
    IERC20 public immutable token; // address(0) ⇒ native ETH
    uint256 public ticketPrice;
    uint16 public prizeBps;
    uint16 public opexBps;
    uint16 public operatorBps;
    uint64 public entryWindow; // seconds an open round accepts entries
    uint64 public minDrawDelay; // seconds after close before a draw is valid
    bool public onchainVdf; // verify the Chronos VDF on-chain (full trustlessness)

    // ── state ───────────────────────────────────────────────────────────────
    uint256 public currentRoundId;
    mapping(uint256 => Round) private _rounds;
    mapping(uint256 => Participant[]) private _participants;
    mapping(uint256 => mapping(address => uint256)) public paidBy; // round ⇒ agent ⇒ refundable tickets
    mapping(uint256 => mapping(address => uint256)) public fundedBy; // round ⇒ sponsor ⇒ refundable funding
    uint256 public opexAccrued;
    uint256 public operatorAccrued;

    // lifetime economy counters (for the monitor / showcase)
    uint256 public totalPrizesPaid;
    uint256 public totalOpexAccrued;
    uint256 public totalFunding;
    uint256 public totalTicketRevenue;

    // ── events (the monitor's activity feed subscribes to these) ─────────────
    event RoundOpened(uint256 indexed roundId, uint64 entriesClose);
    event TicketsBought(uint256 indexed roundId, address indexed agent, uint256 count, uint256 weight, uint256 paid);
    event Funded(uint256 indexed roundId, address indexed benefactor, uint256 amount);
    event EntriesClosed(uint256 indexed roundId, uint256 seedBlock);
    event Drawn(
        uint256 indexed roundId,
        address indexed winner,
        uint256 prize,
        uint256 opex,
        uint256 operatorFee,
        uint256 randomWord
    );
    event PrizeClaimed(uint256 indexed roundId, address indexed winner, uint256 amount);
    event RoundCancelled(uint256 indexed roundId);
    event Refunded(uint256 indexed roundId, address indexed agent, uint256 amount);
    event OpexWithdrawn(address indexed to, uint256 amount);
    event OperatorFeeWithdrawn(address indexed to, uint256 amount);
    event SplitsUpdated(uint16 prizeBps, uint16 opexBps, uint16 operatorBps);

    error InvalidSplits();
    error WrongStatus();
    error ZeroCount();
    error BadPayment();
    error EntriesNotOpen();
    error TooEarly();
    error BlockhashUnavailable();
    error BadSignature();
    error VoucherExpired();
    error NoParticipants();
    error NotWinner();
    error AlreadyClaimed();
    error NothingToRefund();
    error BadReveal();

    constructor(
        address admin,
        address governance,
        address operator,
        address oracleSigner,
        address treasury,
        address token_,
        uint256 ticketPrice_,
        uint16 prizeBps_,
        uint16 opexBps_,
        uint16 operatorBps_,
        uint64 entryWindow_,
        uint64 minDrawDelay_,
        bool onchainVdf_,
        uint48 adminTransferDelay_
    ) EIP712("AIAgentLottery", "1") AccessControlDefaultAdminRules(adminTransferDelay_, admin) {
        require(ticketPrice_ > 0, "ticketPrice=0");
        // keep the draw-delay well under the 256-block blockhash window so a round
        // can't be retroactively bricked; measured from close (see fulfillDraw).
        require(minDrawDelay_ <= 1 hours, "drawDelay too large");
        // Separation of duties (audit H8/M9): GOVERNANCE — itself self-administered —
        // is the admin of the money/fairness roles, so the operational DEFAULT_ADMIN
        // can't self-grant ORACLE_SIGNER/TREASURY. DEFAULT_ADMIN transfer is 2-step,
        // time-delayed, and the last admin cannot be removed (AccessControlDefaultAdminRules).
        _setRoleAdmin(GOVERNANCE_ROLE, GOVERNANCE_ROLE);
        _setRoleAdmin(ORACLE_SIGNER_ROLE, GOVERNANCE_ROLE);
        _setRoleAdmin(TREASURY_ROLE, GOVERNANCE_ROLE);
        _grantRole(GOVERNANCE_ROLE, governance);
        _grantRole(OPERATOR_ROLE, operator);
        _grantRole(ORACLE_SIGNER_ROLE, oracleSigner);
        _grantRole(TREASURY_ROLE, treasury);
        token = IERC20(token_);
        ticketPrice = ticketPrice_;
        _setSplits(prizeBps_, opexBps_, operatorBps_);
        entryWindow = entryWindow_;
        minDrawDelay = minDrawDelay_;
        onchainVdf = onchainVdf_;
    }

    // ── round lifecycle ───────────────────────────────────────────────────────

    function openRound() external onlyRole(OPERATOR_ROLE) whenNotPaused returns (uint256 roundId) {
        roundId = ++currentRoundId;
        Round storage r = _rounds[roundId];
        r.status = Status.Open;
        r.openedAt = uint64(block.timestamp);
        r.entriesClose = uint64(block.timestamp) + entryWindow;
        // Snapshot the economics so a later setSplits can't re-cut THIS round.
        r.sPrizeBps = prizeBps;
        r.sOpexBps = opexBps;
        r.sOperatorBps = operatorBps;
        emit RoundOpened(roundId, r.entriesClose);
    }

    /// @notice Buy `count` tickets for the current open round (flat weight).
    function buyTickets(uint256 roundId, uint256 count) external payable nonReentrant whenNotPaused {
        _buy(roundId, count, BPS);
    }

    /// @notice Buy tickets with a signed LUMEN reputation voucher that boosts odds.
    function buyTicketsWithVoucher(
        uint256 roundId,
        uint256 count,
        uint16 repBonusBps,
        uint64 expiry,
        bytes calldata sig
    ) external payable nonReentrant whenNotPaused {
        require(repBonusBps <= MAX_REP_BONUS_BPS, "rep bonus too high"); // don't silently downgrade a signed value
        if (block.timestamp > expiry) revert VoucherExpired();
        bytes32 digest = _hashTypedDataV4(
            keccak256(abi.encode(REP_VOUCHER_TYPEHASH, msg.sender, roundId, repBonusBps, expiry))
        );
        if (!hasRole(ORACLE_SIGNER_ROLE, ECDSA.recover(digest, sig))) revert BadSignature();
        _buy(roundId, count, BPS + uint256(repBonusBps));
    }

    function _buy(uint256 roundId, uint256 count, uint256 weightBps) internal {
        if (count == 0) revert ZeroCount();
        Round storage r = _rounds[roundId];
        if (r.status != Status.Open) revert EntriesNotOpen();
        if (block.timestamp > r.entriesClose) revert EntriesNotOpen();

        uint256 cost = ticketPrice * count;
        // Credit what ACTUALLY arrived (fee-on-transfer/rebasing safe) — booking the
        // gross would over-state obligations and break solvency. Weight stays ∝ count.
        uint256 received = _pullPayment(cost);

        uint256 weight = (count * weightBps) / BPS;
        if (weight == 0) weight = count; // never below flat weight
        r.totalWeight += weight;
        r.ticketRevenue += received;
        totalTicketRevenue += received;
        paidBy[roundId][msg.sender] += received;

        _participants[roundId].push(Participant({agent: msg.sender, weight: r.totalWeight, paid: received}));
        emit TicketsBought(roundId, msg.sender, count, weight, received);
    }

    /// @notice External benefactor / sponsor (the Hub tithe, or the uni $100/week
    ///         benefactor) contributes to the round's income. Funding is one-way IN
    ///         and joins ticket revenue as the round's TOTAL income, which is then
    ///         split prize/opex/operator by the per-round snapshot — so a configured
    ///         opex share may draw from donations too, while the prize FLOOR
    ///         (MIN_PRIZE_BPS, ≥70%) is guaranteed and opex stays capped & segregated.
    function fund(uint256 roundId, uint256 amount) external payable nonReentrant whenNotPaused {
        Round storage r = _rounds[roundId];
        if (r.status != Status.Open && r.status != Status.Drawing) revert WrongStatus();
        uint256 amt = _pullPayment(amount);
        r.funding += amt;
        totalFunding += amt;
        fundedBy[roundId][msg.sender] += amt; // refundable if the round is cancelled
        emit Funded(roundId, msg.sender, amt);
    }

    /// @param seedCommitment keccak256(abi.encodePacked(platonRandom)) — the operator
    ///        commits the randomness now, BEFORE the seed block's blockhash/prevrandao
    ///        exist, so it cannot later grind platonRandom to steer the winner.
    function closeEntries(uint256 roundId, bytes32 seedCommitment) external onlyRole(OPERATOR_ROLE) {
        Round storage r = _rounds[roundId];
        if (r.status != Status.Open) revert WrongStatus();
        if (block.timestamp < r.entriesClose) revert TooEarly();
        r.status = Status.Drawing;
        r.closedAt = uint64(block.timestamp);
        // Pin the seed to a FIXED future block chosen by the chain, not the operator:
        // blockhash(seedBlock) does not exist yet and cannot be re-picked later, so the
        // winner cannot be ground (reseed only rescues an EXPIRED seed, never re-rolls).
        r.seedBlock = block.number + SEED_BLOCK_OFFSET;
        r.seedCommitment = seedCommitment;
        emit EntriesClosed(roundId, r.seedBlock);
    }

    /// @notice Re-anchor the seed block while Drawing — a RESCUE ONLY, not a re-roll.
    ///         It is refused until the pinned seedBlock has aged past the 256-block
    ///         blockhash window (its hash is now permanently 0 and the round would
    ///         otherwise be undrawable / funds stuck). While blockhash(seedBlock) is
    ///         still available — or not yet mined — this reverts, so the operator
    ///         cannot observe the pending outcome and then pick a fresh blockhash.
    ///         The rescue re-pins to a FIXED future block and re-arms the draw delay,
    ///         so any grind attempt costs a full >256-block wait against an
    ///         unpredictable future hash rather than a cheap re-roll.
    function reseed(uint256 roundId) external onlyRole(OPERATOR_ROLE) {
        Round storage r = _rounds[roundId];
        if (r.status != Status.Drawing) revert WrongStatus();
        // Rescue only: allowed strictly once the committed blockhash has expired.
        if (block.number <= r.seedBlock + BLOCKHASH_WINDOW) revert TooEarly();
        r.closedAt = uint64(block.timestamp); // re-arm the draw delay for the new seed
        r.seedBlock = block.number + SEED_BLOCK_OFFSET;
        emit EntriesClosed(roundId, r.seedBlock);
    }

    struct VdfProof {
        string seed; // the seed string the relayer fed to Chronos (binds g)
        bytes g;
        bytes y;
        bytes pi;
        bytes l;
        bytes N;
        uint256 T;
    }

    /// @notice Settle a round: authenticate the oracle beacon, derive the winner,
    ///         and split the pool. Callable by anyone holding a valid ORACLE_SIGNER
    ///         attestation (the relayer); gated by signature, not just role.
    function fulfillDraw(
        uint256 roundId,
        bytes32 platonRandom,
        uint256 vdfT,
        bytes calldata signerSig,
        VdfProof calldata vdf
    ) external nonReentrant whenNotPaused onlyRole(OPERATOR_ROLE) {
        // OPERATOR-only: stops any mempool observer from capturing a beacon and
        // submitting their own (forged) proof to steer the winner.
        Round storage r = _rounds[roundId];
        if (r.status != Status.Drawing) revert WrongStatus();
        if (block.timestamp < r.closedAt + minDrawDelay) revert TooEarly(); // anchor on CLOSE

        // commit-reveal: the revealed platonRandom must match what was committed at
        // close — the operator/signer cannot grind it after the entropy is known.
        if (keccak256(abi.encodePacked(platonRandom)) != r.seedCommitment) revert BadReveal();

        // blockhash of the recorded close block (must be within the last 256 blocks)
        bytes32 bh = blockhash(r.seedBlock);
        if (bh == bytes32(0)) revert BlockhashUnavailable();

        // The oracle signer attests the full beacon INCLUDING a commitment to the
        // exact VDF proof (extracted to keep the stack shallow).
        _verifyBeacon(roundId, platonRandom, vdfT, signerSig, vdf);
        uint256 randomWord = _randomWord(roundId, bh, platonRandom, vdfT, vdf);

        Participant[] storage ps = _participants[roundId];
        uint256 n = ps.length;
        if (n == 0 || r.totalWeight == 0) revert NoParticipants();

        // weighted winner: smallest index whose cumulative weight > target
        uint256 target = randomWord % r.totalWeight;
        address winner = ps[_upperBound(ps, target)].agent;

        // split TOTAL income (tickets + donations) using the PER-ROUND snapshot.
        // The lottery owns this split (opex% vs prize%); the prize floor is enforced
        // in _setSplits (prize ≥ MIN_PRIZE_BPS), so the winner is always guaranteed
        // ≥70% of income while a capped opex share funds the lottery's operations.
        uint256 income = r.ticketRevenue + r.funding;
        uint256 opex = (income * r.sOpexBps) / BPS;
        uint256 operatorFee = (income * r.sOperatorBps) / BPS;
        uint256 prize = income - opex - operatorFee; // remainder = prize (≥ sPrizeBps share)

        r.prizePool = prize;
        r.winner = winner;
        r.randomWord = randomWord;
        r.status = Status.Settled;
        opexAccrued += opex;
        operatorAccrued += operatorFee;
        totalOpexAccrued += opex;

        emit Drawn(roundId, winner, prize, opex, operatorFee, randomWord);
    }

    /// @dev Verify the oracle-signer beacon, which commits to the exact VDF proof.
    function _verifyBeacon(
        uint256 roundId,
        bytes32 platonRandom,
        uint256 vdfT,
        bytes calldata signerSig,
        VdfProof calldata vdf
    ) private view {
        bytes32 proofHash =
            keccak256(abi.encode(vdf.g, vdf.y, vdf.pi, vdf.l, vdf.N, vdf.T, keccak256(bytes(vdf.seed))));
        bytes32 digest =
            _hashTypedDataV4(keccak256(abi.encode(DRAW_BEACON_TYPEHASH, roundId, platonRandom, vdfT, proofHash)));
        if (!hasRole(ORACLE_SIGNER_ROLE, ECDSA.recover(digest, signerSig))) revert BadSignature();
    }

    /// @dev Derive the random word. onchainVdf: verify the VDF over the pinned
    ///      modulus, g bound to baseSeed → y is the unbiasable word. Else: mix
    ///      block.prevrandao (unknown at signing) so the signer can't grind.
    function _randomWord(uint256 roundId, bytes32 bh, bytes32 platonRandom, uint256 vdfT, VdfProof calldata vdf)
        private
        view
        returns (uint256)
    {
        bytes32 baseSeed = keccak256(abi.encodePacked(roundId, bh, platonRandom));
        if (onchainVdf) {
            require(ChronosVDF.verifyEquation(vdf.N, vdf.g, vdf.y, vdf.pi, vdf.l, vdf.T), "vdf");
            require(keccak256(ChronosVDF.hashToGroup(vdf.seed, vdf.N)) == keccak256(vdf.g), "g-bind");
            require(keccak256(bytes(vdf.seed)) == keccak256(bytes(_toHex(baseSeed))), "seed-bind");
            require(vdf.T == vdfT, "T");
            return uint256(keccak256(vdf.y));
        }
        return uint256(keccak256(abi.encodePacked(baseSeed, block.prevrandao)));
    }

    // ── payouts ────────────────────────────────────────────────────────────

    function claimPrize(uint256 roundId) external nonReentrant {
        Round storage r = _rounds[roundId];
        if (r.status != Status.Settled) revert WrongStatus();
        if (msg.sender != r.winner) revert NotWinner();
        if (r.prizeClaimed) revert AlreadyClaimed();
        r.prizeClaimed = true;
        uint256 amount = r.prizePool;
        totalPrizesPaid += amount;
        _push(msg.sender, amount);
        emit PrizeClaimed(roundId, msg.sender, amount);
    }

    function withdrawOpex(address to, uint256 amount) external onlyRole(TREASURY_ROLE) nonReentrant {
        opexAccrued -= amount; // reverts on underflow
        _push(to, amount);
        emit OpexWithdrawn(to, amount);
    }

    function withdrawOperatorFee(address to, uint256 amount) external onlyRole(TREASURY_ROLE) nonReentrant {
        operatorAccrued -= amount;
        _push(to, amount);
        emit OperatorFeeWithdrawn(to, amount);
    }

    // ── cancel / refund ──────────────────────────────────────────────────────

    function cancelRound(uint256 roundId) external onlyRole(OPERATOR_ROLE) {
        Round storage r = _rounds[roundId];
        if (r.status != Status.Open && r.status != Status.Drawing) revert WrongStatus();
        r.status = Status.Cancelled;
        emit RoundCancelled(roundId);
    }

    /// @notice Refund ticket spend AND sponsor funding after a round is cancelled
    ///         (sponsor funding is now recoverable — it was previously stranded).
    function refund(uint256 roundId) external nonReentrant {
        Round storage r = _rounds[roundId];
        if (r.status != Status.Cancelled) revert WrongStatus();
        uint256 amount = paidBy[roundId][msg.sender] + fundedBy[roundId][msg.sender];
        if (amount == 0) revert NothingToRefund();
        paidBy[roundId][msg.sender] = 0;
        fundedBy[roundId][msg.sender] = 0;
        _push(msg.sender, amount);
        emit Refunded(roundId, msg.sender, amount);
    }

    // ── admin ─────────────────────────────────────────────────────────────────

    function setSplits(uint16 prizeBps_, uint16 opexBps_, uint16 operatorBps_) external onlyRole(DEFAULT_ADMIN_ROLE) {
        _setSplits(prizeBps_, opexBps_, operatorBps_);
    }

    function setTicketPrice(uint256 p) external onlyRole(DEFAULT_ADMIN_ROLE) {
        require(p > 0, "ticketPrice=0");
        ticketPrice = p;
    }

    function setEntryWindow(uint64 w) external onlyRole(DEFAULT_ADMIN_ROLE) {
        entryWindow = w;
    }

    function setMinDrawDelay(uint64 d) external onlyRole(DEFAULT_ADMIN_ROLE) {
        require(d <= 1 hours, "drawDelay too large"); // stay under the 256-block window
        minDrawDelay = d;
    }

    function setOnchainVdf(bool on) external onlyRole(DEFAULT_ADMIN_ROLE) {
        onchainVdf = on;
    }

    function pause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _pause();
    }

    function unpause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _unpause();
    }

    function _setSplits(uint16 p, uint16 o, uint16 op) internal {
        if (uint256(p) + o + op != BPS) revert InvalidSplits();
        if (op > MAX_OPERATOR_BPS || o > MAX_OPEX_BPS || p < MIN_PRIZE_BPS) revert InvalidSplits();
        prizeBps = p;
        opexBps = o;
        operatorBps = op;
        emit SplitsUpdated(p, o, op);
    }

    // ── views (monitor / showcase) ────────────────────────────────────────────

    function getRound(uint256 roundId) external view returns (Round memory) {
        return _rounds[roundId];
    }

    function participantsCount(uint256 roundId) external view returns (uint256) {
        return _participants[roundId].length;
    }

    /// @notice Live economy snapshot for the monitor / showcase.
    function economy()
        external
        view
        returns (
            uint256 round,
            uint256 prizesPaid,
            uint256 opexTotal,
            uint256 fundingTotal,
            uint256 ticketRevenue,
            uint256 opexAvailable,
            uint256 operatorAvailable
        )
    {
        return (
            currentRoundId,
            totalPrizesPaid,
            totalOpexAccrued,
            totalFunding,
            totalTicketRevenue,
            opexAccrued,
            operatorAccrued
        );
    }

    // ── internals ──────────────────────────────────────────────────────────

    /// @dev pulls `amount` of token (or validates msg.value for native).
    function _pullPayment(uint256 amount) internal returns (uint256) {
        if (address(token) == address(0)) {
            if (msg.value != amount) revert BadPayment();
            return amount;
        } else {
            if (msg.value != 0) revert BadPayment();
            uint256 before = token.balanceOf(address(this));
            token.safeTransferFrom(msg.sender, address(this), amount);
            return token.balanceOf(address(this)) - before; // fee-on-transfer safe
        }
    }

    function _push(address to, uint256 amount) internal {
        if (amount == 0) return;
        if (address(token) == address(0)) {
            (bool ok,) = payable(to).call{value: amount}("");
            require(ok, "native transfer failed");
        } else {
            token.safeTransfer(to, amount);
        }
    }

    /// @dev smallest index i with cumulative weight ps[i].weight > target.
    function _upperBound(Participant[] storage ps, uint256 target) internal view returns (uint256) {
        uint256 lo = 0;
        uint256 hi = ps.length - 1;
        while (lo < hi) {
            uint256 mid = (lo + hi) / 2;
            if (ps[mid].weight > target) hi = mid;
            else lo = mid + 1;
        }
        return lo;
    }

    function _toHex(bytes32 v) internal pure returns (string memory) {
        bytes memory alphabet = "0123456789abcdef";
        bytes memory str = new bytes(2 + 64);
        str[0] = "0";
        str[1] = "x";
        for (uint256 i = 0; i < 32; i++) {
            str[2 + i * 2] = alphabet[uint8(v[i] >> 4)];
            str[3 + i * 2] = alphabet[uint8(v[i] & 0x0f)];
        }
        return string(str);
    }

    receive() external payable {}
}
