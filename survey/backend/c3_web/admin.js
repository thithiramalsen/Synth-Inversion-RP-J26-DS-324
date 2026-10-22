/* C3 researcher area: shared researcher sign-in, invitation codes, saved runs, export. */
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const content = $('#content');

async function request(path, method = 'GET', data) {
  const response = await fetch(path, {method, headers: {'Content-Type': 'application/json'},
                                      ...(method === 'POST' ? {body: JSON.stringify(data || {})} : {})});
  if (!response.ok) {
    let detail = 'Request failed';
    try { const body = await response.json(); if (typeof body.detail === 'string') detail = body.detail; } catch (_) { /* not JSON */ }
    const error = new Error(detail); error.status = response.status; throw error;
  }
  return response.json();
}
function showError(error) { $('#error').hidden = false; $('#error').textContent = error.message || String(error); }
function clearError() { $('#error').hidden = true; }

function loginForm() {
  $('#who').textContent = '';
  content.innerHTML = `<span class="eyebrow">Researcher sign-in</span><h1>C3 researcher area</h1>
    <p>Use the same researcher account as the other study panels on this site. C3 runs are rehearsal-only and excluded from research findings.</p>
    <form id="login" class="card"><label class="block" for="username">Username</label><input id="username" name="username" autocomplete="username" required>
    <label class="block" for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" required>
    <div class="actions"><button type="submit">Sign in</button></div></form>`;
  $('#login').onsubmit = async event => {
    event.preventDefault(); clearError();
    const f = new FormData(event.target);
    try { await request('/api/researcher/login', 'POST', {username: f.get('username'), password: f.get('password')}); await load(); }
    catch (error) { showError(error); }
  };
}

function render(summary) {
  $('#who').textContent = `Signed in as ${summary.researcher}`;
  const invites = summary.invitations.map(item => `<div class="invite"><label for="${esc(item.assignment_id)}">${esc(item.assignment_id)} · ${item.used ? 'In use' : 'Unused'}</label><input id="${esc(item.assignment_id)}" readonly value="${esc(item.invitation || 'Code unavailable')}"></div>`).join('');
  const rows = summary.sessions.map(s => `<tr><td>${esc(s.code)}</td><td>${esc(s.purpose.replaceAll('_', ' '))}</td><td>${esc(s.phase)}</td><td>${s.saved_cases}/8</td><td>${s.screen_skipped ? 'skipped' : ''}</td></tr>`).join('');
  content.innerHTML = `<span class="eyebrow">Hosted rehearsal · ${esc(summary.version)}</span><h1>C3 researcher area</h1>
    <div class="note"><p>Research collection is disabled. Independent C3 participants: ${summary.independent_participants}. Repeated rehearsal runs are not independent people.</p></div>
    <section class="card"><h2>Researcher self-review</h2><p>Run the study yourself. You may skip the headphone check (for example in a presentation); such runs are marked and excluded from analysis.</p>
      <div class="actions"><a class="button-link" href="/c3/?view=researcher">Start or resume self-review</a></div></section>
    <section class="card"><h2>C3 preview invitations</h2><p>Issue codes only for authorised rehearsal checks. Send the <a href="/c3/">C3 study link</a> with one unused code; each code starts one saved session.</p>
      <div class="actions"><button type="button" id="create">Create missing C3 preview codes</button></div>
      <div class="invites">${invites || '<p class="muted">No codes yet.</p>'}</div></section>
    <section class="card"><h2>Saved rehearsal runs</h2>${rows ? `<div class="table-wrap"><table><thead><tr><th>Code</th><th>View</th><th>Stage</th><th>Saved cases</th><th>Setup check</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<p class="muted">No C3 runs saved on this deployment.</p>'}
      <div class="actions"><button type="button" class="secondary" id="refresh">Refresh</button><a href="/c3/api/admin/export">Download completed rehearsal runs</a><button type="button" class="text-button" id="logout">Sign out</button></div></section>`;
  $('#create').onclick = async () => { clearError(); try { render(await request('/c3/api/admin/invitations', 'POST', {})); } catch (error) { showError(error); } };
  $('#refresh').onclick = () => load().catch(showError);
  $('#logout').onclick = async () => { try { await request('/api/researcher/logout', 'POST', {}); } catch (_) { /* already signed out */ } loginForm(); };
  document.querySelectorAll('.invite input').forEach(input => input.addEventListener('focus', () => input.select()));
}

async function load() {
  clearError();
  try { render(await request('/c3/api/admin/summary')); }
  catch (error) { if (error.status === 401) loginForm(); else showError(error); }
}
load();
