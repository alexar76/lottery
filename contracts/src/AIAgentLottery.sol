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
 *     randomness. The winner is a pure function of (roundId, blockhash(seedBlock),
 *     platonRandom) — all three fixed before anyone can act on them — so the outcome
 *     does NOT depend on which block the settlement lands in and cannot be re-rolled
 *     by resubmitting later.
 *   - Because the outcome is settlement-block-independent, `fulfillDraw` is
 *     PERMISSIONLESS: a valid ORACLE_SIGNER beacon is the only key that opens it, and
 *     any participant can settle a round the operator is stalling. Withholding a
 *     settlement is therefore not a lever on the result. For the same reason nothing
 *     may NULLIFY a settleable round either: `fulfillDraw` is not Pausable-gated (a
 *     pause would freeze exactly the outcome the admin dislikes) and `cancelRound`
 *     refuses a Drawing round whose pinned blockhash is already readable.
 *   - What the operator can still do, and cannot be fixed on-chain: it alone produces
 *     the beacon, so it may compute the outcome privately, never publish, and let the
 *     round die into a cancel/refund. That costs it a full seed window per attempt,
 *     refunds every player, and earns it nothing — but it does mean the last word on
 *     "this round happens at all" belongs to whoever holds the oracle relay.
 *   - `reseed` is a rescue for a round whose pinned blockhash has aged out of the
 *     256-block window (nobody, operator included, can settle it any more). It is not
 *     a free re-roll: it demands a NEVER-BEFORE-USED randomness commitment (hence a
 *     fresh ORACLE_SIGNER beacon), waits out RESEED_COOLDOWN, is counted and evented,
 *     and is capped at MAX_RESEEDS — after which the round can only be cancelled and
 *     everyone refunded. A round nobody settles at all becomes permissionlessly
 *     cancellable after STALL_CANCEL_DELAY, so funds are never held hostage.
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
    // Blocks between closeEntries and the moment the pinned seed hash is gone for
    // good: the seed is mined SEED_BLOCK_OFFSET blocks after close and its hash then
    // survives exactly BLOCKHASH_WINDOW more blocks. This is the settle window, and
    // it is denominated in BLOCKS — its wall-clock size depends on the chain.
    uint256 public constant SEED_LIFETIME_BLOCKS = SEED_BLOCK_OFFSET + BLOCKHASH_WINDOW;
    // A configured draw delay may eat at most 1/DRAW_DELAY_HEADROOM of the settle
    // window; the rest is headroom for actually landing the settlement tx.
    uint256 public constant DRAW_DELAY_HEADROOM = 2;

    // Rescue budget for a round whose seed hash expired (see reseed): each rescue
    // costs a cooldown, is counted + evented, and after MAX_RESEEDS the round can
    // only be cancelled (full refunds) — so re-rolling is bounded, not unlimited.
    uint16 public constant MAX_RESEEDS = 2;
    uint64 public constant RESEED_COOLDOWN = 1 hours;
    // A round left in Drawing this long (no settlement, no rescue) may be cancelled
    // by ANYONE, so a stalling operator/oracle cannot hold entries hostage.
    uint64 public constant STALL_CANCEL_DELAY = 7 days;
    // A prize left unclaimed this long is recycled into a later round's prize
    // instead of being stranded in the contract forever (see forfeitUnclaimedPrize).
    uint64 public constant UNCLAIMED_PRIZE_TTL = 180 days;
    // Chain block time assumed by every wall-clock bound derived from the
    // block-denominated settle window. Default = the fastest chain this contract
    // targets (Base / OP-stack, 2s), so the derived bound is safe on any slower
    // chain too and only widens when governance explicitly declares a slower one.
    uint64 public constant DEFAULT_SECONDS_PER_BLOCK = 2;
    uint64 public constant MAX_SECONDS_PER_BLOCK = 60;

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
    // Assumed seconds per block on the deployment chain. The settle window is
    // SEED_LIFETIME_BLOCKS *blocks*, so its wall-clock size — and therefore the
    // largest sound minDrawDelay — is a function of this value, not of a
    // hand-computed literal (see maxDrawDelay / setSecondsPerBlock).
    uint64 public secondsPerBlock;
    bool public onchainVdf; // verify the Chronos VDF on-chain (full trustlessness)

    // ── state ───────────────────────────────────────────────────────────────
    uint256 public currentRoundId;
    mapping(uint256 => Round) private _rounds;
    mapping(uint256 => Participant[]) private _participants;
    mapping(uint256 => mapping(address => uint256)) public paidBy; // round ⇒ agent ⇒ refundable tickets
    mapping(uint256 => mapping(address => uint256)) public fundedBy; // round ⇒ sponsor ⇒ refundable funding
    uint256 public opexAccrued;
    uint256 public operatorAccrued;
    // Rescue bookkeeping — kept OUT of `struct Round` so getRound()'s tuple (which
    // off-chain indexers decode positionally) stays byte-compatible.
    mapping(uint256 => uint16) public reseedCount; // round ⇒ rescues used (audit trail)
    mapping(uint256 => uint64) public settledAt; // round ⇒ settle timestamp (claim-TTL anchor)
    mapping(uint256 => uint256) public prizeRolledIn; // round ⇒ forfeited prize recycled into it
    // Every randomness commitment a round has ever used. A rescue must bring an
    // unused one, so it cannot re-roll an already-revealed value (or alternate
    // between two old beacons) against a fresh blockhash.
    mapping(uint256 => mapping(bytes32 => bool)) public commitmentUsed;
    // Prizes forfeited after UNCLAIMED_PRIZE_TTL. Never withdrawable by anyone —
    // the only exit is becoming a later round's prize (see fulfillDraw).
    uint256 public unclaimedPool;

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
    // A rescue is a fairness-relevant event: distinct from EntriesClosed (entries do
    // NOT re-close) and carries the running count so re-rolls are visible on-chain.
    event RoundReseeded(uint256 indexed roundId, uint256 seedBlock, bytes32 seedCommitment, uint16 reseedCount);
    event PrizeForfeited(uint256 indexed roundId, address indexed winner, uint256 amount);
    event UnclaimedPrizeRolledIn(uint256 indexed roundId, uint256 amount);
    event BlockTimeUpdated(uint64 secondsPerBlock, uint64 maxDrawDelay);

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
    error ReseedLimit();
    error StaleCommitment();

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
        // The settle window is SEED_LIFETIME_BLOCKS *blocks* wide, so its duration is
        // block-time dependent: ~8.5 min on a 2s L2 like Base, not the ~52 min a
        // 12s-block L1 would give. A delay above the window would expire EVERY seed
        // and force a rescue loop, so the bound is derived from the declared block
        // time (see maxDrawDelay) rather than a wall-clock literal that silently rots
        // when the contract moves chains.
        secondsPerBlock = DEFAULT_SECONDS_PER_BLOCK;
        require(minDrawDelay_ <= _maxDrawDelay(DEFAULT_SECONDS_PER_BLOCK), "drawDelay > seed window");
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
    ///        commits the randomness now, BEFORE the seed block's blockhash exists, so
    ///        it cannot later grind platonRandom to steer the winner. Recorded in
    ///        `commitmentUsed` so a rescue can never reuse it.
    function closeEntries(uint256 roundId, bytes32 seedCommitment) external onlyRole(OPERATOR_ROLE) {
        Round storage r = _rounds[roundId];
        if (r.status != Status.Open) revert WrongStatus();
        if (block.timestamp < r.entriesClose) revert TooEarly();
        // A zero commitment is unrevealable (keccak of anything is non-zero) and would
        // brick the round into the rescue path — refuse it instead of accepting it.
        if (seedCommitment == bytes32(0)) revert BadReveal();
        commitmentUsed[roundId][seedCommitment] = true;
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
    ///         blockhash window (its hash is now permanently 0, so NOBODY — the
    ///         operator included — can settle the round any more and the funds would
    ///         otherwise be stuck).
    ///
    ///         Three things stop this from being a cheap re-roll of a result the
    ///         operator dislikes. (1) `fulfillDraw` is permissionless, so the operator
    ///         cannot reach this state by simply sitting on a beacon it already
    ///         published — any participant would have settled the round. (2) The rescue
    ///         must bring a NEVER-BEFORE-USED commitment, i.e. a fresh
    ///         ORACLE_SIGNER-attested beacon over new randomness, committed here before
    ///         the new seed block exists; the already-revealed value cannot be replayed
    ///         against a new blockhash. Since ORACLE_SIGNER is administered by
    ///         GOVERNANCE, not by the operator, a re-roll needs a second party. (3) Each
    ///         rescue costs RESEED_COOLDOWN, is counted in `reseedCount` and evented,
    ///         and after MAX_RESEEDS the round can only be cancelled and refunded.
    /// @param newSeedCommitment keccak256(abi.encodePacked(newPlatonRandom)) for the
    ///        FRESH oracle beacon that will settle the rescued round.
    function reseed(uint256 roundId, bytes32 newSeedCommitment) external onlyRole(OPERATOR_ROLE) {
        Round storage r = _rounds[roundId];
        if (r.status != Status.Drawing) revert WrongStatus();
        // Rescue only: allowed strictly once the committed blockhash has expired.
        if (block.number <= r.seedBlock + BLOCKHASH_WINDOW) revert TooEarly();
        // …and never sooner than the cooldown after the current seed was pinned, so a
        // rescue can never be sampled at the pace of the blockhash window itself.
        if (block.timestamp < uint256(r.closedAt) + RESEED_COOLDOWN) revert TooEarly();
        if (reseedCount[roundId] >= MAX_RESEEDS) revert ReseedLimit();
        if (newSeedCommitment == bytes32(0)) revert BadReveal();
        if (commitmentUsed[roundId][newSeedCommitment]) revert StaleCommitment();

        commitmentUsed[roundId][newSeedCommitment] = true;
        r.closedAt = uint64(block.timestamp); // re-arm the draw delay for the new seed
        r.seedBlock = block.number + SEED_BLOCK_OFFSET;
        r.seedCommitment = newSeedCommitment;
        uint16 used = reseedCount[roundId] + 1;
        reseedCount[roundId] = used;
        emit RoundReseeded(roundId, r.seedBlock, newSeedCommitment, used);
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
    ///         and split the pool. PERMISSIONLESS — callable by anyone holding a valid
    ///         ORACLE_SIGNER attestation (normally the relayer, but a participant can
    ///         submit a published beacon to settle a round the operator is stalling).
    /// @dev    An OPERATOR-only gate here bought no security and handed the operator a
    ///         withholding lever: the beacon signature commits to roundId, the exact
    ///         platonRandom (which commit-reveal pins to closeEntries) and the exact
    ///         VDF proof, and the winner is a pure function of those plus
    ///         blockhash(seedBlock). A mempool observer can therefore only replay the
    ///         same beacon and produce the same winner — while the operator, under the
    ///         old gate, could see the outcome and refuse to submit until the seed
    ///         expired and it could reseed.
    /// @dev    Deliberately NOT `whenNotPaused`. Pausing gates the money coming IN
    ///         (openRound / buyTickets / fund); it never gated the money going out
    ///         (claimPrize, refund, withdraw*) nor closeEntries/reseed. Gating only the
    ///         settlement therefore handed the admin the very lever this function
    ///         exists to remove: freeze a round whose winner is already computable,
    ///         wait out the seed window, unpause, reseed. Settling moves no funds (the
    ///         prize is pull-payment), so there is nothing for a pause to protect here.
    ///         The emergency stops that remain are targeted rather than outcome-aware:
    ///         GOVERNANCE can revoke ORACLE_SIGNER_ROLE (invalidating every beacon at
    ///         once) and the operator can cancel a round that nobody can settle.
    function fulfillDraw(
        uint256 roundId,
        bytes32 platonRandom,
        uint256 vdfT,
        bytes calldata signerSig,
        VdfProof calldata vdf
    ) external nonReentrant {
        Round storage r = _rounds[roundId];
        if (r.status != Status.Drawing) revert WrongStatus();
        if (block.timestamp < r.closedAt + minDrawDelay) revert TooEarly(); // anchor on CLOSE

        // commit-reveal: the revealed platonRandom must match what was committed at
        // close — the operator/signer cannot grind it after the entropy is known.
        if (keccak256(abi.encodePacked(platonRandom)) != r.seedCommitment) revert BadReveal();

        // blockhash of the PINNED SEED block (must still be inside the 256-block
        // window; once it isn't, the round needs a rescue — see reseed)
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

        // Recycle any prize forfeited by an unreachable winner. It was already taxed
        // for opex/operator in its own round, so 100% of what is rolled in goes to this
        // prize — taxing it twice would quietly erode the players' share.
        //
        // The roll-in is capped at the round's OWN income, because the pool is free
        // money to whoever wins the absorbing round and nothing stops the operator from
        // being that winner: it could otherwise open a round, buy one ticket, close
        // entries and take the entire pool for the price of a single ticket. Capping at
        // income means draining the pool requires cycling at least as much real capital
        // through rounds that any other agent can enter and win — the pool bleeds back
        // into genuine economic activity instead of being a one-ticket jackpot. Whatever
        // does not fit stays pooled for the next round, so nothing is stranded.
        uint256 rolled = unclaimedPool;
        if (rolled > income) rolled = income;
        if (rolled > 0) {
            unclaimedPool -= rolled;
            prizeRolledIn[roundId] = rolled;
            prize += rolled;
            emit UnclaimedPrizeRolledIn(roundId, rolled);
        }

        r.prizePool = prize;
        r.winner = winner;
        r.randomWord = randomWord;
        r.status = Status.Settled;
        settledAt[roundId] = uint64(block.timestamp); // anchor for UNCLAIMED_PRIZE_TTL
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
    ///      modulus, g bound to baseSeed → y is the unbiasable word. Else: the base
    ///      seed itself.
    ///
    ///      Both branches depend ONLY on values fixed before settlement: roundId, the
    ///      pinned block's hash and the committed platonRandom. `block.prevrandao` was
    ///      previously mixed in "so the signer can't grind" — but commit-reveal already
    ///      pins platonRandom and the blockhash is unknown at commit time, so it added
    ///      no entropy against the signer while making the winner a function of the
    ///      SUBMISSION block. That is precisely a re-roll lever: whoever submits can
    ///      compute the outcome first and resubmit later for a different one (and on
    ///      OP-stack L2s prevrandao is inherited from the L1 origin block, so it is
    ///      identical across many consecutive L2 blocks and predictable to the
    ///      submitter anyway). Dropping it is what makes permissionless settlement safe.
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
        return uint256(baseSeed);
    }

    // ── payouts ────────────────────────────────────────────────────────────

    /// @notice Winner pulls the prize. Available for UNCLAIMED_PRIZE_TTL after the
    ///         draw; afterwards the prize is recycled (see forfeitUnclaimedPrize).
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

    /// @notice Recycle a prize the winner never claimed back into the next draw.
    /// @dev Without this, a winner who loses key access strands the prize in the
    ///      contract forever. The resolution stays non-custodial: the funds do not
    ///      leave the contract here, nobody (operator, treasury, caller) can withdraw
    ///      `unclaimedPool`, and its only exit is becoming the prize of a later round —
    ///      i.e. it goes back to players, untaxed. Permissionless and TTL-bounded, so
    ///      it is neither an operator lever nor a way to race a live claim. The roll-in
    ///      is additionally capped at the absorbing round's own income (see fulfillDraw)
    ///      so the pool cannot be harvested by a one-ticket round.
    function forfeitUnclaimedPrize(uint256 roundId) external {
        Round storage r = _rounds[roundId];
        if (r.status != Status.Settled) revert WrongStatus();
        if (r.prizeClaimed) revert AlreadyClaimed();
        uint64 anchor = settledAt[roundId];
        // Fail closed: no settle anchor ⇒ no provable TTL ⇒ no forfeit.
        if (anchor == 0) revert TooEarly();
        if (block.timestamp < uint256(anchor) + UNCLAIMED_PRIZE_TTL) revert TooEarly();
        r.prizeClaimed = true; // claim window closed — also blocks a double payout
        uint256 amount = r.prizePool;
        unclaimedPool += amount;
        emit PrizeForfeited(roundId, r.winner, amount);
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

    /// @notice Operator cancel — refunds tickets AND sponsor funding via `refund`.
    /// @dev Refused while the round is SETTLEABLE, i.e. exactly while
    ///      `blockhash(seedBlock)` is readable and there is a winner to derive from it.
    ///      Otherwise an unlimited, cooldown-free re-roll sits next to the bounded
    ///      MAX_RESEEDS one: the operator computes the winner the moment the seed block
    ///      is mined and, if it dislikes it, cancels — free, instantly, as often as it
    ///      likes — or simply front-runs a participant's fulfillDraw in the mempool,
    ///      which would make permissionless settlement decorative. The honest exits are
    ///      untouched: an Open round, a Drawing round whose seed is not mined yet
    ///      (nothing is known), one whose seed hash has aged out (nobody can settle it),
    ///      and one with no participants (no winner exists) all still cancel on demand.
    ///      Residual, and irreducible on-chain: the operator alone produces the beacon,
    ///      so it can still privately compute the outcome, never publish, wait out the
    ///      ~SEED_LIFETIME_BLOCKS window and cancel then. That path is slow, refunds
    ///      everyone and earns nothing — see the fairness notes at the top of the file.
    function cancelRound(uint256 roundId) external onlyRole(OPERATOR_ROLE) {
        Round storage r = _rounds[roundId];
        if (r.status != Status.Open && r.status != Status.Drawing) revert WrongStatus();
        if (
            r.status == Status.Drawing && _participants[roundId].length > 0
                && blockhash(r.seedBlock) != bytes32(0)
        ) revert TooEarly();
        r.status = Status.Cancelled;
        emit RoundCancelled(roundId);
    }

    /// @notice Cancel a round that has been stuck in Drawing for STALL_CANCEL_DELAY,
    ///         opening refunds for tickets AND sponsor funding. Permissionless.
    /// @dev Closes the last hostage lever left to a stalling operator: settlement is
    ///      permissionless, but only the operator/oracle can PUBLISH a beacon, so a
    ///      round could otherwise sit in Drawing (neither settled, nor rescued, nor
    ///      cancelled) with entries locked in. The delay is orders of magnitude beyond
    ///      any legitimate settle path (the whole settle window is SEED_LIFETIME_BLOCKS
    ///      blocks, plus at most MAX_RESEEDS rescues that each re-arm `closedAt`), so
    ///      this can never cancel a round that is still drawable. Not gated by
    ///      Pausable: pausing must not be able to trap entries either.
    function cancelStalledRound(uint256 roundId) external {
        Round storage r = _rounds[roundId];
        if (r.status != Status.Drawing) revert WrongStatus();
        if (block.timestamp < uint256(r.closedAt) + STALL_CANCEL_DELAY) revert TooEarly();
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
        // Derived from the block-denominated settle window, never a literal: a larger
        // delay would expire the seed before the draw is even valid, bricking every
        // round into the rescue path.
        require(d <= maxDrawDelay(), "drawDelay > seed window");
        minDrawDelay = d;
    }

    /// @notice Declare the deployment chain's block time (GOVERNANCE, not operations).
    /// @dev Every wall-clock bound on the draw is derived from this, so a chain move
    ///      (or a block-time change on the same chain — Base has already halved its
    ///      block time once) is a single explicit parameter update instead of a stale
    ///      literal. Refuses any value that would leave the CURRENT minDrawDelay
    ///      unsatisfiable: lower the delay first (fail closed).
    function setSecondsPerBlock(uint64 s) external onlyRole(GOVERNANCE_ROLE) {
        require(s > 0 && s <= MAX_SECONDS_PER_BLOCK, "blockTime out of range");
        uint64 newMax = _maxDrawDelay(s);
        require(minDrawDelay <= newMax, "drawDelay > seed window");
        secondsPerBlock = s;
        emit BlockTimeUpdated(s, newMax);
    }

    /// @notice Largest draw delay the settle window can actually satisfy, in seconds.
    function maxDrawDelay() public view returns (uint64) {
        return _maxDrawDelay(secondsPerBlock);
    }

    function _maxDrawDelay(uint64 s) internal pure returns (uint64) {
        return uint64((SEED_LIFETIME_BLOCKS * uint256(s)) / DRAW_DELAY_HEADROOM);
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
