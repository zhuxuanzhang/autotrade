import unittest
from right_side import right_side_buy


class EligibilityTests(unittest.TestCase):
    def signal(self, **overrides):
        args = dict(code='000001', listing_date='2026-05-14', as_of='2026-11-14')
        args.update(risk_record={'name': '普通股票', 'excluded': False}, risk_date='2026-11-14')
        args.update(overrides)
        if 'risk_date' not in overrides:
            args['risk_date'] = args['as_of']
        return right_side_buy([10 + i * .01 for i in range(65)], **args)

    def test_exact_six_month_boundary(self):
        self.assertTrue(self.signal()['buy_signal'])
        self.assertFalse(self.signal(as_of='2026-11-13')['buy_signal'])

    def test_beijing_old_and_new_codes(self):
        for code in ('430047', '830799', '920000', 'bj920000', '920000.BJ'):
            self.assertFalse(self.signal(code=code)['buy_signal'])

    def test_shanghai_and_shenzhen(self):
        for code in ('600000', '688001', '000001', '300001'):
            self.assertTrue(self.signal(code=code)['buy_signal'])

    def test_month_end(self):
        self.assertTrue(self.signal(listing_date='2025-08-31', as_of='2026-02-28')['buy_signal'])
        self.assertFalse(self.signal(listing_date='2025-08-31', as_of='2026-02-27')['buy_signal'])

    def test_risk_filters(self):
        for name in ('ST测试', '*ST测试', 'S*ST测试', '测试退'):
            self.assertFalse(self.signal(risk_record={'name': name, 'excluded': False})['buy_signal'])
        self.assertFalse(self.signal(risk_record={'name': '普通股票', 'excluded': True})['buy_signal'])
        self.assertFalse(self.signal(risk_record=None)['buy_signal'])
        self.assertFalse(self.signal(risk_date='2026-11-13')['buy_signal'])

    def test_missing_metadata_and_conservative_fallback(self):
        self.assertFalse(self.signal(code=None)['buy_signal'])
        self.assertFalse(self.signal(listing_date=None)['buy_signal'])
        result = self.signal(listing_date=None, history_start='2026-05-14')
        self.assertTrue(result['buy_signal'])
        self.assertEqual(result['eligibility']['age_basis'], 'history_start_conservative')


if __name__ == '__main__':
    unittest.main()
