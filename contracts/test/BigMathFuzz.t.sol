// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.28;

import {Test} from "forge-std/Test.sol";
import {BigMath} from "../src/BigMath.sol";

contract BigMathFuzzTest is Test {
    function _be(uint256 x) internal pure returns (bytes memory b) {
        b = abi.encodePacked(x);
    }

    function test_mul_max_limbs() public pure {
        bytes memory a = _be(type(uint256).max);
        bytes memory b = _be(type(uint256).max);
        bytes memory got = BigMath.mul(a, b);
        // (2^256-1)^2 = (2^256-2)*2^256 + 1
        bytes memory expected = abi.encodePacked(type(uint256).max - 1, uint256(1));
        assertTrue(BigMath.eq(got, expected), "max*max");
    }

    function test_mul_carry_propagation_multi_limb() public pure {
        bytes memory a = abi.encodePacked(type(uint256).max, type(uint256).max); // 2^512-1
        bytes memory b = _be(type(uint256).max); // 2^256-1
        bytes memory got = BigMath.mul(a, b);
        // python-computed (2^512-1)*(2^256-1), 96 bytes big-endian:
        bytes memory expected =
            hex"fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe"
            hex"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
            hex"0000000000000000000000000000000000000000000000000000000000000001";
        assertTrue(BigMath.eq(got, expected), "multi-limb carry");
    }

    function test_mul_zero() public pure {
        assertTrue(BigMath.eq(BigMath.mul(hex"00", _be(type(uint256).max)), hex"00"), "0*x");
        assertTrue(BigMath.eq(BigMath.mul(hex"", _be(5)), hex"00"), "empty*x");
    }

    function testFuzz_mul_against_uint(uint128 a, uint128 b) public pure {
        bytes memory ga = abi.encodePacked(a);
        bytes memory gb = abi.encodePacked(b);
        bytes memory got = BigMath.mul(ga, gb);
        uint256 expected = uint256(a) * uint256(b);
        assertTrue(BigMath.eq(got, abi.encodePacked(expected)), "fuzz mul");
    }

    function test_eq_leading_zero_and_empty() public pure {
        assertTrue(BigMath.eq(hex"0000", hex""), "0000==empty");
        assertTrue(BigMath.eq(hex"00", hex"0000"), "00==0000");
        assertTrue(BigMath.eq(hex"0005", hex"05"), "0005==05");
        assertFalse(BigMath.eq(hex"05", hex"06"), "5!=6");
    }
}
