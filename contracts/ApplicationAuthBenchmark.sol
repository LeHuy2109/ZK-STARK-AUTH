// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Application-level authorization benchmark
/// @notice Compares application ECDSA verification, STARK metadata storage,
///         and wrapped STARK/Groth16 verification.
///         The STARK off-chain mode stores proof references only; it does not
///         verify a STARK proof on-chain.
contract ApplicationAuthBenchmark {
    string public constant ECDSA_DOMAIN = "ECDSA_APP_AUTH_V1";
    string public constant STARK_DOMAIN = "STARK_APP_AUTH_V1";
    string public constant STARK_WRAPPED_DOMAIN = "STARK_WRAPPED_APP_AUTH_V1";

    address public owner;
    IWrappedStarkVerifier public wrappedStarkVerifier;

    struct EcdsaRecord {
        uint256 recordId;
        address appSigner;
        address submitter;
        bytes payload;
        bytes32 payloadHash;
        bytes32 authDigest;
        uint256 nonce;
        uint256 timestamp;
        bytes signature;
    }

    struct StarkOffchainRecord {
        uint256 recordId;
        bytes32 identityCommitment;
        address submitter;
        bytes payload;
        bytes32 payloadHash;
        bytes32 authorizationDigest;
        bytes32 proofHash;
        uint256 nonce;
        uint256 timestamp;
        string proofCid;
    }

    struct StarkWrappedRecord {
        uint256 recordId;
        bytes32 identityCommitment;
        address submitter;
        bytes payload;
        bytes32 payloadHash;
        bytes32 authorizationDigest;
        uint256 nonce;
        uint256 timestamp;
        bytes wrappedProof;
        bytes32 imageId;
        bytes32 journalDigest;
    }

    uint256 public nextEcdsaRecordId = 1;
    uint256 public nextStarkOffchainRecordId = 1;
    uint256 public nextStarkWrappedRecordId = 1;

    mapping(uint256 => EcdsaRecord) public ecdsaRecords;
    mapping(uint256 => StarkOffchainRecord) public starkOffchainRecords;
    mapping(uint256 => StarkWrappedRecord) public starkWrappedRecords;
    mapping(address => mapping(uint256 => bool)) public usedEcdsaNonce;
    mapping(bytes32 => mapping(uint256 => bool)) public usedStarkOffchainNonce;
    mapping(bytes32 => mapping(uint256 => bool)) public usedStarkWrappedNonce;

    event EcdsaAuthorizationSubmitted(
        uint256 indexed recordId,
        address indexed appSigner,
        address indexed submitter,
        bytes32 payloadHash,
        bytes32 authDigest,
        uint256 nonce
    );

    event StarkOffchainMetadataSubmitted(
        uint256 indexed recordId,
        bytes32 indexed identityCommitment,
        address indexed submitter,
        bytes32 payloadHash,
        bytes32 authorizationDigest,
        bytes32 proofHash,
        uint256 nonce,
        string proofCid
    );

    event WrappedStarkVerifierUpdated(address indexed verifier);

    event WrappedStarkAuthorizationSubmitted(
        uint256 indexed recordId,
        bytes32 indexed identityCommitment,
        address indexed submitter,
        bytes32 payloadHash,
        bytes32 authorizationDigest,
        bytes32 imageId,
        bytes32 journalDigest,
        uint256 nonce
    );

    modifier onlyOwner() {
        require(msg.sender == owner, "only owner");
        _;
    }

    constructor(address initialWrappedStarkVerifier) {
        owner = msg.sender;
        wrappedStarkVerifier = IWrappedStarkVerifier(initialWrappedStarkVerifier);
        emit WrappedStarkVerifierUpdated(initialWrappedStarkVerifier);
    }

    function setWrappedStarkVerifier(address verifier) external onlyOwner {
        wrappedStarkVerifier = IWrappedStarkVerifier(verifier);
        emit WrappedStarkVerifierUpdated(verifier);
    }

    function submitWithECDSA(
        bytes calldata payload,
        bytes32 payloadHash,
        address appSigner,
        uint256 nonce,
        bytes calldata signature
    ) external returns (uint256 recordId) {
        require(keccak256(payload) == payloadHash, "payload hash mismatch");
        require(appSigner != address(0), "app signer required");
        require(!usedEcdsaNonce[appSigner][nonce], "stale nonce");

        bytes32 authDigest = buildEcdsaDigest(appSigner, payloadHash, nonce);
        bytes32 ethSignedDigest = toEthSignedMessageHash(authDigest);
        address recovered = recoverSigner(ethSignedDigest, signature);
        require(recovered == appSigner, "invalid signature");

        usedEcdsaNonce[appSigner][nonce] = true;
        recordId = nextEcdsaRecordId++;
        ecdsaRecords[recordId] = EcdsaRecord({
            recordId: recordId,
            appSigner: appSigner,
            submitter: msg.sender,
            payload: payload,
            payloadHash: payloadHash,
            authDigest: authDigest,
            nonce: nonce,
            timestamp: block.timestamp,
            signature: signature
        });

        emit EcdsaAuthorizationSubmitted(
            recordId,
            appSigner,
            msg.sender,
            payloadHash,
            authDigest,
            nonce
        );
    }

    /// @notice Stores metadata for an off-chain verified RISC Zero/STARK receipt.
    ///         proofHash and proofCid are availability/audit metadata only, not
    ///         trustless on-chain proof verification.
    function submitStarkOffchainMetadata(
        bytes calldata payload,
        bytes32 payloadHash,
        bytes32 identityCommitment,
        bytes32 authorizationDigest,
        bytes32 proofHash,
        uint256 nonce,
        string calldata proofCid
    ) external returns (uint256 recordId) {
        require(keccak256(payload) == payloadHash, "payload hash mismatch");
        require(identityCommitment != bytes32(0), "identity required");
        require(proofHash != bytes32(0), "proof hash required");
        require(!usedStarkOffchainNonce[identityCommitment][nonce], "stale nonce");
        require(
            authorizationDigest == buildStarkOffchainDigest(identityCommitment, payloadHash, nonce),
            "authorization digest mismatch"
        );

        usedStarkOffchainNonce[identityCommitment][nonce] = true;
        recordId = nextStarkOffchainRecordId++;
        starkOffchainRecords[recordId] = StarkOffchainRecord({
            recordId: recordId,
            identityCommitment: identityCommitment,
            submitter: msg.sender,
            payload: payload,
            payloadHash: payloadHash,
            authorizationDigest: authorizationDigest,
            proofHash: proofHash,
            nonce: nonce,
            timestamp: block.timestamp,
            proofCid: proofCid
        });

        emit StarkOffchainMetadataSubmitted(
            recordId,
            identityCommitment,
            msg.sender,
            payloadHash,
            authorizationDigest,
            proofHash,
            nonce,
            proofCid
        );
    }

    /// @notice Verifies a Groth16/SNARK-wrapped RISC Zero/STARK receipt on-chain.
    ///         This is wrapped proof verification, not pure STARK verification.
    function submitWithWrappedStark(
        bytes calldata payload,
        bytes32 payloadHash,
        bytes32 identityCommitment,
        bytes32 authorizationDigest,
        uint256 nonce,
        bytes calldata wrappedProof,
        bytes32 imageId,
        bytes32 journalDigest
    ) external returns (uint256 recordId) {
        require(address(wrappedStarkVerifier) != address(0), "wrapped verifier not set");
        require(keccak256(payload) == payloadHash, "payload hash mismatch");
        require(identityCommitment != bytes32(0), "identity required");
        require(wrappedProof.length != 0, "wrapped proof required");
        require(!usedStarkWrappedNonce[identityCommitment][nonce], "stale nonce");
        require(
            authorizationDigest == buildWrappedStarkDigest(identityCommitment, payloadHash, nonce),
            "authorization digest mismatch"
        );

        bytes memory journal = buildWrappedStarkJournal(
            identityCommitment,
            authorizationDigest,
            payloadHash,
            nonce
        );
        require(sha256(journal) == journalDigest, "journal digest mismatch");
        require(
            wrappedStarkVerifier.verifyWrappedProof(wrappedProof, imageId, journalDigest),
            "invalid wrapped proof"
        );

        usedStarkWrappedNonce[identityCommitment][nonce] = true;
        recordId = nextStarkWrappedRecordId++;
        starkWrappedRecords[recordId] = StarkWrappedRecord({
            recordId: recordId,
            identityCommitment: identityCommitment,
            submitter: msg.sender,
            payload: payload,
            payloadHash: payloadHash,
            authorizationDigest: authorizationDigest,
            nonce: nonce,
            timestamp: block.timestamp,
            wrappedProof: wrappedProof,
            imageId: imageId,
            journalDigest: journalDigest
        });

        emit WrappedStarkAuthorizationSubmitted(
            recordId,
            identityCommitment,
            msg.sender,
            payloadHash,
            authorizationDigest,
            imageId,
            journalDigest,
            nonce
        );
    }

    function buildEcdsaDigest(
        address appSigner,
        bytes32 payloadHash,
        uint256 nonce
    ) public view returns (bytes32) {
        return keccak256(
            abi.encode(
                ECDSA_DOMAIN,
                appSigner,
                payloadHash,
                nonce,
                block.chainid,
                address(this)
            )
        );
    }

    function buildStarkOffchainDigest(
        bytes32 identityCommitment,
        bytes32 payloadHash,
        uint256 nonce
    ) public view returns (bytes32) {
        return sha256(
            abi.encodePacked(
                bytes(STARK_DOMAIN),
                identityCommitment,
                payloadHash,
                nonce,
                block.chainid,
                address(this)
            )
        );
    }

    function buildWrappedStarkDigest(
        bytes32 identityCommitment,
        bytes32 payloadHash,
        uint256 nonce
    ) public view returns (bytes32) {
        return sha256(
            abi.encodePacked(
                bytes(STARK_WRAPPED_DOMAIN),
                identityCommitment,
                payloadHash,
                nonce,
                block.chainid,
                address(this)
            )
        );
    }

    function buildWrappedStarkJournal(
        bytes32 identityCommitment,
        bytes32 authorizationDigest,
        bytes32 payloadHash,
        uint256 nonce
    ) public view returns (bytes memory) {
        return abi.encodePacked(
            bytes(STARK_WRAPPED_DOMAIN),
            identityCommitment,
            authorizationDigest,
            payloadHash,
            nonce,
            block.chainid,
            address(this)
        );
    }

    function toEthSignedMessageHash(bytes32 digest) public pure returns (bytes32) {
        return keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", digest));
    }

    function recoverSigner(bytes32 digest, bytes calldata signature) public pure returns (address) {
        require(signature.length == 65, "signature length");

        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := calldataload(signature.offset)
            s := calldataload(add(signature.offset, 32))
            v := byte(0, calldataload(add(signature.offset, 64)))
        }

        if (v < 27) {
            v += 27;
        }
        require(v == 27 || v == 28, "signature v");

        return ecrecover(digest, v, r, s);
    }
}

interface IWrappedStarkVerifier {
    /// @notice Adapter interface for a real RISC Zero/Groth16 verifier contract.
    /// @dev Implementations must verify the wrapped Groth16 seal against the RISC Zero
    ///      image ID and journal digest. Returning true is treated as on-chain wrapped
    ///      proof verification.
    function verifyWrappedProof(
        bytes calldata wrappedProof,
        bytes32 imageId,
        bytes32 journalDigest
    ) external view returns (bool);
}
