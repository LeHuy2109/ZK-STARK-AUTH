use std::{
    fs,
    path::{Path, PathBuf},
    time::Instant,
};

use anyhow::{anyhow, bail, Context, Result};
use clap::{Parser, Subcommand};
use methods::{METHOD_ELF, METHOD_ID};
use risc0_ethereum_contracts::encode_seal;
use risc0_zkvm::{
    default_prover,
    sha::{self, Sha256 as Risc0Sha256},
    Digest as Risc0Digest, ExecutorEnv, InnerReceipt, ProverOpts, Receipt,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

const DEFAULT_STARK_DOMAIN: &str = "STARK_APP_AUTH_V1";

#[derive(Parser)]
#[command(author, version, about = "RISC Zero application authorization prover")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Generate and off-chain verify a RISC Zero/STARK receipt.
    Prove(ProveArgs),
    /// Verify a receipt off-chain against expected public inputs.
    Verify(VerifyArgs),
}

#[derive(Parser)]
struct ProveArgs {
    #[arg(long, default_value = DEFAULT_STARK_DOMAIN)]
    domain: String,
    #[arg(long)]
    payload_hash: String,
    #[arg(long)]
    app_auth_private_key: String,
    #[arg(long)]
    nonce: String,
    #[arg(long)]
    chain_id: String,
    #[arg(long)]
    contract_address: String,
    #[arg(long)]
    output: PathBuf,
    #[arg(long)]
    metadata_output: PathBuf,
    /// Wrap/compress the RISC Zero receipt into Groth16/SNARK form.
    #[arg(long)]
    groth16: bool,
    /// Output path for the wrapped Groth16 receipt. The raw seal is also written beside it.
    #[arg(long)]
    wrapped_output: Option<PathBuf>,
}

#[derive(Parser)]
struct VerifyArgs {
    #[arg(long)]
    receipt: PathBuf,
    #[arg(long, default_value = DEFAULT_STARK_DOMAIN)]
    domain: String,
    #[arg(long)]
    payload_hash: String,
    #[arg(long)]
    identity_commitment: String,
    #[arg(long)]
    authorization_digest: String,
    #[arg(long)]
    nonce: String,
    #[arg(long)]
    chain_id: String,
    #[arg(long)]
    contract_address: String,
    #[arg(long)]
    metadata_output: Option<PathBuf>,
}

#[derive(Serialize)]
struct AuthorizationInput {
    domain: String,
    app_auth_private_key: [u8; 32],
    payload_hash: [u8; 32],
    nonce: [u8; 32],
    chain_id: [u8; 32],
    contract_address: [u8; 20],
}

#[derive(Debug, Deserialize, Serialize)]
struct AuthorizationJournal {
    domain: String,
    identity_commitment: [u8; 32],
    authorization_digest: [u8; 32],
    payload_hash: [u8; 32],
    nonce: [u8; 32],
    chain_id: [u8; 32],
    contract_address: [u8; 20],
}

#[derive(Serialize)]
struct Metadata {
    mode: String,
    domain: String,
    image_id: String,
    journal: String,
    journal_digest: String,
    identity_commitment: String,
    authorization_digest: String,
    payload_hash: String,
    nonce: String,
    chain_id: String,
    contract_address: String,
    receipt_path: Option<String>,
    receipt_size_bytes: Option<u64>,
    journal_size_bytes: usize,
    public_input_size_bytes: usize,
    receipt_sha256: Option<String>,
    prove_seconds: Option<f64>,
    verify_seconds: f64,
    groth16_requested: bool,
    wrapped_receipt_path: Option<String>,
    wrapped_proof_path: Option<String>,
    wrapped_raw_proof_path: Option<String>,
    wrapped_proof_size_bytes: Option<u64>,
    wrapped_raw_proof_size_bytes: Option<u64>,
    wrap_seconds: Option<f64>,
    verifier_parameters: Option<String>,
    note: String,
}

fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::filter::EnvFilter::from_default_env())
        .init();

    match Cli::parse().command {
        Command::Prove(args) => prove(args),
        Command::Verify(args) => verify(args),
    }
}

fn prove(args: ProveArgs) -> Result<()> {
    if args.wrapped_output.is_some() && !args.groth16 {
        bail!("--wrapped-output requires --groth16");
    }

    let input = AuthorizationInput {
        domain: args.domain.clone(),
        app_auth_private_key: parse_hex_32(&args.app_auth_private_key, "app_auth_private_key")?,
        payload_hash: parse_hex_32(&args.payload_hash, "payload_hash")?,
        nonce: parse_u256_be(&args.nonce, "nonce")?,
        chain_id: parse_u256_be(&args.chain_id, "chain_id")?,
        contract_address: parse_address(&args.contract_address)?,
    };

    let env = ExecutorEnv::builder()
        .write(&input)
        .context("failed to write guest input")?
        .build()
        .context("failed to build executor environment")?;

    let prover = default_prover();
    let prove_start = Instant::now();
    let prove_info = prover
        .prove(env, METHOD_ELF)
        .context("RISC Zero proving failed")?;
    let prove_seconds = prove_start.elapsed().as_secs_f64();
    let stark_receipt = prove_info.receipt;

    write_receipt(&args.output, &stark_receipt)?;
    let verify_start = Instant::now();
    let journal =
        verify_receipt_public_inputs(&stark_receipt, &ExpectedInputs::from_prove_args(&args)?)?;
    let verify_seconds = verify_start.elapsed().as_secs_f64();
    let receipt_bytes = fs::read(&args.output).context("failed to re-read receipt")?;

    let mut wrapped_receipt_path = None;
    let mut wrapped_proof_path = None;
    let mut wrapped_raw_proof_path = None;
    let mut wrapped_proof_size_bytes = None;
    let mut wrapped_raw_proof_size_bytes = None;
    let mut wrap_seconds = None;
    let mut verifier_parameters = None;

    if args.groth16 {
        let wrapped_output = args
            .wrapped_output
            .as_ref()
            .ok_or_else(|| anyhow!("--wrapped-output is required with --groth16"))?;
        let wrap_start = Instant::now();
        let wrapped_receipt = prover
            .compress(&ProverOpts::groth16(), &stark_receipt)
            .context("RISC Zero Groth16 wrapping failed")?;
        wrap_seconds = Some(wrap_start.elapsed().as_secs_f64());
        wrapped_receipt
            .verify(METHOD_ID)
            .context("failed to verify wrapped Groth16 receipt off-chain")?;
        write_receipt(wrapped_output, &wrapped_receipt)?;

        let groth16_receipt = match &wrapped_receipt.inner {
            InnerReceipt::Groth16(receipt) => receipt,
            _ => bail!("RISC Zero returned a non-Groth16 receipt for --groth16"),
        };
        let seal_path = wrapped_output.with_extension("seal");
        let evm_seal = encode_seal(&wrapped_receipt)
            .context("failed to encode Groth16 seal for EVM verifier")?;
        fs::write(&seal_path, &evm_seal)
            .with_context(|| format!("failed to write {}", seal_path.display()))?;
        let raw_seal_path = wrapped_output.with_extension("raw-seal");
        fs::write(&raw_seal_path, &groth16_receipt.seal)
            .with_context(|| format!("failed to write {}", raw_seal_path.display()))?;
        wrapped_receipt_path = Some(wrapped_output.as_path());
        wrapped_proof_path = Some(seal_path);
        wrapped_raw_proof_path = Some(raw_seal_path);
        wrapped_proof_size_bytes = Some(evm_seal.len() as u64);
        wrapped_raw_proof_size_bytes = Some(groth16_receipt.seal.len() as u64);
        verifier_parameters = Some(digest_hex(groth16_receipt.verifier_parameters));
    }

    let metadata = build_metadata(MetadataInput {
        mode: if args.groth16 {
            "stark_wrapped_onchain"
        } else {
            "stark_offchain"
        },
        journal: &journal,
        receipt_path: Some(&args.output),
        receipt_size_bytes: Some(receipt_bytes.len() as u64),
        receipt_sha256: Some(hex32(Sha256::digest(&receipt_bytes).into())),
        prove_seconds: Some(prove_seconds),
        verify_seconds,
        groth16_requested: args.groth16,
        wrapped_receipt_path,
        wrapped_proof_path: wrapped_proof_path.as_deref(),
        wrapped_raw_proof_path: wrapped_raw_proof_path.as_deref(),
        wrapped_proof_size_bytes,
        wrapped_raw_proof_size_bytes,
        wrap_seconds,
        verifier_parameters,
    })?;
    write_metadata(&args.metadata_output, &metadata)?;
    println!("{}", serde_json::to_string_pretty(&metadata)?);
    Ok(())
}

fn verify(args: VerifyArgs) -> Result<()> {
    let receipt = read_receipt(&args.receipt)?;
    let expected = ExpectedInputs::from_verify_args(&args)?;
    let verify_start = Instant::now();
    let journal = verify_receipt_public_inputs(&receipt, &expected)?;
    let verify_seconds = verify_start.elapsed().as_secs_f64();
    let receipt_bytes = fs::read(&args.receipt).context("failed to re-read receipt")?;
    let metadata = build_metadata(MetadataInput {
        mode: "stark_offchain_verify",
        journal: &journal,
        receipt_path: Some(&args.receipt),
        receipt_size_bytes: Some(receipt_bytes.len() as u64),
        receipt_sha256: Some(hex32(Sha256::digest(&receipt_bytes).into())),
        prove_seconds: None,
        verify_seconds,
        groth16_requested: false,
        wrapped_receipt_path: None,
        wrapped_proof_path: None,
        wrapped_raw_proof_path: None,
        wrapped_proof_size_bytes: None,
        wrapped_raw_proof_size_bytes: None,
        wrap_seconds: None,
        verifier_parameters: None,
    })?;

    if let Some(path) = args.metadata_output {
        write_metadata(&path, &metadata)?;
    }
    println!("{}", serde_json::to_string_pretty(&metadata)?);
    Ok(())
}

struct ExpectedInputs {
    domain: String,
    payload_hash: [u8; 32],
    identity_commitment: Option<[u8; 32]>,
    authorization_digest: Option<[u8; 32]>,
    nonce: [u8; 32],
    chain_id: [u8; 32],
    contract_address: [u8; 20],
}

impl ExpectedInputs {
    fn from_prove_args(args: &ProveArgs) -> Result<Self> {
        Ok(Self {
            domain: args.domain.clone(),
            payload_hash: parse_hex_32(&args.payload_hash, "payload_hash")?,
            identity_commitment: None,
            authorization_digest: None,
            nonce: parse_u256_be(&args.nonce, "nonce")?,
            chain_id: parse_u256_be(&args.chain_id, "chain_id")?,
            contract_address: parse_address(&args.contract_address)?,
        })
    }

    fn from_verify_args(args: &VerifyArgs) -> Result<Self> {
        Ok(Self {
            domain: args.domain.clone(),
            payload_hash: parse_hex_32(&args.payload_hash, "payload_hash")?,
            identity_commitment: Some(parse_hex_32(
                &args.identity_commitment,
                "identity_commitment",
            )?),
            authorization_digest: Some(parse_hex_32(
                &args.authorization_digest,
                "authorization_digest",
            )?),
            nonce: parse_u256_be(&args.nonce, "nonce")?,
            chain_id: parse_u256_be(&args.chain_id, "chain_id")?,
            contract_address: parse_address(&args.contract_address)?,
        })
    }
}

fn verify_receipt_public_inputs(
    receipt: &Receipt,
    expected: &ExpectedInputs,
) -> Result<AuthorizationJournal> {
    receipt
        .verify(METHOD_ID)
        .context("receipt image ID verification failed")?;
    let journal = decode_journal(&receipt.journal.bytes, &expected.domain)
        .context("failed to decode receipt journal")?;

    ensure_equal(
        &journal.payload_hash,
        &expected.payload_hash,
        "payload_hash",
    )?;
    ensure_equal(&journal.nonce, &expected.nonce, "nonce")?;
    ensure_equal(&journal.chain_id, &expected.chain_id, "chain_id")?;
    ensure_equal(
        &journal.contract_address,
        &expected.contract_address,
        "contract_address",
    )?;

    if let Some(identity_commitment) = expected.identity_commitment {
        ensure_equal(
            &journal.identity_commitment,
            &identity_commitment,
            "identity_commitment",
        )?;
    }
    if let Some(authorization_digest) = expected.authorization_digest {
        ensure_equal(
            &journal.authorization_digest,
            &authorization_digest,
            "authorization_digest",
        )?;
    }

    Ok(journal)
}

struct MetadataInput<'a> {
    mode: &'a str,
    journal: &'a AuthorizationJournal,
    receipt_path: Option<&'a Path>,
    receipt_size_bytes: Option<u64>,
    receipt_sha256: Option<String>,
    prove_seconds: Option<f64>,
    verify_seconds: f64,
    groth16_requested: bool,
    wrapped_receipt_path: Option<&'a Path>,
    wrapped_proof_path: Option<&'a Path>,
    wrapped_raw_proof_path: Option<&'a Path>,
    wrapped_proof_size_bytes: Option<u64>,
    wrapped_raw_proof_size_bytes: Option<u64>,
    wrap_seconds: Option<f64>,
    verifier_parameters: Option<String>,
}

fn build_metadata(input: MetadataInput<'_>) -> Result<Metadata> {
    let journal_bytes = encode_journal(input.journal);
    Ok(Metadata {
        mode: input.mode.to_owned(),
        domain: input.journal.domain.clone(),
        image_id: method_id_hex(),
        journal: hex_bytes(&journal_bytes),
        journal_digest: digest_hex(*sha::Impl::hash_bytes(&journal_bytes)),
        identity_commitment: hex32(input.journal.identity_commitment),
        authorization_digest: hex32(input.journal.authorization_digest),
        payload_hash: hex32(input.journal.payload_hash),
        nonce: u256_decimal(&input.journal.nonce),
        chain_id: u256_decimal(&input.journal.chain_id),
        contract_address: format!("0x{}", hex::encode(input.journal.contract_address)),
        receipt_path: input.receipt_path.map(|path| path.display().to_string()),
        receipt_size_bytes: input.receipt_size_bytes,
        journal_size_bytes: journal_bytes.len(),
        public_input_size_bytes: 32 + 32 + 32 + 32 + 32 + 20,
        receipt_sha256: input.receipt_sha256,
        prove_seconds: input.prove_seconds,
        verify_seconds: input.verify_seconds,
        groth16_requested: input.groth16_requested,
        wrapped_receipt_path: input
            .wrapped_receipt_path
            .map(|path| path.display().to_string()),
        wrapped_proof_path: input
            .wrapped_proof_path
            .map(|path| path.display().to_string()),
        wrapped_raw_proof_path: input
            .wrapped_raw_proof_path
            .map(|path| path.display().to_string()),
        wrapped_proof_size_bytes: input.wrapped_proof_size_bytes,
        wrapped_raw_proof_size_bytes: input.wrapped_raw_proof_size_bytes,
        wrap_seconds: input.wrap_seconds,
        verifier_parameters: input.verifier_parameters,
        note: if input.groth16_requested {
            "RISC Zero/STARK receipt wrapped into Groth16; on-chain verification must use the wrapped verifier"
        } else {
            "RISC Zero/STARK receipt verified off-chain; no STARK proof is verified on-chain"
        }
        .to_owned(),
    })
}

fn write_receipt(path: &Path, receipt: &Receipt) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("failed to create {}", parent.display()))?;
    }
    let encoded = bincode::serialize(receipt).context("failed to serialize receipt")?;
    fs::write(path, encoded).with_context(|| format!("failed to write {}", path.display()))
}

fn read_receipt(path: &Path) -> Result<Receipt> {
    let encoded = fs::read(path).with_context(|| format!("failed to read {}", path.display()))?;
    bincode::deserialize(&encoded).context("failed to deserialize receipt")
}

fn write_metadata(path: &Path, metadata: &Metadata) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("failed to create {}", parent.display()))?;
    }
    let encoded = serde_json::to_vec_pretty(metadata).context("failed to encode metadata")?;
    fs::write(path, encoded).with_context(|| format!("failed to write {}", path.display()))
}

fn encode_journal(journal: &AuthorizationJournal) -> Vec<u8> {
    let mut out = Vec::with_capacity(journal.domain.len() + 180);
    out.extend_from_slice(journal.domain.as_bytes());
    out.extend_from_slice(&journal.identity_commitment);
    out.extend_from_slice(&journal.authorization_digest);
    out.extend_from_slice(&journal.payload_hash);
    out.extend_from_slice(&journal.nonce);
    out.extend_from_slice(&journal.chain_id);
    out.extend_from_slice(&journal.contract_address);
    out
}

fn decode_journal(data: &[u8], domain: &str) -> Result<AuthorizationJournal> {
    let domain_bytes = domain.as_bytes();
    if data.len() != domain_bytes.len() + 180 {
        bail!(
            "journal length mismatch: expected {}, got {}",
            domain_bytes.len() + 180,
            data.len()
        );
    }
    if &data[..domain_bytes.len()] != domain_bytes {
        bail!("journal domain mismatch");
    }

    let mut offset = domain_bytes.len();
    Ok(AuthorizationJournal {
        domain: domain.to_owned(),
        identity_commitment: take_array::<32>(data, &mut offset)?,
        authorization_digest: take_array::<32>(data, &mut offset)?,
        payload_hash: take_array::<32>(data, &mut offset)?,
        nonce: take_array::<32>(data, &mut offset)?,
        chain_id: take_array::<32>(data, &mut offset)?,
        contract_address: take_array::<20>(data, &mut offset)?,
    })
}

fn take_array<const N: usize>(data: &[u8], offset: &mut usize) -> Result<[u8; N]> {
    let end = *offset + N;
    if end > data.len() {
        bail!("journal truncated");
    }
    let chunk = data[*offset..end]
        .try_into()
        .map_err(|_| anyhow!("journal slice length mismatch"))?;
    *offset = end;
    Ok(chunk)
}

fn parse_hex_32(value: &str, field_name: &str) -> Result<[u8; 32]> {
    parse_fixed_hex(value, field_name)
}

fn parse_address(value: &str) -> Result<[u8; 20]> {
    parse_fixed_hex(value, "contract_address")
}

fn parse_fixed_hex<const N: usize>(value: &str, field_name: &str) -> Result<[u8; N]> {
    let raw = value.strip_prefix("0x").unwrap_or(value);
    let decoded = hex::decode(raw).with_context(|| format!("{field_name} is not valid hex"))?;
    if decoded.len() != N {
        bail!("{field_name} must be {N} bytes, got {}", decoded.len());
    }
    decoded
        .try_into()
        .map_err(|_| anyhow!("{field_name} length check failed"))
}

fn parse_u256_be(value: &str, field_name: &str) -> Result<[u8; 32]> {
    if value.starts_with("0x") {
        return parse_hex_32(value, field_name);
    }
    if value.is_empty() {
        bail!("{field_name} is required");
    }

    let mut out = [0u8; 32];
    for byte in value.bytes() {
        if !byte.is_ascii_digit() {
            bail!("{field_name} must be a decimal uint256 or 0x-prefixed bytes32");
        }
        mul_u256_small(&mut out, 10)?;
        add_u256_small(&mut out, byte - b'0')?;
    }
    Ok(out)
}

fn mul_u256_small(value: &mut [u8; 32], factor: u8) -> Result<()> {
    let mut carry = 0u16;
    for byte in value.iter_mut().rev() {
        let product = (*byte as u16) * (factor as u16) + carry;
        *byte = (product & 0xff) as u8;
        carry = product >> 8;
    }
    if carry != 0 {
        bail!("uint256 overflow");
    }
    Ok(())
}

fn add_u256_small(value: &mut [u8; 32], addend: u8) -> Result<()> {
    let mut carry = addend as u16;
    for byte in value.iter_mut().rev() {
        let sum = (*byte as u16) + carry;
        *byte = (sum & 0xff) as u8;
        carry = sum >> 8;
        if carry == 0 {
            return Ok(());
        }
    }
    bail!("uint256 overflow")
}

fn u256_decimal(value: &[u8; 32]) -> String {
    if value.iter().all(|byte| *byte == 0) {
        return "0".to_owned();
    }

    let mut tmp = *value;
    let mut digits = Vec::new();
    while tmp.iter().any(|byte| *byte != 0) {
        let remainder = div_u256_small(&mut tmp, 10);
        digits.push((b'0' + remainder) as char);
    }
    digits.iter().rev().collect()
}

fn div_u256_small(value: &mut [u8; 32], divisor: u8) -> u8 {
    let mut remainder = 0u16;
    for byte in value.iter_mut() {
        let current = (remainder << 8) | (*byte as u16);
        *byte = (current / divisor as u16) as u8;
        remainder = current % divisor as u16;
    }
    remainder as u8
}

fn hex32(value: [u8; 32]) -> String {
    format!("0x{}", hex::encode(value))
}

fn hex_bytes(value: &[u8]) -> String {
    format!("0x{}", hex::encode(value))
}

fn digest_hex(value: Risc0Digest) -> String {
    format!("0x{}", hex::encode(value.as_bytes()))
}

fn method_id_hex() -> String {
    let mut bytes = Vec::with_capacity(32);
    for word in METHOD_ID {
        bytes.extend_from_slice(&word.to_le_bytes());
    }
    hex_bytes(&bytes)
}

fn ensure_equal<T>(actual: &T, expected: &T, field_name: &str) -> Result<()>
where
    T: PartialEq + std::fmt::Debug,
{
    if actual != expected {
        bail!(
            "{field_name} mismatch: actual={:?}, expected={:?}",
            actual,
            expected
        );
    }
    Ok(())
}
