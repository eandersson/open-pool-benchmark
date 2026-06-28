"""Unit tests for the pure helpers in the regtest backend (the RPC-driven parts run live)."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from openbench import regtest

# /openbench/ as ASCII hex, the tag a pool embeds in its coinbase scriptSig.
_TAG_HEX = "2f6f70656e62656e63682f"


def _getblock(address: str, coinbase_sig: str) -> str:
    block = {"tx": [{"vin": [{"coinbase": coinbase_sig}], "vout": [{"scriptPubKey": {}}]}]}
    if address:
        block["tx"][0]["vout"][0]["scriptPubKey"]["address"] = address
    return json.dumps(block)


def _backend(getblock_json: str) -> regtest.Backend:
    backend = regtest.Backend.__new__(regtest.Backend)
    backend._cli = mock.Mock(side_effect=["blockhash\n", getblock_json])  # getblockhash, getblock
    return backend


class CoinbaseInfoTests(unittest.TestCase):
    def test_extracts_payout_address_and_skips_witness_commitment(self) -> None:
        block = {
            "tx": [
                {
                    "vin": [{"coinbase": "03abcdef" + _TAG_HEX + "00"}],
                    "vout": [
                        {"scriptPubKey": {"address": "bcrt1qpayout"}},
                        {"scriptPubKey": {"asm": "OP_RETURN aa21a9ed"}},  # witness commitment
                    ],
                }
            ]
        }
        addresses, sig = regtest.Backend._coinbase_info(block)
        self.assertEqual(addresses, ["bcrt1qpayout"])
        self.assertIn(_TAG_HEX, sig)

    def test_supports_pre22_addresses_list(self) -> None:
        block = {
            "tx": [
                {
                    "vin": [{"coinbase": "00"}],
                    "vout": [{"scriptPubKey": {"addresses": ["addr-a", "addr-b"]}}],
                }
            ]
        }
        addresses, _ = regtest.Backend._coinbase_info(block)
        self.assertEqual(addresses, ["addr-a", "addr-b"])


class CoinbasePaysTests(unittest.TestCase):
    def test_correct_address_and_tag(self) -> None:
        backend = _backend(_getblock("bcrt1qpay", "03aabbcc" + _TAG_HEX))
        self.assertEqual(backend.coinbase_pays(103, "bcrt1qpay", "/openbench/"), (True, True))

    def test_wrong_address_is_false(self) -> None:
        backend = _backend(_getblock("bcrt1qOTHER", "03aabbcc" + _TAG_HEX))
        paid, _ = backend.coinbase_pays(103, "bcrt1qpay", "/openbench/")
        self.assertFalse(paid)

    def test_missing_tag_is_false(self) -> None:
        backend = _backend(_getblock("bcrt1qpay", "03aabbcc"))  # no tag in the scriptSig
        _, tagged = backend.coinbase_pays(103, "bcrt1qpay", "/openbench/")
        self.assertFalse(tagged)

    def test_uppercase_tag_hex_still_matches(self) -> None:
        backend = _backend(_getblock("bcrt1qpay", ("03aabbcc" + _TAG_HEX).upper()))
        self.assertEqual(backend.coinbase_pays(103, "bcrt1qpay", "/openbench/"), (True, True))
