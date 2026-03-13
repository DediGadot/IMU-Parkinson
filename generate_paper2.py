#!/usr/bin/env python3
"""Generate the redesigned manuscript HTML into new_paper2.html by default."""

import argparse
from pathlib import Path

import numpy as np

import generate_paper as gp


ROOT = Path(__file__).parent
DEFAULT_OUTPUT = ROOT / "new_paper2.html"


CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@400;600;700&family=Source+Sans+3:wght@400;600;700&display=swap');
:root {
  --ink: #1f2933;
  --muted: #5f6b76;
  --shell: #f4f0e8;
  --paper: #fffdf8;
  --panel: #f7f3ea;
  --line: #ddd6c7;
  --accent: #186b66;
  --accent-soft: #e4f3f0;
  --warm: #b3513b;
  --shadow: 0 24px 60px rgba(20, 30, 40, 0.08);
}
html { scroll-behavior: smooth; }
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: 'Source Serif 4', Georgia, serif;
  font-size: 11pt;
  line-height: 1.72;
  color: var(--ink);
  background:
    radial-gradient(circle at top right, rgba(24, 107, 102, 0.10), transparent 34%),
    radial-gradient(circle at top left, rgba(179, 139, 42, 0.08), transparent 26%),
    var(--shell);
}
.paper-shell {
  max-width: 1280px;
  margin: 0 auto;
  padding: 32px 20px 72px;
  display: grid;
  grid-template-columns: minmax(0, 940px) 260px;
  gap: 28px;
  align-items: start;
}
.paper {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 28px;
  box-shadow: var(--shadow);
  overflow: hidden;
}
.hero {
  position: relative;
  padding: 48px 56px 30px;
  background: linear-gradient(150deg, #fbf7ee 0%, #f9fcfb 58%, #fffef9 100%);
  border-bottom: 1px solid var(--line);
}
.hero::after {
  content: "";
  position: absolute;
  right: -30px;
  bottom: -70px;
  width: 220px;
  height: 220px;
  background: radial-gradient(circle, rgba(24, 107, 102, 0.18), rgba(24, 107, 102, 0));
  pointer-events: none;
}
.kicker,
.eyebrow,
.abstract-label,
.snapshot-label,
.toc-kicker,
.section-tag {
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-size: 0.73rem;
  font-weight: 700;
}
.kicker { color: var(--accent); margin: 0 0 12px; }
h1, h2, h3, h4 {
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  line-height: 1.18;
}
h1 {
  margin: 0 0 10px;
  font-size: clamp(2rem, 4vw, 2.7rem);
  max-width: 15ch;
}
.deck {
  margin: 0;
  max-width: 62ch;
  color: var(--muted);
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  font-size: 1.04rem;
}
.authors, .affiliations {
  margin: 0;
  color: var(--muted);
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
}
.authors { margin-top: 18px; font-size: 0.96rem; }
.affiliations { font-size: 0.88rem; margin-top: 4px; }
.snapshot-grid,
.takeaway-grid,
.abstract-grid,
.contribution-grid {
  display: grid;
  gap: 14px;
}
.snapshot-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-top: 26px;
}
.snapshot-card,
.takeaway-card,
.abstract-block,
.contribution-card,
.table-card,
figure {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 20px;
  box-shadow: 0 12px 28px rgba(20, 30, 40, 0.04);
}
.snapshot-card,
.takeaway-card,
.abstract-block,
.contribution-card {
  padding: 16px 16px 14px;
}
.snapshot-value,
.takeaway-number {
  display: block;
  margin: 6px 0 4px;
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  font-size: 1.28rem;
  font-weight: 700;
}
.snapshot-detail,
.takeaway-detail,
.contribution-card p {
  margin: 0;
  color: var(--muted);
  font-size: 0.9rem;
}
.claim-banner {
  margin-top: 18px;
  padding: 18px 20px;
  border-radius: 20px;
  border: 1px solid #cfe4df;
  background: linear-gradient(135deg, var(--accent-soft), #f6fbfa 65%, #fffef9 100%);
}
.eyebrow { color: var(--accent); display: block; margin-bottom: 6px; }
.claim-banner p {
  margin: 0;
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  font-size: 1rem;
  line-height: 1.5;
}
.paper-section { padding: 34px 56px 0; }
.paper-section:last-child { padding-bottom: 48px; }
.section-heading {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 18px;
  align-items: end;
  justify-content: space-between;
  margin-bottom: 12px;
}
h2 {
  margin: 0;
  font-size: 1.46rem;
  color: var(--accent);
}
.section-tag { color: var(--muted); }
.section-lead,
.callout {
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  color: #33414c;
}
.section-lead {
  margin: 0;
  max-width: 56ch;
  font-size: 0.98rem;
  color: var(--muted);
}
h3 {
  margin: 1.8rem 0 0.65rem;
  font-size: 1.08rem;
  color: #29414d;
}
p { margin: 0 0 1rem; }
.abstract-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-top: 14px;
}
.abstract-block {
  background: var(--panel);
  box-shadow: none;
}
.abstract-label { color: var(--accent); margin-bottom: 8px; display: block; }
.takeaway-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-top: 18px;
}
.takeaway-title {
  margin: 0 0 6px;
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  font-size: 0.95rem;
  font-weight: 700;
}
.takeaway-number { color: var(--warm); }
.contribution-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin: 18px 0 24px;
}
.contribution-card h4 {
  margin: 0 0 8px;
  font-size: 0.98rem;
}
.callout {
  margin: 16px 0 20px;
  padding: 14px 18px;
  background: #f3faf8;
  border-left: 4px solid var(--accent);
  border-radius: 0 16px 16px 0;
  font-size: 0.95rem;
}
figure {
  margin: 22px 0 18px;
  padding: 18px 18px 14px;
  page-break-inside: avoid;
}
figure img {
  max-width: 100%;
  display: block;
  border-radius: 14px;
}
figcaption {
  margin-top: 12px;
  color: var(--muted);
  font-size: 0.87rem;
}
figcaption strong { color: var(--ink); }
.table-card {
  margin: 18px 0 24px;
  overflow: hidden;
}
.table-wrap { overflow-x: auto; }
table {
  border-collapse: collapse;
  width: 100%;
  min-width: 720px;
  margin: 0;
  font-size: 0.92rem;
  page-break-inside: avoid;
}
caption {
  caption-side: top;
  text-align: left;
  padding: 18px 18px 8px;
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  font-size: 0.96rem;
  font-weight: 700;
}
th {
  background: #f3ede2;
  text-align: left;
  padding: 9px 10px;
  font-weight: 700;
  border-top: 2px solid #3c4a54;
  border-bottom: 1px solid #bfc7cf;
}
td {
  padding: 7px 10px;
  border-bottom: 1px solid #e3ddd2;
}
tr:nth-child(even) { background: #fcfbf7; }
tr.highlight { background: #edf8f2; font-weight: 600; }
tr.primary { background: #fff6df; }
.note {
  margin: 0;
  padding: 0 18px 18px;
  color: var(--muted);
  font-size: 0.82rem;
}
.ref { font-size: 0.92rem; }
.ref ol { padding-left: 1.3rem; margin-top: 0.8rem; }
.ref li { margin-bottom: 0.65rem; }
sup { font-size: 0.7em; }
.toc { position: sticky; top: 24px; }
.toc-card {
  padding: 20px 18px;
  background: rgba(255, 253, 248, 0.88);
  border: 1px solid var(--line);
  border-radius: 24px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(10px);
}
.toc-kicker { color: var(--accent); margin-bottom: 4px; }
.toc-title {
  margin: 0 0 12px;
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  font-size: 1.06rem;
  font-weight: 700;
}
.toc-list { list-style: none; margin: 0; padding: 0; }
.toc-list li { margin: 0 0 0.5rem; }
.toc-list a {
  color: var(--ink);
  text-decoration: none;
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  font-size: 0.92rem;
}
.toc-list a:hover { color: var(--accent); }
.obs-meter {
  margin-top: 16px;
  border-top: 1px solid var(--line);
  padding-top: 14px;
}
.obs-bar {
  display: flex;
  height: 12px;
  border-radius: 999px;
  overflow: hidden;
  margin-bottom: 10px;
}
.obs-direct { background: #1b7f64; width: 18.2%; }
.obs-partial { background: #c17a18; width: 51.5%; }
.obs-unobs { background: #b8483a; width: 30.3%; }
.obs-list {
  list-style: none;
  margin: 0;
  padding: 0;
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  font-size: 0.84rem;
  color: var(--muted);
}
.obs-list li { margin-bottom: 0.35rem; }
code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.92em;
  background: #f3efe7;
  padding: 0.08em 0.32em;
  border-radius: 6px;
}
@media (max-width: 1100px) {
  .paper-shell { grid-template-columns: 1fr; }
  .toc { position: static; }
}
@media (max-width: 820px) {
  .hero, .paper-section { padding-left: 24px; padding-right: 24px; }
  .snapshot-grid, .takeaway-grid, .abstract-grid, .contribution-grid { grid-template-columns: 1fr; }
  table { min-width: 640px; }
}
@media print {
  body { background: #fff; }
  .paper-shell { display: block; padding: 0; }
  .paper, .toc-card, figure, .table-card, .snapshot-card, .takeaway-card, .abstract-block, .contribution-card {
    box-shadow: none;
    border-color: #cfc8b8;
  }
  .toc { display: none; }
  .hero, .paper-section { padding-left: 0; padding-right: 0; }
}
</style>
"""


def table_card(table_html: str) -> str:
    return f'<div class="table-card"><div class="table-wrap">{table_html}</div></div>'


def table4_severity(confounds: dict) -> str:
    return gp._table_severity(confounds).replace("Table 6.", "Table 4.")


def table5_sensor(d: gp.PaperData) -> str:
    return gp._table4_sensor(d).replace("Table 4.", "Table 5.")


def table6_context() -> str:
    return """
<table>
<caption><strong>Table 6.</strong> Cross-dataset context with endpoint comparability made explicit.</caption>
<tr><th>Study</th><th>Endpoint</th><th>N</th><th>Setting</th><th>Sensors</th><th>Evaluation</th><th>MAE</th><th>r</th><th>Comparable to our total-score benchmark?</th></tr>
<tr><td>This work</td><td>Total UPDRS-III</td><td>98 PD</td><td>Controlled gait</td><td>13 IMUs</td><td>PD-only LOOCV</td><td>8.15</td><td>0.429</td><td>Yes</td></tr>
<tr><td>This work</td><td>Total UPDRS-III</td><td>36</td><td>Controlled gait</td><td>13 IMUs</td><td>Held-out once</td><td>9.36</td><td>0.615</td><td>Yes</td></tr>
<tr class="highlight"><td>This work</td><td>Directly observable subscore (0-24)</td><td>94 PD</td><td>Controlled gait</td><td>13 IMUs</td><td>PD-only LOOCV</td><td>1.77</td><td>0.667</td><td>No; different endpoint and range</td></tr>
<tr><td>Hssayeni 2021</td><td>Total motor score</td><td>24 PD</td><td>Free-living</td><td>Wrist + ankle gyro</td><td>LOOCV</td><td>5.95</td><td>0.74</td><td>Only partially</td></tr>
<tr><td>Shuqair 2024</td><td>Total motor score</td><td>24 PD</td><td>Free-living</td><td>Wrist + ankle</td><td>LOOCV</td><td>~5.65</td><td>0.89</td><td>Only partially</td></tr>
<tr><td>Sotirakis 2023</td><td>Total motor score</td><td>74 PD</td><td>Unspecified daily-life mix</td><td>Wrist + back</td><td>5-fold CV</td><td>RMSE 10.02</td><td>&mdash;</td><td>No; protocol differs and leakage risk is unclear</td></tr>
</table>
<p class="note">The observable subscore row is retained because it is clinically important, but it should not be visually compared against total-score MAE as if it were the same prediction target.</p>"""


def build_html(d: gp.PaperData, test_stats: dict, figures: dict) -> str:
    mt = d.pd_only["master_table"]
    dp = d.demo_pd
    dc = d.demo_hc
    obs = d.obs3["subscores"]
    loocv = d.loocv_stats

    fm_loocv = mt["loocv_fm"]
    demo_loocv = mt["loocv_demo"]
    direct = obs["direct"]["loocv"]
    partial = obs["partial"]["loocv"]
    unobs_l = obs["unobs"]["loocv"]
    binary_obs = obs["binary_obs"]["loocv"]
    held = mt["held_out_full"]
    held_demo = mt["held_out_demo"]
    p10_b1_v2 = mt["10split_b1_v2"]
    p10_demo = mt["10split_demographic"]
    p10_fm = mt["10split_b1_fm_stk"]
    partial_corr = loocv["partial_correlation"]
    bland = loocv["bland_altman"]
    clinical = loocv["clinical_significance"]

    fm_mixed = np.array(gp.SPLIT_MAES_FM)
    v2_mixed = np.array(gp.SPLIT_MAES_V2)
    _, p_fm_v2 = gp.wilcoxon(fm_mixed, v2_mixed, alternative="less")
    hb = {h["label"]: h for h in d.pd_only["holm_bonferroni"]}

    direct_share = 24 / 132 * 100
    partial_share = 68 / 132 * 100
    unobs_share = 40 / 132 * 100

    snapshot_cards = f"""
<div class="snapshot-grid">
  <div class="snapshot-card">
    <span class="snapshot-label">Dataset</span>
    <span class="snapshot-value">{gp.N_ANALYZED} participants</span>
    <p class="snapshot-detail">{gp.N_ANALYZED_PD} PD, {gp.N_ANALYZED_HC} HC, 13 IMUs, 6 controlled tasks.</p>
  </div>
  <div class="snapshot-card">
    <span class="snapshot-label">Endpoint mismatch</span>
    <span class="snapshot-value">24 / 132 points</span>
    <p class="snapshot-detail">Only {direct_share:.1f}% of the total score range is directly observable during gait.</p>
  </div>
  <div class="snapshot-card">
    <span class="snapshot-label">Best aligned endpoint</span>
    <span class="snapshot-value">MAE {direct['mae']:.2f} | CCC {direct['ccc']:.2f}</span>
    <p class="snapshot-detail">Directly observable subscore in PD-only LOOCV.</p>
  </div>
  <div class="snapshot-card">
    <span class="snapshot-label">Minimal deployment</span>
    <span class="snapshot-value">5 sensors ~= 13</span>
    <p class="snapshot-detail">{mt['sensor_minimal_5']['mae_mean']:.2f} vs {mt['sensor_all_13']['mae_mean']:.2f} MAE, p=0.851.</p>
  </div>
</div>"""

    abstract_blocks = f"""
<div class="abstract-grid">
  <div class="abstract-block">
    <span class="abstract-label">Question</span>
    <p>Can gait IMUs estimate total MDS-UPDRS-III severity, or only the motor signs that are physically expressed while walking?</p>
  </div>
  <div class="abstract-block">
    <span class="abstract-label">Design</span>
    <p>First regression benchmark on WearGait-PD: {gp.N_ANALYZED} analyzed participants, 13 body-worn IMUs, PD-only LOOCV, 10-split cross-validation, and one pre-registered held-out test.</p>
  </div>
  <div class="abstract-block">
    <span class="abstract-label">Results</span>
    <p>Total score prediction plateaued at MAE {fm_loocv['mae']:.2f}, CCC {fm_loocv['ccc']:.2f}, while a demographic Ridge baseline reached MAE {p10_demo['mae_mean']:.2f}. The directly observable subscore performed much better: MAE {direct['mae']:.2f}, CCC {direct['ccc']:.2f}.</p>
  </div>
  <div class="abstract-block">
    <span class="abstract-label">Interpretation</span>
    <p>The bottleneck is endpoint observability rather than model class. Wearables capture clinically meaningful gait signal, but they are better suited to the gait-observable slice of UPDRS-III than to the full composite score.</p>
  </div>
</div>"""

    takeaway_cards = f"""
<div class="takeaway-grid">
  <div class="takeaway-card">
    <p class="takeaway-title">Total-score ceiling</p>
    <span class="takeaway-number">MAE {fm_loocv['mae']:.2f}</span>
    <p class="takeaway-detail">On PD-only LOOCV, absolute error remains large and calibration collapses toward the cohort mean.</p>
  </div>
  <div class="takeaway-card">
    <p class="takeaway-title">Sensor signal is real</p>
    <span class="takeaway-number">Partial r {partial_corr['r']:.2f}</span>
    <p class="takeaway-detail">After controlling for age and disease duration, inertial signal still contributes beyond demographics.</p>
  </div>
  <div class="takeaway-card">
    <p class="takeaway-title">Foundation model caveat</p>
    <span class="takeaway-number">p={p_fm_v2:.4f} mixed</span>
    <p class="takeaway-detail">MOMENT helps when PD-vs-HC separation is available, but the benefit shrinks in PD-only severity grading.</p>
  </div>
  <div class="takeaway-card">
    <p class="takeaway-title">Clinical path forward</p>
    <span class="takeaway-number">Direct subscore</span>
    <p class="takeaway-detail">The most defensible wearable endpoint is the motor subdomain the sensors can actually observe.</p>
  </div>
</div>"""

    contribution_cards = """
<div class="contribution-grid">
  <div class="contribution-card">
    <h4>Rigorous benchmark</h4>
    <p>Subject-level PD-only LOOCV remains the primary comparison to prior literature, but we also include repeated splits and a pre-registered held-out test.</p>
  </div>
  <div class="contribution-card">
    <h4>Observability-aware endpoint design</h4>
    <p>The paper separates total score prediction from what gait sensors can directly, partially, or not at all observe.</p>
  </div>
  <div class="contribution-card">
    <h4>Foundation models under a harder criterion</h4>
    <p>We test frozen MOMENT-1 embeddings where the real problem is within-PD severity ranking, not disease-versus-control screening.</p>
  </div>
  <div class="contribution-card">
    <h4>Deployment-oriented reduction</h4>
    <p>We show that a clinically lighter 5-sensor configuration retains essentially all of the performance of the full 13-sensor setup.</p>
  </div>
</div>"""

    toc_html = f"""
<aside class="toc">
  <div class="toc-card">
    <div class="toc-kicker">Reader guide</div>
    <p class="toc-title">Contents</p>
    <ul class="toc-list">
      <li><a href="#abstract">Abstract</a></li>
      <li><a href="#intro">1. Introduction</a></li>
      <li><a href="#results">2. Results</a></li>
      <li><a href="#results-baseline">2.2 Total-score challenge</a></li>
      <li><a href="#results-observability">2.3 Observability decomposition</a></li>
      <li><a href="#results-heldout">2.4 Held-out test</a></li>
      <li><a href="#results-calibration">2.6 Calibration</a></li>
      <li><a href="#results-sensor">2.8 Sensor reduction</a></li>
      <li><a href="#discussion">3. Discussion</a></li>
      <li><a href="#methods">4. Methods</a></li>
      <li><a href="#references">References</a></li>
      <li><a href="#supplementary">Supplementary</a></li>
    </ul>
    <div class="obs-meter">
      <div class="toc-kicker">Score-range anatomy</div>
      <div class="obs-bar">
        <span class="obs-direct"></span>
        <span class="obs-partial"></span>
        <span class="obs-unobs"></span>
      </div>
      <ul class="obs-list">
        <li>Direct: 24/132 ({direct_share:.1f}%)</li>
        <li>Partial: 68/132 ({partial_share:.1f}%)</li>
        <li>Unobservable: 40/132 ({unobs_share:.1f}%)</li>
      </ul>
    </div>
  </div>
</aside>"""

    table1_block = table_card(gp._table1(dp, dc))
    table2_block = table_card(gp._table2(mt, held, held_demo, d.phase1.get("splits", [])))
    table3_block = table_card(gp._table3(obs, direct, partial, unobs_l, binary_obs))
    table4_block = table_card(table4_severity(d.confounds))
    table5_block = table_card(table5_sensor(d))
    table6_block = table_card(table6_context())
    table_s1_block = table_card(gp._table_dl(d))
    table_s2_block = table_card(gp._table_holm(d))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Wearable Gait Sensors Predict Observable Motor Severity in Parkinson's Disease</title>
{CSS}
</head>
<body>
<main class="paper-shell">
  <article class="paper">
    <header class="hero" id="top">
      <p class="kicker">Computational Neurology | Wearable Biomarkers | Parkinson's Disease</p>
      <h1>Wearable gait sensors predict observable but not unobservable motor severity in Parkinson's disease</h1>
      <p class="deck">A subject-level benchmark on WearGait-PD shows that the key bottleneck is not model capacity. It is whether the clinical endpoint is physically expressed in gait.</p>
      <p class="authors">Author list pending final manuscript metadata.</p>
      <p class="affiliations">Institutional affiliations pending final manuscript metadata.</p>
      {snapshot_cards}
      <div class="claim-banner">
        <span class="eyebrow">Central claim</span>
        <p>Gait IMUs do contain clinically relevant Parkinsonian motor information, but only a minority of the total MDS-UPDRS-III score is directly observable during walking. The model ceiling therefore comes from endpoint mismatch more than from lack of algorithmic sophistication.</p>
      </div>
    </header>

    <section class="paper-section" id="abstract">
      <div class="section-heading">
        <h2>Abstract</h2>
        <p class="section-tag">Structured for fast reading</p>
      </div>
      {abstract_blocks}
      {takeaway_cards}
    </section>

    <section class="paper-section" id="intro">
      <div class="section-heading">
        <h2>1. Introduction</h2>
        <p class="section-lead">The paper asks a narrow but important question: what portion of a clinician-rated motor scale is a gait sensor actually entitled to predict?</p>
      </div>
      <p>Parkinson's disease (PD) affects over 8.5 million people worldwide, making it the fastest-growing neurological disorder<sup>1</sup>. The MDS-UPDRS Part III motor examination remains the clinical reference standard, but it compresses heterogeneous phenomena into one score: gait and posture, rigidity, speech, facial expression, seated rapid alternating movements, and tremor. That heterogeneity matters because a body-worn IMU can only sense a subset of those motor signs during walking.</p>
      <p>Prior wearable studies have reported promising total-score regression results, but most were conducted on small cohorts with leave-one-out validation and materially different sensing setups<sup>3,4</sup>. Some published results are also hard to interpret because of leakage risk or because they target classification rather than continuous severity estimation<sup>5,6</sup>. WearGait-PD offers a cleaner stress test: a larger controlled-gait dataset with complete motor scores and enough subjects to separate PD-only grading from easier PD-versus-control discrimination.</p>
      <p>WearGait-PD comprises {gp.N_ENROLLED_PD + gp.N_ENROLLED_HC} enrolled participants ({gp.N_ENROLLED_PD} PD, {gp.N_ENROLLED_HC} HC), of whom {gp.N_ANALYZED} ({gp.N_ANALYZED_PD} PD, {gp.N_ANALYZED_HC} HC) had complete recordings<sup>7</sup>. No prior paper has reported continuous UPDRS-III regression on this dataset.</p>
      {contribution_cards}
      <figure>
        <img src="{figures['fig1']}" alt="Study design pipeline">
        <figcaption><strong>Figure 1.</strong> Study design and analysis pipeline. WearGait-PD recordings from 13 IMUs across six gait and balance tasks pass through two feature pathways: handcrafted features and frozen MOMENT-1 embeddings. After within-fold feature selection, a multi-seed LightGBM stack predicts either total UPDRS-III or the directly observable gait-relevant subscore.</figcaption>
      </figure>
    </section>

    <section class="paper-section" id="results">
      <div class="section-heading">
        <h2>2. Results</h2>
        <p class="section-lead">The results progress from a benchmark question to a mechanism question, then to held-out confirmation and deployment constraints.</p>
      </div>

      <h3 id="results-cohort">2.1 Cohort Description</h3>
      <p>Of {gp.N_ENROLLED_PD + gp.N_ENROLLED_HC} enrolled participants, {gp.N_ANALYZED} ({gp.N_ANALYZED_PD} PD, {gp.N_ANALYZED_HC} HC) had complete sensor recordings and were included. PD participants had moderate motor severity (UPDRS-III {dp['updrs3_mean']}&nbsp;&plusmn;&nbsp;{dp['updrs3_std']}; range {dp['updrs3_range']}), and Hoehn &amp; Yahr staging was available for {dp['hy_n_available']} patients. The HC group was older ({dc['age_mean']}&nbsp;&plusmn;&nbsp;{dc['age_std']} years, p&nbsp;&lt;&nbsp;0.001), an imbalance that is important for interpreting mixed-cohort gains. Medication state was not systematically controlled in the source protocol.</p>
      {table1_block}

      <h3 id="results-baseline">2.2 Total UPDRS-III Prediction: The Demographic Baseline Challenge</h3>
      <p>In PD-only 10-split cross-validation (N&nbsp;=&nbsp;98), the best sensor model reached MAE&nbsp;=&nbsp;{p10_b1_v2['mae_mean']:.2f}&nbsp;&plusmn;&nbsp;{p10_b1_v2['mae_std']:.2f} with CCC&nbsp;=&nbsp;{p10_b1_v2['ccc_mean']:.3f}. A demographic Ridge model using only age, sex, disease duration, height, and weight achieved MAE&nbsp;=&nbsp;{p10_demo['mae_mean']:.2f}&nbsp;&plusmn;&nbsp;{p10_demo['mae_std']:.2f}, slightly better on absolute error. The same tension persisted in LOOCV: FM-augmented IMU MAE&nbsp;=&nbsp;{fm_loocv['mae']:.2f} versus demographic baseline MAE&nbsp;=&nbsp;{demo_loocv['mae']:.2f}, with poor calibration for both (sensor slope&nbsp;=&nbsp;{fm_loocv['cal_slope']:.3f}, demographic slope&nbsp;=&nbsp;{demo_loocv['cal_slope']:.3f}).</p>
      <div class="callout"><strong>Interpretation.</strong> Success on total UPDRS-III is not synonymous with measuring gait-expressed motor state. A large fraction of the score tracks disease stage or clinician-only signs that an IMU cannot directly observe.</div>
      <p>The sensor model still contains real motor signal. It significantly beat a mean-prediction baseline (permutation p<sub>adj</sub>&nbsp;=&nbsp;{hb['P2_permutation']['p_adj']:.4f}), and partial correlation after controlling for age and disease duration remained {partial_corr['r']:.2f} (p<sub>adj</sub>&nbsp;=&nbsp;{hb['P2_partial_corr']['p_adj']:.4f}). But only 24 of 132 total score points are directly available to gait sensing; the rest are indirect or clinically inaccessible to an IMU-only system.</p>
      <p>HC-augmented training further clarified the problem. When the model trained on PD+HC and was evaluated on PD severity, MAE worsened to {mt['10split_b2_fm_stk']['mae_mean']:.2f}&nbsp;&plusmn;&nbsp;{mt['10split_b2_fm_stk']['mae_std']:.2f}, suggesting that the representation learns disease-versus-control separation more readily than within-PD ordering.</p>
      {table2_block}
      <p>Absolute agreement remained limited: only {clinical['pct_within_mcid_3.25']:.1f}% of LOOCV predictions fell within the MCID context band of 3.25 points, although ranking was better than calibration (Spearman &rho;&nbsp;=&nbsp;{d.confounds['spearman']['rho']:.3f}, p<sub>adj</sub>&nbsp;=&nbsp;{hb['P4_spearman']['p_adj']:.4f}). Weighted kappa for severity quartiles was {d.confounds['weighted_kappa']:.3f}, and missing-data sensitivity analysis showed little evidence that incomplete recordings alone explain the ceiling.</p>

      <h3 id="results-observability">2.3 Three-Level Observability Decomposition</h3>
      <p>We therefore decomposed MDS-UPDRS-III into three tiers defined by sensing physics rather than by clinical tradition. <em>Directly observable</em> items (3.9&ndash;3.14) generate gait-manifest kinematic signatures. <em>Partially observable</em> items (3.5&ndash;3.8, 3.15&ndash;3.17) share biomechanical substrate with gait but are not administered during walking. <em>Clinically unobservable</em> items (3.1&ndash;3.4, 3.18) require modalities beyond inertial sensing.</p>
      <p>The decomposition exposes the ceiling cleanly. In PD-only LOOCV, the directly observable tier achieved CCC&nbsp;=&nbsp;{direct['ccc']:.2f} and MAE&nbsp;=&nbsp;{direct['mae']:.2f}. The partially observable tier retained similar normalized error ({partial['mae']/68*100:.1f}% of its scale range) but collapsed to CCC&nbsp;=&nbsp;{partial['ccc']:.2f}, indicating weak rank-ordering and calibration. The clinically unobservable tier performed worst overall (CCC&nbsp;=&nbsp;{unobs_l['ccc']:.2f}, nMAE&nbsp;=&nbsp;{unobs_l['mae']/40*100:.1f}%). The important point is not just error magnitude; it is that agreement degrades exactly as observability degrades.</p>
      <div class="callout"><strong>Endpoint anatomy.</strong> Directly observable gait-relevant signs account for only {direct_share:.1f}% of the total MDS-UPDRS-III score range. The remaining {100 - direct_share:.1f}% is either only indirect or not physically accessible to gait IMUs at all.</div>
      <figure>
        <img src="{figures['fig2']}" alt="Observability decomposition">
        <figcaption><strong>Figure 2.</strong> The total endpoint is mostly made of signs that gait sensors do not directly see. Once the score is partitioned by observability, concordance declines in the same direction as sensing access.</figcaption>
      </figure>
      {table3_block}

      <h3 id="results-heldout">2.4 Pre-Registered Held-Out Test</h3>
      <p>The held-out split functions as a confirmation step rather than the primary source of evidence. On the pre-registered test set (N&nbsp;=&nbsp;36: 21 PD, 15 HC), the FM-augmented model achieved MAE&nbsp;=&nbsp;{held['mae']:.2f}, CCC&nbsp;=&nbsp;{held['ccc']:.3f}, and r&nbsp;=&nbsp;{held['r']:.3f}, outperforming the demographic baseline on the full cohort. But the stricter PD-only subset remained modest (MAE&nbsp;=&nbsp;{mt['held_out_pd_subset']['mae']:.2f}, CCC&nbsp;=&nbsp;{mt['held_out_pd_subset']['ccc']:.3f}), consistent with the main claim that cohort separation helps more than within-PD grading.</p>
      <p>Importantly, the directly observable held-out subscore also reproduced the same pattern (MAE&nbsp;=&nbsp;{d.held_out['obs_subscore_test']['mae']:.2f}, CCC&nbsp;=&nbsp;{d.held_out['obs_subscore_test']['ccc']:.3f}). That replication matters more than the exact total-score number because it shows the observability structure survives outside the main LOOCV analysis.</p>
      <figure>
        <img src="{figures['fig3']}" alt="Held-out performance">
        <figcaption><strong>Figure 3.</strong> The left panel shows the full held-out split, where PD-versus-HC separation contributes substantially to the fit. The right panel isolates the harder PD-only subset, where the remaining challenge is genuine severity grading.</figcaption>
      </figure>

      <h3 id="results-item">2.5 Item-Level Analysis and Feature&ndash;Anatomy Alignment</h3>
      <p>Item-level analysis provides the mechanistic sanity check. The highest-correlation items were predominantly the directly observable gait-related ones, while the lowest-correlation items were speech, facial expression, rigidity, and tremor constancy. Feature importance also aligned with anatomy: foot and trunk sensors drove gait and posture items, wrist sensors supported upper-limb items, and no coherent inertial pathway rescued the clinically inaccessible signs. This is the pattern expected from genuine biomechanics rather than from a spurious demographic shortcut.</p>
      <figure>
        <img src="{figures['fig4']}" alt="Item-level predictability">
        <figcaption><strong>Figure 4.</strong> Per-item predictability ranked by Pearson r. The sensor-item anatomy is clinically coherent: gait-related items cluster at the top, while clinician-only signs stay at the bottom.</figcaption>
      </figure>

      <h3 id="results-calibration">2.6 Severity-Stratified Error and Calibration</h3>
      <p>The model is substantially better at placing patients into the broad middle of the cohort than at estimating severity at the extremes. Moderate-severity quartiles (Q2&ndash;Q3) had MAE near 6 points, whereas Q1 and Q4 exceeded 14 points with opposite biases: overprediction in mild PD and underprediction in severe PD. This is classic shrinkage toward the cohort center, not a trivial global offset. Bland&ndash;Altman bias was {bland['bias']:.1f} with 95% limits of agreement [{bland['loa_lo']:.1f}, {bland['loa_hi']:.1f}], and proportional bias remained evident (slope&nbsp;=&nbsp;{bland['prop_bias_slope']:.2f}, p&nbsp;&lt;&nbsp;0.001).</p>
      {table4_block}
      <figure>
        <img src="{figures['fig5']}" alt="Severity calibration">
        <figcaption><strong>Figure 5.</strong> Severity error is not uniform. Quartile means compress toward the cohort center, which explains why ranking can be informative while absolute score calibration remains poor.</figcaption>
      </figure>

      <h3 id="results-fm">2.7 Foundation Model Embeddings</h3>
      <p>Frozen MOMENT-1 embeddings improved mixed PD+HC evaluation from {v2_mixed.mean():.2f} to {fm_mixed.mean():.2f} MAE across 10 splits (Wilcoxon p&nbsp;=&nbsp;{p_fm_v2:.4f}), winning 9 of 10 splits. But that gain largely disappeared in PD-only evaluation, where FM stack performance ({p10_fm['mae_mean']:.2f}&nbsp;&plusmn;&nbsp;{p10_fm['mae_std']:.2f}) was not significantly better than the handcrafted baseline after correction (p<sub>adj</sub>&nbsp;=&nbsp;{hb['P1_fm_vs_v2_median']['p_adj']:.2f}). The right interpretation is therefore cautious: foundation models are useful feature extractors, but on this dataset they help most when the task includes easier group-separation structure.</p>
      <figure>
        <img src="{figures['fig6']}" alt="FM impact">
        <figcaption><strong>Figure 6.</strong> Foundation model embeddings win consistently in the mixed cohort, but that advantage does not translate cleanly to the harder PD-only grading problem.</figcaption>
      </figure>

      <h3 id="results-sensor">2.8 Sensor Ablation</h3>
      <p>Sensor reduction is the main deployment-positive result. After re-extracting FM embeddings for each configuration to avoid leakage, a 5-sensor set (lower back, bilateral wrists, bilateral ankles) matched the full 13-sensor setup ({mt['sensor_minimal_5']['mae_mean']:.2f} vs {mt['sensor_all_13']['mae_mean']:.2f} MAE, p&nbsp;=&nbsp;0.851). Even wrists alone remained surprisingly competitive, while a single lower-back sensor was reliably worse. The implication is pragmatic: clinically realistic wear-time configurations may be possible without sacrificing much performance.</p>
      <figure>
        <img src="{figures['fig7']}" alt="Sensor ablation">
        <figcaption><strong>Figure 7.</strong> Once feature extraction is re-run per configuration, the minimal 5-sensor setup is statistically indistinguishable from the full-body arrangement.</figcaption>
      </figure>
      {table5_block}

      <h3 id="results-context">2.9 Cross-Dataset Context</h3>
      <p>Cross-dataset comparison is useful only if endpoint mismatch is kept explicit. Figure&nbsp;8 therefore restricts the visual comparison to studies that predict a total motor score. Our directly observable subscore is kept in Table&nbsp;6 as a separate, intentionally non-comparable row because it is a different endpoint with a different score range. Against prior small-cohort free-living studies, the apparent performance gap can be explained by differences in cohort size, sensing configuration, task ecology, and validation protocol rather than by a single algorithmic deficit.</p>
      <figure>
        <img src="{figures['fig8']}" alt="Cross-dataset context">
        <figcaption><strong>Figure 8.</strong> Cross-study context shown without mixing incompatible endpoints. Total-score MAE is only compared against other total-score studies, while a side panel makes the protocol mismatch explicit.</figcaption>
      </figure>
      {table6_block}

      <h3 id="results-failures">2.10 What Did Not Work</h3>
      <p>Negative results are part of the evidence. Five end-to-end deep learning architectures all produced MAE&nbsp;&gt;&nbsp;10. Additional failed strategies included item-wise decomposition and summation, mixture-of-experts by severity, severity-stratified training, cross-sensor coordination features, two-stage observable-to-total mapping, broad hyperparameter sweeps, and freezing-of-gait transfer. The point is not that every avenue has been exhausted, but that a wide range of model classes already converges on the same total-score ceiling while the observability-aligned subscore remains learnable.</p>
    </section>

    <section class="paper-section" id="discussion">
      <div class="section-heading">
        <h2>3. Discussion</h2>
        <p class="section-lead">The main lesson is conceptual: benchmark performance improves when the endpoint respects sensing physics.</p>
      </div>
      <h3>3.1 The Observability Ceiling</h3>
      <p>Our central contribution is not a new best total-score MAE. It is the argument that total MDS-UPDRS-III from gait alone has a structural ceiling because the scale aggregates motor signs that are only partially or not at all present during ambulation. Rigidity requires passive examination, speech and facial expression are not inertial phenomena, and several upper-limb and tremor items are administered outside the locomotor regime. Once the endpoint is decomposed this way, performance falls in the exact order that observability predicts.</p>
      <p>The convergence evidence is broad rather than absolute. Random kernels, handcrafted features, frozen foundation models, and multiple deep-learning architectures all settle around MAE&nbsp;&approx;&nbsp;8 on total score, while the directly observable subscore reaches CCC&nbsp;=&nbsp;{direct['ccc']:.2f}. That pattern is strongly consistent with an observability-driven ceiling, though cross-dataset replication with independent clinician review of the tier definitions would strengthen the claim.</p>
      <h3>3.2 The Demographic Baseline Problem</h3>
      <p>The demographic baseline is a feature, not a nuisance result. If age and disease duration can nearly match wearable performance on total score, then the endpoint is partly a stage proxy. Three observations show that the wearable model is still doing something clinically meaningful: partial correlation beyond demographics, anatomically coherent feature attribution, and the much stronger performance on the directly observable subscore. The real problem is that total score rewards prediction of latent disease stage at least as much as it rewards measurement of gait-expressed motor state.</p>
      <h3>3.3 Clinical Implications</h3>
      <p>The directly observable subscore (items 3.9&ndash;3.14) is the endpoint that best fits the sensing modality. Its LOOCV performance (MAE&nbsp;=&nbsp;{direct['mae']:.2f}, CCC&nbsp;=&nbsp;{direct['ccc']:.2f}) suggests that wearables are promising for continuous monitoring of gait, posture, arising, and body bradykinesia, even if they cannot replace the full neurological examination. This reframes the deployment question from <em>replacement</em> to <em>targeted augmentation</em>.</p>
      <p>We also keep the MCID comparison appropriately limited. The canonical 3.25-point threshold was derived for longitudinal change detection rather than cross-sectional prediction error<sup>2</sup>. It is useful as context, but not as a formal pass-fail criterion for this manuscript.</p>
      <h3>3.4 Foundation Models for Clinical Time Series</h3>
      <p>Frozen foundation models are useful here mainly as robust feature extractors. They help in the mixed cohort because they separate groups well, but they do not magically solve the within-PD severity problem. That is still valuable: it suggests that self-supervised time-series representations may be most helpful when paired with clinically aligned endpoints and explicit control of cohort shortcuts.</p>
      <h3>3.5 Limitations</h3>
      <p>Several limitations matter. First, the analysis is confined to a single controlled-gait dataset. Second, medication state was not standardized. Third, the HC cohort was older than the PD cohort, which likely benefits mixed-cohort separation. Fourth, N&nbsp;=&nbsp;98 PD subjects still limits held-out statistical power, especially for the PD-only subset. Fifth, calibration is poor enough that the current model is better framed as a ranking or monitoring tool than as an absolute score estimator. Sixth, the observability tiering is clinically motivated but still includes judgment calls, especially for partially observable items. Finally, DBS-stratified sensitivity analysis was not performed despite 23 PD participants having DBS.</p>
      <h3>3.6 Future Directions</h3>
      <p>The next work should test transfer to external datasets, especially ones with different task ecology, and should move from cross-sectional severity estimation toward longitudinal change tracking. Endpoint design should remain central: either predict the directly observable subdomain, or combine gait IMUs with additional modalities that can close the observability gap. On the deployment side, the 5-sensor result makes prospective validation with lighter wearability burdens realistic.</p>
    </section>

    <section class="paper-section" id="methods">
      <div class="section-heading">
        <h2>4. Methods</h2>
        <p class="section-lead">Methods are kept explicit because leakage control and evaluation protocol are as important as model choice for this question.</p>
      </div>
      <h3>4.1 Dataset</h3>
      <p>WearGait-PD<sup>7</sup> (Synapse syn55052683) comprises {gp.N_ENROLLED_PD} PD and {gp.N_ENROLLED_HC} HC participants, of whom {gp.N_ANALYZED} ({gp.N_ANALYZED_PD} PD, {gp.N_ANALYZED_HC} HC) had complete recordings. Each subject wore 13 Xsens MTw Awinda IMU sensors placed at the lower back, bilateral wrists, bilateral mid-lateral thighs, bilateral lateral shanks, bilateral dorsal feet, bilateral ankles, xiphoid process, and forehead. Sensors sampled at 100&nbsp;Hz across six standardized gait and balance tasks. Motor severity was assessed by trained clinicians using MDS-UPDRS Part III.</p>
      <h3>4.2 Evaluation Protocol</h3>
      <p>We used three complementary evaluation protocols. <em>PD-only LOOCV</em> (N&nbsp;=&nbsp;98) is the primary benchmark. <em>PD-only 10-split CV</em> (N&nbsp;=&nbsp;98) uses multi-label stratification over UPDRS bins and age terciles to estimate variance. <em>Pre-registered held-out test</em> (N&nbsp;=&nbsp;36; seed&nbsp;=&nbsp;20260309) was specified before model selection and used once. All splits preserved strict subject-level separation.</p>
      <h3>4.3 Feature Extraction</h3>
      <p>Recordings were segmented into 10-second windows with 50% overlap. Handcrafted features (1,752 total) captured time-domain dispersion, jerk, zero-crossing rate, spectral content, gait regularity, task contrasts, and clinical covariates. Foundation model embeddings used the frozen MOMENT-1-base encoder<sup>8</sup>, yielding 768-dimensional subject-level representations from accelerometer and gyroscope magnitude channels after per-recording z-normalization and deterministic averaging.</p>
      <h3>4.4 Feature Selection and Model</h3>
      <p>XGBoost gain-based ranking selected top-K features within each training fold. The primary regressor was LightGBM with MAE objective and early stopping, ensembled across five seeds. The demographic baseline was Ridge regression on age, sex, disease duration, height, and weight.</p>
      <h3>4.5 Three-Level Observability Classification</h3>
      <p>Items were assigned according to whether the target sign is physically expressed during gait. Directly observable items (3.9&ndash;3.14) produce gait-manifest kinematics. Partially observable items (3.5&ndash;3.8, 3.15&ndash;3.17) share substrate with gait but are not administered in the gait regime. Clinically unobservable items (3.1&ndash;3.4, 3.18) require modalities beyond inertial sensing.</p>
      <h3>4.6 Statistical Analysis</h3>
      <p>The primary agreement metric was Lin's concordance correlation coefficient. Confidence intervals used BCa bootstrap (10,000 replicates), stratified by group when appropriate. LOOCV model comparisons used paired bootstrap; 10-split comparisons used Wilcoxon signed-rank. Multiple testing used Holm&ndash;Bonferroni correction. Additional analyses included Bland&ndash;Altman bias and partial correlation controlling for age and disease duration.</p>
      <h3>4.7 Code and Data Availability</h3>
      <p>WearGait-PD is available on Synapse (syn55052683)<sup>7</sup>. Analysis code will accompany the final public release of this manuscript.</p>
    </section>

    <section class="paper-section" id="references">
      <div class="section-heading"><h2>References</h2></div>
      <div class="ref">
        <ol>
          <li>GBD 2019 Collaborators. Global, regional, and national burden of neurological disorders, 1990&ndash;2019. <em>Lancet Neurol.</em> 20, 797&ndash;820 (2021).</li>
          <li>Horvath, K. et al. Minimal clinically important difference on the Motor Examination part of MDS-UPDRS. <em>Parkinsonism Relat. Disord.</em> 21, 1421&ndash;1426 (2015).</li>
          <li>Hssayeni, M. D. et al. Wearable sensors for estimation of Parkinsonian tremor severity during free body movement. <em>BioMed. Eng. OnLine</em> 20, 24 (2021).</li>
          <li>Shuqair, H. et al. Self-supervised representation learning for motor severity estimation. <em>Bioengineering</em> 11, 689 (2024).</li>
          <li>Sotirakis, C. et al. Identification of motor progression in Parkinson's disease using wearable sensors. <em>npj Parkinsons Dis.</em> 9, 74 (2023).</li>
          <li>Li, J. et al. TRIP: Transformer-based IMU pretraining for Parkinson's disease. <em>arXiv</em> 2510.15748 (2025).</li>
          <li>WearGait-PD dataset. <em>Sci. Data</em> (2026). doi:10.1038/s41597-026-06806-2.</li>
          <li>Goswami, M. et al. MOMENT: A family of open time-series foundation models. <em>ICML</em> (2024).</li>
          <li>Varghese, J. et al. PADS: Parkinson's disease smartwatch dataset. <em>PhysioNet</em> (2024).</li>
        </ol>
      </div>
    </section>

    <section class="paper-section" id="supplementary">
      <div class="section-heading"><h2>Supplementary Information</h2></div>
      <h3>Table S1: Deep Learning Comparison</h3>
      {table_s1_block}
      <h3>Table S2: Holm&ndash;Bonferroni Corrected p-Values</h3>
      {table_s2_block}
    </section>
  </article>
  {toc_html}
</main>
</body>
</html>"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output HTML path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output

    print("=" * 60)
    print("PAPER GENERATOR V2 — WearGait-PD UPDRS-III Regression")
    print("=" * 60)

    print("\n[1/5] Loading artifacts...")
    d = gp.load_all_data()

    print("\n[2/5] Computing held-out statistics...")
    test_stats = gp.compute_test_stats(d)
    if test_stats:
        print(f"  Test: MAE={test_stats['mae']:.2f}, CCC={test_stats['ccc']:.3f}, r={test_stats['r']:.3f}")

    print("\n[3/5] Generating figures...")
    figures = {
        "fig1": gp.fig1_study_design(),
        "fig2": gp.fig2_observability_summary(d),
        "fig3": gp.fig3_main_scatter(d, test_stats),
        "fig4": gp.fig4_item_predictability(d),
        "fig5": gp.fig5_severity_calibration(d),
        "fig6": gp.fig6_fm_impact(),
        "fig7": gp.fig7_sensor_ablation(d),
        "fig8": gp.fig8_cross_dataset(),
    }

    print("\n[4/5] Assembling redesigned HTML...")
    html = build_html(d, test_stats, figures)

    print("\n[5/5] Validating...")
    issues = gp.validate_html(html)
    if issues:
        print("  WARNINGS:")
        for issue in issues:
            print(f"    - {issue}")
    else:
        print("  Validation passed.")

    output.write_text(html, encoding="utf-8")
    size_kb = output.stat().st_size / 1024
    print(f"\nSaved: {output} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
