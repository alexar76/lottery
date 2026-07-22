// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.28;

/**
 * @title BigMath
 * @notice Minimal arbitrary-precision modular arithmetic over big-endian byte
 *         strings, used to verify RSA-group (2048+ bit) operations on-chain.
 *
 * Built on the EVM `modexp` precompile (address 0x05), which computes
 * `base^exp mod modulus` for arbitrary-length inputs and conveniently reduces
 * the base modulo the modulus first — so `modexp(a, 1, m) == a mod m` for any a.
 * The only piece the precompile can't do is a plain product `a*b`; we implement
 * a schoolbook multiply and then reduce with `modexp(prod, 1, m)`.
 *
 * Numbers are big-endian, leading zeros insignificant. This is deliberately
 * simple/readable (not gas-micro-optimized): the on-chain VDF check runs once
 * per lottery draw, not in a hot loop.
 */
library BigMath {
    bytes private constant ONE = hex"01";

    /// @notice base^exp mod m via precompile 0x05. Returns an m-length buffer.
    function modexp(bytes memory base, bytes memory exp, bytes memory m)
        internal
        view
        returns (bytes memory out)
    {
        uint256 bl = base.length;
        uint256 el = exp.length;
        uint256 ml = m.length;
        require(ml > 0, "BigMath: zero modulus length");
        // Reject a zero-VALUED modulus: the modexp precompile returns 0 for it
        // without reverting, which would let mod()/modmul() "succeed" as 0 and
        // make a VDF equation check pass for arbitrary inputs.
        bool nonzeroMod;
        for (uint256 i = 0; i < ml; i++) {
            if (m[i] != 0) {
                nonzeroMod = true;
                break;
            }
        }
        require(nonzeroMod, "BigMath: zero modulus");
        bytes memory input = abi.encodePacked(bl, el, ml, base, exp, m);
        out = new bytes(ml);
        uint256 inLen = input.length;
        bool ok;
        assembly {
            ok := staticcall(gas(), 0x05, add(input, 0x20), inLen, add(out, 0x20), ml)
        }
        require(ok, "BigMath: modexp failed");
    }

    /// @notice a mod m  ==  a^1 mod m (the precompile reduces the base).
    function mod(bytes memory a, bytes memory m) internal view returns (bytes memory) {
        return modexp(a, ONE, m);
    }

    /// @notice (a * b) mod m.
    function modmul(bytes memory a, bytes memory b, bytes memory m)
        internal
        view
        returns (bytes memory)
    {
        return modexp(mul(a, b), ONE, m);
    }

    /// @notice schoolbook multiply of two big-endian bignums -> big-endian bytes.
    function mul(bytes memory a, bytes memory b) internal pure returns (bytes memory) {
        uint256[] memory x = _toLimbs(a); // little-endian limbs (limb[0] = LSW)
        uint256[] memory y = _toLimbs(b);
        if (x.length == 0 || y.length == 0) return hex"00";
        uint256[] memory r = new uint256[](x.length + y.length);
        // Carry-detecting additions intentionally wrap mod 2^256; do them
        // unchecked so 0.8's overflow guard doesn't panic on the wrap we rely on.
        for (uint256 i = 0; i < x.length; i++) {
            uint256 carry = 0;
            uint256 xi = x[i];
            for (uint256 j = 0; j < y.length; j++) {
                (uint256 hi, uint256 lo) = _mul256(xi, y[j]);
                unchecked {
                    uint256 s0 = lo + r[i + j];
                    uint256 c0 = s0 < lo ? 1 : 0;
                    uint256 s1 = s0 + carry;
                    uint256 c1 = s1 < s0 ? 1 : 0;
                    r[i + j] = s1;
                    carry = hi + c0 + c1; // <= 2^256-1, proven not to overflow
                }
            }
            uint256 k = i + y.length;
            while (carry != 0) {
                unchecked {
                    uint256 s = r[k] + carry;
                    carry = s < r[k] ? 1 : 0;
                    r[k] = s;
                }
                k++;
            }
        }
        return _fromLimbs(r);
    }

    /// @notice numeric equality ignoring leading zeros.
    function eq(bytes memory a, bytes memory b) internal pure returns (bool) {
        return keccak256(_trim(a)) == keccak256(_trim(b));
    }

    // ── internals ─────────────────────────────────────────────────────────

    /// 256x256 -> 512 multiply (Remco Bloemen's mulmod trick).
    function _mul256(uint256 a, uint256 b) private pure returns (uint256 hi, uint256 lo) {
        assembly {
            let mm := mulmod(a, b, not(0))
            lo := mul(a, b)
            hi := sub(sub(mm, lo), lt(mm, lo))
        }
    }

    /// big-endian bytes -> little-endian uint256 limbs.
    function _toLimbs(bytes memory a) private pure returns (uint256[] memory limbs) {
        bytes memory t = _trim(a);
        uint256 n = t.length;
        if (n == 0) return new uint256[](0);
        uint256 nl = (n + 31) / 32;
        limbs = new uint256[](nl);
        for (uint256 idx = 0; idx < nl; idx++) {
            uint256 end = n - idx * 32; // exclusive
            uint256 start = end >= 32 ? end - 32 : 0;
            uint256 word = 0;
            uint256 shift = 0;
            uint256 p = end;
            while (p > start) {
                p--;
                word |= uint256(uint8(t[p])) << shift;
                shift += 8;
            }
            limbs[idx] = word;
        }
    }

    /// little-endian uint256 limbs -> trimmed big-endian bytes.
    function _fromLimbs(uint256[] memory limbs) private pure returns (bytes memory out) {
        uint256 nl = limbs.length;
        out = new bytes(nl * 32);
        for (uint256 idx = 0; idx < nl; idx++) {
            uint256 word = limbs[nl - 1 - idx]; // most-significant limb first
            uint256 base = idx * 32;
            for (uint256 b = 0; b < 32; b++) {
                out[base + b] = bytes1(uint8(word >> (8 * (31 - b))));
            }
        }
        out = _trim(out);
        if (out.length == 0) out = hex"00";
    }

    function _trim(bytes memory a) private pure returns (bytes memory) {
        uint256 i = 0;
        while (i < a.length && a[i] == 0) i++;
        if (i == 0) return a;
        uint256 n = a.length - i;
        bytes memory r = new bytes(n);
        for (uint256 k = 0; k < n; k++) r[k] = a[i + k];
        return r;
    }
}
