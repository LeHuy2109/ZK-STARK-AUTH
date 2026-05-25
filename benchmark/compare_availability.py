"""Aggregate availability benchmark results into a report-friendly table."""

from __future__ import annotations

import json
from pathlib import Path


RESULTS_DIR = Path(__file__).resolve().parent / "results"
INPUT_FILES = {
    "traditional": RESULTS_DIR / "availability_traditional.json",
    "stark_offchain": RESULTS_DIR / "availability_stark_offchain.json",
}
OUTPUT_MD = RESULTS_DIR / "availability_summary.md"


def load_result(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing result file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def fmt_number(value: object, decimals: int = 6) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{decimals}f}"
    return str(value)


def percentile(sorted_values: list[float], ratio: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]

    index = ratio * (len(sorted_values) - 1)
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = index - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


def get_summary_metric(payload: dict, key: str) -> float | int | None:
    summary = payload["summary"]
    if key in summary:
        return summary[key]

    runs = payload.get("runs", [])
    latencies = sorted(run["benchmark"]["send_and_confirm_seconds"] for run in runs)

    if key == "p95_latency_seconds":
        return percentile(latencies, 0.95)
    if key == "p99_latency_seconds":
        return percentile(latencies, 0.99)
    if key == "throughput_tx_per_second":
        elapsed = summary.get("benchmark_elapsed_seconds")
        success_count = summary.get("success_count")
        if elapsed and success_count is not None and elapsed > 0:
            return success_count / elapsed
        return None

    return None


def build_rows(results: dict[str, dict]) -> list[list[str]]:
    rows: list[list[str]] = []
    for mode, payload in results.items():
        summary = payload["summary"]
        runs = payload.get("runs", [])
        avg_gas = None
        if runs:
            avg_gas = sum(run["gas_used"] for run in runs) / len(runs)

        avg_prove = None
        avg_verify = None
        avg_receipt = None
        stark_runs = [run for run in runs if "stark" in run]
        if stark_runs:
            avg_prove = sum(run["benchmark"]["risc0_prove_seconds"] for run in stark_runs) / len(stark_runs)
            avg_verify = sum(run["benchmark"]["risc0_verify_seconds"] for run in stark_runs) / len(stark_runs)
            avg_receipt = sum(run["stark"]["receipt_size_bytes"] for run in stark_runs) / len(stark_runs)

        rows.append(
            [
                mode,
                str(summary["success_count"]),
                str(summary["failure_count"]),
                f"{summary['success_rate_percent']}%",
                fmt_number(summary["average_latency_seconds"]),
                fmt_number(get_summary_metric(payload, "p95_latency_seconds")),
                fmt_number(get_summary_metric(payload, "p99_latency_seconds")),
                fmt_number(get_summary_metric(payload, "throughput_tx_per_second")),
                str(summary["retry_count"]),
                fmt_number(avg_gas, 2),
                fmt_number(avg_prove),
                fmt_number(avg_verify),
                fmt_number(avg_receipt, 2),
            ]
        )
    return rows


def render_markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    header_line = "| " + " | ".join(headers) + " |"
    separator_line = "| " + " | ".join(["---"] * len(headers)) + " |"
    body_lines = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([header_line, separator_line, *body_lines])


def render_error_breakdown(results: dict[str, dict]) -> str:
    lines = ["## Error Breakdown", ""]
    for mode, payload in results.items():
        breakdown = payload["summary"].get("error_breakdown", {})
        if breakdown:
            details = ", ".join(f"{error_type}={count}" for error_type, count in sorted(breakdown.items()))
        else:
            details = "none"
        lines.append(f"- {mode}: {details}")
    return "\n".join(lines)


def build_markdown_report(results: dict[str, dict]) -> str:
    headers = [
        "Mode",
        "Success",
        "Failure",
        "Success Rate",
        "Avg Latency (s)",
        "P95 (s)",
        "P99 (s)",
        "Throughput (tx/s)",
        "Retries",
        "Avg Gas",
        "Avg Prove (s)",
        "Avg Verify (s)",
        "Avg Receipt Bytes",
    ]
    rows = build_rows(results)
    table = render_markdown_table(headers, rows)

    lines = [
        "# Availability Summary",
        "",
        "RISC Zero receipt verification is off-chain in this version.",
        "The Ethereum transaction is still submitted using a normal ECDSA account.",
        "RISC Zero replaces application-level authorization, not chain-native transaction signing.",
        "",
        table,
        "",
        "## Source Files",
        "",
    ]
    for mode, path in INPUT_FILES.items():
        lines.append(f"- {mode}: `{path.name}`")
    lines.extend(["", render_error_breakdown(results)])
    return "\n".join(lines) + "\n"


def print_console_summary(results: dict[str, dict]) -> None:
    headers = [
        "mode",
        "success_rate",
        "avg_latency_s",
        "p95_s",
        "throughput_tx_s",
        "retries",
        "avg_gas",
        "avg_prove_s",
        "avg_verify_s",
        "avg_receipt_bytes",
    ]
    rows = []
    for row in build_rows(results):
        rows.append([row[0], row[3], row[4], row[5], row[7], row[8], row[9], row[10], row[11], row[12]])

    widths = []
    for index, header in enumerate(headers):
        max_width = len(header)
        for row in rows:
            max_width = max(max_width, len(row[index]))
        widths.append(max_width)

    def format_row(values: list[str]) -> str:
        return "  ".join(value.ljust(widths[index]) for index, value in enumerate(values))

    print("Availability Comparison")
    print(format_row(headers))
    print(format_row(["-" * width for width in widths]))
    for row in rows:
        print(format_row(row))


def main() -> None:
    results = {mode: load_result(path) for mode, path in INPUT_FILES.items()}
    print_console_summary(results)
    markdown_report = build_markdown_report(results)
    OUTPUT_MD.write_text(markdown_report, encoding="utf-8")
    print(f"Markdown report saved to: {OUTPUT_MD}")


if __name__ == "__main__":
    main()
