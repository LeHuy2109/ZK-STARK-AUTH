"""Run the CIA Integrity scenario for ZK-STARK-AUTH.

This script uses the stark_wrapped_onchain mode to show that the contract
accepts the original payload plus wrapped proof, rejects a tampered payload
bound to the original payload hash, and rejects replay of an already consumed
authorization nonce.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from eth_account import Account

from common import (
    DEFAULT_ABI_PATH,
    PROJECT_ROOT,
    STARK_WRAPPED_DOMAIN,
    build_nonce,
    build_tx_options,
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
    raw_transaction_bytes,
    require_app_auth_private_key,
    require_env,
    send_contract_transaction,
    verify_risc0_auth,
    write_result,
)


DEFAULT_PAYLOAD = {
    "action": "transfer",
    "resource": "cia-integrity",
    "amount": 1,
}
DEFAULT_TAMPERED_PAYLOAD = {
    "action": "transfer",
    "resource": "cia-integrity",
    "amount": 999,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Exercise integrity checks with wrapped STARK on-chain verification."
    )
    parser.add_argument(
        "--payload",
        default=json.dumps(DEFAULT_PAYLOAD, separators=(",", ":")),
        help="Original UTF-8 payload bytes to authorize.",
    )
    parser.add_argument(
        "--tampered-payload",
        default=json.dumps(DEFAULT_TAMPERED_PAYLOAD, separators=(",", ":")),
        help="Tampered UTF-8 payload bytes for the negative case.",
    )
    parser.add_argument("--nonce", type=int, default=None, help="Authorization nonce.")
    parser.add_argument(
        "--skip-positive",
        action="store_true",
        help="Build and verify the proof, but do not first submit the positive transaction.",
    )
    parser.add_argument(
        "--gas-limit",
        type=int,
        default=2_000_000,
        help="Gas limit for positive and expected-revert transactions.",
    )
    return parser.parse_args()


def send_expected_revert_transaction(
    *,
    w3: Any,
    function_call: Any,
    submitter_private_key: str,
    gas: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Send a real transaction and classify receipt status without eth_call."""
    account = Account.from_key(submitter_private_key)
    try:
        tx_build_start = time.perf_counter()
        tx = function_call.build_transaction(
            build_tx_options(w3, account.address, w3.eth.get_transaction_count(account.address), gas)
        )
        tx_build_seconds = time.perf_counter() - tx_build_start

        tx_sign_start = time.perf_counter()
        signed_tx = account.sign_transaction(tx)
        submitter_tx_sign_seconds = time.perf_counter() - tx_sign_start
        raw_tx = raw_transaction_bytes(signed_tx)

        send_start = time.perf_counter()
        tx_hash = w3.eth.send_raw_transaction(raw_tx)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout_seconds)
        send_and_confirm_seconds = time.perf_counter() - send_start
        receipt_status = receipt["status"]

        return {
            "accepted": receipt_status == 1,
            "reverted": receipt_status == 0,
            "tx_hash": w3.to_hex(tx_hash),
            "gas_used": receipt["gasUsed"],
            "receipt_status": receipt_status,
            "tx_build_seconds": round(tx_build_seconds, 6),
            "submitter_tx_sign_seconds": round(submitter_tx_sign_seconds, 6),
            "send_and_confirm_seconds": round(send_and_confirm_seconds, 6),
            "raw_tx_size_bytes": len(raw_tx),
        }
    except Exception as exc:
        return {
            "accepted": False,
            "reverted": True,
            "error": str(exc),
        }


def expected_rejection_case(
    *,
    name: str,
    expected_reason: str,
    tx_result: dict[str, Any],
    nonce: int,
) -> dict[str, Any]:
    return {
        "case": name,
        "expected_reject_reason": expected_reason,
        "nonce": nonce,
        "accepted": tx_result.get("accepted", False),
        "reverted": tx_result.get("reverted", False),
        "status": "FAIL" if tx_result.get("accepted") else "PASS",
        **tx_result,
    }


def resolve_artifact_path(path_value: str) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def main() -> None:
    args = parse_args()
    load_dotenv()

    rpc_url = require_env("RPC_URL")
    submitter_private_key = require_env("SUBMITTER_PRIVATE_KEY")
    contract_address = require_env("CONTRACT_ADDRESS")
    app_auth_private_key = require_app_auth_private_key()
    abi_path = require_env("CONTRACT_ABI_PATH", str(DEFAULT_ABI_PATH))
    timeout_seconds = optional_env_int("TX_TIMEOUT_SECONDS", 120)

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
    receipt_path = results_dir / "cia_integrity_base_receipt.bin"
    wrapped_receipt_path = results_dir / "cia_integrity_groth16_receipt.bin"
    metadata_path = results_dir / "cia_integrity_metadata.json"
    verify_metadata_path = results_dir / "cia_integrity_verify_metadata.json"

    prove_metadata, stark_prove_and_wrap_seconds = prove_risc0_auth(
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
    verify_metadata, stark_verify_seconds = verify_risc0_auth(
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

    wrapped_proof = resolve_artifact_path(prove_metadata["wrapped_proof_path"]).read_bytes()
    image_id = prove_metadata["image_id"]
    journal_digest = prove_metadata["journal_digest"]

    positive_case: dict[str, Any]
    positive_gas_used = None
    raw_tx_size_bytes = None
    positive_accepted = False
    if args.skip_positive:
        positive_case = {
            "skipped": True,
            "accepted": False,
            "status": "SKIPPED",
            "reason": "--skip-positive was set",
        }
    else:
        tx_metrics = send_contract_transaction(
            w3=w3,
            function_call=contract.functions.submitWithWrappedStark(
                payload,
                payload_hash,
                identity_commitment,
                authorization_digest,
                nonce,
                wrapped_proof,
                image_id,
                journal_digest,
            ),
            submitter_private_key=submitter_private_key,
            gas=args.gas_limit,
            timeout_seconds=timeout_seconds,
        )
        positive_accepted = tx_metrics["status"] == 1
        positive_gas_used = tx_metrics["gas_used"]
        raw_tx_size_bytes = tx_metrics["raw_tx_size_bytes"]
        positive_case = {
            "accepted": positive_accepted,
            "status": "PASS" if positive_accepted else "FAIL",
            "tx_hash": tx_metrics["tx_hash"],
            "gas_used": tx_metrics["gas_used"],
            "receipt_status": tx_metrics["status"],
            "raw_tx_size_bytes": tx_metrics["raw_tx_size_bytes"],
        }

    tampered_payload = args.tampered_payload.encode("utf-8")
    tampered_nonce = nonce + 1
    tampered_tx = send_expected_revert_transaction(
        w3=w3,
        function_call=contract.functions.submitWithWrappedStark(
            tampered_payload,
            payload_hash,
            identity_commitment,
            authorization_digest,
            tampered_nonce,
            wrapped_proof,
            image_id,
            journal_digest,
        ),
        submitter_private_key=submitter_private_key,
        gas=args.gas_limit,
        timeout_seconds=timeout_seconds,
    )
    tampered_payload_case = expected_rejection_case(
        name="tampered_payload",
        expected_reason="payload hash mismatch",
        tx_result=tampered_tx,
        nonce=tampered_nonce,
    )
    tampered_payload_case["payload"] = args.tampered_payload

    if positive_accepted or args.skip_positive:
        replay_tx = send_expected_revert_transaction(
            w3=w3,
            function_call=contract.functions.submitWithWrappedStark(
                payload,
                payload_hash,
                identity_commitment,
                authorization_digest,
                nonce,
                wrapped_proof,
                image_id,
                journal_digest,
            ),
            submitter_private_key=submitter_private_key,
            gas=args.gas_limit,
            timeout_seconds=timeout_seconds,
        )
        replay_nonce_case = expected_rejection_case(
            name="replay_nonce",
            expected_reason="stale nonce",
            tx_result=replay_tx,
            nonce=nonce,
        )
        if args.skip_positive:
            replay_nonce_case["precondition"] = (
                "nonce must already be consumed on-chain when --skip-positive is used"
            )
    else:
        replay_nonce_case = {
            "case": "replay_nonce",
            "expected_reject_reason": "stale nonce",
            "nonce": nonce,
            "accepted": False,
            "reverted": False,
            "status": "SKIPPED",
            "reason": "positive case did not consume the nonce",
        }

    result = {
        "scenario": "integrity",
        "mode": "stark_wrapped_onchain",
        "domain": STARK_WRAPPED_DOMAIN,
        "chain_id": chain_id,
        "contract_address": w3.to_checksum_address(contract_address),
        "payload": args.payload,
        "payload_hash": payload_hash,
        "identity_commitment": identity_commitment,
        "authorization_digest": authorization_digest,
        "nonce": nonce,
        "image_id": image_id,
        "journal_digest": journal_digest,
        "positive_case": positive_case,
        "tampered_payload_case": tampered_payload_case,
        "replay_nonce_case": replay_nonce_case,
        "benchmark": {
            "stark_prove_seconds": round(prove_metadata.get("prove_seconds") or 0.0, 6),
            "wrap_seconds": round(prove_metadata.get("wrap_seconds") or 0.0, 6),
            "stark_prove_and_wrap_seconds": round(stark_prove_and_wrap_seconds, 6),
            "stark_verify_seconds": round(stark_verify_seconds, 6),
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
            "positive_gas_used": positive_gas_used,
            "raw_tx_size_bytes": raw_tx_size_bytes,
        },
        "wrapped_receipt_path": str(wrapped_receipt_path),
        "wrapped_proof_path": prove_metadata["wrapped_proof_path"],
        "risc0_verify_receipt_sha256": None
        if verify_metadata is None
        else verify_metadata.get("receipt_sha256"),
    }

    output_path = write_result("cia_integrity_result.json", result)
    print(json.dumps(result, indent=2))
    print(f"Result written to {output_path}")


if __name__ == "__main__":
    main()
