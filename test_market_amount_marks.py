import unittest
from market_amount_marks import selected, entry_values


class MarketAmountMarksTests(unittest.TestCase):
    def test_exact_boundaries(self):
        for value in (1.13, 1.16, 1.20, 1.450001, 1.6):
            self.assertTrue(selected(value), value)
        for value in (1.05, 1.129999, 1.200001, 1.22, 1.45, float('nan'), float('inf')):
            self.assertFalse(selected(value), value)

    def test_nonoverlapping_window_and_no_same_day_data(self):
        dates = [f'2026-01-{i:02}' for i in range(1,18)]
        rows = {day:dict(amount=100. if i<10 else 115.) for i,day in enumerate(dates)}
        result = entry_values(rows, dates, dates[-1])
        self.assertAlmostEqual(result[dates[15]]['ratio'], 1.15)
        self.assertEqual(result[dates[15]]['reference_date'], dates[14])
        self.assertTrue(result[dates[15]]['marked'])
        rows[dates[15]]['amount'] = 1000000.
        self.assertEqual(result[dates[15]],entry_values(rows,dates,dates[-1])[dates[15]])

    def test_missing_day_does_not_use_stale_window(self):
        dates = [f'2026-01-{i:02}' for i in range(1,18)]
        rows = {d:dict(amount=100.) for d in dates}
        del rows[dates[4]]
        self.assertNotIn(dates[15], entry_values(rows, dates, dates[-1]))

    def test_asof_and_weekend_calendar(self):
        dates = ['2026-01-02','2026-01-05','2026-01-06','2026-01-07','2026-01-08',
                 '2026-01-09','2026-01-12','2026-01-13','2026-01-14','2026-01-15',
                 '2026-01-16','2026-01-19','2026-01-20','2026-01-21','2026-01-22',
                 '2026-01-23','2026-01-26']
        rows = {d:dict(amount=100.) for d in dates}
        self.assertEqual(set(entry_values(rows,dates,'2026-01-23')), {'2026-01-23'})
        self.assertEqual(entry_values(rows,dates,dates[-1])['2026-01-26']['reference_date'],'2026-01-23')


if __name__ == '__main__':
    unittest.main()
