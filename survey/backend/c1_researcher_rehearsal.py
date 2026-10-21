"""Separate C1 instance for fresh researcher-entered rehearsal responses."""
import argparse
from contextlib import asynccontextmanager
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import sys
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

ROOT = Path(__file__).resolve().parents[2]
STUDY_ID = 'c1_researcher_rehearsal_v1'
ORIGIN = 'researcher_entered_rehearsal'
REHEARSAL_COOKIE = 'c1_researcher_rehearsal_session'
DEFAULT_STATE = ROOT/'data/processed'/STUDY_ID


def database_identity(url):
    parsed = urlsplit(url)
    return parsed.hostname, parsed.port or 5432, parsed.path.rstrip('/')


def configure(state_dir=DEFAULT_STATE, use_postgres=False):
    """Configure only this new process; never inherit the participant database."""
    state_dir = Path(state_dir).resolve()
    bundle = ROOT/'survey/deploy/study/c1_researcher_rehearsal_v1.json'
    config = ROOT/'survey/config/c1_researcher_rehearsal_v1.json'
    if not bundle.is_file() or not config.is_file():
        raise RuntimeError('Prepare the researcher rehearsal package first')
    data = json.loads(bundle.read_text(encoding='utf-8'))
    cfg = json.loads(config.read_text(encoding='utf-8'))
    if (data.get('study_id') != STUDY_ID or data.get('rehearsal') is not True
            or cfg.get('study_id') != STUDY_ID or cfg.get('collection_mode') != 'researcher_rehearsal'):
        raise RuntimeError('This runner only accepts the labelled researcher rehearsal')
    inherited = os.environ.get('SURVEY_DATABASE_URL', '')
    if use_postgres:
        url = os.environ.get('SURVEY_REHEARSAL_DATABASE_URL', '')
        if not url or (inherited and database_identity(url) == database_identity(inherited)):
            raise RuntimeError('Set SURVEY_REHEARSAL_DATABASE_URL to a separate rehearsal database')
        if (len(os.environ.get('SURVEY_REHEARSAL_ADMIN_TOKEN', '')) < 32
                or not os.environ.get('SURVEY_RESEARCHER_USERNAME')
                or '$' not in os.environ.get('SURVEY_RESEARCHER_PASSWORD_HASH', '')):
            raise RuntimeError('Configure the separate rehearsal admin token and researcher login')
        secret = os.environ['SURVEY_REHEARSAL_ADMIN_TOKEN']
    else:
        if os.environ.get('RENDER') == 'true':
            raise RuntimeError('Use --postgres with a separate persistent database on Render')
        url = ''
        state_dir.mkdir(parents=True, exist_ok=True)
        private = state_dir/'private_access.json'
        if private.exists():
            access = json.loads(private.read_text(encoding='utf-8'))
        else:
            access = dict(admin_token=secrets.token_urlsafe(40), researcher_username='researcher',
                          researcher_password=secrets.token_urlsafe(18))
            private.write_text(json.dumps(access, indent=2)+'\n', encoding='utf-8')
        secret = access['admin_token']
        salt = secrets.token_urlsafe(16)
        digest = hashlib.pbkdf2_hmac('sha256', access['researcher_password'].encode(), salt.encode(), 600_000).hex()
        os.environ.update(SURVEY_RESEARCHER_USERNAME=access['researcher_username'],
                          SURVEY_RESEARCHER_PASSWORD_HASH=f'{salt}${digest}')
    os.environ.update(SURVEY_DATABASE_URL=url, SURVEY_DATABASE_PATH=str(state_dir/'researcher_rehearsal.sqlite'),
                      SURVEY_C1_BUNDLE=str(bundle), SURVEY_C1_CONFIG=str(config), SURVEY_C1_LEGACY_BUNDLES='',
                      SURVEY_ADMIN_TOKEN=secret, SURVEY_INVITATION_SECRET='', SURVEY_REMOTE_MODE='1',
                      SURVEY_C1_OPEN='0', SURVEY_C4_OPEN='0', SURVEY_ALLOWED_ORIGINS='')
    # The normal app captures this path at import time. Reset it explicitly for
    # tests; actual participant and rehearsal servers run in separate processes.
    import database
    database.DATABASE_PATH = state_dir/'researcher_rehearsal.sqlite'
    return state_dir


def assert_separate_store():
    from database import get_connection
    with get_connection() as db:
        if os.environ.get('SURVEY_DATABASE_URL'):
            names = db.execute("SELECT table_name AS name FROM information_schema.tables WHERE table_schema=current_schema()").fetchall()
        else:
            names = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = {row['name'] for row in names}
        if tables and 'rehearsal_session_actors' not in tables:
            raise RuntimeError('Use an empty, separate rehearsal database; this schema has no rehearsal marker')
        if 'c1_sessions' in tables:
            ids = db.execute('SELECT DISTINCT study_id FROM c1_sessions').fetchall()
            if any(row['study_id'] != STUDY_ID for row in ids):
                raise RuntimeError('Refusing to use a database containing another C1 study')
        for table in ('c4_sessions', 'sessions'):
            if table in tables and db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]:
                raise RuntimeError('Refusing to use a database containing another study')


def create_app(state_dir=DEFAULT_STATE, use_postgres=False):
    configure(state_dir, use_postgres)
    import main as shared
    from database import get_connection
    from security import SESSION_COOKIE, require_admin

    @asynccontextmanager
    async def lifespan(app):
        assert_separate_store()
        async with shared.lifespan(app):
            with get_connection() as db:
                db.execute('CREATE TABLE IF NOT EXISTS rehearsal_session_actors (session_id TEXT PRIMARY KEY, researcher TEXT NOT NULL)')
            yield

    app = FastAPI(title='C1 researcher rehearsal', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.router.routes.extend(shared.app.router.routes)

    def actor(request, cookie):
        return require_admin(authorization=request.headers.get('authorization', ''),
                             researcher_session=cookie)

    @app.middleware('http')
    async def researcher_boundary(request: Request, call_next):
        path = request.url.path
        allowed = (path.startswith('/assets/') or path.startswith('/api/researcher/')
                   or path.startswith('/api/c1-pilot/') or path in ('/', '/researcher', '/admin', '/pilot', '/pilot/admin', '/api/health', '/favicon.ico'))
        if not allowed:
            return JSONResponse({'detail': 'This instance contains only the C1 researcher rehearsal'}, status_code=404)
        if path in ('/', '/researcher', '/admin'):
            return RedirectResponse('/pilot/admin')
        cookie = request.cookies.get(REHEARSAL_COOKIE)
        protected = path == '/pilot' or path.startswith('/api/c1-pilot/')
        researcher = None
        if protected:
            try:
                researcher = actor(request, cookie)
            except HTTPException as error:
                if path == '/pilot':
                    return RedirectResponse('/pilot/admin')
                return JSONResponse({'detail': 'Sign in as a researcher to use this rehearsal'}, status_code=error.status_code,
                                    headers={'Cache-Control': 'private, no-store'})
        prefix = '/api/c1-pilot/sessions/'
        if path.startswith(prefix):
            session_id = path[len(prefix):].split('/')[0]
            with get_connection() as db:
                owner = db.execute('SELECT researcher FROM rehearsal_session_actors WHERE session_id=?', (session_id,)).fetchone()
            if owner is None or owner['researcher'] != researcher:
                return JSONResponse({'detail': 'This rehearsal session belongs to another researcher'}, status_code=403)
        # Keep localhost rehearsal logins independent of any pilot on another
        # port. Forward only the dedicated cookie under the shared API's alias.
        request.scope['headers'] = [(key, value) for key, value in request.scope['headers'] if key.lower() != b'cookie']
        if cookie:
            request.scope['headers'].append((b'cookie', f'{SESSION_COOKIE}={cookie}'.encode('ascii')))
        response = await call_next(request)
        if response.headers.get('set-cookie'):
            response.headers['set-cookie'] = response.headers['set-cookie'].replace(f'{SESSION_COOKIE}=', f'{REHEARSAL_COOKIE}=', 1)
        if path.startswith('/api/c1-pilot/'):
            response.headers['Cache-Control'] = 'private, no-store'
        capture = (path == '/api/c1-pilot/sessions' and request.method == 'POST' and response.status_code == 200)
        exported = path in ('/api/c1-pilot/admin/export', '/api/c1-pilot/admin/sessions') and response.status_code == 200
        if not capture and not exported:
            return response
        body = b''.join([chunk async for chunk in response.body_iterator])
        headers = dict(response.headers)
        headers.pop('content-length', None)
        if capture:
            session_id = json.loads(body)['session_id']
            with get_connection() as db:
                db.execute('INSERT INTO rehearsal_session_actors(session_id,researcher) VALUES (?,?)', (session_id, researcher))
                row = db.execute('SELECT entry_json FROM c1_sessions WHERE session_id=?', (session_id,)).fetchone()
                entry = json.loads(row['entry_json'])
                entry.update(data_origin=ORIGIN, entered_by=researcher)
                db.execute('UPDATE c1_sessions SET entry_json=? WHERE session_id=?', (json.dumps(entry), session_id))
        else:
            rows = csv.DictReader(io.StringIO(body.decode()))
            columns = [*(rows.fieldnames or []), 'data_origin', 'entered_by', 'session_type']
            with get_connection() as db:
                owners = {row['session_id']: row['researcher'] for row in db.execute('SELECT * FROM rehearsal_session_actors').fetchall()}
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                row.update(data_origin=ORIGIN, entered_by=owners.get(row['session_id'], ''), session_type='researcher_rehearsal')
                if 'analysis_include' in row:
                    row['analysis_include'] = 'False'
                writer.writerow(row)
            body = output.getvalue().encode()
            suffix = 'responses' if path.endswith('/export') else 'sessions'
            headers['Content-Disposition'] = f'attachment; filename="c1_researcher_rehearsal_{suffix}.csv"'
        return Response(body, status_code=response.status_code, headers=headers)

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '8790')))
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--postgres', action='store_true', help='Use a separate SURVEY_REHEARSAL_DATABASE_URL')
    args = parser.parse_args()
    app = create_app(use_postgres=args.postgres)
    print(f'C1 researcher rehearsal: http://{args.host}:{args.port}/pilot/admin', flush=True)
    if not args.postgres:
        print(f'Private local login: {DEFAULT_STATE / "private_access.json"}', flush=True)
    import uvicorn
    # Render terminates TLS at its ingress. Trust its forwarded scheme only in
    # this deployed mode so login cookies receive Secure on the public HTTPS URL.
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=True,
                forwarded_allow_ips='*' if args.postgres else '127.0.0.1')


if __name__ == '__main__':
    main()
