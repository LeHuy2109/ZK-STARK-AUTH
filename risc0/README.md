# RISC Zero Application Authorization Host

This workspace implements the `stark_offchain` benchmark mode.

The guest proves the application authorization statement:

```text
identity_commitment = SHA256(APP_AUTH_PRIVATE_KEY)

authorization_digest = SHA256(
  domain,
  identity_commitment,
  payload_hash,
  nonce,
  chain_id,
  contract_address
)
```

The receipt is verified off-chain by the host. This is not on-chain STARK proof
verification.

## Milestone 1 Commands

Show CLI help:

```bash
cargo run -p host -- --help
```

Generate an off-chain RISC Zero/STARK receipt:

```bash
cargo run --release -p host -- prove \
  --domain STARK_APP_AUTH_V1 \
  --payload-hash 0x0000000000000000000000000000000000000000000000000000000000000000 \
  --app-auth-private-key 0x1111111111111111111111111111111111111111111111111111111111111111 \
  --nonce 1 \
  --chain-id 31337 \
  --contract-address 0x0000000000000000000000000000000000000001 \
  --output ../benchmark/results/stark_offchain_receipt.bin \
  --metadata-output ../benchmark/results/stark_offchain_metadata.json
```

Verify the receipt off-chain:

```bash
cargo run --release -p host -- verify \
  --receipt ../benchmark/results/stark_offchain_receipt.bin \
  --domain STARK_APP_AUTH_V1 \
  --payload-hash 0x0000000000000000000000000000000000000000000000000000000000000000 \
  --identity-commitment 0x... \
  --authorization-digest 0x... \
  --nonce 1 \
  --chain-id 31337 \
  --contract-address 0x0000000000000000000000000000000000000001
```

## Milestone 2 Placeholder

The host exposes `--groth16` so the wrapped proof path is explicit, but
Milestone 1 deliberately fails if the flag is used. That avoids pretending that
a proof hash, CID, or unwrapped STARK receipt is on-chain proof verification.
