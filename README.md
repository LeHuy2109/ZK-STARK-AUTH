# Benchmark Xác Thực Ủy Quyền Ở Tầng Ứng Dụng

Repo này benchmark cơ chế xác thực ủy quyền ở tầng ứng dụng, không benchmark
chữ ký giao dịch native của Ethereum. Mọi giao dịch thật gửi lên chain vẫn dùng
`SUBMITTER_PRIVATE_KEY` để ký transaction và trả gas. Credential được benchmark
là một khóa ứng dụng dùng chung: `APP_AUTH_PRIVATE_KEY`.

Điểm quan trọng:

```text
SUBMITTER_PRIVATE_KEY
  dùng để deploy contract, gửi transaction, trả gas
  không phải đối tượng benchmark authorization

APP_AUTH_PRIVATE_KEY
  private key secp256k1 dài 32 byte
  dùng chung cho cả 3 mode authorization
  phải tách biệt với SUBMITTER_PRIVATE_KEY
```

## Các Chế Độ Benchmark

```text
ecdsa_onchain
  APP_AUTH_PRIVATE_KEY được dùng như Ethereum private key
  derive Ethereum-style address
  sign authorization digest off-chain
  Solidity verify on-chain bằng ecrecover

stark_offchain
  cùng APP_AUTH_PRIVATE_KEY được dùng làm private witness cho RISC Zero
  tạo RISC Zero/STARK receipt off-chain
  verify receipt off-chain
  không verify STARK proof on-chain
  proofHash/proofCid on-chain, nếu có, chỉ là metadata

stark_wrapped_onchain
  cùng APP_AUTH_PRIVATE_KEY được dùng làm private witness cho RISC Zero
  tạo RISC Zero/STARK receipt off-chain
  wrap/compress receipt sang Groth16/SNARK bằng --groth16
  Solidity verify wrapped proof on-chain qua verifier adapter
  đây không phải pure STARK on-chain verification
```

So sánh verifier on-chain công bằng là:

```text
ecdsa_onchain
vs
stark_wrapped_onchain
```

`stark_offchain` chỉ dùng để đánh giá feasibility off-chain. Không được so
metadata gas của `stark_offchain` với verifier gas của `ecdsa_onchain`.

## Cài Đặt

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env
```

Điền `.env`:

```env
RPC_URL=https://eth-sepolia.g.alchemy.com/v2/...
SUBMITTER_PRIVATE_KEY=0x...
CONTRACT_ADDRESS=0x...
WRAPPED_STARK_VERIFIER_ADDRESS=0x0000000000000000000000000000000000000000

APP_AUTH_PRIVATE_KEY=0x...

CONTRACT_ABI_PATH=contracts/ApplicationAuthBenchmarkABI.json
TX_TIMEOUT_SECONDS=120
TX_GAS_LIMIT=1000000

RISC0_HOST_DIR=risc0
RISC0_HOST_PACKAGE=host
RISC0_CARGO_FEATURES=

OFFCHAIN_STORE_DIR=benchmark/results/offchain_store
IPFS_API_URL=
```

## Lấy Các Biến `.env`

`RPC_URL`

Repo này đang hướng dẫn theo Sepolia testnet. Lấy Sepolia RPC URL từ một nhà
cung cấp RPC như Alchemy, Infura, QuickNode, Ankr hoặc node riêng.

Ví dụ với Alchemy:

```env
RPC_URL=https://eth-sepolia.g.alchemy.com/v2/YOUR_API_KEY
```

`SUBMITTER_PRIVATE_KEY`

Export private key từ ví Sepolia của bạn, ví dụ MetaMask hoặc ví CLI riêng.
Account này cần có Sepolia ETH để deploy contract và gửi transaction.

Không dùng ví mainnet nhiều tiền cho benchmark. Nên tạo ví test riêng.

`APP_AUTH_PRIVATE_KEY`

Tạo mới bằng Foundry:

```bash
cast wallet new
```

Lấy dòng private key điền vào:

```env
APP_AUTH_PRIVATE_KEY=0x...
```

Không dùng trùng với `SUBMITTER_PRIVATE_KEY` nếu không có lý do rõ ràng.

`CONTRACT_ADDRESS`

Đây là địa chỉ `ApplicationAuthBenchmark` sau khi deploy. Sau khi deploy xong,
copy dòng `Deployed to: 0x...` vào `.env`.

`WRAPPED_STARK_VERIFIER_ADDRESS`

Biến này là địa chỉ verifier adapter của benchmark trên Sepolia, không phải
luôn là địa chỉ verifier gốc của RISC Zero.

Contract `ApplicationAuthBenchmark` gọi interface:

```solidity
function verifyWrappedProof(
    bytes calldata wrappedProof,
    bytes32 imageId,
    bytes32 journalDigest
) external view returns (bool);
```

Vì vậy `WRAPPED_STARK_VERIFIER_ADDRESS` phải là địa chỉ một contract adapter do
bạn deploy, và adapter đó phải gọi verifier RISC Zero/Groth16 thật phía sau.

Nguồn địa chỉ verifier RISC Zero chính thức là file deployment của repo
`risc0-ethereum`:

```text
https://github.com/risc0/risc0-ethereum/blob/main/contracts/deployment.toml
```

Tại thời điểm kiểm tra gần nhất, Sepolia có:

```text
RiscZeroGroth16Verifier v3.0.0
selector = 0x73c457ba
verifier = 0x2a098988600d87650Fb061FfAff08B97149Fa84D

RiscZeroSetVerifier v0.9.0
selector = 0x242f9d5b
verifier = 0xcb9D14347b1e816831ECeE46EC199144F360B55c
```

Nhưng không điền thẳng các địa chỉ này vào `WRAPPED_STARK_VERIFIER_ADDRESS` nếu
chúng không implement đúng interface `verifyWrappedProof(...)` ở trên. Cách lấy
đúng biến này là:

```text
1. Chọn verifier RISC Zero/Groth16 Sepolia đúng với SDK/proof bạn dùng.
2. Deploy adapter implement IWrappedStarkVerifier.
3. Adapter gọi verifier RISC Zero chính thức và bind wrappedProof, imageId,
   journalDigest theo format của verifier đó.
4. Lấy địa chỉ adapter vừa deploy điền vào WRAPPED_STARK_VERIFIER_ADDRESS.
```

Nếu chỉ chạy `ecdsa_onchain` hoặc `stark_offchain`, hoặc chưa có adapter, để:

```env
WRAPPED_STARK_VERIFIER_ADDRESS=0x0000000000000000000000000000000000000000
```

Không chạy `stark_wrapped_onchain` khi biến này vẫn là `address(0)`.

## Build

```bash
forge build
forge inspect contracts/ApplicationAuthBenchmark.sol:ApplicationAuthBenchmark abi --json > contracts/ApplicationAuthBenchmarkABI.json
cd risc0 && cargo check -p host
```

Kiểm tra CLI host:

```bash
cd risc0
cargo run -p host -- --help
cargo run -p host -- prove --help
```

## Deploy Contract Lên Sepolia

Trước khi deploy, load `.env` vào shell hiện tại:

```bash
set -a
source .env
set +a
```

Kiểm tra `RPC_URL` đã trỏ tới Sepolia:

```bash
test -n "$RPC_URL" || echo "RPC_URL dang rong"
cast chain-id --rpc-url "$RPC_URL"
```

Kết quả đúng cho Sepolia là:

```text
11155111
```

Nếu lệnh trên cố kết nối `http://localhost:8545`, nghĩa là `.env` chưa được
load hoặc `RPC_URL` trong `.env` vẫn đang là localhost.

Deploy lên Sepolia:

```bash
forge create contracts/ApplicationAuthBenchmark.sol:ApplicationAuthBenchmark \
  --rpc-url "$RPC_URL" \
  --private-key "$SUBMITTER_PRIVATE_KEY" \
  --broadcast \
  --constructor-args "$WRAPPED_STARK_VERIFIER_ADDRESS"
```

Sau đó điền địa chỉ `Deployed to` được in ra vào:

```env
CONTRACT_ADDRESS=0x...
```

Nếu deploy benchmark trước khi có wrapped verifier thật, owner có thể cập nhật
sau bằng `setWrappedStarkVerifier`.

## Chạy Benchmark


Chạy ECDSA verify on-chain:
Trước khi chạy benchmark, đảm bảo `.env` đã có:

```env
RPC_URL=...
SUBMITTER_PRIVATE_KEY=...
CONTRACT_ADDRESS=...
APP_AUTH_PRIVATE_KEY=...
```

Trong cả 3 mode:

```text
APP_AUTH_PRIVATE_KEY
  là credential authorization ở tầng ứng dụng
  được dùng để ký ECDSA hoặc làm private witness cho RISC Zero

SUBMITTER_PRIVATE_KEY
  chỉ dùng để ký Ethereum transaction và trả gas
  không phải đối tượng benchmark authorization
```

Nếu `wrappedStarkVerifier()` trên contract đã được cập nhật sang địa chỉ adapter
khác `address(0)`, hai benchmark `ecdsa_onchain` và `stark_offchain` vẫn hoạt
động bình thường. Verifier wrapped chỉ được dùng khi gọi
`submitWithWrappedStark`, nên nó không ảnh hưởng tới `submitWithECDSA` hoặc
`submitStarkOffchainMetadata`.

### `ecdsa_onchain`

Chạy:

```bash
python3 scripts/ecdsa_onchain_demo.py
```

Chạy STARK feasibility off-chain:
Luồng hoạt động:

```text
1. Script load .env.
2. Build payload mẫu.
3. Tính payload_hash = keccak256(payload).
4. Đọc APP_AUTH_PRIVATE_KEY.
5. Derive app_address theo Ethereum-style address.
6. Build authorization digest với:
   domain, app_address, payload_hash, nonce, chain_id, contract_address.
7. Sign digest off-chain bằng secp256k1/EIP-191.
8. Gửi transaction bằng SUBMITTER_PRIVATE_KEY tới submitWithECDSA.
9. Contract kiểm tra payload hash, nonce, rebuild digest và verify ecrecover.
10. Script ghi benchmark/results/ecdsa_onchain_result.json.
```

On-chain verification thật sự xảy ra ở bước contract gọi `ecrecover`.

### `stark_offchain`

Chạy:

```bash
python3 scripts/stark_offchain_demo.py
```

Hai mode trên không cần wrapped verifier. Nếu benchmark contract được deploy
với `WRAPPED_STARK_VERIFIER_ADDRESS=0x0000000000000000000000000000000000000000`
thì vẫn chạy bình thường.
Luồng hoạt động:

```text
1. Script load .env.
2. Build payload mẫu.
3. Tính payload_hash = keccak256(payload).
4. Đọc APP_AUTH_PRIVATE_KEY.
5. Tính identity_commitment = SHA256(APP_AUTH_PRIVATE_KEY).
6. Gọi RISC Zero host để prove statement:
   authorization_digest = H(domain, identity_commitment, payload_hash,
   nonce, chain_id, contract_address).
7. Host tạo RISC Zero/STARK receipt.
8. Host verify receipt off-chain.
9. Script lưu receipt vào local off-chain store hoặc IPFS nếu cấu hình.
10. Script ghi benchmark/results/stark_offchain_result.json.
```

Mode này không verify STARK proof trên Ethereum. Nó đo:

```text
prove time
off-chain verify time
proof/receipt size
journal size
public input size
```
Tùy chọn gửi STARK metadata lên chain:

python3 scripts/stark_offchain_demo.py --submit-metadata
```

Lệnh trên chỉ lưu `proofHash`/`proofCid` làm metadata. Đây không phải on-chain
proof verification.
Luồng bổ sung khi có `--submit-metadata`:

Chạy wrapped STARK/Groth16 on-chain sau khi đã có verifier adapter thật:
```text
1. Sau khi receipt đã được verify off-chain, script tính proofHash/proofCid.
2. Script gửi transaction tới submitStarkOffchainMetadata.
3. Contract chỉ kiểm tra payload hash, nonce và authorization_digest.
4. Contract lưu proofHash/proofCid làm metadata.
```

`proofHash` và `proofCid` chỉ là metadata phục vụ audit/availability. Đây không
phải on-chain proof verification, và gas của transaction này không được gọi là
STARK verifier gas.

### `stark_wrapped_onchain`

Chạy sau khi đã có verifier adapter thật:


```bash
python3 scripts/stark_wrapped_onchain_demo.py
```
trường RISC Zero/Groth16 phù hợp. Nếu máy local yếu, chạy lệnh này trên máy
khác rồi dùng output để submit hoặc benchmark.

Luồng hoạt động:

```text
1. Script load .env.
2. Build payload mẫu.
3. Tính payload_hash = keccak256(payload).
4. Đọc APP_AUTH_PRIVATE_KEY.
5. Tính identity_commitment = SHA256(APP_AUTH_PRIVATE_KEY).
6. Gọi RISC Zero host với domain STARK_WRAPPED_APP_AUTH_V1.
7. Host tạo RISC Zero/STARK receipt.
8. Host verify receipt off-chain.
9. Host chạy --groth16 để wrap/compress receipt sang Groth16/SNARK form.
10. Host verify wrapped receipt off-chain.
11. Script đọc wrapped proof seal, image_id và journal_digest từ metadata.
12. Script gửi transaction bằng SUBMITTER_PRIVATE_KEY tới submitWithWrappedStark.
13. Contract kiểm tra payload hash, nonce, authorization_digest và journalDigest.
14. Contract gọi wrappedStarkVerifier.verifyWrappedProof(...).
15. Nếu verifier trả true, contract lưu wrapped authorization record.
16. Script ghi benchmark/results/stark_wrapped_onchain_result.json.
```

On-chain verification trong mode này là wrapped proof verification. Đây là
STARK/RISC Zero authorization được wrap sang Groth16/SNARK để verify on-chain,
không phải pure STARK verification trực tiếp trên Ethereum.


## Tạo Báo Cáo So Sánh

```bash
python3 benchmark/compare_application_auth.py
```

Report tách riêng:

```text
Off-chain cost
  ecdsa_onchain
  stark_offchain
  stark_wrapped_onchain

On-chain verifier comparison
  chỉ so ecdsa_onchain với stark_wrapped_onchain
```

## Ghi Chú Về RISC Zero/Groth16

Host CLI hỗ trợ:

```bash
cd risc0
cargo run --release -p host -- prove \
  --domain STARK_WRAPPED_APP_AUTH_V1 \
  --payload-hash 0x... \
  --app-auth-private-key 0x... \
  --nonce 1 \
  --chain-id 31337 \
  --contract-address 0x... \
  --output ../benchmark/results/stark_wrapped_base_receipt.bin \
  --metadata-output ../benchmark/results/stark_wrapped_metadata.json \
  --groth16 \
  --wrapped-output ../benchmark/results/stark_wrapped_groth16_receipt.bin
```

Khi có `--groth16`, host sẽ:

```text
1. tạo RISC Zero/STARK receipt
2. verify receipt off-chain
3. compress/wrap sang Groth16 receipt
4. verify wrapped receipt off-chain
5. ghi raw wrapped proof seal ra file .seal
6. xuất metadata gồm image_id, journal, journal_digest
```

Không dùng proof giả. Không coi `proofHash` hoặc `proofCid` là on-chain proof
verification.
