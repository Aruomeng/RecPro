from __future__ import annotations
import hashlib,unittest
from scripts.build_g11_identity_successor_plan import build_plan
from scripts.execute_g11_identity_successor import canonical,completion_statements,dry_run_report

class IdentitySuccessorPlanTests(unittest.TestCase):
    def test_exact_forward_only_statement_subset(self)->None:
        statements=completion_statements(); self.assertEqual(7,len(statements)); self.assertTrue(all("DROP" not in item.upper() and "DELETE" not in item.upper() for item in statements))
        report=dry_run_report(); self.assertEqual(0,report["database_connections"]); self.assertEqual(37,report["maximum_rows"])
    def test_canonical_plan_freezes_confirmed_partial_state(self)->None:
        plan=build_plan(reviewed_commit="d"*40,created_at="2026-08-26T03:00:00Z"); unsigned=dict(plan); expected=unsigned.pop("plan_hash"); self.assertEqual(expected,hashlib.sha256(canonical(unsigned)).hexdigest()); self.assertEqual(7,len(plan["targets"])); self.assertEqual(0,plan["safety_assertions"]["database_physical_deletions"])
if __name__=="__main__":unittest.main()
