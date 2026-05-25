"""Compare the three application authorization benchmark result files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULT_FILES = {
    "ecdsa_onchain": RESULTS_DIR / "ecdsa_onchain_result.json",
    "stark_offchain": RESULTS_DIR / "stark_offchain_result.json",
    "stark_wrapped_onchain": RESULTS_DIR / "stark_wrapped_onchain_result.json",
}
OUTPUT_JSON = RESULTS_DIR / "comparison.json"
OUTPUT_MD = RESULTS_DIR / "comparison.md"


def load_optional(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def metric(result: dict[str, Any] | None, key: str) -> Any:
    if not result:
        return None
    return result.get("benchmark", {}).get(key)


def result_value(result: dict[str, Any] | None, key: str) -> Any:
    if not result:
        return None
    return result.get(key)


def nested_value(result: dict[str, Any] | None, *keys: str) -> Any:
    value: Any = result
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def tx_status(result: dict[str, Any] | None) -> str:
    status = result_value(result, "status")
    if status == 1:
        return "success"
    if status == 0:
        return "failed"
    if result is None:
        return "missing"
    return "not_applicable"


def ratio(numerator: Any, denominator: Any) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def build_comparison(results: dict[str, dict[str, Any] | None]) -> dict[str, Any]:
    ecdsa_gas = metric(results["ecdsa_onchain"], "ecdsa_verify_gas_used")
    wrapped_gas = metric(results["stark_wrapped_onchain"], "wrapped_verify_gas_used")
    ecdsa_raw_tx = metric(results["ecdsa_onchain"], "raw_tx_size_bytes")
    wrapped_raw_tx = metric(results["stark_wrapped_onchain"], "raw_tx_size_bytes")
    ecdsa_sig_size = metric(results["ecdsa_onchain"], "signature_size_bytes")
    wrapped_proof_size = metric(results["stark_wrapped_onchain"], "wrapped_proof_size_bytes")
    stark_receipt_size = metric(results["stark_offchain"], "proof_size_bytes")
    wrapped_receipt_size = nested_value(
        results["stark_wrapped_onchain"], "risc0_verify_metadata", "receipt_size_bytes"
    )

    return {
        "scope": "application authorization benchmark",
        "warning": (
            "Do not compare Ethereum native transaction signatures against STARK proofs. "
            "SUBMITTER_PRIVATE_KEY is only for transaction submission and gas payment."
        ),
        "mode_semantics": {
            "ecdsa_onchain": {
                "authorization_secret": "APP_AUTH_PRIVATE_KEY as secp256k1 private key",
                "proof_or_signature": "65-byte ECDSA r/s/v signature",
                "where_authorization_is_verified": "on-chain Solidity ecrecover",
                "benchmark_role": "fair on-chain verifier baseline",
            },
            "stark_offchain": {
                "authorization_secret": "APP_AUTH_PRIVATE_KEY as private RISC Zero witness",
                "proof_or_signature": "RISC Zero/STARK receipt",
                "where_authorization_is_verified": "off-chain only",
                "benchmark_role": "off-chain feasibility only",
            },
            "stark_wrapped_onchain": {
                "authorization_secret": "APP_AUTH_PRIVATE_KEY as private RISC Zero witness",
                "proof_or_signature": "Groth16/SNARK-wrapped RISC Zero seal",
                "where_authorization_is_verified": "on-chain wrapped proof verifier",
                "benchmark_role": "fair on-chain verifier candidate",
            },
        },
        "execution_status": {
            "ecdsa_onchain": {
                "result_file_present": results["ecdsa_onchain"] is not None,
                "tx_status": tx_status(results["ecdsa_onchain"]),
                "tx_hash": result_value(results["ecdsa_onchain"], "tx_hash"),
            },
            "stark_offchain": {
                "result_file_present": results["stark_offchain"] is not None,
                "receipt_verified_offchain": results["stark_offchain"] is not None,
                "metadata_tx_status": tx_status(nested_value(results["stark_offchain"], "metadata_tx")),
                "proof_hash": result_value(results["stark_offchain"], "proof_hash"),
            },
            "stark_wrapped_onchain": {
                "result_file_present": results["stark_wrapped_onchain"] is not None,
                "tx_status": tx_status(results["stark_wrapped_onchain"]),
                "tx_hash": result_value(results["stark_wrapped_onchain"], "tx_hash"),
            },
        },
        "authorization_binding": {
            "bound_fields": [
                "domain",
                "identity",
                "payload_hash",
                "nonce",
                "chain_id",
                "contract_address",
            ],
            "ecdsa_identity": "Ethereum-style address derived from APP_AUTH_PRIVATE_KEY",
            "stark_identity": "SHA-256 identity_commitment derived from APP_AUTH_PRIVATE_KEY",
            "shared_payload_hash": result_value(results["ecdsa_onchain"], "payload_hash"),
            "chain_id": result_value(results["ecdsa_onchain"], "chain_id"),
            "contract_address": result_value(results["ecdsa_onchain"], "contract_address"),
        },
        "offchain_cost": {
            "ecdsa_onchain": {
                "ecdsa_sign_seconds": metric(results["ecdsa_onchain"], "ecdsa_sign_seconds"),
                "signature_size_bytes": metric(results["ecdsa_onchain"], "signature_size_bytes"),
            },
            "stark_offchain": {
                "stark_prove_seconds": metric(results["stark_offchain"], "stark_prove_seconds"),
                "stark_verify_seconds": metric(results["stark_offchain"], "stark_verify_seconds"),
                "proof_size_bytes": metric(results["stark_offchain"], "proof_size_bytes"),
            },
            "stark_wrapped_onchain": {
                "status": "pending_milestone_2" if results["stark_wrapped_onchain"] is None else "available",
                "stark_prove_seconds": metric(results["stark_wrapped_onchain"], "stark_prove_seconds"),
                "stark_verify_seconds": metric(results["stark_wrapped_onchain"], "stark_verify_seconds"),
                "wrap_seconds": metric(results["stark_wrapped_onchain"], "wrap_seconds"),
                "wrapped_proof_size_bytes": metric(
                    results["stark_wrapped_onchain"], "wrapped_proof_size_bytes"
                ),
            },
        },
        "artifact_sizes": {
            "ecdsa_onchain": {
                "signature_size_bytes": ecdsa_sig_size,
                "raw_tx_size_bytes": ecdsa_raw_tx,
            },
            "stark_offchain": {
                "stark_receipt_size_bytes": stark_receipt_size,
                "journal_size_bytes": metric(results["stark_offchain"], "journal_size_bytes"),
                "public_input_size_bytes": metric(results["stark_offchain"], "public_input_size_bytes"),
            },
            "stark_wrapped_onchain": {
                "base_receipt_size_bytes": nested_value(
                    results["stark_wrapped_onchain"], "risc0_prove_metadata", "receipt_size_bytes"
                ),
                "wrapped_receipt_size_bytes": wrapped_receipt_size,
                "wrapped_evm_seal_size_bytes": wrapped_proof_size,
                "wrapped_raw_seal_size_bytes": nested_value(
                    results["stark_wrapped_onchain"],
                    "risc0_prove_metadata",
                    "wrapped_raw_proof_size_bytes",
                ),
                "raw_tx_size_bytes": wrapped_raw_tx,
                "journal_size_bytes": metric(results["stark_wrapped_onchain"], "journal_size_bytes"),
                "public_input_size_bytes": metric(
                    results["stark_wrapped_onchain"], "public_input_size_bytes"
                ),
            },
        },
        "onchain_verifier_comparison": {
            "eligible_modes": ["ecdsa_onchain", "stark_wrapped_onchain"],
            "excluded_modes": {
                "stark_offchain": "off-chain feasibility only; on-chain proofHash/proofCid is metadata only"
            },
            "ecdsa_onchain": {
                "ecdsa_verify_gas_used": metric(results["ecdsa_onchain"], "ecdsa_verify_gas_used"),
                "total_tx_gas_used": metric(results["ecdsa_onchain"], "total_tx_gas_used"),
            },
            "stark_wrapped_onchain": {
                "status": "pending_milestone_2" if results["stark_wrapped_onchain"] is None else "available",
                "wrapped_verify_gas_used": metric(
                    results["stark_wrapped_onchain"], "wrapped_verify_gas_used"
                ),
                "total_tx_gas_used": metric(results["stark_wrapped_onchain"], "total_tx_gas_used"),
            },
        },
        "onchain_ratios": {
            "wrapped_gas_over_ecdsa_gas": ratio(wrapped_gas, ecdsa_gas),
            "wrapped_raw_tx_over_ecdsa_raw_tx": ratio(wrapped_raw_tx, ecdsa_raw_tx),
            "wrapped_evm_seal_over_ecdsa_signature": ratio(wrapped_proof_size, ecdsa_sig_size),
            "stark_receipt_over_wrapped_evm_seal": ratio(stark_receipt_size, wrapped_proof_size),
            "wrapped_receipt_over_wrapped_evm_seal": ratio(wrapped_receipt_size, wrapped_proof_size),
        },
        "interpretation": {
            "fair_onchain_winner_by_gas": (
                "ecdsa_onchain"
                if ecdsa_gas is not None and wrapped_gas is not None and ecdsa_gas < wrapped_gas
                else None
            ),
            "stark_offchain_is_not_onchain_verification": True,
            "wrapped_onchain_status": tx_status(results["stark_wrapped_onchain"]),
            "main_takeaway": (
                "ECDSA is cheaper for simple on-chain application authorization. "
                "Wrapped STARK proves private witness knowledge and verifies on-chain, "
                "but pays substantially higher verifier gas and off-chain proving/wrapping cost."
            ),
        },
    }


def render_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    lines.extend("| " + " | ".join(fmt(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def render_markdown(comparison: dict[str, Any]) -> str:
    semantics = comparison["mode_semantics"]
    status = comparison["execution_status"]
    binding = comparison["authorization_binding"]
    offchain = comparison["offchain_cost"]
    artifacts = comparison["artifact_sizes"]
    onchain = comparison["onchain_verifier_comparison"]
    ratios = comparison["onchain_ratios"]
    interpretation = comparison["interpretation"]
    lines = [
        "# Application Authorization Benchmark Comparison",
        "",
        "This benchmark compares application-level authorization only. Ethereum transaction signing is separate and uses `SUBMITTER_PRIVATE_KEY` only for transaction submission and gas payment.",
        "",
        "## Mode Semantics",
        "",
        render_table(
            ["Mode", "Secret Role", "Credential", "Verification Location", "Benchmark Role"],
            [
                [
                    "ecdsa_onchain",
                    semantics["ecdsa_onchain"]["authorization_secret"],
                    semantics["ecdsa_onchain"]["proof_or_signature"],
                    semantics["ecdsa_onchain"]["where_authorization_is_verified"],
                    semantics["ecdsa_onchain"]["benchmark_role"],
                ],
                [
                    "stark_offchain",
                    semantics["stark_offchain"]["authorization_secret"],
                    semantics["stark_offchain"]["proof_or_signature"],
                    semantics["stark_offchain"]["where_authorization_is_verified"],
                    semantics["stark_offchain"]["benchmark_role"],
                ],
                [
                    "stark_wrapped_onchain",
                    semantics["stark_wrapped_onchain"]["authorization_secret"],
                    semantics["stark_wrapped_onchain"]["proof_or_signature"],
                    semantics["stark_wrapped_onchain"]["where_authorization_is_verified"],
                    semantics["stark_wrapped_onchain"]["benchmark_role"],
                ],
            ],
        ),
        "",
        "## Execution Status",
        "",
        render_table(
            ["Mode", "Result Present", "Status", "Primary Hash"],
            [
                [
                    "ecdsa_onchain",
                    status["ecdsa_onchain"]["result_file_present"],
                    status["ecdsa_onchain"]["tx_status"],
                    status["ecdsa_onchain"]["tx_hash"],
                ],
                [
                    "stark_offchain",
                    status["stark_offchain"]["result_file_present"],
                    "offchain_verified",
                    status["stark_offchain"]["proof_hash"],
                ],
                [
                    "stark_wrapped_onchain",
                    status["stark_wrapped_onchain"]["result_file_present"],
                    status["stark_wrapped_onchain"]["tx_status"],
                    status["stark_wrapped_onchain"]["tx_hash"],
                ],
            ],
        ),
        "",
        "## Authorization Binding",
        "",
        render_table(
            ["Criterion", "Value"],
            [
                ["Bound fields", ", ".join(binding["bound_fields"])],
                ["ECDSA identity", binding["ecdsa_identity"]],
                ["STARK identity", binding["stark_identity"]],
                ["Shared payload hash", binding["shared_payload_hash"]],
                ["Chain ID", binding["chain_id"]],
                ["Contract address", binding["contract_address"]],
            ],
        ),
        "",
        "## Off-chain Cost",
        "",
        render_table(
            ["Mode", "Sign/Prove (s)", "Verify (s)", "Wrap (s)", "Auth/Proof Bytes"],
            [
                [
                    "ecdsa_onchain",
                    offchain["ecdsa_onchain"]["ecdsa_sign_seconds"],
                    "-",
                    "-",
                    offchain["ecdsa_onchain"]["signature_size_bytes"],
                ],
                [
                    "stark_offchain",
                    offchain["stark_offchain"]["stark_prove_seconds"],
                    offchain["stark_offchain"]["stark_verify_seconds"],
                    "-",
                    offchain["stark_offchain"]["proof_size_bytes"],
                ],
                [
                    "stark_wrapped_onchain",
                    offchain["stark_wrapped_onchain"]["stark_prove_seconds"],
                    offchain["stark_wrapped_onchain"]["stark_verify_seconds"],
                    offchain["stark_wrapped_onchain"]["wrap_seconds"],
                    offchain["stark_wrapped_onchain"]["wrapped_proof_size_bytes"],
                ],
            ],
        ),
        "",
        "## Artifact And Transaction Sizes",
        "",
        render_table(
            [
                "Mode",
                "Signature/Seal Bytes",
                "Receipt Bytes",
                "Raw Tx Bytes",
                "Journal Bytes",
                "Public Input Bytes",
            ],
            [
                [
                    "ecdsa_onchain",
                    artifacts["ecdsa_onchain"]["signature_size_bytes"],
                    "-",
                    artifacts["ecdsa_onchain"]["raw_tx_size_bytes"],
                    "-",
                    "-",
                ],
                [
                    "stark_offchain",
                    "-",
                    artifacts["stark_offchain"]["stark_receipt_size_bytes"],
                    "-",
                    artifacts["stark_offchain"]["journal_size_bytes"],
                    artifacts["stark_offchain"]["public_input_size_bytes"],
                ],
                [
                    "stark_wrapped_onchain",
                    artifacts["stark_wrapped_onchain"]["wrapped_evm_seal_size_bytes"],
                    artifacts["stark_wrapped_onchain"]["wrapped_receipt_size_bytes"],
                    artifacts["stark_wrapped_onchain"]["raw_tx_size_bytes"],
                    artifacts["stark_wrapped_onchain"]["journal_size_bytes"],
                    artifacts["stark_wrapped_onchain"]["public_input_size_bytes"],
                ],
            ],
        ),
        "",
        "## On-chain Applicability",
        "",
        "Fair on-chain verifier comparison is only `ecdsa_onchain` vs `stark_wrapped_onchain`. `stark_offchain` is off-chain feasibility only; metadata gas is not proof verification gas.",
        "",
        render_table(
            ["Mode", "Verifier Gas", "Total Tx Gas", "Status"],
            [
                [
                    "ecdsa_onchain",
                    onchain["ecdsa_onchain"]["ecdsa_verify_gas_used"],
                    onchain["ecdsa_onchain"]["total_tx_gas_used"],
                    "available",
                ],
                [
                    "stark_wrapped_onchain",
                    onchain["stark_wrapped_onchain"]["wrapped_verify_gas_used"],
                    onchain["stark_wrapped_onchain"]["total_tx_gas_used"],
                    onchain["stark_wrapped_onchain"]["status"],
                ],
            ],
        ),
        "",
        "## Ratios",
        "",
        render_table(
            ["Metric", "Ratio"],
            [
                ["Wrapped gas / ECDSA gas", ratios["wrapped_gas_over_ecdsa_gas"]],
                ["Wrapped raw tx bytes / ECDSA raw tx bytes", ratios["wrapped_raw_tx_over_ecdsa_raw_tx"]],
                [
                    "Wrapped EVM seal bytes / ECDSA signature bytes",
                    ratios["wrapped_evm_seal_over_ecdsa_signature"],
                ],
                ["STARK receipt bytes / wrapped EVM seal bytes", ratios["stark_receipt_over_wrapped_evm_seal"]],
                [
                    "Wrapped receipt bytes / wrapped EVM seal bytes",
                    ratios["wrapped_receipt_over_wrapped_evm_seal"],
                ],
            ],
        ),
        "",
        "## Assessment",
        "",
        render_table(
            ["Criterion", "Assessment"],
            [
                ["Fair on-chain gas winner", interpretation["fair_onchain_winner_by_gas"]],
                ["Wrapped on-chain status", interpretation["wrapped_onchain_status"]],
                [
                    "stark_offchain comparability",
                    "off-chain feasibility only; do not compare metadata gas against verifier gas",
                ],
                ["Main takeaway", interpretation["main_takeaway"]],
            ],
        ),
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results = {mode: load_optional(path) for mode, path in RESULT_FILES.items()}
    comparison = build_comparison(results)
    OUTPUT_JSON.write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    OUTPUT_MD.write_text(render_markdown(comparison), encoding="utf-8")
    print(json.dumps(comparison, indent=2))
    print(f"Comparison written to {OUTPUT_JSON} and {OUTPUT_MD}")


if __name__ == "__main__":
    main()
