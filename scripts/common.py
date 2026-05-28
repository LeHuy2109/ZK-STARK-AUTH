"""Shared helpers for the application authorization benchmark demos."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_abi import encode as abi_encode
from web3 import Web3


PROJECT_ROOT = Path(
    os.environ.get("STARK_PROJECT_ROOT", Path(__file__).resolve().parents[1])
).resolve()
DEFAULT_ABI_PATH = PROJECT_ROOT / "contracts" / "ApplicationAuthBenchmarkABI.json"
DEFAULT_RISC0_HOST_DIR = PROJECT_ROOT / "risc0"
DEFAULT_RISC0_HOST_PACKAGE = "host"

ECDSA_DOMAIN = "ECDSA_APP_AUTH_V1"
STARK_DOMAIN = "STARK_APP_AUTH_V1"
STARK_WRAPPED_DOMAIN = "STARK_WRAPPED_APP_AUTH_V1"
ZERO_BYTES32 = "0x" + ("00" * 32)
SECP256K1_ORDER = int(
    "fffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141", 16
)


def load_dotenv() -> None:
    """Load project-level .env values without overriding existing env vars."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def require_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if not value:
        print(f"Missing required env var: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def optional_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        print(f"Invalid integer env var: {name}={value}", file=sys.stderr)
        sys.exit(1)


def optional_env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        print(f"Invalid float env var: {name}={value}", file=sys.stderr)
        sys.exit(1)


def load_abi(abi_path: str) -> list[dict[str, Any]]:
    resolved_path = Path(abi_path)
    if not resolved_path.is_absolute():
        resolved_path = (PROJECT_ROOT / resolved_path).resolve()
    with open(resolved_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def build_web3(rpc_url: str) -> Web3:
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        print("Failed to connect to RPC", file=sys.stderr)
        sys.exit(1)
    return w3


def ensure_results_dir() -> Path:
    result_dir = PROJECT_ROOT / "benchmark" / "results"
    result_dir.mkdir(parents=True, exist_ok=True)
    return result_dir


def write_result(filename: str, payload: dict[str, Any]) -> Path:
    output_path = ensure_results_dir() / filename
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def build_nonce() -> int:
    return int(time.time_ns())


def strip_0x(value: str) -> str:
    return value[2:] if value.lower().startswith("0x") else value


def hex_to_bytes(value: str, expected_len: int | None = None, field_name: str = "hex") -> bytes:
    raw = strip_0x(value)
    try:
        decoded = bytes.fromhex(raw)
    except ValueError as exc:
        raise ValueError(f"{field_name} is not valid hex") from exc

    if expected_len is not None and len(decoded) != expected_len:
        raise ValueError(f"{field_name} must be {expected_len} bytes, got {len(decoded)}")
    return decoded


def normalize_hex(value: str, expected_len: int | None = None, field_name: str = "hex") -> str:
    return "0x" + hex_to_bytes(value, expected_len, field_name).hex()


def normalize_bytes32(value: str, field_name: str = "bytes32") -> str:
    return normalize_hex(value, 32, field_name)


def bytes_to_hex(value: bytes | bytearray | str) -> str:
    if isinstance(value, str):
        return normalize_hex(value)
    return "0x" + bytes(value).hex()


def address_to_bytes(address: str) -> bytes:
    return Web3.to_bytes(hexstr=Web3.to_checksum_address(address))


def sha256_hex(data: bytes) -> str:
    return "0x" + hashlib.sha256(data).hexdigest()


def payload_hash_hex(w3: Web3, payload: bytes) -> str:
    return w3.to_hex(w3.keccak(payload))


def receipt_hash_hex(receipt_bytes: bytes) -> str:
    return sha256_hex(receipt_bytes)


def normalize_private_key(value: str, field_name: str = "APP_AUTH_PRIVATE_KEY") -> str:
    normalized = normalize_hex(value, 32, field_name)
    key_int = int(strip_0x(normalized), 16)
    if key_int <= 0 or key_int >= SECP256K1_ORDER:
        raise ValueError(f"{field_name} must be a valid secp256k1 private key")
    return normalized


def require_app_auth_private_key() -> str:
    return normalize_private_key(require_env("APP_AUTH_PRIVATE_KEY"))


def derive_app_address(app_auth_private_key: str) -> str:
    private_key = normalize_private_key(app_auth_private_key)
    return Account.from_key(private_key).address


def derive_identity_commitment(app_auth_private_key: str) -> str:
    return sha256_hex(hex_to_bytes(normalize_private_key(app_auth_private_key), 32))


def normalize_nonce_or_chain_id(value: int, field_name: str) -> int:
    if value < 0 or value >= 2**256:
        raise ValueError(f"{field_name} must fit in uint256")
    return value


def _u256_be(value: int, field_name: str) -> bytes:
    return normalize_nonce_or_chain_id(value, field_name).to_bytes(32, byteorder="big")


def build_ecdsa_app_digest(
    *,
    app_address: str,
    payload_hash: str,
    nonce: int,
    chain_id: int,
    contract_address: str,
) -> str:
    encoded = abi_encode(
        ["string", "address", "bytes32", "uint256", "uint256", "address"],
        [
            ECDSA_DOMAIN,
            Web3.to_checksum_address(app_address),
            hex_to_bytes(payload_hash, 32, "payload_hash"),
            normalize_nonce_or_chain_id(nonce, "nonce"),
            normalize_nonce_or_chain_id(chain_id, "chain_id"),
            Web3.to_checksum_address(contract_address),
        ],
    )
    return Web3.to_hex(Web3.keccak(encoded))


def eth_signed_message_digest(app_digest: str) -> str:
    digest_bytes = hex_to_bytes(normalize_bytes32(app_digest, "app_digest"), 32)
    return Web3.to_hex(Web3.keccak(b"\x19Ethereum Signed Message:\n32" + digest_bytes))


def sign_ecdsa_authorization(
    *,
    app_auth_private_key: str,
    payload_hash: str,
    nonce: int,
    chain_id: int,
    contract_address: str,
) -> dict[str, Any]:
    private_key = normalize_private_key(app_auth_private_key)
    app_address = derive_app_address(private_key)
    app_digest = build_ecdsa_app_digest(
        app_address=app_address,
        payload_hash=payload_hash,
        nonce=nonce,
        chain_id=chain_id,
        contract_address=contract_address,
    )
    message = encode_defunct(primitive=hex_to_bytes(app_digest, 32, "ecdsa_digest"))
    signed = Account.sign_message(message, private_key=private_key)
    signature = signed.signature.hex()
    if not signature.startswith("0x"):
        signature = "0x" + signature
    return {
        "app_address": app_address,
        "ecdsa_digest": app_digest,
        "eth_signed_digest": eth_signed_message_digest(app_digest),
        "signature": signature,
        "signature_size_bytes": len(hex_to_bytes(signature, 65, "signature")),
    }


def compute_stark_authorization_digest(
    *,
    domain: str,
    identity_commitment: str,
    payload_hash: str,
    nonce: int,
    chain_id: int,
    contract_address: str,
) -> bytes:
    return b"".join(
        [
            domain.encode("utf-8"),
            hex_to_bytes(identity_commitment, 32, "identity_commitment"),
            hex_to_bytes(payload_hash, 32, "payload_hash"),
            _u256_be(nonce, "nonce"),
            _u256_be(chain_id, "chain_id"),
            address_to_bytes(contract_address),
        ]
    )


def compute_stark_authorization_digest_hex(
    *,
    domain: str = STARK_DOMAIN,
    payload_hash: str,
    identity_commitment: str,
    nonce: int,
    chain_id: int,
    contract_address: str,
) -> str:
    return sha256_hex(
        compute_stark_authorization_digest(
            domain=domain,
            payload_hash=payload_hash,
            identity_commitment=identity_commitment,
            nonce=nonce,
            chain_id=chain_id,
            contract_address=contract_address,
        )
    )


def public_input_size_bytes(
    *,
    domain: str = STARK_DOMAIN,
    payload_hash: str,
    identity_commitment: str,
    authorization_digest: str,
    nonce: int,
    chain_id: int,
    contract_address: str,
) -> int:
    expected_digest = compute_stark_authorization_digest_hex(
        domain=domain,
        payload_hash=payload_hash,
        identity_commitment=identity_commitment,
        nonce=nonce,
        chain_id=chain_id,
        contract_address=contract_address,
    )
    if normalize_bytes32(authorization_digest, "authorization_digest") != expected_digest:
        raise ValueError("authorization_digest does not match public inputs")
    return 32 + 32 + 32 + 32 + 32 + 20


def resolve_risc0_host_dir() -> Path:
    host_dir = Path(os.getenv("RISC0_HOST_DIR", str(DEFAULT_RISC0_HOST_DIR)))
    if not host_dir.is_absolute():
        host_dir = (PROJECT_ROOT / host_dir).resolve()
    return host_dir


def risc0_host_package() -> str:
    return os.getenv("RISC0_HOST_PACKAGE", DEFAULT_RISC0_HOST_PACKAGE)


def _sensitive_cli_values(args: list[str]) -> list[str]:
    values: list[str] = []
    sensitive_flags = {"--app-auth-private-key"}
    for index, arg in enumerate(args[:-1]):
        if arg in sensitive_flags:
            values.append(args[index + 1])
    return values


def _sensitive_env_values() -> list[str]:
    return [
        value
        for name in ("APP_AUTH_PRIVATE_KEY", "SUBMITTER_PRIVATE_KEY")
        for value in [os.getenv(name)]
        if value
    ]


def _redact_sensitive_text(text: str, args: list[str] | None = None) -> str:
    redacted = text
    sensitive_values = _sensitive_env_values()
    if args is not None:
        sensitive_values.extend(_sensitive_cli_values(args))

    for value in sensitive_values:
        variants = [value]
        if value.startswith("0x"):
            variants.append(value[2:])
        for variant in variants:
            if variant:
                redacted = redacted.replace(variant, "[REDACTED]")
    return redacted


def _risc0_failure_hint(stderr: str) -> str:
    if "docker returned failure exit code: Some(137)" in stderr or "exit code: Some(137)" in stderr:
        return (
            "\nHint: Docker exit code 137 usually means the Groth16 wrapping container "
            "was killed by the OS, most often due to insufficient RAM. Increase Docker/WSL "
            "memory, add swap, or run a non-wrapped scenario such as cia_confidentiality_demo.py."
        )
    return ""


def run_risc0_host(host_args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = ["cargo", "run", "--release", "-p", risc0_host_package()]
    cargo_features = os.getenv("RISC0_CARGO_FEATURES", "").strip()
    if cargo_features:
        cmd.extend(["--features", cargo_features])
    cmd.extend(["--", *host_args])
    completed = subprocess.run(
        cmd,
        cwd=resolve_risc0_host_dir(),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        stdout = _redact_sensitive_text(completed.stdout, host_args)
        stderr = _redact_sensitive_text(completed.stderr, host_args)
        raise RuntimeError(
            "RISC Zero host failed with exit code "
            f"{completed.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
            f"{_risc0_failure_hint(completed.stderr)}"
        )
    return completed


def prove_risc0_auth(
    *,
    payload_hash: str,
    app_auth_private_key: str,
    nonce: int,
    chain_id: int,
    contract_address: str,
    receipt_path: Path,
    metadata_path: Path,
    domain: str = STARK_DOMAIN,
    groth16: bool = False,
    wrapped_output_path: Path | None = None,
) -> tuple[dict[str, Any], float]:
    args = [
        "prove",
        "--domain",
        domain,
        "--payload-hash",
        normalize_bytes32(payload_hash, "payload_hash"),
        "--app-auth-private-key",
        normalize_private_key(app_auth_private_key),
        "--nonce",
        str(nonce),
        "--chain-id",
        str(chain_id),
        "--contract-address",
        Web3.to_checksum_address(contract_address),
        "--output",
        str(receipt_path),
        "--metadata-output",
        str(metadata_path),
    ]
    if groth16:
        if wrapped_output_path is None:
            raise ValueError("wrapped_output_path is required when groth16=True")
        args.extend(["--groth16", "--wrapped-output", str(wrapped_output_path)])

    start = time.perf_counter()
    run_risc0_host(args)
    elapsed = time.perf_counter() - start
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    return metadata, elapsed


def verify_risc0_auth(
    *,
    receipt_path: Path,
    domain: str = STARK_DOMAIN,
    payload_hash: str,
    identity_commitment: str,
    authorization_digest: str,
    nonce: int,
    chain_id: int,
    contract_address: str,
    metadata_path: Path | None = None,
) -> tuple[dict[str, Any] | None, float]:
    args = [
        "verify",
        "--receipt",
        str(receipt_path),
        "--domain",
        domain,
        "--payload-hash",
        normalize_bytes32(payload_hash, "payload_hash"),
        "--identity-commitment",
        normalize_bytes32(identity_commitment, "identity_commitment"),
        "--authorization-digest",
        normalize_bytes32(authorization_digest, "authorization_digest"),
        "--nonce",
        str(nonce),
        "--chain-id",
        str(chain_id),
        "--contract-address",
        Web3.to_checksum_address(contract_address),
    ]
    if metadata_path is not None:
        args.extend(["--metadata-output", str(metadata_path)])

    start = time.perf_counter()
    completed = run_risc0_host(args)
    elapsed = time.perf_counter() - start

    if metadata_path is not None and metadata_path.exists():
        return json.loads(metadata_path.read_text(encoding="utf-8")), elapsed
    try:
        return json.loads(completed.stdout), elapsed
    except json.JSONDecodeError:
        return None, elapsed


def build_tx_options(w3: Web3, account: str, nonce: int, gas: int) -> dict[str, Any]:
    tx_options: dict[str, Any] = {
        "from": account,
        "nonce": nonce,
        "gas": gas,
        "chainId": w3.eth.chain_id,
    }

    latest = w3.eth.get_block("latest")
    if latest.get("baseFeePerGas") is not None:
        tx_options["maxFeePerGas"] = w3.to_wei(
            str(optional_env_float("MAX_FEE_PER_GAS_GWEI", 30.0)), "gwei"
        )
        tx_options["maxPriorityFeePerGas"] = w3.to_wei(
            str(optional_env_float("MAX_PRIORITY_FEE_PER_GAS_GWEI", 1.0)), "gwei"
        )
    else:
        tx_options["gasPrice"] = w3.to_wei(
            str(optional_env_float("GAS_PRICE_GWEI", 30.0)), "gwei"
        )

    return tx_options


def raw_transaction_bytes(signed_tx: Any) -> bytes:
    raw_tx = getattr(signed_tx, "rawTransaction", None) or getattr(
        signed_tx, "raw_transaction"
    )
    return bytes(raw_tx)


def send_contract_transaction(
    *,
    w3: Web3,
    function_call: Any,
    submitter_private_key: str,
    gas: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    account = Account.from_key(submitter_private_key)
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

    return {
        "submitter": account.address,
        "tx_hash": w3.to_hex(tx_hash),
        "gas_used": receipt["gasUsed"],
        "status": receipt["status"],
        "tx_build_seconds": round(tx_build_seconds, 6),
        "submitter_tx_sign_seconds": round(submitter_tx_sign_seconds, 6),
        "send_and_confirm_seconds": round(send_and_confirm_seconds, 6),
        "raw_tx_size_bytes": len(raw_tx),
    }
