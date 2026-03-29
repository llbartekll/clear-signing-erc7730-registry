import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "generate-index-v2.py"

spec = importlib.util.spec_from_file_location("generate_index_v2", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

PERMIT2_KEY_OP = "eip155:10:0x000000000022d473030f116ddee9f6b43ac78ba3"
VELORA_KEY_OP = "eip155:10:0x0000000000bbf5c5fd284e657f01bd000933c96d"
PERMIT2_PATH = "registry/uniswap/eip712-uniswap-permit2.json"
UNISWAPX_PATHS = {
    "registry/uniswap/eip712-UniswapX-DutchOrder.json",
    "registry/uniswap/eip712-UniswapX-ExclusiveDutchOrder.json",
    "registry/uniswap/eip712-UniswapX-LimitOrder.json",
    "registry/uniswap/eip712-uniswap-V2DutchOrder.json",
}


class GenerateIndexV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (
            cls.legacy_index,
            cls.calldata_index,
            cls.eip712_index,
            cls.warnings,
        ) = module.build_indexes()

    def test_permit2_effective_descriptor_inherits_context_from_include(self):
        warnings = []
        descriptor = module.load_effective_descriptor(
            str(ROOT / PERMIT2_PATH),
            PERMIT2_PATH,
            warnings=warnings,
        )
        deployments = descriptor["context"]["eip712"]["deployments"]
        self.assertIn(
            {"chainId": 10, "address": "0x000000000022D473030F116dDEE9F6B43aC78BA3"},
            deployments,
        )
        self.assertEqual(warnings, [])

    def test_permit2_entry_is_indexed_on_optimism(self):
        entries = self.legacy_index["eip712"].get(PERMIT2_KEY_OP)
        self.assertIsNotNone(entries)
        entry_pairs = {(entry["primaryType"], entry["path"]) for entry in entries}
        self.assertIn(("PermitSingle", PERMIT2_PATH), entry_pairs)
        self.assertIn(("PermitBatch", PERMIT2_PATH), entry_pairs)

    def test_uniswapx_include_based_files_are_indexed(self):
        entries = self.legacy_index["eip712"].get(PERMIT2_KEY_OP, [])
        witness_paths = {
            entry["path"]
            for entry in entries
            if entry["primaryType"] == "PermitWitnessTransferFrom"
        }
        self.assertTrue(UNISWAPX_PATHS.issubset(witness_paths), witness_paths)

    def test_known_good_velora_entry_is_preserved(self):
        entries = self.legacy_index["eip712"].get(VELORA_KEY_OP, [])
        self.assertIn(
            {"primaryType": "Order", "path": "registry/paraswap/eip712-Velora-DeltaV2.json"},
            entries,
        )

    def test_split_calldata_index_preserves_current_shape(self):
        self.assertEqual(
            self.calldata_index.get("eip155:10:0x6a000f20005980200259b80c5102003040001068"),
            "registry/paraswap/calldata-AugustusSwapper-v6.2.json",
        )

    def test_split_eip712_index_groups_per_primary_type_with_hashes(self):
        permit2_bucket = self.eip712_index.get(PERMIT2_KEY_OP, {})
        witness_entries = permit2_bucket.get("PermitWitnessTransferFrom", [])
        witness_paths = {entry["path"] for entry in witness_entries}
        self.assertTrue(UNISWAPX_PATHS.issubset(witness_paths), witness_paths)
        for entry in witness_entries:
            self.assertTrue(entry["encodeTypeHashes"], entry)
            self.assertEqual(len(entry["encodeTypeHashes"]), len(set(entry["encodeTypeHashes"])))

    def test_circle_receive_with_authorization_is_indexed_with_hash(self):
        bucket = self.eip712_index.get("eip155:1:0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", {})
        entries = bucket.get("ReceiveWithAuthorization", [])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["path"], "registry/circle/eip712-ReceiveWithAuthorization.json")
        self.assertTrue(entries[0]["encodeTypeHashes"], entries[0])

    def test_generator_rejects_non_canonical_eip712_short_keys(self):
        with self.assertRaisesRegex(ValueError, "non-canonical EIP-712 format key"):
            module.extract_eip712_format_hashes(
                {"display": {"formats": {"ReceiveWithAuthorization": {}}}},
                "registry/circle/eip712-ReceiveWithAuthorization.json",
            )


if __name__ == "__main__":
    unittest.main()
