"""IPv4 routing must preserve TLS identity and avoid stale hard-coded IPs."""
import os
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from postgres_support import connect_postgres, ipv4_connection_options
from psycopg.conninfo import conninfo_to_dict, make_conninfo

URL = 'postgresql://fixture:secret@db.example.invalid:5432/test?sslmode=verify-full&channel_binding=require'


def records(*addresses):
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (address, 5432))
            for address in addresses]


class PostgresRoutingTests(unittest.TestCase):
    def test_default_keeps_original_driver_routing(self):
        with patch.dict(os.environ, {'SURVEY_POSTGRES_IPV4': '0'}), \
                patch('socket.getaddrinfo') as lookup, patch('psycopg.connect') as connect:
            connect_postgres(URL, connect_timeout=15)
            lookup.assert_not_called()
            connect.assert_called_once_with(URL, connect_timeout=15)

    def test_ipv4_retains_failover_and_tls_hostname_without_changing_credentials(self):
        with patch('socket.getaddrinfo', return_value=records('192.0.2.1', '192.0.2.2', '192.0.2.1')) as lookup:
            options = ipv4_connection_options(URL)
        self.assertEqual(lookup.call_args.kwargs['family'], socket.AF_INET)
        self.assertEqual(options['hostaddr'], '192.0.2.1,192.0.2.2')
        self.assertEqual(options['host'], 'db.example.invalid,db.example.invalid')
        merged = conninfo_to_dict(make_conninfo(URL, **options))
        original = conninfo_to_dict(URL)
        for key in ('user', 'password', 'dbname', 'port', 'sslmode', 'channel_binding'):
            self.assertEqual(merged[key], original[key])
        self.assertEqual(set(options), {'host', 'hostaddr'})

    def test_each_connection_refreshes_addresses_and_keeps_driver_options(self):
        with patch.dict(os.environ, {'SURVEY_POSTGRES_IPV4': '1'}), \
                patch('socket.getaddrinfo', side_effect=[records('192.0.2.1'), records('192.0.2.2')]), \
                patch('psycopg.connect') as connect:
            connect_postgres(URL, autocommit=True, connect_timeout=15)
            connect_postgres(URL, autocommit=True, connect_timeout=15)
        self.assertEqual([call.kwargs['hostaddr'] for call in connect.call_args_list], ['192.0.2.1', '192.0.2.2'])
        self.assertTrue(all(call.kwargs['autocommit'] for call in connect.call_args_list))
        self.assertTrue(all(call.args == (URL,) for call in connect.call_args_list))

    def test_failed_ipv4_lookup_does_not_fall_back_to_broken_ipv6(self):
        for value in ([], OSError('private endpoint detail')):
            with self.subTest(value=type(value).__name__), \
                    patch.dict(os.environ, {'SURVEY_POSTGRES_IPV4': '1'}), \
                    patch('socket.getaddrinfo', **({'side_effect': value} if isinstance(value, Exception) else {'return_value': value})), \
                    patch('psycopg.connect') as connect:
                with self.assertRaises(RuntimeError) as error:
                    connect_postgres(URL)
                self.assertNotIn('private endpoint detail', str(error.exception))
                connect.assert_not_called()

    def test_explicit_ipv4_address_is_respected_and_ipv6_is_rejected(self):
        with patch('socket.getaddrinfo') as lookup:
            self.assertEqual(ipv4_connection_options(URL+'&hostaddr=192.0.2.3'), {})
            with self.assertRaises(ValueError):
                ipv4_connection_options(URL+'&hostaddr=%3A%3A1')
            lookup.assert_not_called()


if __name__ == '__main__':
    unittest.main()
