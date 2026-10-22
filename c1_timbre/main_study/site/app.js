/* C1 main-study demonstration site. No server: a session lives in this browser only. */
'use strict';

const TRAITS = ['brightness', 'roughness', 'percussiveness', 'sustainedness'];
let STUDY = null;
let state = null;
let KEY = 'c1-main-demo';

// ---------------------------------------------------------------- helpers
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v === null || v === undefined) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'text') el.textContent = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) el.append(c.nodeType ? c : String(c));
  return el;
}
const pad = n => String(n).padStart(2, '0');
const now = () => new Date().toISOString().replace(/\.\d+Z$/, 'Z');
function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* storage unavailable: session lasts for this page only */ } }
function load() { try { return JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (e) { return null; } }
function clearSaved() { try { localStorage.removeItem(KEY); } catch (e) { /* ignore */ } }
function shuffle(a) { a = a.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; }
const block = () => STUDY.assignments.find(b => b.assignment_id === state.block);
const trials = () => block().trials;
const studyTrials = () => trials().filter(t => t.kind !== 'practice');
function audioSrc(sampleId) { return STUDY.sounds[sampleId].file; }

// ---------------------------------------------------------------- views
function showView(name) {
  for (const v of ['participant', 'design']) {
    document.getElementById('view-' + v).hidden = v !== name;
    document.getElementById('tab-' + v).setAttribute('aria-selected', String(v === name));
  }
  try { localStorage.setItem(KEY + ':view', name); } catch (e) { /* ignore */ }
  window.scrollTo({ top: 0 });
}

const root = () => document.getElementById('participant');
function render(...nodes) {
  const r = root();
  r.replaceChildren(h('div', { class: 'demo-band' },
    h('strong', { text: 'Demonstration. ' }),
    'Sounds come from a provisional dry-run selection and will be replaced. Your answers stay in this browser and are not research data.'), ...nodes);
}

// ---------------------------------------------------------------- entry
function entryView() {
  const c = STUDY.config, d = STUDY.design;
  const values = { activities: [] };
  const checks = [['consent', 'I have read this information and voluntarily agree to take part.']];
  const setup = [['adult', 'I am 18 or older.'], ['understands_language', 'I can comfortably understand these English instructions.'],
    ['headphones', 'I am using headphones or earphones.'], ['quiet_environment', 'I am in a quiet place and can listen without interruption.']];
  const box = (key, text) => h('label', { class: 'check' }, h('input', { type: 'checkbox', id: 'f-' + key, required: true, onchange: e => { values[key] = e.target.checked; } }), text);
  let next = 1; try { next = Number(localStorage.getItem(KEY + ':next') || 1); } catch (e) { /* ignore */ }
  const blockSelect = h('select', { id: 'f-block' },
    h('option', { value: 'auto', text: `Next in issue order (block_${pad(next)})` }),
    STUDY.assignments.map(b => h('option', { value: b.assignment_id, text: b.assignment_id })));
  const form = h('form', { onsubmit: e => { e.preventDefault(); start(values, blockSelect.value, next); } },
    h('div', { class: 'hero' }, h('p', { class: 'eyebrow', text: 'Synth timbre research · main study' }), h('h1', { text: 'A closer listen.' }),
      h('p', { class: 'lede', text: 'How do we describe the character of a sound? Listen to short synthesizer clips and rate what you hear.' }),
      h('div', { class: 'facts' },
        h('span', {}, h('b', { text: String(c.descriptors.length) }), 'qualities'),
        h('span', {}, h('b', { text: String(d.presentations_per_person) }), 'presentations'),
        h('span', {}, h('b', { text: `~${Math.round(d.median_minutes)} min` }), 'median time'),
        h('span', {}, h('b', { text: 'Headphones' }), 'required'))),
    h('section', { class: 'card' }, h('h2', { text: 'Before you take part' }), c.information.map(t => h('p', { class: 'muted', text: t })), checks.map(([k, t]) => box(k, t))),
    h('section', { class: 'card' }, h('h2', { text: 'Your listening setup' }), setup.map(([k, t]) => box(k, t)),
      h('p', { class: 'muted', text: 'Turn off optional sound enhancements or EQ where practical.' })),
    h('section', { class: 'card' }, h('h2', { text: 'Your experience' }),
      h('p', { class: 'muted', text: 'Tell us about your practical music or sound-design experience. Leave out names, contact details and identifying links.' }),
      h('fieldset', {}, h('legend', { text: 'Which have you done? Select at least one.' }),
        c.activities.map(a => h('label', { class: 'check' }, h('input', { type: 'checkbox', onchange: e => { values.activities = e.target.checked ? [...values.activities, a] : values.activities.filter(x => x !== a); } }), a))),
      h('div', { class: 'cols' },
        h('label', { class: 'field' }, 'Approximately how many months?', h('input', { id: 'f-months', type: 'number', min: 0, max: 1200, required: true, oninput: e => { values.experience_months = Number(e.target.value); } })),
        h('label', { class: 'field' }, 'How often recently?', h('select', { id: 'f-freq', required: true, onchange: e => { values.recent_frequency = e.target.value; } },
          h('option', { value: '', text: 'Choose frequency' }), ['Less than monthly', 'Monthly', 'Weekly', 'Daily'].map(f => h('option', { text: f }))))),
      h('label', { class: 'field' }, c.experience_tools_label || 'Which tools have you used?', h('input', { id: 'f-tools', required: true, minlength: 2, maxlength: 250, placeholder: c.experience_tools_placeholder || '', oninput: e => { values.tools = e.target.value; } })),
      h('label', { class: 'field' }, c.experience_question.label, h('textarea', { id: 'f-example', required: true, minlength: 20, maxlength: 700, rows: 2, placeholder: c.experience_question.placeholder, oninput: e => { values.example = e.target.value; } })),
      h('p', { class: 'muted', text: c.experience_question.help })),
    h('section', { class: 'card' },
      h('label', { class: 'field' }, 'Assignment block (demonstration)', blockSelect),
      h('p', { class: 'muted', text: `In the real study an invitation code assigns one of ${STUDY.assignments.length} balanced blocks. Here you can pick one to preview.` }),
      h('button', { class: 'btn btn-primary', type: 'submit' }, 'Start listening setup', h('span', { 'aria-hidden': 'true', text: '→' }))));
  render(form);
}

function start(entry, choice, next) {
  if (!entry.activities.length) { alertBox('Select at least one experience category.'); return; }
  const blockId = choice === 'auto' ? `block_${pad(next)}` : choice;
  if (choice === 'auto') { try { localStorage.setItem(KEY + ':next', String(next % STUDY.assignments.length + 1)); } catch (e) { /* ignore */ } }
  state = { version: STUDY.version, participant: 'DEMO_' + Math.random().toString(36).slice(2, 8).toUpperCase(),
    session: 'DEMO_S_' + Date.now().toString(36), block: blockId, entry, phase: 'volume', started_at: now(),
    screens: shuffle(STUDY.headphones).map(s => s.screen_id), screenAnswers: [], index: 0, breakDone: false,
    responses: {}, feedback: null, completed_at: null, withdrawn_at: null };
  save(); route();
}

function alertBox(message) {
  const old = document.getElementById('inline-alert'); if (old) old.remove();
  const el = h('div', { id: 'inline-alert', class: 'card', role: 'alert' }, h('strong', { text: 'Please check this. ' }), message);
  root().prepend(el); el.scrollIntoView({ block: 'center' });
}

// ---------------------------------------------------------------- shared pieces
function sessionBar(extra) {
  return h('div', { class: 'session-bar' }, h('span', { class: 'pill', text: `${state.participant} · ${state.block}` }), extra || null);
}
function footerLinks() {
  return h('div', { class: 'actions', style: 'margin-top:28px' },
    h('button', { class: 'linkish', onclick: () => withdrawPrompt() }, 'Withdraw this session'),
    h('button', { class: 'linkish', onclick: () => { clearSaved(); state = null; entryView(); } }, 'Discard demo session'));
}
function player({ label, src, gated, onStart, counts }) {
  const holder = h('div');
  const make = () => {
    const a = h('audio', { controls: true, controlsList: 'nodownload noplaybackrate', preload: 'auto', src });
    a.addEventListener('play', () => { counts.plays++; });
    a.addEventListener('ended', () => { counts.completed++; counts.onChange && counts.onChange(); });
    a.addEventListener('error', () => { holder.replaceChildren(h('p', { text: 'This audio could not be loaded. Serve the site over http (see README) and reload.' })); });
    return a;
  };
  if (gated) {
    holder.append(h('button', { class: 'btn btn-primary', type: 'button', onclick: () => {
      onStart && onStart(); const a = make(); holder.replaceChildren(a); a.play().catch(() => { /* user can press play */ });
    } }, 'Start this sound'));
  } else holder.append(make());
  return h('div', { class: 'player', role: 'region', 'aria-label': 'Sound player' },
    h('span', { class: 'player-icon', 'aria-hidden': 'true', text: '♫' }),
    h('div', {}, h('strong', { text: label }), h('p', { text: 'Play the full clip. Replay whenever you need.' }), holder));
}

// ---------------------------------------------------------------- setup steps
function volumeView() {
  const counts = { plays: 0, completed: 0 };
  const go = h('button', { class: 'btn btn-primary', disabled: true, onclick: () => { state.phase = 'headphones'; save(); route(); } }, 'This level is comfortable →');
  counts.onChange = () => { go.disabled = false; };
  render(sessionBar(), h('p', { class: 'eyebrow', text: 'Setup · 1 of 2' }), h('h1', { text: 'Find a comfortable level.' }),
    h('p', { class: 'lede', text: 'Start with a low device volume, play the tone and adjust it to a comfortable level. Keep that setting for the rest of the session.' }),
    player({ label: 'Volume reference', src: STUDY.volume, counts }), go, footerLinks());
}

function headphonesView() {
  const n = state.screenAnswers.length;
  const screen = STUDY.headphones.find(s => s.screen_id === state.screens[n]);
  const counts = { plays: 0, completed: 0 };
  let choice = 0;
  const go = h('button', { class: 'btn btn-primary', disabled: true }, 'Continue →');
  const update = () => { go.disabled = !(choice && counts.completed); };
  counts.onChange = update;
  const buttons = [1, 2, 3].map(i => h('button', { type: 'button', 'aria-pressed': 'false', onclick: () => {
    choice = i; buttons.forEach((b, k) => b.setAttribute('aria-pressed', String(k + 1 === i))); update();
  } }, ['First', 'Second', 'Third'][i - 1]));
  go.addEventListener('click', () => {
    state.screenAnswers.push({ screen_id: screen.screen_id, interval: choice, completed_plays: counts.completed, correct: choice === screen.correct_interval, submitted_at: now() });
    if (state.screenAnswers.length === 6) state.phase = state.screenAnswers.filter(a => a.correct).length >= 5 ? 'rating' : 'screen_failed';
    save(); route();
  });
  render(sessionBar(), h('p', { class: 'eyebrow', text: 'Setup · 2 of 2' }), h('h1', { text: 'A quick headphone check.' }),
    h('p', { class: 'lede', text: 'You will hear three tones. Which is the quietest? Listen to all three before choosing.' }),
    h('p', { class: 'muted', text: `Check ${n + 1} of 6` }),
    player({ label: `Headphone check ${n + 1} of 6`, src: 'audio/' + screen.path, counts }),
    h('section', { class: 'card' }, h('fieldset', {}, h('legend', { text: 'Which tone was quietest?' }), h('div', { class: 'intervals' }, buttons)), go), footerLinks());
}

// ---------------------------------------------------------------- rating
function scale(descriptor, value, onChange) {
  const buttons = [];
  const unclear = h('button', { type: 'button', class: 'unclear', 'aria-pressed': String(value === 'unclear') }, STUDY.config.scale.unclear_label);
  const set = v => { buttons.forEach((b, i) => b.setAttribute('aria-checked', String(v === i + 1))); unclear.setAttribute('aria-pressed', String(v === 'unclear')); onChange(v); };
  for (let i = 1; i <= 7; i++) buttons.push(h('button', { type: 'button', role: 'radio', 'aria-checked': String(value === i), 'aria-label': `${descriptor.label}: ${i}`, onclick: () => set(i) }, String(i)));
  unclear.addEventListener('click', () => set('unclear'));
  return h('fieldset', { class: 'scale' }, h('legend', { text: descriptor.label }), h('p', { text: descriptor.definition }),
    h('div', { class: 'ratings', role: 'radiogroup', 'aria-label': descriptor.label }, buttons),
    h('div', { class: 'anchors' }, h('span', { text: STUDY.config.scale.low_label }), h('span', { text: STUDY.config.scale.high_label })), unclear);
}

function ratingForm({ initial, onSubmit, submitLabel, needPlay, counts, extraButtons }) {
  const answers = { ...initial };
  const complete = () => TRAITS.every(t => answers[t] === 'unclear' || Number.isInteger(answers[t]));
  const saveBtn = h('button', { class: 'btn btn-primary', type: 'submit', disabled: true }, submitLabel);
  const note = h('span', {});
  const update = () => {
    const played = !needPlay || counts.completed > 0;
    saveBtn.disabled = !(played && complete());
    note.textContent = !played ? 'Play the full clip to continue.' : complete() ? 'Ready to save.' : 'Answer all four qualities, or choose “cannot judge”.';
  };
  counts.onChange = update;
  const comment = h('textarea', { id: 'f-comment', rows: 2, maxlength: 1000, oninput: e => { answers.comment = e.target.value; } });
  comment.value = answers.comment || '';
  const form = h('form', { onsubmit: e => { e.preventDefault(); onSubmit(answers); } },
    h('p', { class: 'muted', text: '1 means “not at all”; 7 means “very”. Use “cannot judge” if you are unsure what a term means.' }),
    h('section', { class: 'card rating-card' }, STUDY.config.descriptors.map(d => scale(d, answers[d.id], v => { answers[d.id] = v; update(); }))),
    h('label', { class: 'field' }, 'Anything unclear? ', h('span', { class: 'muted', text: 'Optional' }), comment),
    h('div', { class: 'save-row' }, note, h('div', { class: 'actions' }, extraButtons || null, saveBtn)));
  update();
  return form;
}

function ratingView() {
  const all = trials(), t = all[state.index];
  const practice = t.kind === 'practice';
  const studyList = studyTrials(), studyPos = studyList.indexOf(t) + 1;
  const practiceTotal = all.filter(x => x.kind === 'practice').length;
  const number = practice ? state.index + 1 : studyPos, total = practice ? practiceTotal : studyList.length;
  const counts = { plays: 0, completed: 0 };
  const startedAt = now();
  let started = false;
  const prev = state.index > 0 ? all[state.index - 1] : null;
  const prevRow = prev && state.responses[prev.presentation_id] && !state.justResumedFromBreak
    ? h('div', { class: 'prev-row' }, h('button', { class: 'btn btn-secondary', type: 'button', onclick: () => correctionView(prev) }, '← Correct previous sound'),
      h('span', { text: 'You can correct the previous response until you start the next sound.' })) : null;
  const form = ratingForm({ initial: { comment: '' }, submitLabel: 'Save and continue →', needPlay: true, counts,
    onSubmit: answers => {
      state.responses[t.presentation_id] = { answers, first: { ...answers }, plays: counts.plays, completed: counts.completed, started_at: startedAt, submitted_at: now(), revisions: [] };
      state.justResumedFromBreak = false;
      state.index++;
      if (state.index >= all.length) state.phase = 'feedback';
      else if (!practice && studyPos === STUDY.config.break_after_rated && !state.breakDone) state.phase = 'break';
      save(); route(); window.scrollTo({ top: 0 });
    } });
  render(sessionBar(h('button', { onclick: () => pauseView() }, 'Pause')),
    h('p', { class: 'eyebrow', text: practice ? 'Get familiar with the questions' : 'Listen · describe · continue' }),
    h('h1', {}, `${practice ? 'Practice' : 'Sound'} ${pad(number)}`, h('span', { class: 'count', text: ` / ${total}` })),
    practice ? null : h('div', { class: 'progress' }, h('span', { style: `width:${Math.round((number - 1) / total * 100)}%` })),
    h('p', { class: 'lede', text: practice ? 'Try each scale. Practice responses are saved separately and are not analysed.' : 'Rate each quality independently, based on the sound you hear.' }),
    prevRow,
    player({ label: `${practice ? 'Practice' : 'Sound'} ${pad(number)} / ${total}`, src: audioSrc(t.sample_id), gated: true, counts,
      onStart: () => { started = true; if (prevRow) prevRow.remove(); } }),
    form, footerLinks());
}

function correctionView(trial) {
  const r = state.responses[trial.presentation_id];
  const counts = { plays: 0, completed: 0 };
  const all = trials(), studyList = studyTrials();
  const practice = trial.kind === 'practice';
  const number = practice ? all.indexOf(trial) + 1 : studyList.indexOf(trial) + 1;
  const form = ratingForm({ initial: { ...r.answers }, submitLabel: 'Save correction', needPlay: false, counts,
    extraButtons: h('button', { class: 'btn btn-secondary', type: 'button', onclick: () => route() }, 'Cancel correction'),
    onSubmit: answers => {
      r.revisions.push({ answers: { ...answers }, plays: counts.plays, submitted_at: now() });
      r.answers = answers; save(); route();
    } });
  render(sessionBar(), h('p', { class: 'eyebrow', text: 'Correct previous response' }),
    h('h1', {}, `${practice ? 'Practice' : 'Sound'} ${pad(number)}`),
    h('p', { class: 'lede', text: 'Update your answers below. Replaying the sound is optional.' }),
    player({ label: 'Previous sound', src: audioSrc(trial.sample_id), counts }), form);
}

// ---------------------------------------------------------------- other steps
function breakView() {
  render(sessionBar(), h('section', { class: 'card' }, h('p', { class: 'eyebrow', text: 'Halfway through' }), h('h1', { text: 'A moment to rest.' }),
    h('p', { text: 'You have completed half the rated presentations. Take a short break, then continue with the same listening setup and volume.' }),
    h('button', { class: 'btn btn-primary', onclick: () => { state.breakDone = true; state.justResumedFromBreak = true; state.phase = 'rating'; save(); route(); } }, 'Continue listening →')), footerLinks());
}

function feedbackView() {
  const fb = { clarity: '', length: '', comment: '' };
  const sel = (label, key, options) => h('label', { class: 'field' }, label, h('select', { id: 'f-' + key, required: true, onchange: e => { fb[key] = e.target.value; } },
    h('option', { value: '', text: 'Choose an answer' }), options.map(o => h('option', { text: o }))));
  render(sessionBar(), h('form', { class: 'card', onsubmit: e => { e.preventDefault(); state.feedback = fb; state.phase = 'complete'; state.completed_at = now(); save(); route(); } },
    h('p', { class: 'eyebrow', text: 'One last thing' }), h('h1', { text: 'How was the experience?' }),
    sel('Were the descriptor questions clear?', 'clarity', ['Clear', 'Some terms unclear', 'Difficult to understand']),
    sel('How did the session length feel?', 'length', ['About right', 'Too long', 'Could be longer']),
    h('label', { class: 'field' }, 'Anything we should improve? ', h('span', { class: 'muted', text: 'Optional' }), h('textarea', { rows: 3, maxlength: 1500, oninput: e => { fb.comment = e.target.value; } })),
    h('button', { class: 'btn btn-primary', type: 'submit' }, 'Finish session →')));
}

function pauseView() {
  render(sessionBar(), h('section', { class: 'card' }, h('h1', { text: 'Take your time.' }),
    h('p', { text: 'Your saved responses are kept in this browser. Resume when you are ready to listen in a quiet place.' }),
    h('button', { class: 'btn btn-primary', onclick: () => route() }, 'Resume listening')));
}

function withdrawPrompt() {
  render(sessionBar(), h('section', { class: 'card' }, h('h1', { text: 'Withdraw this session?' }),
    h('p', { text: 'Your responses will be marked as withdrawn and excluded from analysis.' }),
    h('div', { class: 'actions' },
      h('button', { class: 'btn btn-primary', onclick: () => { state.phase = 'withdrawn'; state.withdrawn_at = now(); save(); route(); } }, 'Withdraw my responses'),
      h('button', { class: 'btn btn-secondary', onclick: () => route() }, 'Keep my session'))));
}

function csv() {
  const cols = ['participant_id', 'session_id', 'study_id', 'assignment_id', 'presentation_id', 'sample_id', 'source_sample_id', 'kind', 'repeat_of',
    'trial_order', 'phase', 'analysis_include', ...TRAITS, 'comment', 'play_count', 'completed_plays', 'started_at', 'submitted_at',
    ...TRAITS.map(t => t + '_first'), 'revision_count', 'label_source', 'site_version'];
  const esc = v => { v = v === null || v === undefined ? '' : String(v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
  const rows = [cols.join(',')];
  trials().forEach((t, i) => {
    const r = state.responses[t.presentation_id]; if (!r) return;
    const row = { participant_id: state.participant, session_id: state.session, study_id: 'c1_main_v1_DEMO', assignment_id: state.block,
      presentation_id: t.presentation_id, sample_id: t.sample_id, source_sample_id: STUDY.sounds[t.sample_id].source, kind: t.kind,
      repeat_of: t.repeat_of || '', trial_order: i, phase: state.phase, analysis_include: false, comment: r.answers.comment || '',
      play_count: r.plays, completed_plays: r.completed, started_at: r.started_at, submitted_at: r.submitted_at,
      revision_count: r.revisions.length, label_source: 'demo_browser', site_version: STUDY.version };
    TRAITS.forEach(k => { row[k] = r.answers[k]; row[k + '_first'] = r.first[k]; });
    rows.push(cols.map(c => esc(row[c])).join(','));
  });
  return rows.join('\n');
}

function endView() {
  const p = state.phase;
  const n = Object.keys(state.responses).length;
  const text = csv();
  const area = h('textarea', { class: 'csv', readonly: true, 'aria-label': 'Demo responses as CSV' }); area.value = text;
  const status = h('span', { class: 'muted', role: 'status' });
  const repeats = trials().filter(t => t.kind === 'repeat' && state.responses[t.presentation_id]).map(t => {
    const a = state.responses[t.presentation_id].answers, b = state.responses[t.repeat_of].answers;
    return TRAITS.map(k => (Number.isInteger(a[k]) && Number.isInteger(b[k])) ? Math.abs(a[k] - b[k]) : null).filter(x => x !== null);
  }).flat();
  render(sessionBar(),
    h('section', { class: 'card finish' }, h('span', { class: 'finish-mark', 'aria-hidden': 'true', text: p === 'complete' ? '✓' : '·' }),
      h('h1', { text: p === 'complete' ? 'Thank you for listening.' : p === 'withdrawn' ? 'Your session is withdrawn.' : 'This setup did not pass the check.' }),
      h('p', { class: 'muted', text: p === 'complete' ? `All ${n} of ${trials().length} responses are saved, including practice, and your feedback too.` : p === 'withdrawn' ? 'Your responses are marked as excluded from analysis.' : 'Please contact the researcher if you think there was a setup problem.' })),
    h('section', { class: 'card' }, h('h2', { text: 'Demo data from this session' }),
      h('p', { class: 'muted', text: repeats.length ? `Hidden repeats: ${repeats.filter(d => d <= 1).length} of ${repeats.length} repeated ratings were within ±1 of the first rating.` : 'No hidden repeats were reached in this session.' }),
      area, h('div', { class: 'actions', style: 'margin-top:12px' },
        h('button', { class: 'btn btn-secondary', onclick: () => {
          const done = () => { status.textContent = 'Copied.'; };
          if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, () => { area.select(); status.textContent = 'Press Ctrl+C to copy the selected text.'; });
          else { area.select(); status.textContent = 'Press Ctrl+C to copy the selected text.'; }
        } }, 'Copy CSV'),
        h('button', { class: 'btn btn-primary', onclick: () => { clearSaved(); state = null; entryView(); window.scrollTo({ top: 0 }); } }, 'Start a new demo session'), status)));
}

function route() {
  if (!state) return entryView();
  ({ volume: volumeView, headphones: headphonesView, rating: ratingView, break: breakView, feedback: feedbackView,
     complete: endView, withdrawn: endView, screen_failed: endView })[state.phase]();
}

// ---------------------------------------------------------------- design view
function designView() {
  const d = STUDY.design, c = STUDY.config, el = document.getElementById('design');
  const pct = x => `${Math.round(x * 100)}%`;
  const fmt = (x, n = 2) => (x === null || x === undefined) ? '–' : Number(x).toFixed(n);
  const S = d.unique_per_person, R = d.hidden_repeats, half = d.break_after;
  const first = half, second = S + R - half;

  const reliability = h('div', { class: 'table-wrap' }, h('table', {},
    h('thead', {}, h('tr', {}, ['Descriptor', 'Pilot unclear', 'Pilot ICC(1)', `Reliability at ${d.min_listeners} listeners`, 'Listeners for 0.80', 'Decision'].map(t => h('th', { text: t })))),
    h('tbody', {}, TRAITS.map(t => { const r = d.reliability[t]; return h('tr', {},
      h('td', { text: t[0].toUpperCase() + t.slice(1) }), h('td', { class: 'num', text: pct(d.pilot.unclear[t]) }), h('td', { class: 'num', text: fmt(r.icc1) }),
      h('td', { class: 'num', text: fmt(r.at_min_listeners) }), h('td', { class: 'num', text: r.listeners_for_target ?? '–' }),
      h('td', {}, h('span', { class: 'tag' + (r.at_min_listeners < 0.8 ? ' weak' : ''), text: d.descriptor_status[t].action === 'retain_unchanged' ? (r.at_min_listeners < 0.8 ? 'Keep · below 0.80' : 'Keep') : 'Revise wording' }))); }))));

  const options = h('div', { class: 'table-wrap' }, h('table', {},
    h('thead', {}, h('tr', {}, ['Unique sounds / person', 'Min listeners / sound', 'Predicted median', 'Feasible'].map(t => h('th', { text: t })))),
    h('tbody', {}, d.session_options.filter(o => o.unique_per_person <= 28).map(o => h('tr', {},
      h('td', { class: 'num', text: o.unique_per_person + (o.unique_per_person === S ? ' ◂ chosen' : '') }), h('td', { class: 'num', text: o.min_listeners }),
      h('td', { class: 'num', text: `${o.predicted_median_min} min` }), h('td', { text: o.feasible ? 'yes' : 'no' }))))));

  // range chart: corpus 5-95% band and selected min-max per variable
  const W = 760, rowH = 34, left = 190, right = 20;
  const labels = { pred_brightness: 'Predicted brightness', pred_roughness: 'Predicted roughness', pred_percussiveness: 'Predicted percussiveness',
    pred_sustainedness: 'Predicted sustainedness', log2_centroid: 'Spectral centroid (log2 Hz)', log_am_rough_15_150: 'Roughness modulation (log)',
    held_drop_db: 'Peak-to-body drop (dB)', log_attack_s: 'Attack time (log s)' };
  const svgNS = 'http://www.w3.org/2000/svg';
  const s = (tag, attrs) => { const e = document.createElementNS(svgNS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; };
  const svg = s('svg', { viewBox: `0 0 ${W} ${d.ranges.length * rowH + 30}`, class: 'range-chart', role: 'img', 'aria-label': 'Corpus 5–95% range compared with the selected range for each variable' });
  d.ranges.forEach((r, i) => {
    const lo = Math.min(r.corpus_p05, r.selected_min), hi = Math.max(r.corpus_p95, r.selected_max);
    const x = v => left + (v - lo) / (hi - lo || 1) * (W - left - right);
    const y = 18 + i * rowH;
    const label = s('text', { x: 0, y: y + 4, 'font-size': 12, fill: 'var(--ink)' }); label.textContent = labels[r.variable] || r.variable; svg.append(label);
    svg.append(s('rect', { x: x(r.corpus_p05), y: y - 7, width: Math.max(2, x(r.corpus_p95) - x(r.corpus_p05)), height: 14, rx: 3, fill: 'var(--bar-corpus)' }));
    svg.append(s('line', { x1: x(r.corpus_median), x2: x(r.corpus_median), y1: y - 9, y2: y + 9, stroke: 'var(--muted)', 'stroke-width': 2 }));
    svg.append(s('line', { x1: x(r.selected_min), x2: x(r.selected_max), y1: y, y2: y, stroke: 'var(--bar-selected)', 'stroke-width': 3 }));
    svg.append(s('circle', { cx: x(r.selected_median), cy: y, r: 5, fill: 'var(--bar-selected)' }));
    const ks = s('text', { x: W - right, y: y - 10, 'font-size': 10, fill: 'var(--muted)', 'text-anchor': 'end' }); ks.textContent = `KS ${r.ks.toFixed(2)}`; svg.append(ks);
  });

  // sound browser
  let filter = 'all', sortKey = 'id';
  let current = null; const audio = new Audio();
  audio.addEventListener('ended', () => { if (current) current.setAttribute('aria-pressed', 'false'); current = null; });
  const tbody = h('tbody');
  const ids = Object.keys(STUDY.sounds).filter(k => STUDY.sounds[k].role !== 'practice');
  function fill() {
    let list = ids.filter(k => filter === 'all' || (filter === 'anchor' && STUDY.sounds[k].role === 'anchor') || (filter === 'new' && STUDY.sounds[k].role === 'new') || (filter === 'weak' && STUDY.sounds[k].weak_support));
    if (sortKey !== 'id') list = list.slice().sort((a, b) => STUDY.sounds[b].pred[sortKey] - STUDY.sounds[a].pred[sortKey]);
    tbody.replaceChildren(...list.map(k => { const x = STUDY.sounds[k];
      const btn = h('button', { class: 'play', 'aria-pressed': 'false', 'aria-label': `Play ${k}`, text: '▶' });
      btn.addEventListener('click', () => {
        if (current === btn) { audio.pause(); btn.setAttribute('aria-pressed', 'false'); current = null; return; }
        if (current) current.setAttribute('aria-pressed', 'false');
        audio.src = x.file; audio.play().catch(() => {}); btn.setAttribute('aria-pressed', 'true'); current = btn;
      });
      return h('tr', {}, h('td', {}, btn), h('td', { text: k }),
        h('td', {}, h('span', { class: 'tag' + (x.role === 'anchor' ? ' anchor' : ''), text: x.role === 'anchor' ? `anchor · pilot ${x.pilot}` : 'new' })),
        TRAITS.map(t => h('td', {}, h('span', { class: 'mini' }, h('span', { style: `width:${Math.max(0, Math.min(1, (x.pred[t] - 1) / 6)) * 100}%` })), fmt(x.pred[t], 1))),
        h('td', {}, x.weak_support ? h('span', { class: 'tag weak', text: 'outside pilot support' }) : ''),
        h('td', { class: 'muted', text: x.source.replace('restricted_bend_sustain_', '') }));
    }));
  }
  const filterSel = h('select', { 'aria-label': 'Filter sounds', onchange: e => { filter = e.target.value; fill(); } },
    [['all', 'All 128 sounds'], ['anchor', 'Pilot anchors'], ['new', 'New sounds'], ['weak', 'Outside pilot support']].map(([v, t]) => h('option', { value: v, text: t })));
  const sortSel = h('select', { 'aria-label': 'Sort sounds', onchange: e => { sortKey = e.target.value; fill(); } },
    h('option', { value: 'id', text: 'Sort by sound number' }), TRAITS.map(t => h('option', { value: t, text: `Sort by predicted ${t}` })));
  fill();

  // assignment viewer
  const blockSel = h('select', { 'aria-label': 'Assignment block' }, STUDY.assignments.map(b => h('option', { value: b.assignment_id, text: b.assignment_id })));
  const blockList = h('div', { class: 'block-list' });
  function showBlock() {
    const b = STUDY.assignments.find(x => x.assignment_id === blockSel.value);
    let studyN = 0; const items = [];
    b.trials.forEach(t => {
      if (t.kind !== 'practice') studyN++;
      items.push(h('div', { class: 'k-' + t.kind }, h('span', { text: t.kind === 'practice' ? t.presentation_id.replace('_', ' ') : `${pad(studyN)} ${t.kind === 'repeat' ? 'repeat' : ''}` }), h('b', { text: t.sample_id.replace('sound_', '#') })));
      if (t.kind !== 'practice' && studyN === d.break_after) items.push(h('div', { class: 'k-break', text: 'break' }));
    });
    blockList.replaceChildren(...items);
  }
  blockSel.addEventListener('change', showBlock); showBlock();
  const cov = d.prefix_coverage[String(d.n_participants)];

  el.replaceChildren(
    h('span', { class: 'status', text: d.status }),
    h('h1', { text: 'Main study design' }),
    h('p', { class: 'lede', text: `${d.n_sounds} synthesizer sounds rated on four qualities by ${d.n_participants} listeners. Every number here is produced by the planning script from the pilot export; this build uses a ${d.pilot_label_source.join(', ')} pilot.` }),
    h('div', { class: 'numbers' },
      h('div', {}, h('b', { text: d.n_sounds }), h('span', { text: `${d.n_anchors} pilot anchors + ${d.n_sounds - d.n_anchors} new` })),
      h('div', {}, h('b', { text: d.n_participants }), h('span', { text: 'completed participants' })),
      h('div', {}, h('b', { text: `${S} + ${R}` }), h('span', { text: 'unique sounds + hidden repeats each' })),
      h('div', {}, h('b', { text: `≥ ${d.min_listeners}` }), h('span', { text: `listeners per sound (${d.extra_listener_sounds} get ${d.min_listeners + 1})` })),
      h('div', {}, h('b', { text: `~${Math.round(d.median_minutes)}` }), h('span', { text: 'minutes, predicted median' })),
      h('div', {}, h('b', { text: d.capacity }), h('span', { text: `assignment blocks (${d.spares} spare)` }))),

    h('div', { class: 'section' }, h('h2', { text: 'One session' }),
      h('p', { class: 'muted', text: `Setup and headphone check, 3 practice sounds, ${first} presentations, a break, ${second} presentations, then feedback. Each block hides ${R} repeats of earlier sounds to measure test–retest consistency.` }),
      h('div', { class: 'timeline', 'aria-hidden': 'true' },
        h('div', { class: 't-setup', text: 'setup' }), h('div', { class: 't-practice', text: 'practice' }),
        h('div', { class: 't-study', style: `flex:${first}`, text: `${first} sounds` }), h('div', { class: 't-break', text: 'break' }),
        h('div', { class: 't-study', style: `flex:${second - R}`, text: `${second - R} sounds` }), h('div', { class: 't-repeat', style: `flex:${R}`, text: 'rep' }),
        h('div', { class: 't-setup', style: 'flex:1.5', text: 'feedback' })),
      h('div', { class: 'legend-row' }, h('span', {}, h('i', { style: 'background:var(--accent)' }), 'unique study sounds'), h('span', {}, h('i', { style: 'background:var(--focus)' }), 'hidden repeats (placed in the second half)'))),

    h('div', { class: 'section' }, h('h2', { text: 'What the pilot decided' }),
      h('p', { class: 'muted', text: `Pilot: ${d.pilot.participants} listeners, ${d.pilot.sounds} sounds, ${d.pilot.evaluations} evaluations. Reliability of a sound's mean rating is projected from the pilot's single-listener agreement with the Spearman–Brown formula.` }),
      reliability,
      d.wording_review ? h('p', { class: 'muted', style: 'margin-top:10px', text: 'Pilot feedback flagged the descriptor wording as unclear for more than 30% of listeners: review the definitions before the main study.' }) : null,
      h('h3', { style: 'margin-top:24px', text: 'Session length options' }),
      h('p', { class: 'muted', text: 'The design takes the most listeners per sound that keeps the predicted median session under the time limit, then the fewest sounds giving that coverage.' }),
      options),

    h('div', { class: 'section' }, h('h2', { text: 'How the 128 sounds were chosen' }),
      h('p', { class: 'muted', text: `All 131,072 corpus sounds were screened with the pilot's audio rules; ${d.eligible.toLocaleString()} were eligible. Sounds were chosen to be maximally different across the 13 controls, the audio features and the pilot model's predicted ratings, with minimum counts in every range. ${d.weak_support_selected} sit outside what the pilot covered.` }),
      h('div', { class: 'card' }, h('h3', { text: 'Selected range against the corpus' }),
        h('div', { class: 'legend-row', style: 'margin-bottom:8px' }, h('span', {}, h('i', { style: 'background:var(--bar-corpus)' }), 'corpus 5–95% (tick = median)'), h('span', {}, h('i', { style: 'background:var(--bar-selected)' }), 'selected min–max (dot = median)')),
        svg)),

    h('div', { class: 'section' }, h('h2', { text: 'Listen to the selection' }),
      h('p', { class: 'muted', text: 'Predicted ratings come from the pilot model (1 = not at all, 7 = very); they are model estimates, not listener judgments.' }),
      h('div', { class: 'toolbar' }, filterSel, sortSel),
      h('div', { class: 'table-wrap', style: 'max-height:520px' }, h('table', {},
        h('thead', {}, h('tr', {}, ['', 'Sound', 'Role', ...TRAITS.map(t => t[0].toUpperCase() + t.slice(1)), 'Support', 'Corpus #'].map(t => h('th', { text: t })))), tbody))),

    h('div', { class: 'section' }, h('h2', { text: 'Assignment blocks' }),
      h('p', { class: 'muted', text: `Blocks are issued in order and any unfinished block is reissued. After ${d.n_participants} completed blocks: ${Object.entries(cov).map(([k, v]) => `${v} sounds with ${k} listeners`).join(', ')}.` }),
      h('div', { class: 'toolbar' }, blockSel), blockList),

    h('div', { class: 'section card' }, h('h2', { text: 'Limitations of this build' }),
      h('p', { class: 'muted', text: 'The pilot used here is simulated, so the timing, agreement and predicted ratings are assumptions. After the real pilot the planning script is rerun and this site is rebuilt with the resulting sounds. Equal RMS level is not equal loudness; listen to every sound before freezing the set.' })));
}

// ---------------------------------------------------------------- boot
document.getElementById('tab-participant').addEventListener('click', () => showView('participant'));
document.getElementById('tab-design').addEventListener('click', () => showView('design'));
fetch('study.json').then(r => { if (!r.ok) throw new Error(); return r.json(); }).then(study => {
  STUDY = study; KEY = 'c1-main-demo:' + study.version;
  const saved = load();
  state = saved && saved.version === study.version && STUDY.assignments.some(b => b.assignment_id === saved.block) ? saved : null;
  designView(); route();
  let view = 'participant'; try { view = localStorage.getItem(KEY + ':view') || view; } catch (e) { /* ignore */ }
  if (location.hash === '#design') view = 'design';
  showView(view);
}).catch(() => {
  root().replaceChildren(h('div', { class: 'card', role: 'alert' }, h('h2', { text: 'The study files could not be loaded.' }),
    h('p', { text: 'Open this site through a local web server (python -m http.server) rather than as a file.' })));
});
