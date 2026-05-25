# Application Authorization Benchmark

Repo này benchmark xác thực ủy quyền ở tầng ứng dụng. Nó không benchmark chữ ký
giao dịch native của Ethereum.

Có hai loại private key khác nhau:

```text
APP_AUTH_PRIVATE_KEY
  secret ứng dụng được benchmark
  dùng chung cho cả 3 mode authorization

SUBMITTER_PRIVATE_KEY
  chỉ dùng để deploy contract, gửi transaction và trả gas
```

Không so sánh Ethereum transaction signing với STARK proof. Transaction signing
chỉ là cơ chế gửi giao dịch lên Ethereum.

## Ba Mode Benchmark

```text
ecdsa_onchain
  ký app authorization digest off-chain bằng secp256k1
  verify on-chain bằng Solidity ecrecover

stark_offchain
  dùng APP_AUTH_PRIVATE_KEY làm private witness cho RISC Zero
  prove và verify STARK/RISC Zero receipt off-chain
  nếu gửi proofHash/proofCid lên chain thì chỉ là metadata

stark_wrapped_onchain
  tạo RISC Zero/STARK proof off-chain
  wrap sang Groth16/SNARK bằng --groth16
  verify wrapped proof on-chain qua verifier adapter
```

So sánh verifier on-chain công bằng chỉ là:

```text
ecdsa_onchain vs stark_wrapped_onchain
```

`stark_offchain` chỉ dùng để đánh giá feasibility off-chain.

## Tài Liệu Chính

```text
SEPOLIA_BENCHMARK_RUNBOOK.md
  các lệnh cần chạy trên Sepolia từ cài đặt, deploy đến benchmark

TECHNICAL_OVERVIEW.md
  ý nghĩa từng file, kiến trúc, luồng hoạt động của scripts benchmark

```

## Chạy Nhanh

Làm theo runbook:

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env
```

Build:

```bash
forge build
cd risc0
cargo check -p host
cd ..
```

Chạy các mode sau khi `.env` và contract đã sẵn sàng:

```bash
python3 scripts/ecdsa_onchain_demo.py
python3 scripts/stark_offchain_demo.py
python3 scripts/stark_wrapped_onchain_demo.py
python3 benchmark/compare_application_auth.py
```

Chi tiết deploy contract, lấy `WRAPPED_STARK_VERIFIER_ADDRESS`, và chạy trên
Sepolia nằm trong `SEPOLIA_BENCHMARK_RUNBOOK.md`.

## Kết Quả

Các output benchmark được ghi vào:

```text
benchmark/results/
```

Các file result là output local và không nên coi là source of truth cố định.
Muốn có số liệu mới thì chạy lại benchmark cùng một môi trường.
