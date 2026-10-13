"""Opt-in C4 API checks in a disposable schema of a dedicated test database."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).parent))
import test_c4_pilot as c4_tests
import database


@unittest.skipUnless(os.environ.get('SURVEY_TEST_POSTGRES_URL'), 'PostgreSQL test URL not configured')
class PostgresC4Tests(c4_tests.C4PilotTests):
    def setUp(self):
        from psycopg import sql
        from postgres_support import connect_postgres
        self.postgres_test_url = os.environ['SURVEY_TEST_POSTGRES_URL']
        options = '-c lock_timeout=10000 -c statement_timeout=30000'
        self.enterContext(patch.dict(os.environ, SURVEY_POSTGRES_OPTIONS=options))
        schema = 'survey_test_' + uuid.uuid4().hex

        def connect():
            return connect_postgres(self.postgres_test_url, autocommit=True,
                                    connect_timeout=15, options=options)

        with connect() as db:
            db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))

        def cleanup():
            if not schema.startswith('survey_test_') or len(schema) != 44:
                raise RuntimeError('Unexpected test schema')
            with connect() as db:
                db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        self.addCleanup(cleanup)
        adapter = database.PostgresConnection

        def isolated(connection):
            connection.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
            return adapter(connection)
        self.enterContext(patch.object(database, 'PostgresConnection', isolated))
        super().setUp()
