// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.28;

import {Script, console2} from "forge-std/Script.sol";
import {AIAgentLottery} from "../src/AIAgentLottery.sol";

/**
 * @title DeployLottery
 * @notice One-command deploy of the AI-Agent Oracle Lottery to any EVM chain.
 *
 *   forge script script/DeployLottery.s.sol:DeployLottery \
 *     --rpc-url $RPC_SEPOLIA --broadcast --verify
 *
 * All parameters come from env (with safe defaults → the deployer holds every
 * role for a quick testnet bring-up). For real value, set ADMIN/OPERATOR/
 * ORACLE_SIGNER/TREASURY to DISTINCT multisig/timelock addresses and set
 * ONCHAIN_VDF=true — see docs/AUDIT.md (Residual) and docs/README.md.
 */
contract DeployLottery is Script {
    function run() external returns (AIAgentLottery lottery) {
        uint256 pk = vm.envUint("PRIVATE_KEY");
        address deployer = vm.addr(pk);

        address admin = vm.envOr("ADMIN", deployer);
        address governance = vm.envOr("GOVERNANCE", deployer); // admins the money/fairness roles
        address operator = vm.envOr("OPERATOR", deployer);
        address oracleSigner = vm.envOr("ORACLE_SIGNER", deployer);
        address treasury = vm.envOr("TREASURY", deployer);
        uint48 adminDelay = uint48(vm.envOr("ADMIN_TRANSFER_DELAY", uint256(2 days)));
        address token = vm.envOr("TOKEN", address(0)); // address(0) = native ETH; else ERC-20 (e.g. USDC)
        uint256 ticketPrice = vm.envOr("TICKET_PRICE", uint256(0.001 ether));
        uint16 prizeBps = uint16(vm.envOr("PRIZE_BPS", uint256(8000)));
        uint16 opexBps = uint16(vm.envOr("OPEX_BPS", uint256(1200)));
        uint16 operatorBps = uint16(vm.envOr("OPERATOR_BPS", uint256(800)));
        uint64 entryWindow = uint64(vm.envOr("ENTRY_WINDOW", uint256(1 days)));
        uint64 minDrawDelay = uint64(vm.envOr("MIN_DRAW_DELAY", uint256(60)));
        bool onchainVdf = vm.envOr("ONCHAIN_VDF", false);

        vm.startBroadcast(pk);
        lottery = new AIAgentLottery(
            admin, governance, operator, oracleSigner, treasury, token,
            ticketPrice, prizeBps, opexBps, operatorBps,
            entryWindow, minDrawDelay, onchainVdf, adminDelay
        );
        vm.stopBroadcast();

        console2.log("AIAgentLottery deployed:", address(lottery));
        console2.log("  token (0=native):", token);
        console2.log("  ticketPrice:", ticketPrice);
        console2.log("Next: set sponsor.yaml lottery_address to the above, then run the relayer.");
    }
}
