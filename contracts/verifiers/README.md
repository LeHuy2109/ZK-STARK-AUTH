# Wrapped STARK Verifier Adapter

`ApplicationAuthBenchmark` does not pretend that a proof hash or CID is proof
verification. For `stark_wrapped_onchain`, it calls a real verifier adapter:

```solidity
function verifyWrappedProof(
    bytes calldata wrappedProof,
    bytes32 imageId,
    bytes32 journalDigest
) external view returns (bool);
```

The adapter deployed at `wrappedStarkVerifier` must connect this interface to
the chosen RISC Zero/Groth16 Solidity verifier stack. The benchmark contract
then performs the application-level checks itself:

```text
payload hash
fresh nonce
wrapped domain
identity_commitment
authorization_digest
RISC Zero image_id
RISC Zero journal_digest
```

Deploy `ApplicationAuthBenchmark` with `address(0)` for Milestone 1 only, or
with the adapter address when running `stark_wrapped_onchain`. The owner can
also set the adapter later with `setWrappedStarkVerifier`.

On Sepolia, do not use the raw RISC Zero verifier address directly as
`WRAPPED_STARK_VERIFIER_ADDRESS`. Deploy
`RiscZeroWrappedVerifierAdapter.sol` with the raw verifier address as its
constructor argument, then put the deployed adapter address in `.env`.
