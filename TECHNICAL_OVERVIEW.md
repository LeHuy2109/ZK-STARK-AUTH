# Technical Overview

Tài liệu này giải thích ý nghĩa các file chính trong repo, cách các thành phần
liên kết với nhau, và luồng hoạt động của từng script benchmark.

## Mục Tiêu Kỹ Thuật

Repo benchmark xác thực ủy quyền ở tầng ứng dụng với đúng 3 mode:

```text
ecdsa_onchain
  app authorization được ký bằng secp256k1
  verify on-chain bằng ecrecover

stark_offchain
  app authorization được chứng minh bằng RISC Zero/STARK
  verify proof off-chain
  metadata on-chain, nếu có, không phải proof verification

stark_wrapped_onchain
  app authorization được chứng minh bằng RISC Zero/STARK
  proof được wrap sang Groth16/SNARK
  verify wrapped proof on-chain
```

So sánh on-chain công bằng chỉ là `ecdsa_onchain` với
`stark_wrapped_onchain`. `stark_offchain` là benchmark feasibility off-chain.

## Secret Model

```text
APP_AUTH_PRIVATE_KEY
  private key ứng dụng
  dùng chung cho cả 3 mode
  trong ECDSA: derive Ethereum-style address và ký app digest
  trong STARK: là private witness cho RISC Zero guest

SUBMITTER_PRIVATE_KEY
  private key ví Sepolia
  dùng để deploy, gửi transaction và trả gas
  không phải credential authorization được benchmark
```

Ethereum transaction signing luôn tồn tại khi gửi transaction, nhưng không phải
đối tượng so sánh của benchmark này.

## Cấu Trúc File

### Root

```text
README.md
  tổng quan ngắn gọn, trỏ sang các tài liệu chi tiết

SEPOLIA_BENCHMARK_RUNBOOK.md
  runbook chứa các lệnh cài đặt, build, deploy, lấy verifier address và chạy
  benchmark trên Sepolia

TECHNICAL_OVERVIEW.md
  tài liệu kỹ thuật này

.env.example
  template biến môi trường

.env
  secrets local, không commit

.gitignore
  bỏ qua secrets, build output và benchmark results local

requirements.txt
  dependencies Python cho scripts benchmark

foundry.toml
  cấu hình Foundry/Solidity
```

### Solidity Contracts

```text
contracts/ApplicationAuthBenchmark.sol
  smart contract benchmark chính

contracts/ApplicationAuthBenchmarkABI.json
  ABI generate từ Foundry để Python scripts gọi contract

contracts/verifiers/RiscZeroWrappedVerifierAdapter.sol
  adapter nối interface benchmark với raw RISC Zero Groth16 verifier

contracts/verifiers/README.md
  ghi chú riêng về wrapped verifier adapter
```

`ApplicationAuthBenchmark.sol` chứa:

```text
submitWithECDSA
  verify signature bằng ecrecover
  lưu ECDSA authorization record

submitStarkOffchainMetadata
  lưu proofHash/proofCid
  không verify STARK proof on-chain

submitWithWrappedStark
  kiểm tra context authorization
  kiểm tra journal digest
  gọi wrappedStarkVerifier.verifyWrappedProof(...)
  lưu wrapped authorization record khi verifier trả true
```

Contract cũng có:

```text
buildEcdsaDigest
buildStarkOffchainDigest
buildWrappedStarkDigest
buildWrappedStarkJournal
recoverSigner
setWrappedStarkVerifier
nonce tracking riêng cho từng mode
```

`RiscZeroWrappedVerifierAdapter.sol` gọi raw RISC Zero verifier:

```text
IRiscZeroVerifier.verify(seal, imageId, journalDigest)
```

Raw verifier revert khi proof sai. Adapter bắt lỗi bằng `try/catch` và trả
`true` hoặc `false` cho benchmark contract.

### Python Scripts

```text
scripts/common.py
  helper chung: load .env, validate private key, build digest, gọi RISC Zero
  host, build/sign/send transaction, ghi result JSON

scripts/ecdsa_onchain_demo.py
  chạy mode ecdsa_onchain

scripts/stark_offchain_demo.py
  chạy mode stark_offchain, có tùy chọn --submit-metadata

scripts/stark_wrapped_onchain_demo.py
  chạy mode stark_wrapped_onchain

scripts/offchain_storage.py
  lưu receipt theo kiểu local CID store hoặc IPFS nếu IPFS_API_URL được cấu hình
```

Các scripts đều dùng payload mặc định:

```json
{"action":"transfer","resource":"application-auth-benchmark","amount":1}
```

Có thể truyền payload khác bằng `--payload`.

### Benchmark Reports

```text
benchmark/compare_application_auth.py
  đọc result JSON của 3 mode và sinh comparison.json/comparison.md

benchmark/results/
  output local của các lần benchmark
```

Các file thường thấy trong `benchmark/results/`:

```text
ecdsa_onchain_result.json
  kết quả mode ECDSA on-chain

stark_offchain_result.json
  kết quả prove/verify STARK off-chain

stark_offchain_receipt.bin
  RISC Zero receipt của mode off-chain

stark_offchain_metadata.json
stark_offchain_verify_metadata.json
  metadata do RISC Zero host xuất ra khi prove/verify

stark_wrapped_onchain_result.json
  kết quả wrapped proof on-chain

stark_wrapped_base_receipt.bin
  RISC Zero/STARK receipt trước khi wrap

stark_wrapped_groth16_receipt.bin
  wrapped Groth16 receipt

stark_wrapped_groth16_receipt.seal
  EVM-encoded seal để gửi vào Solidity verifier

stark_wrapped_groth16_receipt.raw-seal
  raw Groth16 seal 256 bytes, chỉ để debug

comparison.json
comparison.md
  report so sánh tổng hợp
```

### RISC Zero Workspace

```text
risc0/Cargo.toml
  workspace Rust gồm host và methods

risc0/Cargo.lock
  lockfile dependencies Rust của workspace RISC Zero

risc0/LICENSE
  license đi kèm template/workspace RISC Zero

risc0/README.md
  README gốc của workspace RISC Zero scaffold

risc0/host/Cargo.toml
  dependencies của host CLI

risc0/host/src/main.rs
  CLI prove/verify, tạo receipt, wrap Groth16, encode seal cho EVM

risc0/methods/Cargo.toml
  crate methods chứa guest program

risc0/methods/build.rs
  build guest ELF và method ID

risc0/methods/src/lib.rs
  expose METHOD_ELF và METHOD_ID được generate lúc build

risc0/methods/guest/Cargo.toml
  dependencies của guest

risc0/methods/guest/Cargo.lock
  lockfile dependencies riêng của guest crate nếu Cargo sinh ra

risc0/methods/guest/src/main.rs
  RISC Zero guest program

risc0/rust-toolchain.toml
  toolchain Rust dùng cho RISC Zero
```

Host CLI có 2 subcommand:

```text
prove
  tạo receipt, verify receipt, ghi metadata
  nếu có --groth16 thì wrap receipt và ghi EVM seal

verify
  đọc receipt, verify off-chain, kiểm tra public inputs, ghi metadata
```

Guest program:

```text
1. đọc AuthorizationInput từ host
2. tính identity_commitment = SHA256(APP_AUTH_PRIVATE_KEY)
3. tính authorization_digest = SHA256(domain, identity_commitment,
   payload_hash, nonce, chain_id, contract_address)
4. commit journal public gồm domain, identity_commitment,
   authorization_digest, payload_hash, nonce, chain_id, contract_address
```

## Authorization Context

Mọi mode đều bind authorization vào:

```text
domain
identity
payload_hash
nonce
chain_id
contract_address
```

ECDSA identity:

```text
Ethereum-style address derive từ APP_AUTH_PRIVATE_KEY
```

STARK identity:

```text
identity_commitment = SHA256(APP_AUTH_PRIVATE_KEY)
```

ECDSA digest dùng `keccak256(abi.encode(...))` và EIP-191 signing trên digest
32 byte. STARK digest dùng SHA-256 trên canonical bytes do host/guest và
contract cùng build.

## Luồng `ecdsa_onchain`

Script:

```text
scripts/ecdsa_onchain_demo.py
```

Luồng:

```text
1. Load .env.
2. Đọc RPC_URL, SUBMITTER_PRIVATE_KEY, CONTRACT_ADDRESS,
   APP_AUTH_PRIVATE_KEY, CONTRACT_ABI_PATH.
3. Kết nối RPC và load ABI.
4. Encode payload thành bytes.
5. Tính payload_hash = keccak256(payload).
6. Tạo nonce nếu user không truyền --nonce.
7. Lấy chain_id từ RPC.
8. Derive app_address từ APP_AUTH_PRIVATE_KEY.
9. Build ECDSA app digest với domain, app_address, payload_hash, nonce,
   chain_id, contract_address.
10. Ký digest off-chain bằng EIP-191.
11. Build transaction gọi submitWithECDSA.
12. Ký transaction bằng SUBMITTER_PRIVATE_KEY.
13. Gửi transaction và chờ receipt.
14. Contract rebuild digest, gọi ecrecover và kiểm tra recovered signer.
15. Script ghi benchmark/results/ecdsa_onchain_result.json.
```

Điểm đo chính:

```text
ecdsa_sign_seconds
signature_size_bytes
ecdsa_verify_gas_used
total_tx_gas_used
raw_tx_size_bytes
send_and_confirm_seconds
```

## Luồng `stark_offchain`

Script:

```text
scripts/stark_offchain_demo.py
```

Luồng:

```text
1. Load .env.
2. Đọc APP_AUTH_PRIVATE_KEY, CONTRACT_ADDRESS và RPC_URL.
3. Lấy chain_id từ RPC hoặc --chain-id.
4. Encode payload và tính payload_hash.
5. Tạo nonce nếu user không truyền --nonce.
6. Tính identity_commitment = SHA256(APP_AUTH_PRIVATE_KEY).
7. Tính authorization_digest theo STARK_DOMAIN.
8. Gọi RISC Zero host subcommand prove.
9. Host chạy guest để tạo RISC Zero/STARK receipt.
10. Host verify receipt off-chain và ghi stark_offchain_metadata.json.
11. Script gọi RISC Zero host subcommand verify để verify receipt lần nữa
    với expected public inputs.
12. Script tính proof_hash = SHA256(receipt bytes).
13. Script lưu receipt vào local CID store hoặc IPFS.
14. Script ghi stark_offchain_result.json.
```

Nếu có `--submit-metadata`:

```text
15. Script load SUBMITTER_PRIVATE_KEY và ABI.
16. Gửi transaction gọi submitStarkOffchainMetadata.
17. Contract kiểm tra payload hash, nonce và authorization_digest.
18. Contract lưu proofHash/proofCid làm metadata.
```

Quan trọng:

```text
submitStarkOffchainMetadata không verify STARK proof on-chain
proofHash/proofCid không phải proof verification
metadata gas không được so với verifier gas
```

Điểm đo chính:

```text
host_prove_seconds
host_verify_seconds
script_prove_wall_seconds
script_verify_wall_seconds
proof_size_bytes
journal_size_bytes
public_input_size_bytes
receipt_upload_seconds
metadata_tx_gas_used nếu có --submit-metadata
```

`host_*` là thời gian nội bộ do Rust/RISC Zero host đo. `script_*_wall_seconds`
là thời gian Python đo khi gọi process `cargo run`, có thể bao gồm startup,
cache, IO hoặc compile.

## Luồng `stark_wrapped_onchain`

Script:

```text
scripts/stark_wrapped_onchain_demo.py
```

Điều kiện:

```text
ApplicationAuthBenchmark.wrappedStarkVerifier() phải trỏ tới adapter thật
Adapter phải trỏ tới raw RISC Zero Groth16 verifier đúng version
Máy chạy cần đủ mạnh để chạy --groth16
```

Luồng:

```text
1. Load .env.
2. Đọc RPC_URL, SUBMITTER_PRIVATE_KEY, CONTRACT_ADDRESS,
   APP_AUTH_PRIVATE_KEY, CONTRACT_ABI_PATH.
3. Kết nối RPC và load ABI.
4. Encode payload và tính payload_hash.
5. Tạo nonce nếu user không truyền --nonce.
6. Tính identity_commitment = SHA256(APP_AUTH_PRIVATE_KEY).
7. Tính authorization_digest theo STARK_WRAPPED_DOMAIN.
8. Gọi RISC Zero host subcommand prove với --groth16.
9. Host tạo base RISC Zero/STARK receipt.
10. Host verify base receipt off-chain.
11. Host compress/wrap receipt bằng ProverOpts::groth16().
12. Host verify wrapped receipt off-chain.
13. Host encode seal bằng risc0_ethereum_contracts::encode_seal.
14. Host ghi:
    stark_wrapped_base_receipt.bin
    stark_wrapped_groth16_receipt.bin
    stark_wrapped_groth16_receipt.seal
    stark_wrapped_groth16_receipt.raw-seal
    stark_wrapped_metadata.json
15. Script gọi host subcommand verify trên wrapped receipt.
16. Script đọc EVM-encoded seal từ .seal.
17. Script gửi transaction gọi submitWithWrappedStark.
18. Contract kiểm tra payload hash, nonce, authorization_digest.
19. Contract rebuild journal và kiểm tra sha256(journal) == journalDigest.
20. Contract gọi wrappedStarkVerifier.verifyWrappedProof.
21. Adapter gọi raw RISC Zero verifier.
22. Nếu proof hợp lệ, contract lưu StarkWrappedRecord.
23. Script ghi stark_wrapped_onchain_result.json.
```

Điểm đo chính:

```text
host_prove_seconds
host_wrap_seconds
host_prove_and_wrap_seconds
host_verify_seconds
script_prove_and_wrap_wall_seconds
script_verify_wall_seconds
wrapped_proof_size_bytes
wrapped_verify_gas_used
total_tx_gas_used
raw_tx_size_bytes
```

`host_prove_and_wrap_seconds` là tổng thời gian nội bộ RISC Zero cho prove và
wrap. `script_prove_and_wrap_wall_seconds` là thời gian Python nhìn từ ngoài cho
cả lệnh `prove --groth16`.

Lưu ý về seal:

```text
.seal
  EVM-encoded seal dùng để gửi lên verifier contract

.raw-seal
  raw Groth16 seal 256 bytes, chỉ để debug
```

Nếu gửi raw seal lên verifier on-chain, transaction sẽ revert với lỗi
`invalid wrapped proof`.

## Luồng Tạo Report

Script:

```text
benchmark/compare_application_auth.py
```

Luồng:

```text
1. Đọc ecdsa_onchain_result.json nếu có.
2. Đọc stark_offchain_result.json nếu có.
3. Đọc stark_wrapped_onchain_result.json nếu có.
4. Tạo comparison.json với dữ liệu cấu trúc.
5. Tạo comparison.md cho người đọc.
```

Report hiện có các nhóm:

```text
Mode Semantics
Execution Status
Authorization Binding
Off-chain Cost
Artifact And Transaction Sizes
On-chain Applicability
Ratios
Assessment
```

`On-chain Applicability` chỉ so `ecdsa_onchain` với
`stark_wrapped_onchain`. `stark_offchain` bị loại khỏi so sánh verifier
on-chain vì nó chỉ verify proof off-chain.

## Vai Trò Của `.env`

Các biến quan trọng:

```text
RPC_URL
  endpoint Sepolia

SUBMITTER_PRIVATE_KEY
  ví trả gas và ký transaction

APP_AUTH_PRIVATE_KEY
  secret authorization được benchmark

CONTRACT_ADDRESS
  địa chỉ ApplicationAuthBenchmark đã deploy

WRAPPED_STARK_VERIFIER_ADDRESS
  địa chỉ RiscZeroWrappedVerifierAdapter đã deploy

CONTRACT_ABI_PATH
  đường dẫn ABI JSON cho Python scripts

TX_TIMEOUT_SECONDS
  timeout chờ receipt

TX_GAS_LIMIT
  gas limit khi build transaction

RISC0_HOST_DIR
  thư mục Rust workspace RISC Zero

RISC0_HOST_PACKAGE
  package host

RISC0_CARGO_FEATURES
  features bổ sung nếu cần

OFFCHAIN_STORE_DIR
  thư mục lưu receipt off-chain

IPFS_API_URL
  nếu set thì offchain_storage dùng IPFS API thay local store
```

Chi tiết cách điền biến và deploy nằm trong `SEPOLIA_BENCHMARK_RUNBOOK.md`.

## Các File Generated Và Local

Các file sau thường là output local:

```text
benchmark/results/*
out/
cache/
target/
risc0/target/
__pycache__/
*.pyc
```

Chúng không phải source code chính. Nếu cần số liệu mới, chạy lại scripts thay
vì sửa tay result JSON.

## Các Check Nên Chạy Sau Khi Sửa Code

```bash
forge build
cd risc0
cargo fmt --check
cargo check -p host
cargo run -p host -- --help
cd ..
python3 -m py_compile scripts/*.py benchmark/*.py
```

Không tự chạy `--groth16` trên máy yếu nếu chỉ cần kiểm tra compile.
