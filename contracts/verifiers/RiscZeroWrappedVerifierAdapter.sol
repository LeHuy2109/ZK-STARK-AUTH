// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IRiscZeroVerifier {
    function verify(
        bytes calldata seal,
        bytes32 imageId,
        bytes32 journalDigest
    ) external view;
}

/// @notice Adapter from this benchmark's bool-returning verifier interface to
///         the official RISC Zero verifier interface, which reverts on failure.
contract RiscZeroWrappedVerifierAdapter {
    IRiscZeroVerifier public immutable RISC_ZERO_VERIFIER;

    constructor(address verifier) {
        require(verifier != address(0), "verifier required");
        RISC_ZERO_VERIFIER = IRiscZeroVerifier(verifier);
    }

    function verifyWrappedProof(
        bytes calldata wrappedProof,
        bytes32 imageId,
        bytes32 journalDigest
    ) external view returns (bool) {
        try RISC_ZERO_VERIFIER.verify(wrappedProof, imageId, journalDigest) {
            return true;
        } catch {
            return false;
        }
    }
}
