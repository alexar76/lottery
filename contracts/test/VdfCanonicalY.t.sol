// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.28;

import {Test} from "forge-std/Test.sol";
import {BigMath} from "../src/BigMath.sol";
import {ChronosVDF} from "../src/ChronosVDF.sol";

/// The beacon signer must not be able to choose the winner.
///
/// With `onchainVdf` on, the draw's random word was `keccak256(vdf.y)` — the RAW bytes the
/// caller supplied. But `verifyEquation` only ever compares `y` as a RESIDUE
/// (`BigMath.eq(left, BigMath.mod(y, N))`), so infinitely many byte strings satisfy the
/// SAME proof: `y`, `0x00‖y`, and `y + k·N` for every k. Each hashes to a different word,
/// so whoever holds ORACLE_SIGNER could enumerate k after the seed block is mined and pick
/// the k whose word lands on the ticket it wants — the VDF is there to make the draw
/// unbiasable, and this made it biasable by exactly the party it was protecting against.
///
/// Two changes, and both are needed: the word is derived from the canonical residue (so the
/// leading-zero variants collapse onto one value), and `verifyEquation` refuses a `y` that
/// is not already reduced (so `y + k·N` is not a valid proof at all).
contract VdfCanonicalYTest is Test {
    bytes N;
    bytes g;
    bytes y;
    bytes pi;
    bytes l;
    uint256 T;

    function setUp() public {
        string memory j = vm.readFile("test/vectors/chronos_vector.json");
        N = vm.parseJsonBytes(j, ".N_hex");
        g = vm.parseJsonBytes(j, ".g_hex");
        y = vm.parseJsonBytes(j, ".y_hex");
        pi = vm.parseJsonBytes(j, ".pi_hex");
        l = vm.parseJsonBytes(j, ".l_hex");
        T = vm.parseJsonUint(j, ".T");
    }

    function test_the_honest_proof_still_verifies() public view {
        assertTrue(ChronosVDF.verifyEquation(N, g, y, pi, l, T), "real vector must verify");
    }

    /// y + N carries the same residue, so it satisfied the same equation.
    function test_a_shifted_y_is_no_longer_a_valid_proof() public view {
        bytes memory shifted = _add(y, N);
        // Sanity: it is a DIFFERENT byte string with the SAME residue mod N.
        assertFalse(BigMath.eq(shifted, y), "fixture is not exercising the shift");
        assertTrue(BigMath.eq(BigMath.mod(shifted, N), BigMath.mod(y, N)), "same residue");
        assertFalse(
            ChronosVDF.verifyEquation(N, g, shifted, pi, l, T),
            "y + N verified: the signer can grind the random word"
        );
    }

    /// A leading zero byte changes keccak256 while leaving the value untouched.
    function test_a_leading_zero_y_yields_the_same_canonical_word() public view {
        bytes memory padded = abi.encodePacked(hex"00", y);
        assertTrue(
            ChronosVDF.verifyEquation(N, g, padded, pi, l, T),
            "a leading zero must not invalidate an honest proof"
        );
        assertEq(
            keccak256(ChronosVDF.canonicalY(padded, N)),
            keccak256(ChronosVDF.canonicalY(y, N)),
            "0x00-padded y produced a different random word"
        );
        // And the raw bytes really do differ — otherwise this test proves nothing.
        assertTrue(keccak256(padded) != keccak256(y), "fixture is not exercising the padding");
    }

    function test_canonical_y_is_the_residue() public view {
        assertTrue(BigMath.eq(ChronosVDF.canonicalY(y, N), BigMath.mod(y, N)), "residue");
    }

    /// Big-endian byte addition. BigMath has no `add` (it only ever needs modular ops), and
    /// a test needs one to build the shifted witness. Test-only on purpose.
    function _add(bytes memory a, bytes memory b) private pure returns (bytes memory) {
        uint256 len = (a.length > b.length ? a.length : b.length) + 1;
        bytes memory out = new bytes(len);
        uint256 carry = 0;
        for (uint256 i = 0; i < len; i++) {
            uint256 av = i < a.length ? uint8(a[a.length - 1 - i]) : 0;
            uint256 bv = i < b.length ? uint8(b[b.length - 1 - i]) : 0;
            uint256 sum = av + bv + carry;
            out[len - 1 - i] = bytes1(uint8(sum & 0xff));
            carry = sum >> 8;
        }
        return out;
    }
}
