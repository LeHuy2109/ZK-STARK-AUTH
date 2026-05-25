"""Run the stark_offchain application authorization benchmark mode."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import (
    DEFAULT_ABI_PATH,
    PROJECT_ROOT,
    STARK_DOMAIN,
    build_nonce,
    build_web3,
    compute_stark_authorization_digest_hex,
    derive_identity_commitment,
    ensure_results_dir,
    load_abi,
    load_dotenv,
    optional_env_int,
    payload_hash_hex,
    prove_risc0_auth,
    public_input_size_bytes,
    receipt_hash_hex,
    require_app_auth_private_key,
    require_env,
    send_contract_transaction,
    verify_risc0_auth,
    write_result,
)
from offchain_storage import save_receipt, storage_backend_name


DEFAULT_PAYLOAD = {
    "action": "transfer",
    "resource": "application-auth-benchmark",
    "amount": 1,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and verify a RISC Zero/STARK app-authorization proof off-chain."
    )
    parser.add_argument(
        "--payload",
        default=json.dumps(DEFAULT_PAYLOAD, separators=(",", ":")),
        help="UTF-8 payload bytes to authorize.",
    )
    parser.add_argument("--nonce", type=int, default=None, help="Authorization nonce.")
    parser.add_argument(
        "--chain-id",
        type=int,
        default=None,
        help="Chain id to bind into the proof. Defaults to RPC chain id.",
    )
    parser.add_argument(
        "--submit-metadata",
        action="store_true",
        help="Submit proof hash/CID metadata on-chain. This is not proof verification.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv()

    app_auth_private_key = require_app_auth_private_key()
    contract_address = require_env("CONTRACT_ADDRESS")
    rpc_url = require_env("RPC_URL")

    w3 = build_web3(rpc_url)
    chain_id = args.chain_id if args.chain_id is not None else w3.eth.chain_id
    payload = args.payload.encode("utf-8")
    payload_hash = payload_hash_hex(w3, payload)
    nonce = args.nonce if args.nonce is not None else build_nonce()
    identity_commitment = derive_identity_commitment(app_auth_private_key)
    authorization_digest = compute_stark_authorization_digest_hex(
        domain=STARK_DOMAIN,
        payload_hash=payload_hash,
        identity_commitment=identity_commitment,
        nonce=nonce,
        chain_id=chain_id,
        contract_address=contract_address,
    )

    results_dir = ensure_results_dir()
    receipt_path = results_dir / "stark_offchain_receipt.bin"
    metadata_path = results_dir / "stark_offchain_metadata.json"
    verify_metadata_path = results_dir / "stark_offchain_verify_metadata.json"

    prove_metadata, stark_prove_seconds = prove_risc0_auth(
        payload_hash=payload_hash,
        app_auth_private_key=app_auth_private_key,
        nonce=nonce,
        chain_id=chain_id,
        contract_address=contract_address,
        receipt_path=receipt_path,
        metadata_path=metadata_path,
        domain=STARK_DOMAIN,
    )
    verify_metadata, stark_verify_seconds = verify_risc0_auth(
        receipt_path=receipt_path,
        domain=STARK_DOMAIN,
        payload_hash=payload_hash,
        identity_commitment=identity_commitment,
        authorization_digest=authorization_digest,
        nonce=nonce,
        chain_id=chain_id,
        contract_address=contract_address,
        metadata_path=verify_metadata_path,
    )

    receipt_bytes = receipt_path.read_bytes()
    proof_hash = receipt_hash_hex(receipt_bytes)
    proof_cid, stored_path, receipt_upload_seconds = save_receipt(
        receipt_bytes, Path(require_env("OFFCHAIN_STORE_DIR", str(PROJECT_ROOT / "benchmark/results/offchain_store")))
    )

    metadata_tx = None
    if args.submit_metadata:
        submitter_private_key = require_env("SUBMITTER_PRIVATE_KEY")
        abi_path = require_env("CONTRACT_ABI_PATH", str(DEFAULT_ABI_PATH))
        timeout_seconds = optional_env_int("TX_TIMEOUT_SECONDS", 120)
        gas_limit = optional_env_int("TX_GAS_LIMIT", 1_000_000)
        contract = w3.eth.contract(
            address=w3.to_checksum_address(contract_address),
            abi=load_abi(abi_path),
        )
        metadata_tx = send_contract_transaction(
            w3=w3,
            function_call=contract.functions.submitStarkOffchainMetadata(
                payload,
                payload_hash,
                identity_commitment,
                authorization_digest,
                proof_hash,
                nonce,
                proof_cid,
            ),
            submitter_private_key=submitter_private_key,
            gas=gas_limit,
            timeout_seconds=timeout_seconds,
        )

    benchmark = {
        "stark_prove_seconds": round(stark_prove_seconds, 6),
        "stark_verify_seconds": round(stark_verify_seconds, 6),
        "proof_size_bytes": len(receipt_bytes),
        "journal_size_bytes": prove_metadata["journal_size_bytes"],
        "public_input_size_bytes": public_input_size_bytes(
            domain=STARK_DOMAIN,
            payload_hash=payload_hash,
            identity_commitment=identity_commitment,
            authorization_digest=authorization_digest,
            nonce=nonce,
            chain_id=chain_id,
            contract_address=contract_address,
        ),
        "receipt_upload_seconds": receipt_upload_seconds,
    }
    if metadata_tx is not None:
        benchmark.update(
            {
                "metadata_tx_gas_used": metadata_tx["gas_used"],
                "metadata_send_and_confirm_seconds": metadata_tx["send_and_confirm_seconds"],
                "tx_build_seconds": metadata_tx["tx_build_seconds"],
                "submitter_tx_sign_seconds": metadata_tx["submitter_tx_sign_seconds"],
                "raw_tx_size_bytes": metadata_tx["raw_tx_size_bytes"],
            }
        )

    result = {
        "mode": "stark_offchain",
        "domain": STARK_DOMAIN,
        "chain_id": chain_id,
        "contract_address": w3.to_checksum_address(contract_address),
        "payload": args.payload,
        "payload_hash": payload_hash,
        "nonce": nonce,
        "identity_commitment": identity_commitment,
        "authorization_digest": authorization_digest,
        "proof_hash": proof_hash,
        "proof_cid": proof_cid,
        "receipt_path": str(receipt_path),
        "stored_receipt_path": str(stored_path),
        "storage_backend": storage_backend_name(),
        "risc0_prove_metadata": prove_metadata,
        "risc0_verify_metadata": verify_metadata,
        "metadata_tx": metadata_tx,
        "benchmark": benchmark,
        "notes": [
            "RISC Zero/STARK receipt is generated and verified off-chain.",
            "Optional on-chain proofHash/proofCid submission is metadata only, not trustless proof verification.",
            "Do not compare metadata gas against ecdsa_onchain verifier gas.",
        ],
    }
    output_path = write_result("stark_offchain_result.json", result)
    print(json.dumps(result, indent=2))
    print(f"Result written to {output_path}")


if __name__ == "__main__":
    main()
