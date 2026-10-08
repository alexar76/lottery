// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.28;

import {Test} from "forge-std/Test.sol";
import {BigMath} from "../src/BigMath.sol";
import {ChronosVDF} from "../src/ChronosVDF.sol";

/// Validates the on-chain bignum + Wesolowski VDF verifier against a REAL vector
/// generated from the live Chronos oracle (test/vectors/chronos_vector.json).
contract ChronosVDFTest is Test {
    bytes N;
    bytes g;
    bytes y;
    bytes pi;
    bytes l;
    bytes r;
    bytes A;
    bytes B;
    bytes AB;
    uint256 T;
    string seed;

    function setUp() public {
        string memory j = vm.readFile("test/vectors/chronos_vector.json");
        N = vm.parseJsonBytes(j, ".N_hex");
        g = vm.parseJsonBytes(j, ".g_hex");
        y = vm.parseJsonBytes(j, ".y_hex");
        pi = vm.parseJsonBytes(j, ".pi_hex");
        l = vm.parseJsonBytes(j, ".l_hex");
        r = vm.parseJsonBytes(j, ".r_hex");
        A = vm.parseJsonBytes(j, ".A_modexp_pi_l_N_hex");
        B = vm.parseJsonBytes(j, ".B_modexp_g_r_N_hex");
        AB = vm.parseJsonBytes(j, ".AB_mod_N_hex");
        T = vm.parseJsonUint(j, ".T");
        seed = vm.parseJsonString(j, ".seed");
    }

    function test_modexp_matches_oracle_intermediates() public view {
        // r = 2^T mod l
        assertTrue(BigMath.eq(BigMath.modexp(hex"02", _u(T), l), r), "r");
        // A = pi^l mod N ; B = g^r mod N
        assertTrue(BigMath.eq(BigMath.modexp(pi, l, N), A), "A");
        assertTrue(BigMath.eq(BigMath.modexp(g, r, N), B), "B");
    }

    function test_modmul_matches_oracle() public view {
        // (A * B) mod N == AB == y
        assertTrue(BigMath.eq(BigMath.modmul(A, B, N), AB), "modmul==AB");
        assertTrue(BigMath.eq(AB, y), "AB==y");
    }

    function test_verify_real_vdf_proof() public view {
        assertTrue(ChronosVDF.verifyEquation(N, g, y, pi, l, T), "valid proof must verify");
    }

    function test_reject_tampered_y() public view {
        bytes memory yBad = bytes.concat(y);
        yBad[yBad.length - 1] = bytes1(uint8(yBad[yBad.length - 1]) ^ 0x01);
        assertFalse(ChronosVDF.verifyEquation(N, g, yBad, pi, l, T), "tampered y must fail");
    }

    function test_reject_tampered_pi() public view {
        bytes memory piBad = bytes.concat(pi);
        piBad[piBad.length - 1] = bytes1(uint8(piBad[piBad.length - 1]) ^ 0x01);
        assertFalse(ChronosVDF.verifyEquation(N, g, y, piBad, l, T), "tampered pi must fail");
    }

    function test_reject_l_equals_one_forgery() public view {
        // AUDIT critical: l=1 collapsed the check to pi==y (free forgery). Now rejected.
        assertFalse(ChronosVDF.verifyEquation(N, g, y, y, hex"01", T), "l=1 forgery must be rejected");
    }

    function test_reject_noncanonical_modulus() public view {
        // AUDIT critical: a caller-supplied (e.g. smooth/zero) N must be rejected.
        bytes memory badN = bytes.concat(N);
        badN[badN.length - 1] = bytes1(uint8(badN[badN.length - 1]) ^ 0x02);
        assertFalse(ChronosVDF.verifyEquation(badN, g, y, pi, l, T), "non-canonical N must be rejected");
    }

    function test_hashToGroup_matches_oracle() public view {
        // on-chain g derivation must equal the oracle's g for the same seed
        assertTrue(BigMath.eq(ChronosVDF.hashToGroup(seed, N), g), "g binding");
    }

    function _u(uint256 x) internal pure returns (bytes memory) {
        if (x == 0) return hex"00";
        uint256 len;
        uint256 t = x;
        while (t != 0) {
            len++;
            t >>= 8;
        }
        bytes memory b = new bytes(len);
        for (uint256 i = 0; i < len; i++) {
            b[len - 1 - i] = bytes1(uint8(x >> (8 * i)));
        }
        return b;
    }
}
