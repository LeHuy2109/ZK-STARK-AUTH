# Sepolia Benchmark Runbook

## 1. Cài đặt

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env
```

Điền `.env`:

```env
RPC_URL=https://ethereum-sepolia-rpc.publicnode.com
SUBMITTER_PRIVATE_KEY=0x... (Địa chỉ private key lấy ở metamask)
APP_AUTH_PRIVATE_KEY=0x... (Chạy lệnh 'cast wallet new' để tạo private key)
CONTRACT_ADDRESS= (Xem ở bước sau)
WRAPPED_STARK_VERIFIER_ADDRESS= (Xem ở bước sau)
```

Load `.env`:

```bash
set -a
source .env
set +a
```

Kiểm tra Sepolia:

```bash
cast chain-id --rpc-url "$RPC_URL"
```

Kết quả đúng:

```text
11155111
```

## 2. Build

```bash
forge build
forge inspect contracts/ApplicationAuthBenchmark.sol:ApplicationAuthBenchmark abi --json > contracts/ApplicationAuthBenchmarkABI.json
cd risc0
cargo check -p host
cd ..
```

## 3. Lấy `WRAPPED_STARK_VERIFIER_ADDRESS`

Raw RISC Zero Groth16 verifier Sepolia hiện dùng cho SDK 3.x:

```bash
export RISC_ZERO_RAW_VERIFIER_ADDRESS=0x2a098988600d87650Fb061FfAff08B97149Fa84D
```

Nguồn kiểm tra địa chỉ:

```text
https://github.com/risc0/risc0-ethereum/blob/main/contracts/deployment.toml
```

Deploy adapter:

```bash
forge create contracts/verifiers/RiscZeroWrappedVerifierAdapter.sol:RiscZeroWrappedVerifierAdapter \
  --rpc-url "$RPC_URL" \
  --private-key "$SUBMITTER_PRIVATE_KEY" \
  --broadcast \
  --constructor-args "$RISC_ZERO_RAW_VERIFIER_ADDRESS"
```

Copy dòng `Deployed to: 0x...` và set:

```bash
export WRAPPED_STARK_VERIFIER_ADDRESS=0x...adapter_deployed_to...
```

Cập nhật `.env`:

```env
WRAPPED_STARK_VERIFIER_ADDRESS=0x...adapter_deployed_to...
```

## 4. Deploy `ApplicationAuthBenchmark`

Deploy với wrapped adapter ngay từ đầu:

```bash
forge create contracts/ApplicationAuthBenchmark.sol:ApplicationAuthBenchmark \
  --rpc-url "$RPC_URL" \
  --private-key "$SUBMITTER_PRIVATE_KEY" \
  --broadcast \
  --constructor-args "$WRAPPED_STARK_VERIFIER_ADDRESS"
```

Copy dòng `Deployed to: 0x...` và set:

```bash
export CONTRACT_ADDRESS=0x...benchmark_deployed_to...
```

Cập nhật `.env`:

```env
CONTRACT_ADDRESS=0x...benchmark_deployed_to...
```

Kiểm tra contract đang dùng adapter:

```bash
cast call "$CONTRACT_ADDRESS" \
  "wrappedStarkVerifier()(address)" \
  --rpc-url "$RPC_URL"
```

Nếu đã deploy benchmark trước với `address(0)`, cập nhật adapter:

```bash
cast send "$CONTRACT_ADDRESS" \
  "setWrappedStarkVerifier(address)" \
  "$WRAPPED_STARK_VERIFIER_ADDRESS" \
  --rpc-url "$RPC_URL" \
  --private-key "$SUBMITTER_PRIVATE_KEY"
```

## 5. Chạy `ecdsa_onchain`

```bash
python3 scripts/ecdsa_onchain_demo.py
```

Output:

```text
benchmark/results/ecdsa_onchain_result.json
```

## 6. Chạy `stark_offchain`

```bash
python3 scripts/stark_offchain_demo.py
```

Output:

```text
benchmark/results/stark_offchain_result.json
benchmark/results/stark_offchain_receipt.bin
benchmark/results/offchain_store/
```

Tùy chọn gửi metadata lên chain:

```bash
python3 scripts/stark_offchain_demo.py --submit-metadata
```

Metadata chỉ là `proofHash`/`proofCid`, không phải proof verification.

## 7. Chạy `stark_wrapped_onchain`

Yêu cầu:

```bash
cast call "$CONTRACT_ADDRESS" \
  "wrappedStarkVerifier()(address)" \
  --rpc-url "$RPC_URL"
```

Kết quả phải khác:

```text
0x0000000000000000000000000000000000000000
```

Chạy benchmark:

```bash
python3 scripts/stark_wrapped_onchain_demo.py
```

Output:

```text
benchmark/results/stark_wrapped_onchain_result.json
benchmark/results/stark_wrapped_base_receipt.bin
benchmark/results/stark_wrapped_groth16_receipt.bin
benchmark/results/stark_wrapped_groth16_receipt.seal
```

## 8. Tạo report

```bash
python3 benchmark/compare_application_auth.py
```

Output:

```text
benchmark/results/comparison.json
benchmark/results/comparison.md
```

## 9. Ghi chú chạy mode

```text
wrappedStarkVerifier = address(0)
  ecdsa_onchain: chạy được
  stark_offchain: chạy được
  stark_wrapped_onchain: không chạy được

wrappedStarkVerifier = adapter thật
  ecdsa_onchain: chạy được
  stark_offchain: chạy được
  stark_wrapped_onchain: chạy được nếu proof và adapter đúng
```
