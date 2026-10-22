/* Local rehearsal only. No third-party scripts, trackers, or audio uploads. */
const TOKEN_KEY = 'c3-human-v2-rehearsal-token';
const DRAFT_PREFIX = 'c3-rehearsal-draft-';
const CONSENT = ['adult', 'english', 'synth_experience', 'information_read', 'voluntary', 'coded_data'];
const SET_QUESTIONS = [
  ['useful_starting_points', 'Which set gives you more useful, different starting points to edit towards the target?'],
  ['closer_overall', 'Which set sounds closer to the target overall?'],
  ['more_different_by_ear', 'In which set do the sounds sound more different from each other?'],
];
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let token = localStorage.getItem(TOKEN_KEY), state = null, playbackQueue = Promise.resolve(), blobs = [];
let playbackError = null;
const content = $('#content');

function showError(error) { $('#error').hidden = false; $('#error').textContent = error.message || String(error); $('#error').scrollIntoView({block:'center'}); }
async function api(path, method='GET', data) {
  const response = await fetch('/api/' + path, {method, headers: {'Content-Type':'application/json', ...(token ? {Authorization:'Bearer '+token} : {})}, ...(data ? {body:JSON.stringify(data)} : {})});
  if (!response.ok) { const body = await response.json(); const error = new Error(typeof body.detail === 'string' ? body.detail : 'Please check the answers and try again.'); error.status = response.status; throw error; }
  return response.json();
}
function stopAudio() { document.querySelectorAll('audio').forEach(a => a.pause()); }
function cleanup() { stopAudio(); blobs.forEach(URL.revokeObjectURL); blobs = []; }
function draftKey() { return `${DRAFT_PREFIX}${state.code}-${state.revision}`; }
function bindDraft(form) {
  const saved = JSON.parse(localStorage.getItem(draftKey()) || '{}');
  for (const element of form.elements) {
    if (!(element.name in saved)) continue;
    if (element.type === 'radio' || element.type === 'checkbox') element.checked = saved[element.name] === element.value;
    else element.value = saved[element.name];
  }
  form.addEventListener('input', () => localStorage.setItem(draftKey(), JSON.stringify(Object.fromEntries(new FormData(form)))));
}
function clearDrafts() { for (const key of Object.keys(localStorage)) if (key.startsWith(`${DRAFT_PREFIX}${state.code}-`)) localStorage.removeItem(key); }
function choices(name, options, required=true) {
  return options.map(([value, label]) => `<label class="choice"><input type="radio" name="${name}" value="${value}" ${required ? 'required' : ''}>${esc(label)}</label>`).join('');
}
function check(name, label) { return `<label class="choice"><input type="checkbox" name="${name}" required>${label}</label>`; }
function select(name, items) { return `<select name="${name}" id="${name}" required><option value="">Choose an answer</option>${items.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join('')}</select>`; }
function audioCard(id, title, extra='') { return `<div class="card ${extra}"><h3>${title}</h3><small>Listen all the way through once; replay as often as you like.</small><audio controls preload="none" data-audio="${id}" aria-label="${title}"></audio></div>`; }
const RATING = [['1','1 — Not close'],['2','2'],['3','3'],['4','4'],['5','5 — Very close'],['cannot_judge','Cannot judge']];

function knobs(params) {
  // 13 bars, each the knob position on this study's 0–100 scale; drawn with SVG attributes only.
  const labels = state.parameter_labels, w = 10, h = 40;
  const bars = params.map((v, i) => {
    const height = Math.max(1, v * h).toFixed(1);
    return `<g><title>${esc(labels[i])}: ${(v * 100).toFixed(0)} / 100</title><rect class="track" x="${i * w}" y="0" width="${w - 2}" height="${h}"></rect><rect class="fill" x="${i * w}" y="${(h - height).toFixed(1)}" width="${w - 2}" height="${height}"></rect></g>`;
  }).join('');
  return `<svg class="knobs" viewBox="0 0 ${params.length * w - 2} ${h}" preserveAspectRatio="none" role="img" aria-label="Knob settings">${bars}</svg>`;
}

async function loadAudio() {
  await Promise.all([...document.querySelectorAll('[data-audio]')].map(async audio => {
    const id = audio.dataset.audio;
    const response = await fetch('/api/audio/' + encodeURIComponent(id), {headers: {Authorization: 'Bearer ' + token}});
    if (!response.ok) throw new Error('Could not load the audio. Please reload to try again.');
    const url = URL.createObjectURL(await response.blob()); blobs.push(url); audio.src = url;
    const record = event => {
      playbackQueue = playbackQueue.then(() => api('play', 'POST', {audio_id: id, event})).catch(error => { playbackError = error; showError(new Error('Playback could not be saved. Reload this page and replay the clip.')); });
    };
    audio.addEventListener('play', () => { document.querySelectorAll('audio').forEach(other => { if (other !== audio) other.pause(); }); record('start'); });
    audio.addEventListener('ended', () => record('end'));
  }));
}
async function send(op, answers={}) {
  stopAudio();
  await playbackQueue;
  if (playbackError && op !== 'withdraw') throw playbackError;
  const oldDraft = draftKey();
  const next = await api('action', 'POST', {revision: state.revision, op, answers});
  localStorage.removeItem(oldDraft); state = next;
  if (op === 'withdraw') clearDrafts();
  await render(); window.scrollTo(0, 0);
}
function formHandler(op, getAnswers) {
  const form = $('#study-form'); bindDraft(form);
  form.addEventListener('submit', async event => {
    event.preventDefault(); const button = form.querySelector('[type=submit]'); button.disabled = true;
    try { await send(op, getAnswers(new FormData(form))); } catch (error) { showError(error); button.disabled = false; }
  });
}

function welcome() {
  cleanup(); $('#session-actions').hidden = true; $('#progress').textContent = 'Before you begin'; $('#session-code').textContent = '';
  content.innerHTML = `<span class="eyebrow">Rehearsal / Not a participant invitation</span><h1>Which set of sounds would you start from?</h1>
    <p class="lead">You’ll hear a short synthesizer sound and two sets of five suggested patches. Each set tries to sound like the target. Tell us how close each sound is and which set you’d rather start editing from.</p>
    <div class="note"><p>This is a local test of the study. Research collection is disabled. Don’t recruit participants with this version. Every saved response is marked as rehearsal data.</p></div>
    <div class="cards"><div class="card"><h3>What you’ll do</h3><p>Set a comfortable volume, check your headphones, try one practice case, then compare sets for eight target sounds. There’s a break halfway.</p><p>Allow about 30–35 minutes; please stop by 40 minutes. You can pause or stop sooner.</p></div>
    <div class="card"><h3>What gets saved</h3><p>Your consent choices, experience range, ratings, set choices, comments, playback counts and step timestamps. No recordings or names.</p><p>Responses use a random code and stay in a separate local rehearsal database. They are excluded from research analysis.</p></div></div>
    <details><summary>Read before taking part</summary><p>Participation is voluntary and unpaid. There are no marks, course credits or employment benefits. You can decline without giving a reason. Use headphones in a quiet place and start at a low volume. Stop if anything feels uncomfortable; never turn the volume up to pass the check.</p><p>This is not a hearing test and does not ask for hearing or health information. You won’t edit a real patch. There are no right or wrong answers, and “Cannot judge” is always a valid answer.</p><p>You can remove your linked rehearsal answers with the withdrawal button, including after completion, on this browser. Keep your code if you want to ask the researcher about your session. A minimal consent/withdrawal record remains. Closing the browser pauses; it does not withdraw.</p><p>Browser storage keeps a secret resume key and unfinished answers on this device. Avoid shared devices. Data are coded, not guaranteed anonymous. Public hosting, researcher/PI contacts, independent complaints contact, ethics approval, retention and withdrawal policy must be finalized before a research version is enabled.</p></details>
    <form id="consent-form"><h2>Eligibility and consent</h2>
      ${check('adult', 'I am 18 or older.')}${check('english', 'I can understand the English instructions.')}
      ${check('synth_experience', 'I have practical experience adjusting synthesizer controls or software instruments.')}
      <label class="block" for="experience">How long have you been doing that?</label>${select('experience', [['under_1', 'Less than a year'], ['1_to_3', '1–3 years'], ['over_3', 'More than 3 years']])}
      ${check('information_read', 'I have read the information above and understand what this rehearsal involves.')}
      ${check('voluntary', 'I understand that joining is voluntary and I can pause or withdraw.')}
      ${check('coded_data', 'I agree to these coded responses being saved locally for testing this study, not used as research data.')}
      <div class="actions"><button type="submit">Start the rehearsal</button><button type="button" class="secondary" id="decline">No thanks</button></div></form>`;
  $('#decline').onclick = () => { content.innerHTML = '<h1>No problem.</h1><p>No new session or answers have been saved. You can close this tab.</p>'; };
  $('#consent-form').onsubmit = async event => {
    event.preventDefault(); const button = event.target.querySelector('[type=submit]'); button.disabled = true;
    try {
      if (!token) { token = [...crypto.getRandomValues(new Uint8Array(32))].map(x => x.toString(16).padStart(2, '0')).join(''); localStorage.setItem(TOKEN_KEY, token); }
      const f = new FormData(event.target), consent = Object.fromEntries(CONSENT.map(k => [k, f.has(k)]));
      state = await api('start', 'POST', {consent, experience: f.get('experience')}); await render(); window.scrollTo(0, 0);
    } catch (error) { showError(error); button.disabled = false; }
  };
}

async function render() {
  cleanup(); playbackError = null; $('#error').hidden = true;
  $('#session-code').textContent = state.code;
  $('#progress').innerHTML = `${state.scored_completed} of ${state.total_cases} cases saved · ${state.phase === 'practice' ? 'Practice is not scored' : 'You can pause at any point'}<progress max="${state.total_cases}" value="${state.scored_completed}"></progress>`;
  $('#session-actions').hidden = state.phase === 'withdrawn';
  const phase = state.phase;
  if (phase === 'volume') {
    content.innerHTML = `<span class="eyebrow">Setup / 1 of 2</span><h1>Get comfortable first.</h1><p>Put on headphones and start with your device volume low. Play the reference, then set a comfortable level. Keep that level for the study. If later clips feel uncomfortable, stop.</p>${audioCard('volume_reference', 'Volume reference')}<form id="study-form">${check('headphones', 'I am using headphones.')}${check('quiet', 'I am in a quiet place.')}${check('comfortable', 'The playback level is comfortable.')}<button type="submit">Check my setup</button></form>`;
    formHandler('volume', f => Object.fromEntries(['headphones', 'quiet', 'comfortable'].map(k => [k, f.has(k)])));
  } else if (phase === 'headphones') {
    content.innerHTML = `<span class="eyebrow">Setup / 2 of 2</span><h1>Which tone is quietest?</h1><p>Check ${state.screen_number} of 6. You’ll hear three tones with gaps between them. Choose the quietest. Keep your current volume; don’t turn it up to pass.</p>${audioCard(state.audio_ids[0], 'Three-tone setup check')}<form id="study-form"><fieldset><legend>The quietest tone was…</legend><div class="inline-options">${choices('interval', [['1', 'First'], ['2', 'Second'], ['3', 'Third']])}</div></fieldset><button type="submit">Save and continue</button></form>`;
    formHandler('headphone', f => ({interval: Number(f.get('interval'))}));
  } else if (phase === 'practice' || phase === 'task') {
    renderCase();
  } else if (phase === 'instructions') {
    content.innerHTML = `<span class="eyebrow">Practice complete</span><h1>Ready for the eight cases?</h1><p>Your practice answers don’t count toward the study results.</p><div class="note"><p><strong>Set A and Set B are chosen in two different ways</strong>, and which is “A” changes from case to case. Neither is the right answer. A sound can appear in both sets; it then keeps the same number.</p></div><p>The bars show each suggested patch’s 13 knob settings on this study’s 0–100 scale. Patches with different bar shapes are different recipes, even when they sound alike. Judge closeness by ear; use the bars to think about which set gives you useful, different places to start editing.</p><button id="continue">Begin the cases</button>`;
    $('#continue').onclick = () => send('continue').catch(showError);
  } else if (phase === 'break') {
    content.innerHTML = `<span class="eyebrow">Halfway / ${state.scored_completed} cases saved</span><h1>Time for a short break.</h1><p>Take your headphones off if you like. Your answers are saved. Keep the same comfortable volume when you return.</p><button id="continue">Continue with case ${state.scored_completed + 1}</button>`;
    $('#continue').onclick = () => send('continue').catch(showError);
  } else if (phase === 'feedback') {
    content.innerHTML = `<span class="eyebrow">Last step</span><h1>How did that feel?</h1><form id="study-form"><label class="block" for="knob_bars">How useful were the knob bars for choosing between the sets?</label>${select('knob_bars', [['1', '1 — Not at all useful'], ['2', '2'], ['3', '3'], ['4', '4'], ['5', '5 — Very useful'], ['cannot_judge', 'Cannot judge']])}<fieldset><legend>The session length was…</legend>${choices('length', [['about_right', 'About right'], ['too_long', 'Too long'], ['could_be_longer', 'Could be longer']])}</fieldset><label class="block" for="comment">Anything useful or confusing? <small>(optional)</small></label><textarea id="comment" name="comment" maxlength="1000"></textarea><div class="actions"><button type="submit">Finish the rehearsal</button></div></form>`;
    formHandler('finish', f => ({knob_bars: f.get('knob_bars') === 'cannot_judge' ? 'cannot_judge' : Number(f.get('knob_bars')), length: f.get('length'), comment: f.get('comment')}));
  } else if (phase === 'complete') {
    content.innerHTML = `<span class="eyebrow">All saved</span><h1>Thanks. You’re finished.</h1><p>Your completion code is:</p><div class="code">${esc(state.code)}</div><p>This was a rehearsal. These responses will not be included in research findings. Save the code if you want the researcher to find your session.</p><p>You can still withdraw below from this browser.</p><button type="button" class="secondary" id="new-rehearsal">Start another test session</button>`;
    $('#new-rehearsal').onclick = () => { if (confirm('Keep this completed rehearsal and start another? Save your code first. This browser will stop resuming this session.')) { clearDrafts(); localStorage.removeItem(TOKEN_KEY); token = null; state = null; welcome(); } };
  } else if (phase === 'withdrawn') {
    content.innerHTML = '<h1>Your answers have been removed.</h1><p>The linked answers were removed from active local storage. A minimal consent/withdrawal record remains. This does not promise removal from any separately made copies or backups.</p><p>You can close this tab.</p>'; clearDrafts();
  } else if (phase === 'screen_failed') {
    content.innerHTML = '<h1>We’ll stop here.</h1><p>This setup check did not pass. That is not a diagnosis or a hearing test result. Don’t increase the volume or keep retrying to pass. Your session is incomplete and will not be treated as a completed study.</p><p>You can withdraw the saved setup answers below, or close this tab.</p>';
  }
  await loadAudio();
}

function renderCase() {
  const item = state.case, practice = state.phase === 'practice';
  const byNumber = Object.fromEntries(item.sounds.map(s => [s.number, s]));
  const inA = new Set(item.sets.A), inB = new Set(item.sets.B);
  const column = (label, cls, numbers, other) => `<section class="set ${cls}" aria-label="Set ${label}"><h2>Set ${label} <small>${numbers.length} sounds</small></h2>${numbers.map(n => {
    const sound = byNumber[n];
    return `<div class="sound"><div class="sound-head"><strong>Sound ${n}</strong>${other.has(n) ? `<span class="tag">in both sets</span>` : ''}</div><audio controls preload="none" data-audio="${sound.sound_id}" aria-label="Sound ${n}"></audio>${knobs(sound.params)}</div>`;
  }).join('')}</section>`;
  const numbers = item.sounds.map(s => s.number).sort((a, b) => a - b);
  content.innerHTML = `<span class="eyebrow">${practice ? 'Practice / Not scored' : `Case ${state.scored_completed + 1} of ${state.total_cases}`}</span><h1>Which set would you start from?</h1>
    <p>Listen to the target, then to every sound in Set A and Set B. Each sound was suggested because it sounds similar to the target.</p>
    ${audioCard(item.target_audio_id, 'Target sound', 'target')}
    <div class="sets">${column('A', 'a', item.sets.A, inB)}${column('B', 'b', item.sets.B, inA)}</div>
    <div class="legend"><span>Bars, left to right:</span>${state.parameter_labels.map((l, i) => `<span><b>${i + 1}</b> ${esc(l)}</span>`).join('')}</div>
    <form id="study-form"><h2>How close is each sound to the target?</h2><p class="muted">Judge by ear. A sound in both sets is rated once.</p>
    <div class="ratings-table">${numbers.map(n => `<div><label for="close_${n}">Sound ${n} <small>(${inA.has(n) && inB.has(n) ? 'both sets' : inA.has(n) ? 'Set A' : 'Set B'})</small></label>${select('close_' + n, RATING)}</div>`).join('')}</div>
    <h2>Compare the two sets</h2><div class="compare">${SET_QUESTIONS.map(([name, label]) => `<fieldset><legend>${esc(label)}</legend>${choices(name, [['A', 'Set A'], ['B', 'Set B'], ['no_difference', 'No difference'], ['cannot_judge', 'Cannot judge']])}</fieldset>`).join('')}</div>
    <label class="block" for="confidence">How confident are you in these answers?</label>${select('confidence', [['1', '1 — Not confident'], ['2', '2'], ['3', '3'], ['4', '4'], ['5', '5 — Very confident'], ['cannot_judge', 'Cannot judge']])}
    <label class="block" for="reason">What led to your choices? <small>(optional)</small></label><textarea name="reason" id="reason" maxlength="1000"></textarea>
    <div class="actions"><button type="submit">${practice ? 'Finish practice' : 'Save and continue'}</button><small>Answers save when you continue. Unfinished choices stay on this browser.</small></div></form>`;
  const value = v => v === 'cannot_judge' ? 'cannot_judge' : Number(v);
  formHandler('response', f => {
    const answers = {closeness: Object.fromEntries(numbers.map(n => [String(n), value(f.get('close_' + n))])),
                     confidence: value(f.get('confidence')), reason: f.get('reason') || ''};
    for (const [name] of SET_QUESTIONS) answers[name] = f.get(name);
    return answers;
  });
}

$('#pause').onclick = () => { cleanup(); $('#session-actions').hidden = true; content.innerHTML = '<div class="pause-panel"><span class="eyebrow">Paused</span><h1>Your place is saved.</h1><p>You can close this tab and return on the same browser and device. Unfinished choices are saved on this device; submitted answers are in the local rehearsal database.</p><p>Closing the tab does not withdraw. Resume to use the withdrawal button.</p><button id="resume">Resume</button></div>'; $('#resume').onclick = () => render().catch(showError); };
$('#withdraw').onclick = () => { if (confirm('Withdraw this rehearsal and remove the linked answers from active local storage? A minimal consent/withdrawal record will remain.')) send('withdraw').catch(showError); };
async function boot() {
  try {
    await api('info');
    if (token) { try { state = await api('session'); await render(); return; } catch (error) { if (error.status !== 401) throw error; token = null; localStorage.removeItem(TOKEN_KEY); } }
    welcome();
  } catch (error) { content.innerHTML = '<h1>The rehearsal is unavailable.</h1><p>Check that its local server is running, then reload. No new answers were saved.</p>'; showError(error); }
}
boot();
