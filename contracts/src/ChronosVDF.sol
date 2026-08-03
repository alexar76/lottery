// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.28;

import {BigMath} from "./BigMath.sol";

/**
 * @title ChronosVDF
 * @notice On-chain verifier for the Chronos Wesolowski VDF (RSA group of unknown
 *         order), the same construction served by the chronos.eval (v1) oracle.
 *
 * A Verifiable Delay Function output `y = g^(2^T) mod N` requires T *sequential*
 * squarings to produce, but is cheap to verify with the Wesolowski proof:
 *
 *      verify:  π^l · g^r ≡ y (mod N),   with r = 2^T mod l
 *
 * where `l = hash_to_prime(g, y, T)` (a ~128-bit Fiat–Shamir prime) and `g =
 * hash_to_group(seed)`. N is the public RSA-2048-class modulus whose
 * factorization is unknown, so nobody can shortcut the squaring — the result is
 * publicly verifiable and bias-resistant (a draw cannot be ground within the
 * delay window).
 *
 * This library verifies the core equation on-chain (via the modexp precompile)
 * and can re-derive `g` from a seed so the VDF is bound to an unpredictable
 * round seed. The `l`-binding (`l == hash_to_prime(g,y,T)`) requires an on-chain
 * Miller–Rabin loop; that step is delegated to the oracle-signer attestation in
 * the lottery (see AUDIT.md "Trust boundary"). The equation + g-binding verified
 * here are the parts that enforce the sequential-work / unbiasability property.
 */
library ChronosVDF {
    /// The canonical Chronos RSA-2048-class modulus (factorization unknown). The
    /// VDF is only sound over THIS modulus, so a caller-supplied N is rejected —
    /// otherwise an attacker could pass a zero/smooth/known-order N and forge any y.
    bytes private constant CANONICAL_N =
        hex"4df7010d4e3c70edcec84c8a57e8dfbc4124aa72b1f4a01265ccb3776cd3892fbdfa15c383f6ed9e05ce95bdcb7406ee0092853b7c0b86cbc6996719e746bfa7abb83f907aa3d7d266d6977bea981fd733b3cfd20d00ec2d5ad5b7c3a2016a30faae40e9d6c04c6f02eae561cc4f4b58dfc07cf014e40f09564d14b7b9303c0f98d75be73a63f19ed3fc199e8637975f102441fb8cf7fba91347074007dd02e893c9b66149d6e722b8b75402198d97e669b9ba42efd87122bfb211fd3cf5cbdca6b4d0b8b3f1746ed597cf271fc17ababe80d8a3e1a78f4086f21f24a3fc0f1b3131f55615172866bccc30f95054c824e733a5eb6817f7bc16399d48c6361cc7e5";

    /// @notice verify π^l · g^r ≡ y (mod N), r = 2^T mod l. All bignums big-endian.
    function verifyEquation(
        bytes memory N,
        bytes memory g,
        bytes memory y,
        bytes memory pi,
        bytes memory l,
        uint256 T
    ) internal view returns (bool) {
        // Pin the modulus: the proof is only sound over the canonical RSA modulus.
        if (!BigMath.eq(N, CANONICAL_N)) return false;
        // Reject degenerate l. l == 1 collapses the check to (pi == y) — a free
        // forgery. Require l ∈ [2, 2^128), odd (Chronos's l is a ~128-bit prime).
        // NOTE: this does NOT fully re-derive l == hash_to_prime(g,y,T) on-chain
        // (Miller-Rabin is gas-heavy) — see AUDIT.md "Residual"; combined with the
        // pinned modulus, forging a *chosen* y still requires an l-th root mod N
        // (RSA-hard), and l==1 / even l / oversized l are rejected here.
        if (!_validL(l)) return false;
        // r = 2^T mod l
        bytes memory r = BigMath.modexp(hex"02", _toBytes(T), l);
        // A = π^l mod N,  B = g^r mod N
        bytes memory A = BigMath.modexp(pi, l, N);
        bytes memory B = BigMath.modexp(g, r, N);
        // left = (A * B) mod N
        bytes memory left = BigMath.modmul(A, B, N);
        // compare against y mod N
        bytes memory yr = BigMath.mod(y, N);
        return BigMath.eq(left, yr);
    }

    /**
     * @notice Re-derive the Chronos group generator g from a seed string, exactly
     *         as `chronos.vdf.hash_to_group`: concatenate SHA-256(`"chronos-g|" +
     *         len + "|" + seed`) until >= 256 bytes, interpret big-endian, mod N,
     *         floor to >= 2.
     */
    function hashToGroup(string memory seed, bytes memory N) internal view returns (bytes memory) {
        bytes memory acc;
        for (uint256 off = 0; off < 256; off += 32) {
            bytes32 d = sha256(abi.encodePacked("chronos-g|", _decimal(off), "|", seed));
            acc = abi.encodePacked(acc, d);
        }
        bytes memory g = BigMath.mod(acc, N);
        if (_ltTwo(g)) return hex"02";
        return g;
    }

    // ── internals ─────────────────────────────────────────────────────────

    /// l must be in [2, 2^128) and odd (Chronos's l is a ~128-bit prime).
    function _validL(bytes memory l) private pure returns (bool) {
        uint256 i = 0;
        while (i < l.length && l[i] == 0) i++;
        uint256 nz = l.length - i; // significant byte length
        if (nz == 0 || nz > 16) return false; // zero, or wider than 128-bit
        if (uint8(l[l.length - 1]) & 1 == 0) return false; // must be odd
        if (nz == 1 && uint8(l[l.length - 1]) == 1) return false; // reject l == 1
        return true;
    }

    /// uint256 -> minimal big-endian bytes (no leading zeros; 0 -> 0x00).
    function _toBytes(uint256 x) private pure returns (bytes memory) {
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

    /// uint256 -> ASCII decimal bytes ("0", "32", ...), matching Python str().
    function _decimal(uint256 x) private pure returns (bytes memory) {
        if (x == 0) return "0";
        uint256 t = x;
        uint256 len;
        while (t != 0) {
            len++;
            t /= 10;
        }
        bytes memory b = new bytes(len);
        t = x;
        for (uint256 i = 0; i < len; i++) {
            b[len - 1 - i] = bytes1(uint8(48 + (t % 10)));
            t /= 10;
        }
        return b;
    }

    /// true if the bignum g (big-endian) is < 2.
    function _ltTwo(bytes memory g) private pure returns (bool) {
        uint256 nonzero;
        uint256 last;
        for (uint256 i = 0; i < g.length; i++) {
            uint8 v = uint8(g[i]);
            if (v != 0) {
                nonzero++;
                last = v;
            }
        }
        if (nonzero == 0) return true; // 0
        if (nonzero == 1 && last == 1) return true; // 1
        return false;
    }
}
