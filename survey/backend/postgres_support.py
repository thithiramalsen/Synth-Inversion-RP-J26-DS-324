"""Optional IPv4 routing for networks where database IPv6 connections time out."""
import ipaddress
import os
import socket


def ipv4_connection_options(url):
    from psycopg.conninfo import conninfo_to_dict

    settings = conninfo_to_dict(url)
    host = settings.get('host', '')
    if not host or ',' in host:
        raise ValueError('IPv4 mode requires one explicit database hostname')
    # Respect explicitly supplied addresses instead of silently overriding them.
    if supplied := settings.get('hostaddr'):
        if not all(ipaddress.ip_address(value).version == 4 for value in supplied.split(',')):
            raise ValueError('IPv4 mode cannot use an explicit IPv6 hostaddr; use the original hostname URL')
        return {}
    try:
        port = int(settings.get('port', '5432'))
        resolved = socket.getaddrinfo(host, port, family=socket.AF_INET,
                                      type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except (OSError, ValueError):
        raise RuntimeError('Could not resolve an IPv4 address for the database endpoint') from None
    addresses = list(dict.fromkeys(item[4][0] for item in resolved))
    if not addresses:
        raise RuntimeError('No IPv4 address was returned for the database endpoint')
    # libpq accepts parallel host/hostaddr lists. Keep ALL IPv4 candidates for
    # failover, with the original hostname for TLS/SNI and authentication.
    # Resolve on each connection: never pin a managed database's changing IPs.
    return {'host': ','.join([host] * len(addresses)), 'hostaddr': ','.join(addresses)}


def connect_postgres(url, **kwargs):
    import psycopg

    if os.environ.get('SURVEY_POSTGRES_IPV4') == '1':
        kwargs.update(ipv4_connection_options(url))
    return psycopg.connect(url, **kwargs)
