"""Locate a PostgreSQL test wait without printing connection strings or passwords."""
import argparse
import faulthandler
import os
from pathlib import Path
import socket
import ssl
import struct
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEST = ('survey.backend.tests.test_postgres.PostgresPilotTests.'
                'test_authentication_invitation_reuse_and_no_screen_bypass')


def network_probe(url, progress):
    """Check transport only: no credentials or SQL are sent to the server."""
    from psycopg.conninfo import conninfo_to_dict

    try:
        settings = conninfo_to_dict(url)
        host = settings.get('host', '')
        port = int(settings.get('port', '5432'))
        if not host or ',' in host or not 1 <= port <= 65535:
            progress('Use one database hostname and one valid port in the test URL.')
            return 2
        progress('URL parsed. Host, username, password and database values are hidden.')
        progress('Resolving database hostname (DNS)...')
        family = socket.AF_INET if os.environ.get('SURVEY_POSTGRES_IPV4') == '1' else socket.AF_UNSPEC
        resolved = socket.getaddrinfo(host, port, family=family, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
        addresses = list(dict.fromkeys(resolved))
    except Exception as error:
        progress(f'URL/DNS check failed: {type(error).__name__}')
        return 1

    progress(f'DNS succeeded: {len(addresses)} address(es). Testing up to four.')
    reached_tcp = False
    for index, (family, kind, protocol, _, address) in enumerate(addresses[:4], 1):
        version = 'IPv6' if family == socket.AF_INET6 else 'IPv4'
        label = f'Address {index} ({version})'
        stage = 'TCP connection'
        try:
            progress(f'{label}: opening database port (5-second socket timeout)...')
            with socket.socket(family, kind, protocol) as connection:
                connection.settimeout(5)
                connection.connect(address)
                reached_tcp = True
                progress(f'{label}: TCP connected. Requesting PostgreSQL encryption...')
                stage = 'PostgreSQL SSL response'
                connection.sendall(struct.pack('!II', 8, 80877103))
                if connection.recv(1) != b'S':
                    progress(f'{label}: endpoint did not accept PostgreSQL SSL negotiation.')
                    continue
                stage = 'TLS handshake/certificate verification'
                progress(f'{label}: server accepted encryption. Verifying TLS certificate...')
                with ssl.create_default_context().wrap_socket(connection, server_hostname=host):
                    pass
            progress('PASS: DNS, TCP and verified TLS succeeded. Authentication is not tested here.')
            return 0
        except (OSError, ValueError) as error:
            progress(f'{label}: {stage} failed ({type(error).__name__}).')

    if reached_tcp:
        progress('TCP was reachable, but PostgreSQL encryption did not complete on the checked addresses.')
    else:
        progress('No checked address accepted a TCP connection. Check endpoint availability or the network path.')
    return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--connection-only', action='store_true')
    parser.add_argument('--network-only', action='store_true', help='Check DNS, TCP and TLS without logging into the database')
    parser.add_argument('--network-worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--ipv4', action='store_true', help='Use IPv4 for this command and its isolated test')
    parser.add_argument('--all', action='store_true', help='Run all PostgreSQL integration tests with visible progress')
    args = parser.parse_args(argv)
    url = os.environ.get('SURVEY_TEST_POSTGRES_URL')
    if not url:
        print('SURVEY_TEST_POSTGRES_URL is missing in this terminal. No test ran.', flush=True)
        return 2

    if args.ipv4:
        with patch.dict(os.environ, {'SURVEY_POSTGRES_IPV4': '1'}):
            return run_checks(args, url)
    return run_checks(args, url)


def run_checks(args, url):
    from psycopg.conninfo import conninfo_to_dict
    sys.path.insert(0, str(ROOT))
    from survey.backend.postgres_support import connect_postgres

    started = time.monotonic()

    def progress(message):
        print(f'[{time.monotonic()-started:6.1f}s] {message}', flush=True)

    if os.environ.get('SURVEY_POSTGRES_IPV4') == '1':
        progress('IPv4 mode enabled for these checks; original hostname and TLS settings retained.')
    if args.network_worker:
        return network_probe(url, progress)
    if args.network_only:
        # DNS lookup itself has no portable socket timeout. Isolate this read-only
        # probe so even a stuck resolver cannot leave the command waiting forever.
        command = [sys.executable, '-B', '-u', str(Path(__file__).resolve()), '--network-worker']
        progress('Starting read-only network checks (60-second overall limit)...')
        try:
            return subprocess.run(command, timeout=60, check=False).returncode
        except subprocess.TimeoutExpired:
            progress('Network probe stopped at its overall limit. The last printed stage identifies the wait.')
            return 1

    # Stack traces contain code locations, not local-variable/credential values.
    # This diagnoses socket waits and locks without trying to guess their cause.
    faulthandler.dump_traceback_later(30, repeat=True)
    try:
        try:
            settings = conninfo_to_dict(url)
            if '-pooler' in settings.get('host', ''):
                progress('Pooled endpoint detected. Use a direct test-database connection for this suite.')
                return 2
            progress('Connecting to the test database (15-second timeout per address)...')
            with connect_postgres(url, autocommit=True, connect_timeout=15,
                                  options='-c lock_timeout=10000 -c statement_timeout=30000') as db:
                progress('Connected. Sending SELECT 1...')
                if db.execute('SELECT 1').fetchone()[0] != 1:
                    raise RuntimeError('Unexpected database reply')
                progress('Database query succeeded.')
        except Exception as error:
            # Driver errors may include host/user details. Do not echo the DSN
            # or the exception message; class + SQLSTATE are safe diagnostics.
            progress(f'Connection/query failed: {type(error).__name__}; SQLSTATE={getattr(error, "sqlstate", None)}')
            return 1

        if args.connection_only:
            return 0
        label = 'all PostgreSQL integration tests' if args.all else 'the isolated C1 test'
        progress(f'Starting {label}. Full-session cases take several minutes over a remote database.')
        progress('Progress is shown below; a thread stack is printed if progress pauses for 30 seconds.')
        sys.path.insert(0, str(ROOT))
        with patch.dict(os.environ, {'SURVEY_POSTGRES_TEST_PROGRESS': '1', 'SURVEY_POSTGRES_TEST_WATCHDOG': '1'}):
            target = 'survey.backend.tests.test_postgres' if args.all else DEFAULT_TEST
            suite = unittest.defaultTestLoader.loadTestsFromName(target)
            result = unittest.TextTestRunner(verbosity=2).run(suite)
        passed = result.wasSuccessful() and not result.skipped
        progress('Tests passed.' if passed else 'Tests failed or were skipped; inspect the output above.')
        return 0 if passed else 1
    finally:
        faulthandler.cancel_dump_traceback_later()


if __name__ == '__main__':
    raise SystemExit(main())
