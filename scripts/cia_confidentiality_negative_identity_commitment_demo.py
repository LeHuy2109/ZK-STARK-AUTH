"""Run a negative CIA Confidentiality scenario by tampering identity_commitment at verify time."""

from __future__ import annotations

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
    require_app_auth_private_key,
    require_env,
    verify_risc0_auth,
    write_result,
)


DEFAULT_PAYLOAD = {
    "action": "transfer",
    "resource": "cia-confidentiality-negative-identity-commitment",
    "amount": 1,
}


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
                "status": "FAIL_EXPECTED",
                "reason": str(exc),
                "metadata_path": str(metadata_path),
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


def tamper_identity_commitment(identity_commitment: str) -> str:
    raw = bytearray(bytes.fromhex(identity_commitment[2:]))
    raw[-1] ^= 0x01
    return "0x" + raw.hex()


def main() -> None:
    load_dotenv()

    app_auth_private_key = require_app_auth_private_key()
    contract_address = require_env("CONTRACT_ADDRESS")
    rpc_url = require_env("RPC_URL")

    w3 = build_web3(rpc_url)
    chain_id = w3.eth.chain_id
    payload = json.dumps(DEFAULT_PAYLOAD, separators=(",", ":")).encode("utf-8")
    payload_hash = payload_hash_hex(w3, payload)
    nonce = build_nonce()
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
    receipt_path = results_dir / "cia_confidentiality_negative_identity_commitment_receipt.bin"
    metadata_path = results_dir / "cia_confidentiality_negative_identity_commitment_metadata.json"
    negative_verify_metadata_path = (
        results_dir / "cia_confidentiality_negative_identity_commitment_verify_metadata.json"
    )

    prove_risc0_auth(
        payload_hash=payload_hash,
        app_auth_private_key=app_auth_private_key,
        nonce=nonce,
        chain_id=chain_id,
        contract_address=contract_address,
        receipt_path=receipt_path,
        metadata_path=metadata_path,
        domain=STARK_DOMAIN,
    )

    tampered_identity_commitment = tamper_identity_commitment(identity_commitment)
    negative_case, _ = verify_case(
        receipt_path=receipt_path,
        domain=STARK_DOMAIN,
        payload_hash=payload_hash,
        identity_commitment=tampered_identity_commitment,
        authorization_digest=authorization_digest,
        nonce=nonce,
        chain_id=chain_id,
        contract_address=contract_address,
        metadata_path=negative_verify_metadata_path,
    )
    if negative_case["verified"]:
        negative_case["status"] = "FAIL"
        negative_case["reason"] = "receipt unexpectedly verified after tampering identity_commitment"

    reason = negative_case["reason"]
    if negative_case["verified"]:
        reason = "receipt unexpectedly verified after tampering identity_commitment"

    result: dict[str, Any] = {
        "reason": reason,
    }

    output_path = write_result(
        "cia_confidentiality_negative_identity_commitment_result.json",
        result,
    )
    print(json.dumps(result, indent=2))
    print(f"Result written to {output_path}")


if __name__ == "__main__":
    main()
