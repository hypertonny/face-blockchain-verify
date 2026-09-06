// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title FaceVerifyRegistry
/// @notice Tamper-evident anchor log for face-verification records.
/// @dev Stores NOTHING personal: only the SHA-256 of the canonical
///      off-chain record (face embedding hash + match post URL live in
///      out/record.json). First write wins; history is immutable.
contract FaceVerifyRegistry {
    struct Anchor {
        address submitter;   // account that anchored the record
        uint64 timestamp;    // block timestamp of anchoring
        string matchUrl;     // public social-media post URL (≤ 256 chars)
        bool exists;
    }

    mapping(bytes32 => Anchor) private _anchors;
    uint256 public totalAnchored;

    event Anchored(bytes32 indexed recordHash, address indexed submitter,
                   string matchUrl, uint64 timestamp);

    error EmptyHash();
    error AlreadyAnchored(bytes32 recordHash);
    error UrlTooLong();

    /// @param recordHash SHA-256 (32 bytes) of the canonical record JSON.
    /// @param matchUrl Public post URL of the verified social-media match.
    function anchor(bytes32 recordHash, string calldata matchUrl) external {
        if (recordHash == bytes32(0)) revert EmptyHash();
        if (_anchors[recordHash].exists) revert AlreadyAnchored(recordHash);
        if (bytes(matchUrl).length > 256) revert UrlTooLong();
        uint64 ts = uint64(block.timestamp);
        _anchors[recordHash] = Anchor(msg.sender, ts, matchUrl, true);
        totalAnchored += 1;
        emit Anchored(recordHash, msg.sender, matchUrl, ts);
    }

    function get(bytes32 recordHash)
        external view returns (address submitter, uint64 timestamp,
                               string memory matchUrl, bool exists)
    {
        Anchor storage a = _anchors[recordHash];
        return (a.submitter, a.timestamp, a.matchUrl, a.exists);
    }
}
