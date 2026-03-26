# How We Built an AI-Assisted Research Pipeline and Wrote a Paper in Three Weeks

*A knowledge transfer document for university labs wanting to replicate this workflow.*

---

## Prologue

In early March 2026, we set out to do something no one had done before: predict Parkinson's disease motor severity -- the full MDS-UPDRS Part III score -- from wearable inertial sensors on the WearGait-PD dataset. The dataset had been public for a few months. Other groups had used it for classification. No one had attempted regression. We saw an opening to own a benchmark.

Three weeks later, we had a manuscript targeting Nature Digital Medicine, a breakthrough method (ordinal ranking) that improved concordance from 0.70 to 0.865, and a codebase of 50 experiment scripts backed by 101 JSON result artifacts and 129 unit tests. Along the way, we discovered that our early results were contaminated, caught the contamination ourselves, recovered with a full audit trail, and came out with a stronger paper because of it.

This document tells the story of how that happened. Not just the science, but the process -- the infrastructure, the AI assistants, the mistakes, the tools, and the workflow that made it possible for a single researcher to do what would traditionally take a small team several months.

---

## Part 1: The Setup

### The machines

The first decision was architectural: where does the code live, where does the data live, and where do experiments run? The WearGait-PD dataset is 52 gigabytes of raw IMU recordings from 178 subjects wearing 13 body-mounted sensors at 100 Hz. You do not want this on your laptop. You also need a GPU for the foundation model embeddings and some of the deep learning experiments.

We settled on a master/slave architecture. The local workstation -- the master -- is the source of truth. All code lives here, all git operations happen here, the paper renders here. The remote GPU server -- the slave -- is disposable. It holds the dataset and the heavy dependencies (PyTorch, CUDA, LightGBM, XGBoost, the MOMENT-1 foundation model). If the remote dies or we need more power, we swap it in 30 minutes.

The entire relationship between master and slave is mediated by a single 144-line bash script called `gpu.sh`. This was one of the best engineering decisions in the project. When you type `./gpu.sh run_compression_ablation.py --phase 5`, it does three things: rsyncs the code to the remote (excluding `.git`, `data/`, and `results/` -- you never want to push 52 GB of data or overwrite remote results), SSHs in, and runs the Python script. When you type `./gpu.sh --pull`, it rsyncs back only the result artifacts (JSON, CSV, log files). That is the complete interface. Deploy, run, pull.

We swapped GPU servers twice during the project. The first time was an upgrade from an RTX 5060 Ti (16 GB VRAM) to an RTX 3090 (24 GB). The process was: update two environment variables (`GPU_REMOTE` and `GPU_PORT`), run `./gpu.sh --setup` (which installs PyTorch with CUDA 12.8 and all dependencies from a pinned `requirements-gpu.txt`), upload cached feature artifacts with `./gpu.sh --push-cache`, and download the dataset from Synapse with `./gpu.sh synapse_download.py`. Thirty minutes, start to finish, including the 47 GB dataset download. The second swap was for the reviewer response experiments, when the first server's rental expired.

### The local environment

On the master, we use `uv` for Python environment management -- not pip, not conda. The local dependencies are deliberately minimal: matplotlib, numpy, pandas, scikit-learn, scipy. That's it. Just enough to run tests, generate figures, and render the paper. The heavy lifting happens on the remote.

Tests run locally with `uv run pytest tests/ -v`. By the end of the project there were 129 passing tests covering the shared utility modules: path handling, data split integrity, sensor filtering, UPDRS column resolution, and metric computations. The experiment scripts themselves are not tested end-to-end -- they are validated by inspecting their JSON output artifacts.

### The AI assistants

This project used three AI coding assistants, each with a different role. Understanding how to use them, when to use each one, and when to ignore all of them is perhaps the most important lesson in this document.

**Claude Code** (Anthropic's Opus 4.6 model, 1M context window) was the primary development environment. It runs in a terminal, has full filesystem access, can execute bash commands, and maintains persistent memory across sessions. Claude Code wrote all 50 experiment scripts, designed the ordinal ranking method that became the paper's core contribution, managed the remote GPU server through `gpu.sh`, generated the 3,896-line paper generator, ran three rounds of self-review on the manuscript, and tracked experiments via structured JSON artifacts. It is, in practice, a junior researcher that never sleeps, never forgets, and can write Python at 200 lines per minute.

The key to making Claude Code effective is a file called `CLAUDE.md` in the project root. Think of this as the briefing document you would give a new lab member on their first day. Ours grew organically over three weeks and ended up containing: the scientific objective and why it matters; the complete SOTA landscape with manually verified citations; what has already been tried and failed (with a strict "DO NOT RETRY" list); hard methodological rules like "NEVER per-subject z-normalize for regression" and "ALWAYS use subject-level splits"; data split warnings and gotchas; the architecture of the codebase; and exact commands to run every experiment. Every time Claude Code starts a new session, it reads this file. Every session inherits all the accumulated knowledge of the project. This is what makes the AI effective over weeks-long projects -- it is not starting from scratch each time.

Claude Code also has a memory system. In `.claude/projects/`, there are markdown files that persist facts, feedback, and technical learnings across sessions. When we discovered that SSL ranking was the breakthrough method, that went into memory. When we discovered that LightGBM's GPU mode is 2.2x slower than CPU for small N, that went into memory. When the reviewer pointed out that "SSL" was a misleading label because PD-only ranking works equally well, that feedback went into memory. The memory system is not perfect -- it can get stale -- but it provides continuity that a fresh prompt cannot.

**Codex CLI** (OpenAI's GPT-5.4 model) was used as a second opinion. You invoke it from the terminal: `codex exec -m gpt-5.4 -c model_reasoning_effort="xhigh" --full-auto "your question"`. It cannot read local files (it runs in a sandbox), so you either paste context into the prompt or describe the situation in words. What Codex contributed to this project was independent methodology advice. When we needed to decide how to implement 5-fold CV for the SSL pipeline, we asked Codex. Its answer was precise: healthy controls can stay in Stage 1 for all folds because they serve as auxiliary anchors with no target leakage; expect 5-12% degradation from reduced training N. The actual result was the opposite -- 5-fold turned out better than LOOCV on total UPDRS (CCC 0.807 vs 0.776). But the leakage analysis was sound and gave us confidence to proceed.

**Gemini CLI** (Google's Gemini 3.1 Pro) was used for domain-specific advice, especially clinical methodology. You invoke it: `gemini -m gemini-3.1-pro-preview -y "your question"`. Gemini contributed the design of the age confound sensitivity analysis -- four concrete strategies: age-matched subgroup, partial correlation controlling for age, age-stratified within-PD evaluation, and SHAP divergence between UPDRS and age prediction. All four were implemented and all four confirmed that age is not driving the results. Gemini also advised on paper restructuring (which sections to promote to main text, which to demote to supplementary) and on clinical framing (how to discuss the MCID in the context of a subscore that has no established MCID).

The most effective pattern was parallel consultation: pose the same question to all three AIs simultaneously, then synthesize the best ideas from each. When addressing the reviewer's age confound concern, Claude Code identified that 5-fold SSL results already existed and no new experiment was needed for two of the reviewer comments. Codex provided the leakage analysis for the SSL CV implementation. Gemini provided the clinical sensitivity analysis strategies. No single AI would have produced the same synthesis.

One hard lesson about AI and literature: all three models hallucinate citations. GPT-5.4 told us that He et al. 2024 was a UPDRS regression paper. Manual verification via web search revealed it predicted levodopa response, not UPDRS-III total. Park 2025 reported MAE=0.76 on z-normalized targets, which is meaningless in raw-point units. The rule we codified in CLAUDE.md was: "ALWAYS verify SOTA claims from LLMs against actual papers." This saved us from citing at least two non-existent or mischaracterized papers.

---

## Part 2: The Experiment Architecture

### The philosophy: shared modules, self-contained scripts

The codebase follows a simple rule: three shared modules provide data loading, paths, and UPDRS column resolution. Everything else is a standalone `run_*.py` script that does its own feature extraction, model training, and evaluation end-to-end.

The three shared modules are small and stable. `data_split.py` (286 lines) handles clinical data parsing, windowing sensor recordings into fixed-length segments, and creating train/test splits. `project_paths.py` (90 lines) centralizes all file paths with environment variable overrides, so the same code runs on both master and slave without modification. `updrs_columns.py` (76 lines) resolves UPDRS subitem column names across the naming variants that exist in the WearGait-PD metadata (the clinical CSV uses different column names for the same items depending on the file version). A fourth utility module, `eval_utils.py` (138 lines), provides the metrics we use everywhere: Lin's concordance correlation coefficient, calibration slope, bootstrap confidence intervals, and XGB-importance-based feature selection.

Each experiment script imports only these modules, then does everything else itself. This means you can understand any experiment by reading one file. If a script breaks, it breaks in isolation. If you want to share an experiment with a collaborator, you send one Python file plus the four shared modules. There is no complex build system, no configuration framework, no dependency injection. Just scripts.

By the end of the project, there were 50 experiment scripts totaling roughly 30,000 lines of Python. The largest is `generate_paper.py` at 3,896 lines (the paper generator, which renders the manuscript from JSON artifacts). The largest experiment runner is `run_pd_only_experiments.py` at 1,759 lines (the 7-phase PD-only evaluation pipeline). Most scripts are in the 300-800 line range.

### JSON artifact discipline

Every experiment outputs a structured JSON file to the `results/` directory. This is the paper's source of truth. The JSON contains all the metrics (CCC, MAE, Pearson r, calibration slope), the sample size, the seeds used, and per-subject predictions. The paper generator reads these JSON files directly and renders tables and figures from them. There are no hardcoded numbers in the paper. If the JSON says CCC=0.865, the paper says CCC=0.865. If you change an experiment and re-run it, the paper updates automatically on the next `uv run python generate_paper.py`.

By the end of the project there were 101 JSON result artifacts. An automated numerical consistency audit (`review_report_numbers.md`) cross-checked 47 numerical claims in the paper against their source JSON files. All 47 passed. This level of rigor is only practical because the pipeline is fully automated: experiment outputs JSON, paper generator reads JSON, audit script compares JSON to rendered HTML. The human never enters a number by hand.

### The execution flow

A typical experiment cycle looks like this. Claude Code writes or modifies a `run_*.py` script locally. You deploy and run it on the remote with `./gpu.sh run_experiment.py --args`. The script runs, prints progress, and writes a JSON artifact to `results/` on the remote. You pull results back with `./gpu.sh --pull`. You validate the JSON (check fields, verify N, compare to baseline). If it is a meaningful improvement, you update the CLAUDE.md file and commit. If it is a breakthrough, you update the memory files. Then you regenerate the paper with `uv run python generate_paper.py` and inspect the updated manuscript.

This cycle ran dozens of times per day during the intensive development phase. A typical experiment takes 20 seconds to 10 minutes on the remote, depending on whether it uses LOOCV (slow) or 5-fold CV (fast). The deploy-run-pull cycle adds about 10 seconds of overhead for the rsync operations.

---

## Part 3: The Autoresearch Loop

### Hitting the wall

About a week into the project, we had a respectable baseline: LightGBM on handcrafted features plus MOMENT-1 foundation model embeddings, evaluated by 5-fold CV, giving MAE=8.49 on total UPDRS-III. We also had a concordance measure on the observable subscore: CCC=0.393. Both numbers felt like they should be improvable by tuning hyperparameters.

So we built an autonomous hyperparameter optimization system. The idea was simple: define a configuration file with all the knobs (learning rate, number of leaves, regularization, feature selection K, etc.), write a fixed evaluation harness that reads the config and outputs metrics, then let the AI agent turn knobs one at a time, measure the effect, and keep or discard each change.

### The three-file architecture

The system has three files. `autoresearch_config.py` is the only file the agent modifies. It contains every tunable parameter: which feature groups to include, how many top features to select, which model to use, which seeds to ensemble, and every LightGBM hyperparameter. `autoresearch_eval.py` (for MAE) and `autoresearch_ccc_eval.py` (for CCC) are the fixed evaluation harnesses. They read the config, build the model, run cross-validation, compare to baseline, and output results. These harnesses are explicitly labeled "DO NOT MODIFY" -- the point is that the evaluation protocol is invariant, so any improvement must come from the configuration, not from changing the rules of the game.

Results are logged to append-only TSV files: `autoresearch_results.tsv` and `autoresearch_ccc_results.tsv`. Each row records a timestamp, experiment name, description, metrics (mean and std across folds), improvement over baseline, Wilcoxon p-value, decision (KEEP or DISCARD), and runtime. These TSVs are the complete audit trail. You can see every experiment that was ever tried, in order, including all the failures.

### What happened

On March 13, the MAE autoresearch loop ran 33 experiments in about 35 minutes. The baseline was MAE=8.671. The best configuration found was MAE=8.036, achieved by switching from MAE to MSE loss (+0.310), increasing feature K from 300 to 600, and adding colsample_bytree=0.5. Most other changes (learning rate, tree depth, number of leaves, subsample ratio, early stopping rounds, different ensemble strategies) had zero or negligible effect. At N=178, the model simply does not have enough data to be sensitive to most hyperparameters.

On March 14, the CCC autoresearch loop ran 32 experiments on the observable subscore. The baseline was CCC=0.393. The single most impactful change was `min_data_in_leaf` from 20 to 10, which gave +0.105 CCC -- by far the largest improvement of any single knob. Lowering `reg_lambda` from 3.0 to 0.5 added another +0.017. After that, the CCC plateaued at 0.515 no matter what we tried. We varied every hyperparameter, tried ensemble strategies (LGB+XGB average, LGB+XGB stacking), dropped features, added features, changed learning rates, changed validation fractions, varied the number of seeds. Nothing moved CCC past 0.515.

This was a crucial moment. The autoresearch loop had given us a definitive answer: the hyperparameter space is exhausted. If CCC is stuck at 0.515, the ceiling is in the representation, not in the tuning. Any further progress must come from changing what the model sees, not how it fits. This realization directly motivated the anti-compression research that followed.

---

## Part 4: The Breakthrough

### Five proposals for anti-compression

Prediction compression is the core problem in small-N clinical regression. When you have only 94 PD subjects and you train a gradient boosting model, it converges toward predicting the population mean for everyone. The MAE might be acceptable (because the population is clustered near the mean), but the concordance is terrible (because the model cannot distinguish mild from severe patients). We needed a way to spread the predictions out without introducing noise.

We developed five anti-compression proposals, each embodied in a phase of `run_compression_ablation.py`:

**Phase 1: Per-item ordinal classification.** Instead of predicting the total score, predict each of the 18 items as an ordinal 0-4 classification, then sum. The hope was that ordinal classifiers would preserve the discrete structure of the scale. The reality was catastrophic: CCC=0.338, a 70% degradation from baseline. The per-item models simply did not have enough power -- each item has a very compressed distribution (mostly 0s and 1s) and the errors compound when you sum 18 noisy predictions.

**Phase 2: Pairwise contrastive boosting.** Generate all subject pairs, train a model to predict which member of each pair has higher severity, then reconstruct absolute scores from the pairwise ordering. This was theoretically elegant but practically mediocre: CCC around 0.62, slower than baseline (because the number of pairs is N-squared), and the reconstruction step re-introduced the compression it was supposed to fix.

**Phase 3: SMOGN tail augmentation.** Oversample the severe tail of the distribution using synthetic minority oversampling for regression (SMOGN). This gave a modest calibration improvement -- slope improved by about 0.02, CCC improved by about 0.05 on the broad observable target. Helpful but not transformative.

**Phase 4: NGBoost distributional regression.** Fit a distributional model (Normal, Poisson, LogNormal output) that predicts both mean and variance. The Poisson variant was the best at CCC=0.671, competitive with baseline but not superior. The distributional output was interesting for uncertainty quantification but did not solve compression.

**Phase 5: Semi-supervised ranking with leaf features.** This was the breakthrough. The idea was: train an XGBRanker on all 178 subjects (PD + HC) where the target is ordinal severity rank. The ranker does not need to predict exact scores -- it just needs to learn "this subject is more severe than that one." Then extract the leaf indices from the ranker (which tree terminal nodes each subject falls into) and use those as features for a downstream LightGBM regressor that predicts actual UPDRS scores on PD subjects only.

The results were immediate and dramatic. On the directly observable subscore (items 3.9-3.14), CCC jumped from 0.591 to 0.868. On total UPDRS-III, CCC jumped from 0.186 to 0.776. Calibration slope improved from 0.508 to 0.745. MAE on the observable subscore dropped to 0.986 -- below 1.0 on a 24-point scale.

### Why it worked

The insight is about representation, not about the model. When you have only 94 PD subjects and 1752 features, the regression model does not have enough calibration signal. It sees wide feature variation but narrow target variation, so it hedges by compressing predictions. But when you include the 80 healthy controls as "known-zero calibration anchors" in the ranking stage, the ranker has 178 subjects to learn from. The HC subjects anchor one end of the severity spectrum. The ranker learns a severity ordering that is well-calibrated across the full range. The leaf indices from this ranker encode "where each subject sits in the severity hierarchy" in a way that the downstream regressor can exploit.

Critically, the healthy controls are used only for representation learning. They never appear in the final evaluation. All evaluation metrics are computed on PD subjects only, using 5-fold cross-validation or leave-one-out cross-validation. There is no leakage.

We later discovered, during the reviewer response, that healthy controls are not even necessary for the ranking benefit. PD-only ranking achieves CCC=0.857 versus PD+HC ranking at CCC=0.858 -- a difference of 0.001. The innovation is ordinal ranking itself (the representation transformation), not semi-supervised learning (the use of HC). This led us to rename the method from "SSL ranking" to "ordinal ranking" in the final manuscript.

---

## Part 5: The Contamination Incident

### What happened

This section exists because it is the most important lesson in the entire project, and because being transparent about it made the paper stronger.

During the first two weeks of development, we followed what seemed like a reasonable protocol: split the data into train and test, train a model, evaluate on the test set, and if the new model beats the previous best on the test set, keep it. We repeated this cycle across dozens of experiments -- different features, different models, different hyperparameters. Each time, the "best" result was the one that performed best on the held-out test set.

This is adaptive test-set reuse, and it is one of the most common and most insidious forms of data contamination in machine learning research. Each time you select a model based on test performance, you leak a tiny bit of information from the test set into your model selection process. After 50+ rounds, the accumulated leakage can be substantial. In our case, it inflated the MAE by approximately 2.8 points: the reported MAE=6.89 was actually closer to MAE=9.5 on truly unseen data.

### How we caught it

We caught it ourselves, not because someone else pointed it out. The trigger was a clean benchmark experiment where we created a completely fresh data split with a new random seed (20260309, chosen to be the date) and re-evaluated all our models from scratch. The "best" model on the old split (MAE=6.89) scored MAE=9.68 on the new split. The baseline model scored MAE=9.47. The "best" model was actually worse than baseline on clean data, because it had been optimized for the specific test subjects in the old split.

### The recovery

The recovery was methodical and fully documented in a file called `CONT.md` (the contamination audit). We identified which scripts had access to the test split, which results were affected, which bug fixes were needed, and what the honest numbers were. We created the new split (`paper3_split.json`, seed=20260309, 142 dev + 36 test, stratified by UPDRS-III quintiles) and committed to never using it for model selection. All subsequent development used cross-validation on the dev set only.

We also codified two rules in CLAUDE.md: "NEVER reuse clean test split for model search" and "NEVER promote a sensitivity-check winner as new primary." The second rule is subtler -- it means that even if you run a one-off sensitivity analysis on the test set and it happens to look good, you cannot adopt that configuration as your new primary model. Doing so would recreate the contamination cycle.

The honest held-out test results, on the clean split, were: LGB baseline MAE=9.47 (r=0.605), deployable stack MAE=9.68 (r=0.579), and the Hoehn & Yahr clinical staging ceiling MAE=8.22 (r=0.705). These are sobering numbers that tell you total UPDRS-III from gait IMU has a genuine prediction ceiling. The observable subscore story, evaluated entirely via cross-validation, is much stronger: CCC=0.865.

### The lesson

If you take one thing from this document, let it be this: create your held-out test split once, at the very beginning of the project, before you have run any experiments. Lock it away. Use cross-validation for all model development. Touch the test set exactly once, at the end, to report final numbers. If you find that you have accidentally contaminated your test set, do not try to salvage it. Create a new split and start the evaluation from scratch. Document the contamination and the recovery. Reviewers will respect the honesty far more than they would respect a suspiciously good number.

---

## Part 6: The Paper

### Programmatic generation

The paper is not written in LaTeX or Word. It is generated programmatically from JSON artifacts by a 3,896-line Python script called `generate_paper.py`. When you run `uv run python generate_paper.py`, it reads all 101 JSON result files from the `results/` directory, renders them into tables and figures, wraps everything in HTML with inline CSS, and outputs a single self-contained file called `NEW.html`. You open it in a browser and you have the complete manuscript: abstract, introduction, methods, results (six sections), discussion, limitations, references, supplementary tables, and supplementary figures.

The reason for this approach is simple: it eliminates the single most common source of errors in academic papers -- manually transcribed numbers. Every number in every table traces directly to a field in a JSON artifact. The `CCC=0.865` in the abstract comes from `compression_P5_TT1_5split.json["ccc"]`. The `N=95` comes from the same file's `["n"]` field. If we re-run an experiment and the CCC changes, the paper updates on the next generation. No one has to remember to update Table 3.

We verified this with a numerical consistency audit. An AI reviewer (Claude Opus) read the HTML, extracted every numerical claim, traced it to its source JSON, and checked for agreement. Forty-seven claims were checked. All forty-seven passed.

The paper went through multiple drafts, saved as hidden files: `.paper_r2.txt` (after initial review), `.paper_r3.txt` (after reviewer response experiments), `.paper_final.txt` (current version). Each draft was generated by updating the `generate_paper.py` script with new sections and tables, then re-running. The script grew from about 2,000 lines in the first draft to 3,896 in the final version, reflecting the accumulation of new results, figures, and reviewer-requested analyses.

### Peer review by AI

Before submitting to a journal, we ran three rounds of AI-driven peer review. The first round used Claude Opus 4.6 in a reviewer persona. The reviewer scored the paper 7.0/10 and identified four major issues:

First, the "semi-supervised learning" (SSL) label was misleading. The paper's own HC ablation showed that PD-only ranking (CCC=0.857) matched PD+HC ranking (CCC=0.858). The innovation was ordinal ranking, not semi-supervised learning. The recommendation was to rename throughout and present HC as a sensitivity analysis rather than the method's foundation.

Second, the main results table mixed incomparable evaluation protocols. The baseline used 5-fold CV while the ranking result used LOOCV. A reader glancing at the table would see MAE improve from 8.09 to 4.65 and assume this was an apples-to-apples comparison. It was not.

Third, the observability gradient was not monotonic. Under ordinal ranking, not-observable items (CCC=0.759) slightly exceeded partially observable items (CCC=0.730), inverting the expected ordering. The paper claimed a gradient but the data showed a partial inversion.

Fourth, the transductive design (where the ranker sees ordinal labels from all subjects, including those in the held-out fold) was more problematic than acknowledged.

These were all legitimate issues. Addressing them made the paper substantially better.

### The reviewer response

To address the review, we needed four new experiments. We wrote a single dedicated script, `run_reviewer_experiments.py`, with four subcommands: `--age-sensitivity`, `--hc-ablation`, `--single-sensor`, and `--obs-5fold`. Before writing the script, we consulted all three AI assistants in parallel.

Claude Code discovered that 5-fold SSL results already existed as JSON artifacts, eliminating the need for two of the planned experiments. Codex advised that healthy controls could stay in Stage 1 of the ranking for all folds without target leakage. Gemini proposed four age-confound sensitivity strategies. We synthesized these recommendations and Claude Code implemented all of them in a single 1,120-line script.

Then we needed a GPU server. The previous rental had expired. We provisioned a new RTX 3090 server, installed all dependencies via `./gpu.sh --setup`, downloaded the 47 GB dataset from Synapse, regenerated the foundation model embeddings (the MOMENT-1 API had changed between versions -- `forward()` became `embed()`), and uploaded cached features. This took about an hour.

All four experiments ran in parallel on the remote, completing in 3-8 minutes each. The results were definitive:

The age sensitivity analysis showed that age is not driving the results. Partial correlation after controlling for age was 0.849 (p < 1e-6). An age-matched HC subset (removing HC subjects older than 75) produced CCC=0.868, identical to the full-HC result. Age-stratified evaluation within PD showed CCC ranging from 0.706 (middle age tertile) to 0.911 (older tertile), with no age group showing degraded performance.

The HC ablation showed that ranking itself helps and HC adds only marginal calibration. The baseline (P0, no ranking) had CCC=0.673. PD-only ranking (P5 without HC) jumped to CCC=0.857. Adding HC back produced CCC=0.858. The improvement from 0.673 to 0.857 is the ranking effect. The improvement from 0.857 to 0.858 is the HC effect. The paper's framing had to change accordingly.

The observability decomposition under unified 5-fold CV confirmed the gradient: direct observable CCC=0.834, partially observable CCC=0.730, not observable CCC=0.759. The inversion between partial and not-observable was real and had to be explained (not-observable items like speech and facial expression correlate with overall disease severity through shared pathophysiology, giving the ranking model a back-door to prediction).

The single-sensor analysis showed that a single wrist sensor achieves CCC=0.791. LowerBack alone achieves CCC=0.867 (remarkably close to the 13-sensor result of 0.857). Clinical deployment does not require a full-body sensor setup.

We then updated `generate_paper.py` with four new table functions, restructured the Results section to use 5-fold as the primary protocol (with LOOCV as confirmatory), renamed "SSL ranking" to "ordinal ranking" throughout, and regenerated the manuscript. The numerical consistency audit was re-run and all claims verified.

---

## Part 7: What Failed

This section is arguably the most valuable part of the knowledge transfer. It catalogs every dead end we hit, so you do not have to hit them yourself. Each of these approaches was designed with a reasonable hypothesis, implemented properly, and evaluated rigorously. They all failed. Failure is information.

**All handcrafted feature groups** -- stride variability, left-right asymmetry, nonlinear dynamics (sample entropy, DFA), extended frequency features, interaction terms, phase-angle features -- were tried as additions to the core v2 feature set. None improved any metric. The core statistical and spectral features (RMS, std, range, IQR, skewness, kurtosis, PSD bands, jerk, zero-crossing rate) capture the available signal. Everything else is either redundant or noise.

**End-to-end deep learning** was tried with five architectures. All performed worse than gradient boosting. At N=178, there are simply not enough subjects to train a deep model effectively, especially when the target range is 0-132 and most subjects cluster between 10-40.

**Item decomposition** -- predicting each of the 18 UPDRS items separately and summing -- was 52% worse than predicting the total directly. The per-item models lack statistical power (most items have distributions compressed to 0-2 out of 0-4) and the errors compound when summed.

**Mixture of experts and severity stratification** -- training different models for mild vs moderate vs severe patients -- failed because there are too few subjects in each stratum.

**Post-hoc calibration** (isotonic regression, Platt scaling, linear recalibration) all failed because the underlying predictions lacked variance. You cannot calibrate a model that predicts the same value for everyone.

**Euler angles and free-acceleration channel expansion** -- using the gravity-removed acceleration and orientation channels in addition to raw acc/gyr -- gave marginal improvements not worth the added complexity.

**Demographics embedded as features** in the tree model were simply ignored. LightGBM cannot use age, sex, and disease duration effectively as 3 features among 1752. The demographic baseline needs its own Ridge regression model.

**Walkway gait metrics** (196 pre-computed gait parameters from an instrumented walkway) were completely redundant with the v2 features extracted from the IMU directly.

**Task-specific ensemble** -- training separate models for each gait task (SelfPace, HurriedPace, TUG, Balance, TandemGait) and averaging -- was worse than pooling all tasks together. Again, too few subjects per task.

**LightGBM GPU mode** was 2.2x slower than CPU mode at N<200. The GPU kernel launch overhead dominates when the dataset fits in cache.

Each of these failures is recorded in the CLAUDE.md file under "What Failed (DO NOT RETRY)" so that no future session wastes time re-attempting them.

---

## Part 8: The Technical Stack

### Feature extraction

At the heart of the pipeline is a multi-tier feature extraction system. The first tier, called "v2 handcrafted," computes 1,752 statistical and spectral features from the raw accelerometer and gyroscope signals. For each of the 13 sensors, for each of the 6 channels (Acc X/Y/Z, Gyr X/Y/Z), for each gait task window, it computes: RMS, standard deviation, range, interquartile range, skewness, kurtosis, jerk (first derivative of acceleration), zero-crossing rate, power spectral density in five frequency bands, spectral entropy, and dominant frequency. On top of this, it adds foot contact features (stride time, stance percentage, cadence, left-right asymmetry), event features from the Walk/Turn/SitToStand annotations, turn-specific features, kinematic features from contact-phase analysis, clinical covariates, and distilled walkway metrics.

The second tier uses MOMENT-1-base, a time-series foundation model, to produce 768-dimensional embeddings from the raw sensor windows. These embeddings are extracted once, cached in `fm_embeddings.npz`, and reused across all experiments. The key finding about these embeddings is that they help for total UPDRS-III prediction (dropping MAE from 8.49 to 7.78) but add essentially nothing for the observable subscore. The interpretation is that foundation model embeddings capture global temporal patterns (useful for predicting the full clinical picture) while handcrafted features capture gait-specific kinematics (better for predicting gait-observable items).

The third tier, MiniRocket (5,000 temporal convolution kernels from the `aeon` library), was explored but ultimately not used in the final pipeline. It did not improve when added to the foundation model features.

The fourth tier -- the breakthrough -- is the XGBRanker leaf features. An XGBRanker is trained on all 178 subjects to predict ordinal severity ranking. The leaf indices (which terminal node each subject lands in, for each of the ranker's trees) are extracted as ~900 binary features. These leaf features encode where each subject sits in the learned severity hierarchy. When concatenated with the original handcrafted features and fed to a LightGBM regressor, they dramatically reduce prediction compression.

### Feature selection

With 1,752 handcrafted features plus 768 FM dimensions plus ~900 leaf features, we have over 3,000 features for fewer than 200 subjects. Feature selection is essential and must be done correctly.

We use XGBoost importance-based selection: fit a quick XGBoost model, rank features by gain importance, and keep the top K. The optimal K varies by target: K=150 for total UPDRS with v2 features only, K=300 for v2 + FM, K=500 for CCC-optimized observable subscore.

The critical rule is that feature selection must happen inside each cross-validation fold. If you select the top K features on all the data and then split into folds, you have leaked information from the test fold into the feature selection step. This is one of the most common forms of subtle leakage in machine learning, and we caught it during the reviewer response experiments.

### Models

The final model is LightGBM with these hyperparameters: MSE objective, 31 leaves, learning rate 0.03, 1000 estimators with early stopping at 100 rounds, min_data_in_leaf=10, reg_lambda=0.5, colsample_bytree=0.5. These were found by the autoresearch loop and verified across multiple evaluation protocols. The model is ensembled across 5 random seeds (42, 123, 456, 789, 2024). Multi-seed ensembling is essential at N<200 -- a single seed can vary by 0.1 CCC purely by chance.

XGBoost was tried as both a standalone model and as part of an average/stacking ensemble with LightGBM. Neither improved over LightGBM alone. CatBoost was also tried and was not competitive.

---

## Part 9: Running the Numbers

### The observable subscore

The paper's primary result is on the directly observable subscore: UPDRS-III items 3.9 through 3.14, covering arising from chair, gait, freezing of gait, postural stability, posture, and global spontaneity of movement (body bradykinesia). These are the items that are physically manifest during gait and should therefore be predictable from gait IMU sensors.

With ordinal ranking and PD-only 5-fold cross-validation (N=95), the pipeline achieves CCC=0.865, calibration slope=0.745, MAE=0.953, and Pearson r=0.877. The baseline (same features, same model, no ranking) achieves CCC=0.700. The improvement of 0.165 CCC is substantial and statistically significant.

With LOOCV (N=94), the results are similar: CCC=0.868, MAE=0.986, slope=0.689, r=0.899. The slight differences between 5-fold and LOOCV are within the expected range and give confidence that neither protocol is inflated.

### Total UPDRS-III

For total UPDRS-III prediction (all 18 items), ordinal ranking achieves CCC=0.807, MAE=4.46 under 5-fold CV. This is substantially better than the baseline CCC of approximately 0.186, but the MAE of 4.46 is above the clinically meaningful threshold of 3.25 points (the MCID from Horvath 2015). This is expected: total UPDRS-III includes items like speech, facial expression, and rigidity that simply cannot be measured by body-worn inertial sensors during gait.

### The observability gradient

The three-level observability decomposition is the paper's conceptual contribution. We classified each of the 18 UPDRS-III items into three tiers: directly observable from gait (items 3.9-3.14), partially observable (items 3.5-3.8 and 3.15-3.17, covering hand movements, pronation-supination, toe tapping, and postural tremor), and not observable (items 3.1-3.4 and 3.18, covering speech, facial expression, rigidity, and rest tremor).

Under 5-fold CV with ordinal ranking, the results are: directly observable CCC=0.834, not observable CCC=0.759, partially observable CCC=0.730. The gradient goes direct > not-observable > partially observable, which partially inverts the expected ordering. The paper explains this: not-observable items correlate with overall disease severity through shared pathophysiology (sicker patients tend to have worse speech AND worse gait), while partially observable items are limb-specific motor signs with higher inter-subject variability. The ranking transformation helps global severity prediction (which benefits not-observable items) more than it helps limb-specific prediction (which benefits partially observable items less).

Under the baseline (no ranking), the gradient is much starker and follows the expected ordering: directly observable CCC=0.545, not observable CCC=0.176, partially observable CCC=0.055. Ordinal ranking improves all three tiers dramatically.

### Cross-dataset comparison

Comparing to published SOTA is fraught because every study uses a different dataset, different sensors, different evaluation protocol, and different subject count. The most relevant comparisons are Hssayeni et al. 2021 (MAE=5.95, 24 PD patients, wrist+ankle, LOOCV) and Shuqair et al. 2024 (r=0.89, same 24 patients, self-supervised CNN-LSTM, LOOCV). Our LOOCV MAE on PD-only total UPDRS is 4.646 on 94 subjects with 13 sensors -- better numerically, but on a completely different dataset with far more sensors. The paper is careful to present these as cross-dataset observations rather than direct comparisons.

---

## Part 10: Lessons for Your Lab

### On using AI assistants

Start with one AI (Claude Code or equivalent) and learn to write an effective CLAUDE.md before adding more. The CLAUDE.md is the bottleneck -- a well-written one makes a mediocre AI effective; a poorly written one makes a brilliant AI useless. Include your objective, your data, your evaluation protocol, your hard rules, and what has already failed. Update it continuously.

Add a second AI (Codex, Gemini, or whatever is current) when you need an independent opinion. The most common situation is methodology design: "Is our evaluation protocol sound? Are there confounds we are missing? What sensitivity analyses should we run?" Different models have different training data and different blind spots. Synthesize, do not defer.

Never trust an AI citation. Verify every paper reference manually. We caught two hallucinated or mischaracterized citations in this project. The rule is: if you cannot find the paper on PubMed or the publisher's website and confirm the specific claim, do not cite it.

### On experiment management

Use JSON artifacts as the source of truth. Every experiment should output a structured JSON file with all metrics, sample sizes, seeds, and per-subject predictions. The paper should read from these files, never from hardcoded numbers. This eliminates transcription errors and makes the paper automatically updatable.

Log every experiment in an append-only file (TSV or CSV). Include both successes and failures. Record the decision (KEEP or DISCARD) and the reason. This log is your audit trail and your "What Failed" list.

Maintain a "What Failed (DO NOT RETRY)" section in your project documentation. This is as valuable as your results. A new student joining the lab should not spend two weeks re-trying approaches that have already been ruled out.

### On data splits

Create your test split once, at the beginning. Never look at it during development. Use cross-validation for everything. If you accidentally contaminate your test set, create a new split, re-run everything, and document the contamination. The honest numbers are always better for your career than inflated ones that do not replicate.

### On feature selection

Always perform feature selection inside cross-validation folds, not before splitting. This is easy to get wrong and hard to detect. The symptoms are suspiciously good cross-validation scores that do not replicate on held-out data.

### On metrics

For clinical regression, use CCC (Lin's concordance correlation coefficient) as your primary metric, not MAE and not Pearson r. MAE does not penalize prediction compression -- a model that predicts the mean for everyone can achieve decent MAE. Pearson r does not penalize miscalibration -- a model that predicts scores on a completely wrong scale can still achieve high r. CCC penalizes both. It is the metric that best captures "can this model distinguish mild from severe patients while getting the absolute scores right?"

### On the paper pipeline

Consider generating your paper programmatically from result artifacts. It requires a larger upfront investment (our generator is nearly 4,000 lines) but pays for itself in numerical accuracy, automatic updates, and the ability to run a consistency audit. Every number in the paper should trace to a specific field in a specific JSON file.

### On infrastructure

Keep the code on your local machine and the data + GPU on the remote. Mediate the relationship with a deployment script (our `gpu.sh`). Make the remote disposable -- you should be able to provision a new server from scratch in under an hour. Cache expensive computations (feature extraction, embeddings) and upload them to new servers.

### On honesty

The contamination incident made our paper better. We caught it ourselves, documented the recovery, and ended up with a cleaner evaluation protocol and more credible results. The reviewers appreciated the honesty. If you find a problem with your methodology, fixing it openly is always the right choice. The short-term pain of lower numbers is nothing compared to the long-term cost of a retraction.

---

## Epilogue

Three weeks, one researcher, three AI assistants, two GPU servers, 52 GB of sensor data, 50 experiment scripts, 101 result artifacts, a contamination scare, a breakthrough method, and a manuscript targeting Nature Digital Medicine. The numbers that survive honest evaluation -- CCC=0.865 on the observable subscore, a three-level observability gradient explaining why total UPDRS-III has a prediction ceiling from gait sensors, and a single-wrist finding that opens the door to clinical deployment -- are solid. Not because they are the highest ever reported, but because they are real.

The process described in this document is reproducible. The infrastructure is simple (a bash script and a remote GPU). The AI tooling is commercially available. The data is public. If your lab has a research question, a dataset, and the patience to write a good CLAUDE.md, you can do this too.

The key insight is not about any specific AI model or any specific method. It is about treating AI assistants as what they are: tireless but imperfect junior researchers who need clear instructions, strict guardrails, and constant verification. They will write 30,000 lines of Python for you. They will suggest the ordinal ranking method that becomes your paper's core contribution. They will also hallucinate citations, miss data leakage, and produce beautiful results that turn out to be contaminated. Your job is to direct, verify, and decide. Their job is to execute, iterate, and remember. Together, you can do the work of a small team in a fraction of the time.

---

*This document was written to transfer the methodology and lessons of the PD-IMU project to university research labs. All facts have been verified against the actual codebase, JSON artifacts, and experiment logs. The project code, cached results, and this document are available in the repository.*
