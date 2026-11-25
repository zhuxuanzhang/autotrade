import unittest
from signal_visibility import suppress_held_signals

class VisibilityTests(unittest.TestCase):
    def test_buy_holding_and_sale_day_block_entries(self):
        for key in ('buys','positions','sells'):
            day={'signals':[{'code':'1'},{'code':'2'}],key:[{'code':'1'}]}
            self.assertEqual(suppress_held_signals(day),[{'code':'2'}])

    def test_after_sale_allows_new_entry(self):
        self.assertEqual(suppress_held_signals({'signals':[{'code':'1'}]}),[{'code':'1'}])

    def test_preserves_original_matches(self):
        day={'signals':[{'code':'1'}],'positions':[{'code':'1'}]}
        suppress_held_signals(day)
        self.assertEqual(len(day['signals']),1)

if __name__=='__main__':unittest.main()
