"""Run the stark_wrapped_onchain application authorization benchmark mode."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import (
    DEFAULT_ABI_PATH,
    PROJECT_ROOT,
    STARK_WRAPPED_DOMAIN,
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
    require_app_auth_private_key,
    require_env,
    send_contract_transaction,
    verify_risc0_auth,
    write_result,
)


DEFAULT_PAYLOAD = {
    "action": "transfer",
    "resource": "application-auth-benchmark",
    "amount": 1,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a RISC Zero proof, wrap it with --groth16, and verify the wrapped proof on-chain."
    )
    parser.add_argument(
        "--payload",
        default=json.dumps(DEFAULT_PAYLOAD, separators=(",", ":")),
        help="UTF-8 payload bytes to authorize.",
    )
    parser.add_argument("--nonce", type=int, default=None, help="Authorization nonce.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv()

    rpc_url = require_env("RPC_URL")
    submitter_private_key = require_env("SUBMITTER_PRIVATE_KEY")
    contract_address = require_env("CONTRACT_ADDRESS")
    app_auth_private_key = require_app_auth_private_key()
    abi_path = require_env("CONTRACT_ABI_PATH", str(DEFAULT_ABI_PATH))
    timeout_seconds = optional_env_int("TX_TIMEOUT_SECONDS", 120)
    gas_limit = optional_env_int("TX_GAS_LIMIT", 2_000_000)

    w3 = build_web3(rpc_url)
    chain_id = w3.eth.chain_id
    contract = w3.eth.contract(
        address=w3.to_checksum_address(contract_address),
        abi=load_abi(abi_path),
    )

    payload = args.payload.encode("utf-8")
    payload_hash = payload_hash_hex(w3, payload)
    nonce = args.nonce if args.nonce is not None else build_nonce()
    identity_commitment = derive_identity_commitment(app_auth_private_key)
    authorization_digest = compute_stark_authorization_digest_hex(
        domain=STARK_WRAPPED_DOMAIN,
        payload_hash=payload_hash,
        identity_commitment=identity_commitment,
        nonce=nonce,
        chain_id=chain_id,
        contract_address=contract_address,
    )

    results_dir = ensure_results_dir()
    receipt_path = results_dir / "stark_wrapped_base_receipt.bin"
    wrapped_receipt_path = results_dir / "stark_wrapped_groth16_receipt.bin"
    metadata_path = results_dir / "stark_wrapped_metadata.json"
    verify_metadata_path = results_dir / "stark_wrapped_verify_metadata.json"

    prove_metadata, script_prove_and_wrap_wall_seconds = prove_risc0_auth(
        payload_hash=payload_hash,
        app_auth_private_key=app_auth_private_key,
        nonce=nonce,
        chain_id=chain_id,
        contract_address=contract_address,
        receipt_path=receipt_path,
        metadata_path=metadata_path,
        domain=STARK_WRAPPED_DOMAIN,
        groth16=True,
        wrapped_output_path=wrapped_receipt_path,
    )
    verify_metadata, script_verify_wall_seconds = verify_risc0_auth(
        receipt_path=wrapped_receipt_path,
        domain=STARK_WRAPPED_DOMAIN,
        payload_hash=payload_hash,
        identity_commitment=identity_commitment,
        authorization_digest=authorization_digest,
        nonce=nonce,
        chain_id=chain_id,
        contract_address=contract_address,
        metadata_path=verify_metadata_path,
    )

    wrapped_proof_path = prove_metadata["wrapped_proof_path"]
    wrapped_proof_file = Path(wrapped_proof_path)
    if not wrapped_proof_file.is_absolute():
        wrapped_proof_file = PROJECT_ROOT / wrapped_proof_file
    wrapped_proof = wrapped_proof_file.read_bytes()

    tx_metrics = send_contract_transaction(
        w3=w3,
        function_call=contract.functions.submitWithWrappedStark(
            payload,
            payload_hash,
            identity_commitment,
            authorization_digest,
            nonce,
            wrapped_proof,
            prove_metadata["image_id"],
            prove_metadata["journal_digest"],
        ),
        submitter_private_key=submitter_private_key,
        gas=gas_limit,
        timeout_seconds=timeout_seconds,
    )

    host_prove_seconds = prove_metadata.get("prove_seconds") or 0.0
    host_wrap_seconds = prove_metadata.get("wrap_seconds") or 0.0
    host_verify_seconds = (verify_metadata or {}).get("verify_seconds") or 0.0

    result = {
        "mode": "stark_wrapped_onchain",
        "domain": STARK_WRAPPED_DOMAIN,
        "chain_id": chain_id,
        "contract_address": w3.to_checksum_address(contract_address),
        "payload": args.payload,
        "payload_hash": payload_hash,
        "nonce": nonce,
        "identity_commitment": identity_commitment,
        "authorization_digest": authorization_digest,
        "image_id": prove_metadata["image_id"],
        "journal": prove_metadata["journal"],
        "journal_digest": prove_metadata["journal_digest"],
        "wrapped_proof_path": wrapped_proof_path,
        "wrapped_receipt_path": prove_metadata["wrapped_receipt_path"],
        "tx_hash": tx_metrics["tx_hash"],
        "gas_used": tx_metrics["gas_used"],
        "status": tx_metrics["status"],
        "risc0_prove_metadata": prove_metadata,
        "risc0_verify_metadata": verify_metadata,
        "benchmark": {
            "host_prove_seconds": round(host_prove_seconds, 6),
            "host_verify_seconds": round(host_verify_seconds, 6),
            "host_wrap_seconds": round(host_wrap_seconds, 6),
            "host_prove_and_wrap_seconds": round(host_prove_seconds + host_wrap_seconds, 6),
            "script_prove_and_wrap_wall_seconds": round(script_prove_and_wrap_wall_seconds, 6),
            "script_verify_wall_seconds": round(script_verify_wall_seconds, 6),
            "stark_prove_seconds": round(host_prove_seconds, 6),
            "stark_verify_seconds": round(host_verify_seconds, 6),
            "wrap_seconds": round(host_wrap_seconds, 6),
            "stark_prove_and_wrap_seconds": round(host_prove_seconds + host_wrap_seconds, 6),
            "wrapped_proof_size_bytes": prove_metadata["wrapped_proof_size_bytes"],
            "journal_size_bytes": prove_metadata["journal_size_bytes"],
            "public_input_size_bytes": public_input_size_bytes(
                domain=STARK_WRAPPED_DOMAIN,
                payload_hash=payload_hash,
                identity_commitment=identity_commitment,
                authorization_digest=authorization_digest,
                nonce=nonce,
                chain_id=chain_id,
                contract_address=contract_address,
            ),
            "wrapped_verify_gas_used": tx_metrics["gas_used"],
            "total_tx_gas_used": tx_metrics["gas_used"],
            "tx_build_seconds": tx_metrics["tx_build_seconds"],
            "submitter_tx_sign_seconds": tx_metrics["submitter_tx_sign_seconds"],
            "send_and_confirm_seconds": tx_metrics["send_and_confirm_seconds"],
            "raw_tx_size_bytes": tx_metrics["raw_tx_size_bytes"],
        },
        "notes": [
            "This mode verifies a Groth16/SNARK-wrapped RISC Zero/STARK proof on-chain.",
            "This is not pure STARK on-chain verification.",
            "SUBMITTER_PRIVATE_KEY signs only the Ethereum transaction and pays gas.",
        ],
    }
    output_path = write_result("stark_wrapped_onchain_result.json", result)
    print(json.dumps(result, indent=2))
    print(f"Result written to {output_path}")


if __name__ == "__main__":
    main()
