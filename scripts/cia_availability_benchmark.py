"""Run the CIA Availability benchmark for ZK-STARK-AUTH.

This script repeatedly executes the existing benchmark mode scripts by
subprocess, then aggregates success rate, wall-clock latency, gas, proof sizes,
and proving/verifying timings. It intentionally reuses the mode scripts instead
of duplicating their authorization or proof logic.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from common import PROJECT_ROOT, build_nonce, load_dotenv, write_result


MODES = ("ecdsa_onchain", "stark_offchain", "stark_wrapped_onchain")
MODE_SCRIPTS = {
    "ecdsa_onchain": PROJECT_ROOT / "scripts" / "ecdsa_onchain_demo.py",
    "stark_offchain": PROJECT_ROOT / "scripts" / "stark_offchain_demo.py",
    "stark_wrapped_onchain": PROJECT_ROOT / "scripts" / "stark_wrapped_onchain_demo.py",
}
MODE_RESULT_FILES = {
    "ecdsa_onchain": PROJECT_ROOT / "benchmark" / "results" / "ecdsa_onchain_result.json",
    "stark_offchain": PROJECT_ROOT / "benchmark" / "results" / "stark_offchain_result.json",
    "stark_wrapped_onchain": PROJECT_ROOT
    / "benchmark"
    / "results"
    / "stark_wrapped_onchain_result.json",
}
DEFAULT_MODES = ["ecdsa_onchain", "stark_offchain", "stark_wrapped_onchain"]
BENCHMARK_KEYS = {
    "ecdsa_sign_seconds",
    "signature_size_bytes",
    "ecdsa_verify_gas_used",
    "total_tx_gas_used",
    "tx_build_seconds",
    "submitter_tx_sign_seconds",
    "send_and_confirm_seconds",
    "raw_tx_size_bytes",
    "stark_prove_seconds",
    "stark_verify_seconds",
    "proof_size_bytes",
    "journal_size_bytes",
    "public_input_size_bytes",
    "receipt_upload_seconds",
    "metadata_tx_gas_used",
    "wrapped_verify_gas_used",
    "wrap_seconds",
    "stark_prove_and_wrap_seconds",
    "wrapped_proof_size_bytes",
}
TOP_LEVEL_KEYS = (
    "mode",
    "domain",
    "chain_id",
    "contract_address",
    "payload",
    "payload_hash",
    "nonce",
    "tx_hash",
    "gas_used",
    "status",
    "proof_hash",
    "proof_cid",
    "receipt_path",
    "storage_backend",
    "identity_commitment",
    "authorization_digest",
    "image_id",
    "journal_digest",
    "wrapped_proof_path",
    "wrapped_receipt_path",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run repeated availability checks across ZK-STARK-AUTH authorization modes."
    )
    parser.add_argument("--rounds", type=int, default=3, help="Number of rounds per mode.")
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=MODES,
        default=DEFAULT_MODES,
        help="Modes to run.",
    )
    parser.add_argument(
        "--skip-wrapped",
        action="store_true",
        help="Remove stark_wrapped_onchain from the selected modes.",
    )
    parser.add_argument(
        "--nonce-start",
        type=int,
        default=None,
        help="Starting nonce. Defaults to a time-based nonce.",
    )
    parser.add_argument(
        "--payload-resource",
        default="cia-availability",
        help="Resource field used in generated compact JSON payloads.",
    )
    parser.add_argument(
        "--submit-stark-metadata",
        action="store_true",
        help="Pass --submit-metadata to stark_offchain_demo.py.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        default=True,
        help="Continue after failed runs. This is the default behavior.",
    )
    return parser.parse_args()


def compact_payload(*, resource: str, mode: str, round_index: int) -> str:
    return json.dumps(
        {
            "action": "transfer",
            "resource": resource,
            "amount": 1,
            "mode": mode,
            "round": round_index,
        },
        separators=(",", ":"),
    )


def build_command(mode: str, payload: str, nonce: int, submit_stark_metadata: bool) -> list[str]:
    command = [
        sys.executable or "python3",
        str(MODE_SCRIPTS[mode].relative_to(PROJECT_ROOT)),
        "--payload",
        payload,
        "--nonce",
        str(nonce),
    ]
    if mode == "stark_offchain" and submit_stark_metadata:
        command.append("--submit-metadata")
    return command


def redaction_values() -> list[str]:
    values = []
    for name in ("APP_AUTH_PRIVATE_KEY", "SUBMITTER_PRIVATE_KEY"):
        value = os.getenv(name)
        if value:
            values.append(value)
            if value.startswith("0x"):
                values.append(value[2:])
    return values


def redact(text: str, secrets: list[str]) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def tail(text: str, limit: int = 2000) -> str | None:
    if not text:
        return None
    return text[-limit:]


def read_result(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def nonce_matches(value: Any, nonce: int) -> bool:
    try:
        return int(value) == nonce
    except (TypeError, ValueError):
        return False


def result_matches_run(result: dict[str, Any], payload: str, nonce: int) -> bool:
    return result.get("payload") == payload and nonce_matches(result.get("nonce"), nonce)


def extract_result(result: dict[str, Any]) -> dict[str, Any]:
    extracted = {key: result[key] for key in TOP_LEVEL_KEYS if key in result}
    benchmark = result.get("benchmark", {})
    if isinstance(benchmark, dict):
        extracted["benchmark"] = {
            key: benchmark[key]
            for key in BENCHMARK_KEYS
            if key in benchmark and benchmark[key] is not None
        }
    metadata_tx = result.get("metadata_tx")
    if isinstance(metadata_tx, dict):
        extracted["metadata_tx"] = {
            key: metadata_tx[key]
            for key in ("tx_hash", "gas_used", "status", "raw_tx_size_bytes")
            if key in metadata_tx
        }
    return extracted


def mode_result_success(mode: str, result: dict[str, Any] | None) -> bool:
    if result is None:
        return False
    status = result.get("status")
    if status is not None and status != 1:
        return False
    metadata_tx = result.get("metadata_tx")
    if isinstance(metadata_tx, dict) and metadata_tx.get("status") != 1:
        return False
    return True


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 6)
    rank = (len(ordered) - 1) * percent
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 6)


def numeric_metric(entry: dict[str, Any], candidates: tuple[str, ...]) -> float | None:
    result = entry.get("result")
    if not isinstance(result, dict):
        return None
    benchmark = result.get("benchmark")
    if isinstance(benchmark, dict):
        for key in candidates:
            value = benchmark.get(key)
            if isinstance(value, (int, float)):
                return float(value)
    for key in candidates:
        value = result.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def average_metric(entries: list[dict[str, Any]], candidates: tuple[str, ...]) -> float | None:
    values = [
        value
        for entry in entries
        if entry.get("success")
        for value in [numeric_metric(entry, candidates)]
        if value is not None
    ]
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def summarize_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
    wall_times = [entry["wall_clock_seconds"] for entry in entries]
    success_count = sum(1 for entry in entries if entry.get("success"))
    failure_count = len(entries) - success_count
    return {
        "success_count": success_count,
        "failure_count": failure_count,
        "success_rate_percent": round((success_count / len(entries) * 100) if entries else 0.0, 2),
        "average_wall_clock_seconds": round(statistics.fmean(wall_times), 6) if wall_times else None,
        "p50_wall_clock_seconds": percentile(wall_times, 0.50),
        "p95_wall_clock_seconds": percentile(wall_times, 0.95),
        "p99_wall_clock_seconds": percentile(wall_times, 0.99),
        "average_gas_used": average_metric(entries, ("total_tx_gas_used", "gas_used")),
        "average_raw_tx_size_bytes": average_metric(entries, ("raw_tx_size_bytes",)),
        "average_proof_size_bytes": average_metric(
            entries,
            ("proof_size_bytes", "wrapped_proof_size_bytes"),
        ),
        "average_stark_prove_seconds": average_metric(entries, ("stark_prove_seconds",)),
        "average_stark_verify_seconds": average_metric(entries, ("stark_verify_seconds",)),
        "average_wrap_seconds": average_metric(entries, ("wrap_seconds",)),
    }


def build_summary(raw_results: list[dict[str, Any]], modes: list[str]) -> dict[str, Any]:
    summary = {"overall": summarize_entries(raw_results)}
    for mode in modes:
        summary[mode] = summarize_entries(
            [entry for entry in raw_results if entry.get("mode") == mode]
        )
    return summary


def main() -> None:
    args = parse_args()
    load_dotenv()

    if args.rounds < 1:
        raise SystemExit("--rounds must be >= 1")

    modes = list(dict.fromkeys(args.modes))
    if args.skip_wrapped:
        modes = [mode for mode in modes if mode != "stark_wrapped_onchain"]
    if not modes:
        raise SystemExit("No modes selected")

    nonce_start = args.nonce_start if args.nonce_start is not None else build_nonce()
    secrets = redaction_values()
    raw_results: list[dict[str, Any]] = []

    for mode_index, mode in enumerate(modes):
        mode_nonce_offset = mode_index * args.rounds
        for round_index in range(args.rounds):
            payload = compact_payload(
                resource=args.payload_resource,
                mode=mode,
                round_index=round_index,
            )
            nonce = nonce_start + mode_nonce_offset + round_index
            command = build_command(mode, payload, nonce, args.submit_stark_metadata)
            started = time.perf_counter()
            completed = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            wall_clock_seconds = round(time.perf_counter() - started, 6)

            result_path = MODE_RESULT_FILES[mode]
            full_result = None
            extracted_result = None
            error = None
            if completed.returncode == 0:
                try:
                    full_result = read_result(result_path)
                    if full_result is None:
                        error = f"missing result file: {result_path}"
                    elif not result_matches_run(full_result, payload, nonce):
                        error = "result file did not match the requested payload and nonce"
                    else:
                        extracted_result = extract_result(full_result)
                except Exception as exc:
                    error = f"failed to read result file: {exc}"
            else:
                error = f"subprocess exited with {completed.returncode}"

            success = (
                completed.returncode == 0
                and error is None
                and mode_result_success(mode, full_result)
            )
            if error is None and not success:
                error = "mode result reported a failed transaction status"

            entry: dict[str, Any] = {
                "mode": mode,
                "round": round_index,
                "nonce": nonce,
                "payload": payload,
                "command": command,
                "exit_code": completed.returncode,
                "success": success,
                "wall_clock_seconds": wall_clock_seconds,
                "result_file": str(result_path),
            }
            if extracted_result is not None:
                entry["result"] = extracted_result
            if error is not None:
                entry["error"] = error
                entry["stderr_tail"] = tail(redact(completed.stderr, secrets))
                entry["stdout_tail"] = tail(redact(completed.stdout, secrets))

            raw_results.append(entry)

            if not success and not args.continue_on_error:
                raise SystemExit(error)

    result = {
        "scenario": "availability",
        "rounds": args.rounds,
        "modes": modes,
        "summary": build_summary(raw_results, modes),
        "raw_results": raw_results,
    }
    output_path = write_result("cia_availability_result.json", result)
    print(json.dumps(result, indent=2))
    print(f"Result written to {output_path}")


if __name__ == "__main__":
    main()
