"""Run the ecdsa_onchain application authorization benchmark mode."""

from __future__ import annotations

import argparse
import json
import time

from common import (
    DEFAULT_ABI_PATH,
    build_nonce,
    build_web3,
    load_abi,
    load_dotenv,
    optional_env_int,
    payload_hash_hex,
    require_app_auth_private_key,
    require_env,
    send_contract_transaction,
    sign_ecdsa_authorization,
    write_result,
)


DEFAULT_PAYLOAD = {
    "action": "transfer",
    "resource": "application-auth-benchmark",
    "amount": 1,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sign an application authorization digest and verify it on-chain with ecrecover."
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
    gas_limit = optional_env_int("TX_GAS_LIMIT", 1_000_000)

    w3 = build_web3(rpc_url)
    contract = w3.eth.contract(address=w3.to_checksum_address(contract_address), abi=load_abi(abi_path))

    payload = args.payload.encode("utf-8")
    payload_hash = payload_hash_hex(w3, payload)
    nonce = args.nonce if args.nonce is not None else build_nonce()
    chain_id = w3.eth.chain_id

    sign_start = time.perf_counter()
    authorization = sign_ecdsa_authorization(
        app_auth_private_key=app_auth_private_key,
        payload_hash=payload_hash,
        nonce=nonce,
        chain_id=chain_id,
        contract_address=contract_address,
    )
    ecdsa_sign_seconds = time.perf_counter() - sign_start

    tx_metrics = send_contract_transaction(
        w3=w3,
        function_call=contract.functions.submitWithECDSA(
            payload,
            payload_hash,
            authorization["app_address"],
            nonce,
            authorization["signature"],
        ),
        submitter_private_key=submitter_private_key,
        gas=gas_limit,
        timeout_seconds=timeout_seconds,
    )

    result = {
        "mode": "ecdsa_onchain",
        "domain": "ECDSA_APP_AUTH_V1",
        "chain_id": chain_id,
        "contract_address": w3.to_checksum_address(contract_address),
        "payload": args.payload,
        "payload_hash": payload_hash,
        "nonce": nonce,
        "app_address": authorization["app_address"],
        "ecdsa_digest": authorization["ecdsa_digest"],
        "eth_signed_digest": authorization["eth_signed_digest"],
        "signature": authorization["signature"],
        "tx_hash": tx_metrics["tx_hash"],
        "gas_used": tx_metrics["gas_used"],
        "status": tx_metrics["status"],
        "benchmark": {
            "ecdsa_sign_seconds": round(ecdsa_sign_seconds, 6),
            "signature_size_bytes": authorization["signature_size_bytes"],
            "ecdsa_verify_gas_used": tx_metrics["gas_used"],
            "total_tx_gas_used": tx_metrics["gas_used"],
            "tx_build_seconds": tx_metrics["tx_build_seconds"],
            "submitter_tx_sign_seconds": tx_metrics["submitter_tx_sign_seconds"],
            "send_and_confirm_seconds": tx_metrics["send_and_confirm_seconds"],
            "raw_tx_size_bytes": tx_metrics["raw_tx_size_bytes"],
        },
        "notes": [
            "APP_AUTH_PRIVATE_KEY signs only the application authorization digest.",
            "SUBMITTER_PRIVATE_KEY signs the Ethereum transaction and pays gas.",
        ],
    }
    output_path = write_result("ecdsa_onchain_result.json", result)
    print(json.dumps(result, indent=2))
    print(f"Result written to {output_path}")


if __name__ == "__main__":
    main()
