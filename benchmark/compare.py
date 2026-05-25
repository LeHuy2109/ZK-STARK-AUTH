"""Compare benchmark outputs from traditional and STARK off-chain demo runs."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt


RESULTS_DIR = Path(__file__).resolve().parent / "results"
TRADITIONAL_RESULT = RESULTS_DIR / "traditional_result.json"
STARK_RESULT = RESULTS_DIR / "stark_result.json"
OUTPUT_PLOT = RESULTS_DIR / "comparison.png"


def load_result(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing result file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def print_summary(traditional: dict, stark: dict) -> None:
    print("Comparison Summary")
    print(f"Traditional tx hash: {traditional['tx_hash']}")
    print(f"STARK off-chain tx hash: {stark['tx_hash']}")
    print(f"Traditional gas used: {traditional['gas_used']}")
    print(f"STARK off-chain gas used: {stark['gas_used']}")
    print(f"Traditional ECDSA signing time: {traditional['benchmark']['ecdsa_sign_seconds']} s")
    print(f"STARK prove time: {stark['benchmark']['risc0_prove_seconds']} s")
    print(f"STARK verify time: {stark['benchmark']['risc0_verify_seconds']} s")
    print(f"RISC Zero receipt size: {stark['stark']['receipt_size_bytes']} bytes")
    print("RISC Zero receipt verification is off-chain in this version.")
    print("Ethereum transaction submission still uses a normal ECDSA account.")


def save_plot(traditional: dict, stark: dict) -> Path:
    labels = [
        "ECDSA sign",
        "Send+confirm",
        "Gas used",
        "Auth bytes",
    ]
    traditional_values = [
        traditional["benchmark"]["ecdsa_sign_seconds"],
        traditional["benchmark"]["send_and_confirm_seconds"],
        traditional["gas_used"],
        traditional["benchmark"]["signature_size_bytes"],
    ]
    stark_values = [
        stark["benchmark"]["risc0_prove_seconds"] + stark["benchmark"]["risc0_verify_seconds"],
        stark["benchmark"]["send_and_confirm_seconds"],
        stark["gas_used"],
        stark["stark"]["receipt_size_bytes"],
    ]

    x_positions = range(len(labels))
    width = 0.35

    plt.figure(figsize=(10, 6))
    plt.bar([x - width / 2 for x in x_positions], traditional_values, width=width, label="Traditional")
    plt.bar([x + width / 2 for x in x_positions], stark_values, width=width, label="STARK off-chain")
    plt.xticks(list(x_positions), labels)
    plt.ylabel("Value")
    plt.title("Traditional ECDSA-only vs RISC Zero STARK off-chain")
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUTPUT_PLOT)
    plt.close()
    return OUTPUT_PLOT


def main() -> None:
    traditional = load_result(TRADITIONAL_RESULT)
    stark = load_result(STARK_RESULT)
    print_summary(traditional, stark)
    plot_path = save_plot(traditional, stark)
    print(f"Plot saved to: {plot_path}")


if __name__ == "__main__":
    main()
