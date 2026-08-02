from __future__ import annotations

import unittest

from scripts.validate_docs import extract_blocks, validate_structured_blocks


class DocumentationContractTest(unittest.TestCase):
    def test_valid_json_and_yaml_examples_pass(self) -> None:
        text = """# Contract
```json
{"status": "PASS"}
```
```yaml
enabled: true
```
"""
        blocks, issues = extract_blocks("contract.md", text)
        self.assertEqual([], issues)
        self.assertEqual(2, len(blocks))
        self.assertEqual([], validate_structured_blocks("contract.md", blocks))

    def test_invalid_json_example_is_rejected(self) -> None:
        text = """```json
{"status": }
```
"""
        blocks, issues = extract_blocks("contract.md", text)
        self.assertEqual([], issues)
        violations = validate_structured_blocks("contract.md", blocks)
        self.assertEqual("INVALID_STRUCTURED_EXAMPLE", violations[0].code)

    def test_unclosed_fence_is_rejected(self) -> None:
        blocks, issues = extract_blocks("contract.md", "```json\n{}\n")
        self.assertEqual([], blocks)
        self.assertEqual("UNCLOSED_CODE_FENCE", issues[0].code)


if __name__ == "__main__":
    unittest.main()
