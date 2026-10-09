"""Run the C1 API suite in isolated PostgreSQL schemas when a test URL is set.

SURVEY_TEST_POSTGRES_URL must point to a dedicated test database, using a direct
connection. No public-schema tables or existing research responses are touched.
"""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sys
from threading import Barrier
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_c1_pilot as c1_tests
import database


@unittest.skipUnless(os.environ.get('SURVEY_TEST_POSTGRES_URL'), 'PostgreSQL test URL not configured')
class PostgresPilotTests(c1_tests.C1PilotTests):
    def setUp(self):
        import psycopg
        from psycopg import sql

        self.postgres_test_url = os.environ['SURVEY_TEST_POSTGRES_URL']
        schema = 'survey_test_' + uuid.uuid4().hex
        with psycopg.connect(self.postgres_test_url, autocommit=True) as db:
            db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))

        def remove_test_schema():
            # Only this randomly named test schema is ever removed.
            if not schema.startswith('survey_test_') or len(schema) != 44:
                raise RuntimeError('Unexpected test schema name')
            with psycopg.connect(self.postgres_test_url, autocommit=True) as db:
                db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))

        self.addCleanup(remove_test_schema)
        adapter = database.PostgresConnection

        def isolated_connection(connection):
            connection.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
            return adapter(connection)

        scope = patch.object(database, 'PostgresConnection', isolated_connection)
        scope.start()
        self.addCleanup(scope.stop)
        super().setUp()

    def test_concurrent_rating_saves_once_and_advances_once(self):
        self.start()
        self.setup_audio()
        current = self.state()
        self.client.post(f"{self.base}/playback/{current['presentation_id']}", headers=self.headers)
        barrier = Barrier(2)

        def submit():
            barrier.wait(timeout=10)
            return self.client.post(self.base+'/ratings', headers=self.headers,
                                    json=self.rating_body(current)).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(lambda _: submit(), range(2))), [200, 409])
        self.assertEqual(self.state()['saved_presentations'], 1)
        with database.get_connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM c1_ratings').fetchone()[0], 1)

    def test_concurrent_signup_claims_invitation_once(self):
        code = self.client.post('/api/researcher/invitations', headers=self.admin, json={}).json()['invitation']
        barrier = Barrier(2)

        def signup(index):
            barrier.wait(timeout=10)
            return self.client.post('/api/researcher/signup', json=dict(
                username=f'researcher{index}', password='test-password-long-enough', invitation=code)).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(signup, range(2))), [201, 400])
        with database.get_connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM researcher_accounts').fetchone()[0], 1)

    def test_expiry_timestamps_retain_precision_after_reconnection(self):
        expected = 1791500000.125
        with database.get_connection() as db:
            db.execute('INSERT INTO researcher_sessions VALUES (?,?,?)', ('test-hash', 'test-user', expected))
        # A fresh connection must retain the exact timestamp, not a float32 value.
        with database.get_connection() as db:
            actual = db.execute('SELECT expires_at FROM researcher_sessions WHERE token_hash=?', ('test-hash',)).fetchone()[0]
        self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
