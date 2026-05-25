use risc0_zkvm::guest::env;
use serde::Deserialize;
use sha2::{Digest, Sha256};

#[derive(Deserialize)]
struct AuthorizationInput {
    domain: String,
    app_auth_private_key: [u8; 32],
    payload_hash: [u8; 32],
    nonce: [u8; 32],
    chain_id: [u8; 32],
    contract_address: [u8; 20],
}

fn main() {
    let input: AuthorizationInput = env::read();

    let identity_commitment = Sha256::digest(input.app_auth_private_key);
    let mut authorization_hasher = Sha256::new();
    authorization_hasher.update(input.domain.as_bytes());
    authorization_hasher.update(identity_commitment);
    authorization_hasher.update(input.payload_hash);
    authorization_hasher.update(input.nonce);
    authorization_hasher.update(input.chain_id);
    authorization_hasher.update(input.contract_address);
    let authorization_digest = authorization_hasher.finalize();

    let mut journal = Vec::with_capacity(input.domain.len() + 180);
    journal.extend_from_slice(input.domain.as_bytes());
    journal.extend_from_slice(&identity_commitment);
    journal.extend_from_slice(&authorization_digest);
    journal.extend_from_slice(&input.payload_hash);
    journal.extend_from_slice(&input.nonce);
    journal.extend_from_slice(&input.chain_id);
    journal.extend_from_slice(&input.contract_address);

    env::commit_slice(&journal);
}
