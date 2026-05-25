"""Local off-chain storage helpers used to emulate CID-addressed proof storage."""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

from common import PROJECT_ROOT


DEFAULT_STORAGE_DIR = PROJECT_ROOT / "benchmark" / "results" / "offchain_store"


def ipfs_api_url() -> str:
    return os.getenv("IPFS_API_URL", "").strip()


def ensure_storage_dir(storage_dir: str | Path | None = None) -> Path:
    resolved_dir = Path(storage_dir) if storage_dir else DEFAULT_STORAGE_DIR
    if not resolved_dir.is_absolute():
        resolved_dir = (PROJECT_ROOT / resolved_dir).resolve()
    resolved_dir.mkdir(parents=True, exist_ok=True)
    return resolved_dir


def build_cid(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def storage_backend_name() -> str:
    return "ipfs" if ipfs_api_url() else "local_cid_store"


def build_ipfs_uri(cid: str) -> str:
    return f"ipfs://{cid}"


def _ipfs_client():
    try:
        import ipfshttpclient  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "IPFS backend requested but ipfshttpclient is not installed. "
            "Install it separately or unset IPFS_API_URL."
        ) from exc

    try:
        return ipfshttpclient.connect(ipfs_api_url())
    except Exception as exc:
        raise RuntimeError(f"Failed to connect to IPFS API at {ipfs_api_url()}: {exc}") from exc


def save_blob(data: bytes, suffix: str, storage_dir: str | Path | None = None) -> tuple[str, Path, float]:
    if ipfs_api_url():
        start = time.perf_counter()
        with _ipfs_client() as client:
            cid = client.add_bytes(data)
        elapsed = time.perf_counter() - start
        return cid, Path(build_ipfs_uri(cid)), round(elapsed, 6)

    start = time.perf_counter()
    cid = build_cid(data)
    output_path = ensure_storage_dir(storage_dir) / f"{cid}.{suffix}"
    output_path.write_bytes(data)
    elapsed = time.perf_counter() - start
    return cid, output_path, round(elapsed, 6)


def load_blob(cid: str, suffix: str, storage_dir: str | Path | None = None) -> tuple[bytes, Path, float]:
    if cid.startswith("ipfs://"):
        cid = cid.removeprefix("ipfs://")

    if ipfs_api_url():
        start = time.perf_counter()
        with _ipfs_client() as client:
            data = client.cat(cid)
        elapsed = time.perf_counter() - start
        return data, Path(build_ipfs_uri(cid)), round(elapsed, 6)

    start = time.perf_counter()
    input_path = ensure_storage_dir(storage_dir) / f"{cid}.{suffix}"
    data = input_path.read_bytes()
    elapsed = time.perf_counter() - start
    return data, input_path, round(elapsed, 6)


def save_receipt(receipt: bytes, storage_dir: str | Path | None = None) -> tuple[str, Path, float]:
    return save_blob(receipt, "risc0_receipt", storage_dir)


def load_receipt(cid: str, storage_dir: str | Path | None = None) -> tuple[bytes, Path, float]:
    return load_blob(cid, "risc0_receipt", storage_dir)
