// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title FaceVerifyRegistry
/// @notice Tamper-evident, hash-chained anchor log for face-verification
///         records. Each new anchor must reference the submitter's previous
///         record hash, so every task builds on the hash of the one before.
/// @dev Stores NOTHING personal: only the SHA-256 of the canonical
///      off-chain record (face embedding hash + match post URL live in
///      out/record.json). First write wins per hash; history is immutable.
contract FaceVerifyRegistry {
    struct Anchor {
        address submitter;   // account that anchored the record
        uint64 timestamp;    // block timestamp of anchoring
        string matchUrl;     // public social-media post URL (≤ 256 chars)
        bytes32 prevHash;    // submitter's previous record (0x0 for genesis)
        bool exists;
    }

    mapping(bytes32 => Anchor) private _anchors;
    /// @notice Latest record hash per submitter — the link new tasks extend.
    mapping(address => bytes32) public latestBySubmitter;
    uint256 public totalAnchored;

    event Anchored(bytes32 indexed recordHash, address indexed submitter,
                   bytes32 prevHash, string matchUrl, uint64 timestamp);

    error EmptyHash();
    error AlreadyAnchored(bytes32 recordHash);
    error UrlTooLong();
    error BadPrevHash(bytes32 expected);

    /// @param recordHash SHA-256 (32 bytes) of the canonical record JSON.
    /// @param matchUrl Public post URL of the verified social-media match.
    /// @param prevHash Caller's previous record hash (0x0 for the first
    ///        task). Must equal latestBySubmitter[msg.sender].
    function anchor(bytes32 recordHash, string calldata matchUrl,
                    bytes32 prevHash) external {
        if (recordHash == bytes32(0)) revert EmptyHash();
        if (_anchors[recordHash].exists) revert AlreadyAnchored(recordHash);
        if (bytes(matchUrl).length > 256) revert UrlTooLong();
        bytes32 expected = latestBySubmitter[msg.sender];
        if (prevHash != expected) revert BadPrevHash(expected);
        uint64 ts = uint64(block.timestamp);
        _anchors[recordHash] = Anchor(msg.sender, ts, matchUrl, prevHash,
                                      true);
        latestBySubmitter[msg.sender] = recordHash;
        totalAnchored += 1;
        emit Anchored(recordHash, msg.sender, prevHash, matchUrl, ts);
    }

    function get(bytes32 recordHash)
        external view returns (address submitter, uint64 timestamp,
                               string memory matchUrl, bytes32 prevHash,
                               bool exists)
    {
        Anchor storage a = _anchors[recordHash];
        return (a.submitter, a.timestamp, a.matchUrl, a.prevHash, a.exists);
    }
}
