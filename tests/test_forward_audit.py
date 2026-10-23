import unittest
from forward_audit import evaluate

class ForwardAuditTests(unittest.TestCase):
    def test_strict_next_tick(self):
        rows=[{'seq':11,'digit':2,'predicted_at_seq':10,'v1':2},
              {'seq':13,'digit':2,'predicted_at_seq':11,'v1':2}]
        a=evaluate(rows)
        self.assertEqual(a['models']['v1']['valid'],1)
        self.assertEqual(a['models']['v1']['skipped'],1)
        self.assertEqual(a['data_warnings']['sequence_gaps'],1)
    def test_no_duplicate_official_outcomes(self):
        rows=[{'seq':1,'digit':1,'contract_id':'X','official_result':'WIN'},
              {'seq':2,'digit':2,'contract_id':'X','official_result':'WIN'}]
        r=evaluate(rows)
        self.assertEqual(r['official_contracts']['WIN'],1)
    def test_unresolved_not_assumed_success(self):
        r=evaluate([{'seq':1,'digit':1,'cycle_id':'A','trade_no':1,'official_result':'LOSS'},
                    {'seq':2,'digit':2,'cycle_id':'B','trade_no':1,'official_result':'WIN'}])
        self.assertEqual(r['cycle_depth']['unresolved_or_censored'],1)
        self.assertEqual(r['cycle_depth']['resolved_within_10'],1)

if __name__=='__main__': unittest.main()
