import os
import tempfile
import unittest
from pathlib import Path

import db
import visuals


class VotingResultsTests(unittest.TestCase):
    def setUp(self):
        self.previous_path = db.DB_PATH
        descriptor, filename = tempfile.mkstemp(dir=Path.cwd(), suffix='.db')
        os.close(descriptor)
        db.DB_PATH = Path(filename)
        db.initialize()
        with db.connect() as conn:
            conn.executemany('INSERT INTO participants VALUES (?,?,?,100)',
                             [(1, 'Alice', 'pin'), (2, 'Bob', 'pin'), (3, 'Not voted', 'pin')])
            conn.executemany('INSERT INTO destinations(id,name,min_tokens,max_tokens) VALUES (?,?,0,100)',
                             [(1, 'Da Nang'), (2, 'Hoi An')])

    def tearDown(self):
        db.DB_PATH.unlink(missing_ok=True)
        db.DB_PATH = self.previous_path

    def test_average_includes_zero_votes_but_excludes_nonvoters(self):
        with db.connect() as conn:
            conn.executemany('INSERT INTO vote_submissions VALUES (?)', [(1,), (2,)])
            conn.executemany('INSERT INTO votes VALUES (?,?,?)',
                             [(1, 1, 100), (1, 2, 0), (2, 1, 25), (2, 2, 75)])
        ranking, count = db.leaderboard()
        self.assertEqual(count, 2)
        self.assertEqual(ranking, [
            {'item': 'Da Nang', 'average_tokens': 62.5, 'supporters': 2},
            {'item': 'Hoi An', 'average_tokens': 37.5, 'supporters': 1}])

    def test_no_votes_returns_zero_averages(self):
        ranking, count = db.leaderboard()
        self.assertEqual(count, 0)
        self.assertTrue(all(item['average_tokens'] == 0 for item in ranking))

    def test_instructions_persist_and_old_callers_preserve_them(self):
        db.save_poll_details('Our stay', 'Stay duration', 'cards', 'Each token represents one night.')
        db.initialize()
        self.assertEqual(db.poll_details()['voting_instructions'], 'Each token represents one night.')
        db.save_poll_details('Our stay', 'Stay duration', 'percentages')
        self.assertEqual(db.poll_details()['voting_instructions'], 'Each token represents one night.')
        db.save_poll_details('Our stay', 'Stay duration', 'percentages', '')
        self.assertEqual(db.poll_details()['voting_instructions'], '')

    def test_average_bar_has_two_lines_and_consistent_hover_details(self):
        segments = [{'item': 'Da Nang', 'tokens': 62.5, 'percentage': 0.625},
                    {'item': 'Hoi An', 'tokens': 37.5, 'percentage': 0.375}]
        colors = visuals.item_colors([s['item'] for s in segments])
        chart = visuals.distribution_chart(segments, colors, 'Average tokens', '.1f').to_dict()
        bar, names, counts = chart['layer']
        self.assertEqual(names['encoding']['text']['field'], 'item')
        self.assertEqual(counts['encoding']['text']['field'], 'label')
        self.assertEqual(bar['encoding']['tooltip'], counts['encoding']['tooltip'])
        self.assertEqual(bar['encoding']['tooltip'], names['encoding']['tooltip'])
        rows = next(iter(chart['datasets'].values()))
        self.assertEqual([r['label'] for r in rows], ['62.5', '37.5'])
        self.assertIn('62.5 avg tokens', visuals.distribution_legend(segments, colors, 'avg tokens', '.1f'))
        self.assertNotIn('start', segments[0])  # Rendering leaves the calculation inputs intact.


if __name__ == '__main__':
    unittest.main()
