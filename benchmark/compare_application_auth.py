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


def build_comparison(results: dict[str, dict[str, Any] | None]) -> dict[str, Any]:
    return {
        "scope": "application authorization benchmark",
        "warning": (
            "Do not compare Ethereum native transaction signatures against STARK proofs. "
            "SUBMITTER_PRIVATE_KEY is only for transaction submission and gas payment."
        ),
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
    }


def render_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    lines.extend("| " + " | ".join(fmt(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def render_markdown(comparison: dict[str, Any]) -> str:
    offchain = comparison["offchain_cost"]
    onchain = comparison["onchain_verifier_comparison"]
    lines = [
        "# Application Authorization Benchmark Comparison",
        "",
        "This benchmark compares application-level authorization only. Ethereum transaction signing is separate and uses `SUBMITTER_PRIVATE_KEY` only for transaction submission and gas payment.",
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
