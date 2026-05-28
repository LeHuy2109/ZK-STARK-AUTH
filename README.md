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

## CIA Scenarios

Ba script CIA chạy lại các primitive hiện có và ghi output vào `benchmark/results/`:

```bash
python3 scripts/cia_confidentiality_demo.py
python3 scripts/cia_integrity_demo.py
python3 scripts/cia_availability_benchmark.py --rounds 3
```

`cia_confidentiality_demo.py` tạo và verify STARK/RISC Zero proof off-chain,
dùng `APP_AUTH_PRIVATE_KEY` làm private witness nhưng không in hoặc ghi secret
vào result. Output chính là `cia_confidentiality_result.json`; thêm
`--negative-wrong-secret` để verify receipt với public input sai và kỳ vọng fail.

`cia_integrity_demo.py` dùng `stark_wrapped_onchain`: positive case gửi payload
gốc và wrapped proof hợp lệ lên contract; negative cases gửi payload bị sửa với
payload hash gốc và replay nonce. Output chính là `cia_integrity_result.json`.
Có thể dùng `--skip-positive` hoặc `--gas-limit`.

`cia_availability_benchmark.py` chạy nhiều vòng bằng subprocess qua 3 demo mode
có sẵn, tổng hợp success rate, wall-clock latency, gas, kích thước proof, và
thời gian prove/verify. Output chính là `cia_availability_result.json`; dùng
`--skip-wrapped` nếu muốn bỏ bước wrapped/prove lâu, hoặc
`--submit-stark-metadata` để bật metadata tx cho `stark_offchain`.

Nếu `stark_wrapped_onchain` hoặc `cia_integrity_demo.py` fail ở bước Groth16 với
`docker returned failure exit code: Some(137)`, Docker/WSL thường đã bị kill do
thiếu RAM. Tăng memory/swap cho Docker/WSL rồi chạy lại; để benchmark nhanh
không wrap có thể dùng `cia_confidentiality_demo.py` hoặc
`cia_availability_benchmark.py --skip-wrapped`.

Chi tiết deploy contract, lấy `WRAPPED_STARK_VERIFIER_ADDRESS`, và chạy trên
Sepolia nằm trong `SEPOLIA_BENCHMARK_RUNBOOK.md`.

## Kết Quả

Các output benchmark được ghi vào:

```text
benchmark/results/
```

Các file result là output local và không nên coi là source of truth cố định.
Muốn có số liệu mới thì chạy lại benchmark cùng một môi trường.
