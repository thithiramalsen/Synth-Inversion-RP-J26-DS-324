"""Loopback-only visual QA using temporary DBs and labelled synthetic responses.

Not shipped in Docker (only backend/*.py is copied). Never use for human testing.
"""
import argparse
import json
import secrets

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

from survey.backend.tests.test_c2_hosted_v2 import HostedC2V2Tests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8782)
    args = parser.parse_args()
    if args.port in {8000, 8765, 8766, 8767, 8768, 8769, 8770}:
        raise ValueError('Use a separate QA port, never an existing app port')
    fixture = HostedC2V2Tests()
    fixture.setUp()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get('/')
    def index():
        return HTMLResponse('<h1>C2 v2 disposable UI checks</h1><p>Temporary database. Machine-generated fixture responses, not human research.</p>' +
            ''.join(f'<p><a href="/qa/prepare/{phase}">{phase}</a></p>' for phase in
                    ('entry', 'listening', 'display-with', 'display-without', 'feedback')))

    @app.get('/qa/prepare/{phase}')
    def prepare(phase: str):
        if phase not in ('entry', 'listening', 'display-with', 'display-without', 'feedback'):
            return HTMLResponse('Unknown fixture', status_code=404)
        script = "localStorage.removeItem('c2-hosted-v2-participant_preview-token');"
        if phase != 'entry':
            fixture.token = secrets.token_hex(32)
            fixture.headers = {'Authorization': 'Bearer ' + fixture.token}
            invites = fixture.client.post('/api/c2-pilot/v2/admin/invitations', headers=fixture.admin, json={}).json()['invitations']
            code = next(i['invitation'] for i in invites if not i['used'])
            state = fixture.setup_listening(code)
            if phase == 'listening':
                fixture.listen(state)
                state = fixture.action(state, 'listening', dict(similarity=3, comment='Synthetic browser fixture, not a human response'))
                state = fixture.action(state, 'continue', {})
            else:
                state = fixture.advance_listening(state)
                state = fixture.action(state, 'continue', {})
                desired = phase.removeprefix('display-')
                while state['phase'] != 'feedback':
                    if state['phase'] == 'display_break':
                        state = fixture.action(state, 'continue', {})
                    elif phase != 'feedback' and state['case']['condition'] == desired:
                        break
                    else:
                        state = fixture.action(state, 'display', dict(clarity=3, usefulness=3))
            script = "localStorage.setItem('c2-hosted-v2-participant_preview-token'," + json.dumps(json.dumps(fixture.token)) + ');'
        return HTMLResponse('<!doctype html><title>Disposable C2 fixture</title><p>Preparing a disposable UI fixture, not a participant session.</p><script>' +
                            script + "window.location.replace('/c2/rehearsal-v2');</script>")

    app.mount('/', fixture.client.app)
    print(f'DISPOSABLE C2 UI FIXTURES ONLY: http://127.0.0.1:{args.port}/', flush=True)
    try:
        uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning')
    finally:
        fixture.doCleanups()


if __name__ == '__main__':
    main()
