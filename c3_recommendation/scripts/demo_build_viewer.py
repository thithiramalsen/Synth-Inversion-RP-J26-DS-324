"""Build the offline C3 demo viewer: one HTML page per audio representation.

ILLUSTRATION ONLY - validation targets, lambda not yet tuned, not an evaluation result.

Writes to ``<outputs_dir>/demo/`` (git-ignored):
  demo_mfcc26.html, demo_logmel_stats.html   open by double-click, no server or internet needed
  clips/<sample_id>.wav                      16-bit PCM copies of the processed corpus audio
  demo_data_<representation>.json            the exact selections shown on each page

Usage (repo root):
    python c3_recommendation/scripts/demo_build_viewer.py [--n-targets 8]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from c3.config import load_config  # noqa: E402
from c3.data_sources import make_source  # noqa: E402
from c3.demo import DEMO_LAMBDAS, build_demo_data  # noqa: E402
from c3.features import REPRESENTATIONS  # noqa: E402
from c3.param_space import ParamDistance  # noqa: E402
from c3.relevance import FeatureCosineRelevance  # noqa: E402
from c3.splits import BANK, VAL, Splits, load_manifest  # noqa: E402

LABELS = {"mfcc26": "MFCC-26", "logmel_stats": "Log-mel"}
PAGE = "demo_{rep}.html"

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>C3 Demo · __LABEL__</title>
<style>
/* Layout: target on top, lambda dial, then plain top 5 and C3 picks side by side */
:root {
  --bg: #f4f6f9; --panel: #ffffff; --ink: #18212c; --muted: #5d6877; --rule: #d9dfe7;
  --accent: #1d5a86; --accent-soft: #e2edf6; --c3: #8a4b0f; --c3-soft: #f6eadc; --target: #18212c;
  --sans: "Segoe UI", system-ui, -apple-system, Roboto, sans-serif; --mono: Consolas, "Cascadia Mono", ui-monospace, monospace;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #10151b; --panel: #171e27; --ink: #e4e9ef; --muted: #9aa6b4; --rule: #2a333e;
    --accent: #7db6e3; --accent-soft: #1b2a38; --c3: #f0a860; --c3-soft: #33251a; --target: #e4e9ef; color-scheme: dark; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.5 var(--sans); padding: 24px max(16px, 3vw) 48px; }
.wrap { max-width: 1180px; margin: 0 auto; display: flex; flex-direction: column; gap: 20px; }
header { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end; gap: 12px; }
h1 { margin: 0; font-size: 28px; line-height: 1.2; }
h1 small { font-weight: 400; color: var(--muted); font-size: 18px; }
.flag { font-size: 12.5px; color: var(--c3); border: 1px solid var(--c3); border-radius: 999px; padding: 2px 10px; white-space: nowrap; }
.switch a { color: var(--accent); font-weight: 600; }
.panel { background: var(--panel); border: 1px solid var(--rule); border-radius: 8px; padding: 16px; }
.targets { display: flex; flex-wrap: wrap; gap: 8px; }
.targets button { font: inherit; padding: 6px 12px; border: 1px solid var(--rule); background: var(--panel); color: var(--ink); border-radius: 6px; cursor: pointer; }
.targets button[aria-pressed="true"] { border-color: var(--accent); background: var(--accent-soft); font-weight: 600; }
.targets button:focus-visible, input:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.target { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr); gap: 16px 24px; align-items: center; }
.label { font-size: 12px; text-transform: uppercase; letter-spacing: .07em; color: var(--muted); font-weight: 600; }
.sid { font-family: var(--mono); font-size: 13px; color: var(--muted); }
audio { width: 100%; height: 36px; }
.dial { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 8px 16px; align-items: center; }
.dial output { font-size: 26px; font-weight: 700; font-variant-numeric: tabular-nums; color: var(--c3); min-width: 4ch; text-align: right; }
.dial input { width: 100%; accent-color: var(--c3); }
.dial .ends { grid-column: 2; display: flex; justify-content: space-between; font-size: 12.5px; color: var(--muted); }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.col { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.col h2 { margin: 0; font-size: 18px; }
.col.topk h2 { color: var(--accent); }
.col.c3 h2 { color: var(--c3); }
.stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.stat { background: var(--bg); border-radius: 6px; padding: 8px 10px; }
.stat b { display: block; font-size: 20px; font-variant-numeric: tabular-nums; }
.stat span { font-size: 12px; color: var(--muted); }
.stat em { font-style: normal; font-size: 12px; font-weight: 600; }
.up { color: #1f7a4d; } .down { color: #b23a2e; }
@media (prefers-color-scheme: dark) { .up { color: #6fcf9a; } .down { color: #f08a7e; } }
.card { display: grid; grid-template-columns: 28px minmax(0, 1fr) 132px; gap: 6px 12px; align-items: center; padding: 10px 12px; border: 1px solid var(--rule); border-radius: 6px; background: var(--panel); }
.col.c3 .card.new { border-color: var(--c3); background: var(--c3-soft); }
.rank { font-weight: 700; font-size: 17px; color: var(--muted); text-align: center; }
.meta { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 12.5px; color: var(--muted); }
.meta strong { color: var(--ink); font-variant-numeric: tabular-nums; }
.tag { font-size: 11.5px; font-weight: 600; padding: 0 6px; border-radius: 4px; background: var(--accent-soft); color: var(--accent); }
.col.c3 .tag.new { background: var(--c3); color: var(--panel); }
.recipe { display: flex; align-items: flex-end; gap: 2px; height: 46px; }
.recipe i { position: relative; flex: 1; height: 100%; background: var(--bg); border-radius: 2px; }
.recipe i b { position: absolute; left: 0; right: 0; bottom: 0; border-radius: 2px; background: var(--accent); }
.col.c3 .recipe i b { background: var(--c3); }
.target .recipe { height: 64px; }
.target .recipe i b { background: var(--target); }
.recipe i u { position: absolute; left: -1px; right: -1px; height: 2px; background: var(--target); opacity: .55; }
.legend { font-size: 12.5px; color: var(--muted); display: flex; flex-wrap: wrap; gap: 4px 14px; }
.legend span b { color: var(--ink); }
footer { font-size: 12.5px; color: var(--muted); display: flex; flex-direction: column; gap: 4px; max-width: 90ch; }
@media (max-width: 820px) { .cols, .target { grid-template-columns: 1fr; } }
@media (max-width: 460px) { .card { grid-template-columns: 24px minmax(0, 1fr); } .card .recipe { grid-column: 1 / -1; } }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <div class="label">C3 · diversity-aware patch recommendation</div>
      <h1>Recommendation demo <small>fingerprint: __LABEL__</small></h1>
    </div>
    <div style="display:flex; gap:12px; align-items:center; flex-wrap:wrap">
      <span class="flag">Illustration · validation sounds · λ not tuned yet</span>
      <span class="switch">Switch to <a href="__OTHER_PAGE__">__OTHER_LABEL__</a></span>
    </div>
  </header>

  <section class="panel" aria-label="Choose a target sound">
    <div class="label" style="margin-bottom:8px">Target sound</div>
    <div class="targets" id="targets"></div>
  </section>

  <section class="panel target" id="target"></section>

  <section class="panel dial" aria-label="Variety dial">
    <label for="lam" class="label">Variety dial λ</label>
    <input type="range" id="lam" min="0" max="0" step="1" value="0">
    <output id="lamOut" for="lam">1</output>
    <div class="ends"><span>1.0 = closeness only (same as plain top 5)</span><span>lower = more variety in knob settings</span></div>
  </section>

  <div class="cols">
    <section class="col topk" id="colTop" aria-label="Plain top 5"></section>
    <section class="col c3" id="colC3" aria-label="C3 picks"></section>
  </div>

  <div class="legend" id="legend"></div>

  <footer>
    <span><b>Closeness</b> = cosine similarity of standardised __LABEL__ fingerprints (scaled with shop-shelf statistics only). <b>Knob distance</b> = distance between 13 knob positions on a 0–1 scale (0 = identical recipe).</span>
    <span>Each candidate comes from a shortlist of the __POOL__ closest-sounding sounds out of __BANK__. The target is a validation sound and is never in its own candidate list. Bars show each sound's 13 knob settings; the thin line on each bar is the target's setting.</span>
    <span>Built __BUILT__ from the frozen split and cached features. λ values are for illustration only; the operating point is chosen on validation data in Phase 7.</span>
  </footer>
</div>

<script type="application/json" id="data">__DATA__</script>
<script>
(function () {
  var data = JSON.parse(document.getElementById('data').textContent);
  var names = data.parameter_names;
  var lambdas = data.lambdas;
  var state = { t: 0, l: Math.max(0, lambdas.indexOf('0.9')) };
  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) { return String(s).replace(/[&<>"]/g, function (c) { return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'})[c]; }); };

  function recipe(values, target) {
    return '<div class="recipe" aria-hidden="true">' + values.map(function (v, i) {
      var mark = target ? '<u style="bottom:calc(' + (target[i] * 100).toFixed(1) + '% - 1px)"></u>' : '';
      return '<i title="' + esc(names[i]) + ': ' + v.toFixed(2) + '"><b style="height:' + Math.max(2, v * 100).toFixed(1) + '%"></b>' + mark + '</i>';
    }).join('') + '</div>';
  }
  function audio(id, label) {
    return '<audio controls preload="none" src="clips/' + encodeURIComponent(id) + '.wav" aria-label="' + esc(label) + '"></audio>';
  }
  function pct(a, b) { return b ? ((a - b) / Math.abs(b)) * 100 : 0; }
  function delta(a, b, higherIsBetter) {
    if (a === b) return '';
    var d = pct(a, b), good = higherIsBetter ? d > 0 : d < 0;
    if (Math.abs(d) < 0.05) return ' <em>0.0%</em>';
    return ' <em class="' + (good ? 'up' : 'down') + '">' + (d > 0 ? '+' : '') + d.toFixed(1) + '%</em>';
  }
  function stats(set, base) {
    return '<div class="stats">' +
      '<div class="stat"><b>' + set.mean_rel.toFixed(3) + '</b><span>mean closeness</span>' + (base ? delta(set.mean_rel, base.mean_rel, true) : '') + '</div>' +
      '<div class="stat"><b>' + set.mean_pair_dist.toFixed(3) + '</b><span>mean knob distance between picks</span>' + (base ? delta(set.mean_pair_dist, base.mean_pair_dist, true) : '') + '</div>' +
      '<div class="stat"><b>' + set.min_pair_dist.toFixed(3) + '</b><span>closest pair of picks</span>' + (base ? delta(set.min_pair_dist, base.min_pair_dist, true) : '') + '</div>' +
      '</div>';
  }
  function cards(set, target, isC3) {
    return set.items.map(function (it, i) {
      var isNew = isC3 && !it.in_topk;
      return '<article class="card' + (isNew ? ' new' : '') + '">' +
        '<div class="rank">' + (i + 1) + '</div>' +
        '<div style="min-width:0; display:flex; flex-direction:column; gap:4px">' +
          audio(it.id, 'Play pick ' + (i + 1)) +
          '<div class="meta"><span>closeness <strong>' + it.relevance.toFixed(3) + '</strong></span>' +
          '<span>shortlist rank <strong>#' + it.audio_rank + '</strong> of ' + data.pool_size + '</span>' +
          (isC3 ? (isNew ? '<span class="tag new">new vs top 5</span>' : '<span class="tag">also in top 5</span>') : '') + '</div>' +
          '<div class="sid">' + esc(it.id) + '</div>' +
        '</div>' + recipe(it.params, target.params) + '</article>';
    }).join('');
  }
  function render() {
    var target = data.targets[state.t];
    var lam = lambdas[state.l];
    var top = target.sets['1'], c3 = target.sets[lam];
    Array.prototype.forEach.call($('targets').children, function (b, i) { b.setAttribute('aria-pressed', i === state.t ? 'true' : 'false'); });
    $('target').innerHTML = '<div style="display:flex; flex-direction:column; gap:6px; min-width:0">' +
      '<div class="label">Target ' + (state.t + 1) + ' of ' + data.targets.length + '</div>' +
      audio(target.id, 'Play target sound') + '<div class="sid">' + esc(target.id) + '</div></div>' +
      '<div><div class="label" style="margin-bottom:6px">Target knob settings</div>' + recipe(target.params) + '</div>';
    $('lamOut').textContent = lam;
    $('colTop').innerHTML = '<h2>Plain top ' + data.k + '</h2>' + stats(top) + cards(top, target, false);
    $('colC3').innerHTML = '<h2>C3 picks (MMR, λ = ' + lam + ')</h2>' + stats(c3, top) + cards(c3, target, true);
  }

  $('targets').innerHTML = data.targets.map(function (t, i) {
    return '<button type="button" id="target-' + i + '">Target ' + (i + 1) + '</button>';
  }).join('');
  Array.prototype.forEach.call($('targets').children, function (b, i) { b.addEventListener('click', function () { state.t = i; render(); }); });
  var slider = $('lam');
  slider.max = String(lambdas.length - 1);
  slider.value = String(state.l);
  slider.addEventListener('input', function () { state.l = Number(slider.value); render(); });
  $('legend').innerHTML = '<span>Bar order, left to right:</span>' + names.map(function (n, i) { return '<span><b>' + (i + 1) + '</b> ' + esc(n) + '</span>'; }).join('');
  render();
})();
</script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None)
    parser.add_argument("--n-targets", type=int, default=8)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--pool-size", type=int, default=100)
    args = parser.parse_args()

    cfg = load_config(args.config)
    if cfg["data.source"] != "corpus_v4":
        raise SystemExit("the demo plays audio: data.source must be corpus_v4")
    out_dir = cfg.path("outputs_dir") / "demo"
    clip_dir = out_dir / "clips"
    clip_dir.mkdir(parents=True, exist_ok=True)
    source = make_source(cfg)
    unit = source.params_unit()
    splits = Splits.from_config(cfg, load_manifest(cfg.path("outputs_dir") / "splits"))
    bank_ids = splits.ids(BANK)
    targets = splits.get_targets(VAL, args.n_targets, cfg.seed)
    distance = ParamDistance.from_schema(source.schema, method=cfg["param_distance.method"])
    built = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    all_clips: set[str] = set()
    for rep in REPRESENTATIONS:
        relevance = FeatureCosineRelevance.from_cache(cfg.path("outputs_dir") / "features", rep)
        data = build_demo_data(relevance, targets, bank_ids, unit, distance, DEMO_LAMBDAS, args.k,
                               args.pool_size, cfg["selection.relevance_scaling"])
        data.update({"representation": rep, "illustration_only": True, "built_utc": built})
        (out_dir / f"demo_data_{rep}.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        other = next(r for r in REPRESENTATIONS if r != rep)
        html = (TEMPLATE.replace("__LABEL__", LABELS[rep]).replace("__OTHER_LABEL__", LABELS[other])
                .replace("__OTHER_PAGE__", PAGE.format(rep=other)).replace("__POOL__", str(args.pool_size))
                .replace("__BANK__", f"{len(bank_ids):,}").replace("__BUILT__", built)
                .replace("__DATA__", json.dumps(data).replace("</", "<\\/")))
        (out_dir / PAGE.format(rep=rep)).write_text(html, encoding="utf-8")
        all_clips.update(data["clips"])
        moved = [t for t in data["targets"] if t["sets"]["0.9"]["overlap_with_topk"] < 1]
        print(f"[{rep}] page written; at lambda=0.9 C3 changed the set for {len(moved)}/{len(targets)} targets")

    written = 0
    for sample_id in sorted(all_clips):
        path = clip_dir / f"{sample_id}.wav"
        if not path.exists():
            audio, sr = source.audio(sample_id)
            sf.write(path, audio, sr, subtype="PCM_16")
            written += 1
    size_mb = sum(p.stat().st_size for p in clip_dir.glob("*.wav")) / 1e6
    print(f"Clips: {len(all_clips)} needed, {written} newly written, folder {size_mb:.1f} MB")
    print(f"Open: {out_dir / PAGE.format(rep='mfcc26')}")
    print(f"      {out_dir / PAGE.format(rep='logmel_stats')}")


if __name__ == "__main__":
    main()
