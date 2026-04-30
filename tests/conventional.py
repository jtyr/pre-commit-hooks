import unittest

from hooks.common.conventional import (
    bump_from_messages,
    parse_commit,
    portion_for_commit,
)


class TestParseCommit(unittest.TestCase):
    def test_simple_feat(self):
        result = parse_commit("feat: add new feature")
        self.assertEqual(result["type"], "feat")
        self.assertIsNone(result["scope"])
        self.assertFalse(result["breaking"])
        self.assertEqual(result["description"], "add new feature")

    def test_simple_fix(self):
        result = parse_commit("fix: correct bug")
        self.assertEqual(result["type"], "fix")
        self.assertFalse(result["breaking"])

    def test_with_scope(self):
        result = parse_commit("feat(api): add endpoint")
        self.assertEqual(result["type"], "feat")
        self.assertEqual(result["scope"], "api")
        self.assertFalse(result["breaking"])

    def test_with_bang(self):
        result = parse_commit("feat!: drop legacy support")
        self.assertEqual(result["type"], "feat")
        self.assertTrue(result["breaking"])

    def test_with_scope_and_bang(self):
        result = parse_commit("refactor(core)!: rewrite")
        self.assertEqual(result["type"], "refactor")
        self.assertEqual(result["scope"], "core")
        self.assertTrue(result["breaking"])

    def test_breaking_change_footer(self):
        msg = "feat: add new flag\n\nBREAKING CHANGE: removes the old flag\n"
        result = parse_commit(msg)
        self.assertEqual(result["type"], "feat")
        self.assertTrue(result["breaking"])

    def test_breaking_change_dash_footer(self):
        msg = "feat: add new flag\n\nBREAKING-CHANGE: removes the old flag\n"
        result = parse_commit(msg)
        self.assertTrue(result["breaking"])

    def test_type_is_normalized_to_lowercase(self):
        result = parse_commit("Feat: do thing")
        self.assertEqual(result["type"], "feat")

    def test_unknown_type_still_parses(self):
        result = parse_commit("wip: some experiment")
        self.assertEqual(result["type"], "wip")

    def test_invalid_no_colon_returns_none(self):
        self.assertIsNone(parse_commit("just some text"))

    def test_invalid_missing_description_returns_none(self):
        self.assertIsNone(parse_commit("feat: "))

    def test_empty_message_returns_none(self):
        self.assertIsNone(parse_commit(""))

    def test_none_message_returns_none(self):
        self.assertIsNone(parse_commit(None))

    def test_strips_leading_blank_lines(self):
        result = parse_commit("\n\nfeat: x")
        self.assertEqual(result["type"], "feat")

    def test_multiline_body_does_not_affect_parsing(self):
        msg = "fix: correct bug\n\nThis fixes something\nthat was broken.\n"
        result = parse_commit(msg)
        self.assertEqual(result["type"], "fix")
        self.assertFalse(result["breaking"])


class TestPortionForCommit(unittest.TestCase):
    def test_feat_is_minor(self):
        self.assertEqual(portion_for_commit(parse_commit("feat: x")), "minor")

    def test_fix_is_patch(self):
        self.assertEqual(portion_for_commit(parse_commit("fix: x")), "patch")

    def test_perf_is_patch(self):
        self.assertEqual(portion_for_commit(parse_commit("perf: x")), "patch")

    def test_refactor_returns_none(self):
        self.assertIsNone(portion_for_commit(parse_commit("refactor: x")))

    def test_revert_returns_none(self):
        self.assertIsNone(portion_for_commit(parse_commit("revert: x")))

    def test_breaking_overrides_to_major(self):
        self.assertEqual(portion_for_commit(parse_commit("fix!: x")), "major")

    def test_breaking_footer_overrides_to_major(self):
        msg = "fix: x\n\nBREAKING CHANGE: drops something\n"
        self.assertEqual(portion_for_commit(parse_commit(msg)), "major")

    def test_chore_returns_none(self):
        self.assertIsNone(portion_for_commit(parse_commit("chore: x")))

    def test_docs_returns_none(self):
        self.assertIsNone(portion_for_commit(parse_commit("docs: x")))

    def test_unknown_type_returns_none(self):
        self.assertIsNone(portion_for_commit(parse_commit("wip: x")))

    def test_none_input_returns_none(self):
        self.assertIsNone(portion_for_commit(None))


class TestBumpFromMessages(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(bump_from_messages([]), (None, False))

    def test_only_non_cc_messages(self):
        self.assertEqual(bump_from_messages(["junk", "noise"]), (None, False))

    def test_only_no_bump_cc_messages(self):
        # Valid CC but none qualify for a bump
        self.assertEqual(
            bump_from_messages(["chore: x", "docs: y", "style: z"]), (None, True)
        )

    def test_only_fix(self):
        self.assertEqual(bump_from_messages(["fix: x"]), ("patch", True))

    def test_only_feat(self):
        self.assertEqual(bump_from_messages(["feat: x"]), ("minor", True))

    def test_feat_and_fix(self):
        self.assertEqual(bump_from_messages(["fix: a", "feat: b"]), ("minor", True))

    def test_feat_bang(self):
        self.assertEqual(bump_from_messages(["feat!: x"]), ("major", True))

    def test_feat_with_breaking_footer(self):
        msg = "feat: x\n\nBREAKING CHANGE: drops y\n"
        self.assertEqual(bump_from_messages([msg]), ("major", True))

    def test_mix_of_all(self):
        msgs = [
            "fix: a",
            "feat: b",
            "feat!: c",
            "docs: d",
        ]
        self.assertEqual(bump_from_messages(msgs), ("major", True))

    def test_ignores_invalid_messages(self):
        self.assertEqual(bump_from_messages(["junk", "fix: x"]), ("patch", True))


if __name__ == "__main__":
    unittest.main()
