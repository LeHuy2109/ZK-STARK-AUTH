"""Run the CIA Confidentiality scenario for ZK-STARK-AUTH.

This script proves that APP_AUTH_PRIVATE_KEY is used as a private RISC Zero
witness for STARK authorization. The secret is never printed or written to the
result JSON; only public commitments, digests, receipt hash, and timing/size
metrics are emitted.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from common import (
    STARK_DOMAIN,
    build_nonce,
    build_web3,
    compute_stark_authorization_digest_hex,
    derive_identity_commitment,
    ensure_results_dir,
    load_dotenv,
    payload_hash_hex,
    prove_risc0_auth,
    public_input_size_bytes,
    receipt_hash_hex,
    require_app_auth_private_key,
    require_env,
    verify_risc0_auth,
    write_result,
)


DEFAULT_PAYLOAD = {
    "action": "transfer",
    "resource": "cia-confidentiality",
    "amount": 1,
}
WRONG_SECRET = "0x" + ("11" * 32)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and verify an off-chain STARK/RISC Zero proof without exposing the app secret."
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
        "--negative-wrong-secret",
        action="store_true",
        help="Also verify the receipt against a wrong public identity commitment.",
    )
    return parser.parse_args()


def verify_case(
    *,
    receipt_path: Path,
    domain: str,
    payload_hash: str,
    identity_commitment: str,
    authorization_digest: str,
    nonce: int,
    chain_id: int,
    contract_address: str,
    metadata_path: Path,
) -> tuple[dict[str, Any], float]:
    start = time.perf_counter()
    try:
        verify_metadata, elapsed = verify_risc0_auth(
            receipt_path=receipt_path,
            domain=domain,
            payload_hash=payload_hash,
            identity_commitment=identity_commitment,
            authorization_digest=authorization_digest,
            nonce=nonce,
            chain_id=chain_id,
            contract_address=contract_address,
            metadata_path=metadata_path,
        )
    except Exception as exc:
        return (
            {
                "verified": False,
                "status": "FAIL",
                "reason": str(exc),
            },
            time.perf_counter() - start,
        )

    return (
        {
            "verified": True,
            "status": "PASS",
            "metadata_path": str(metadata_path),
            "receipt_sha256": None if verify_metadata is None else verify_metadata.get("receipt_sha256"),
        },
        elapsed,
    )


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
    receipt_path = results_dir / "cia_confidentiality_receipt.bin"
    metadata_path = results_dir / "cia_confidentiality_metadata.json"
    verify_metadata_path = results_dir / "cia_confidentiality_verify_metadata.json"

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
    positive_case, stark_verify_seconds = verify_case(
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

    result: dict[str, Any] = {
        "scenario": "confidentiality",
        "mode": "stark_offchain",
        "confidentiality_claim": (
            "APP_AUTH_PRIVATE_KEY is used as private witness and is not written to public output"
        ),
        "secret_exposed": False,
        "payload": args.payload,
        "payload_hash": payload_hash,
        "nonce": nonce,
        "chain_id": chain_id,
        "contract_address": w3.to_checksum_address(contract_address),
        "identity_commitment": identity_commitment,
        "authorization_digest": authorization_digest,
        "proof_hash": proof_hash,
        "receipt_path": str(receipt_path),
        "positive_case": positive_case,
        "benchmark": {
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
        },
    }

    if args.negative_wrong_secret:
        wrong_identity_commitment = derive_identity_commitment(WRONG_SECRET)
        wrong_authorization_digest = compute_stark_authorization_digest_hex(
            domain=STARK_DOMAIN,
            payload_hash=payload_hash,
            identity_commitment=wrong_identity_commitment,
            nonce=nonce,
            chain_id=chain_id,
            contract_address=contract_address,
        )
        negative_case, negative_verify_seconds = verify_case(
            receipt_path=receipt_path,
            domain=STARK_DOMAIN,
            payload_hash=payload_hash,
            identity_commitment=wrong_identity_commitment,
            authorization_digest=wrong_authorization_digest,
            nonce=nonce,
            chain_id=chain_id,
            contract_address=contract_address,
            metadata_path=results_dir / "cia_confidentiality_wrong_secret_verify_metadata.json",
        )
        if negative_case["verified"]:
            negative_case["status"] = "FAIL"
            negative_case["reason"] = "receipt unexpectedly verified with wrong public input"
        else:
            negative_case["status"] = "FAIL_EXPECTED"
        negative_case["verify_seconds"] = round(negative_verify_seconds, 6)
        result["negative_wrong_secret_case"] = negative_case

    output_path = write_result("cia_confidentiality_result.json", result)
    print(json.dumps(result, indent=2))
    print(f"Result written to {output_path}")


if __name__ == "__main__":
    main()
