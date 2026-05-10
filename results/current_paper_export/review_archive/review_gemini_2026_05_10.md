MCP issues detected. Run /mcp list for status.**Reviewer Report**
**Journal:** *Nature Digital Medicine*
**Role:** Senior Movement-Disorders Reviewer
**Manuscript:** *Predicting Parkinson's Disease Motor Severity from Body-Worn Inertial Sensors: A Systematic Feature Engineering Approach on the WearGait-PD Dataset*

---

### General Comments

This manuscript presents a highly rigorous, methodologically transparent evaluation of predicting Parkinson’s disease motor severity (MDS-UPDRS Part III) using wearable inertial sensors. The authors establish a benchmark on the WearGait-PD dataset, moving beyond the optimistic estimates that currently plague the field of digital phenotyping. Most commendably, the authors meticulously document their internal auditing process, explicitly retracting their own prior transductively leaky pipelines and target-construction artifacts in favor of a strict-inductive, clinically grounded evaluation. The reframing of total UPDRS-III prediction as a "cautionary benchmark" rather than a deployment-ready system is a breath of fresh air in the digital medicine literature.

I have evaluated the manuscript across five specific domains:

### 1. Clinical Framing: The iter34 Candidate vs. iter12 Floor Distinction
The distinction between the `iter12-honest` canonical floor (CCC = 0.6550) and the `iter34` hybrid candidate (CCC = 0.7366) for the T1 axial-plus-truncal subscore is excellent. From a clinical perspective, it is entirely logical that incorporating auxiliary tremor signal (items 15 and 18) as multi-task regularizers biases the shared representation toward genuine severity without polluting the primary axial regression target. 

A neurologist would trust this presentation precisely because the authors *do not* blindly promote the higher `iter34` number as the new canonical baseline. By explicitly documenting the auxiliary-label caveats (e.g., the `NLS036` missing-code issue where right/left 9/9 codes were treated as severity in the auxiliary chain) and acknowledging the random-chain order exposure, the authors demonstrate deep respect for the clinical data generating process. Retaining `iter12-honest` as the reliable floor pending independent replication provides a mature, clinically trustworthy framing.

### 2. Related Work Fairness: Contextualizing Prior Benchmarks
The comparison with prior state-of-the-art benchmarks is handled with exceptional fairness and methodological clarity. The manuscript contextualizes the high correlations reported by Hssayeni et al. (r=0.74) and Shuqair et al. (r=0.89) by highlighting that those studies were constrained to N=24 LOOCV evaluations. As the authors correctly point out, LOOCV at N=24 yields 96% train-set overlap across folds, significantly elevating the risk of optimistic bias. 

By contrasting this with their own N=93–98 strict inductive evaluation across a much wider and heterogeneous severity spectrum (including mild cases), the authors successfully argue that their lower absolute performance metrics are a function of realistic cohort diversity and stringent evaluation gates, rather than inferior modeling. They respectfully delineate why their benchmark is a more reliable proxy for generalized clinical performance without disparaging the foundational contributions of prior small-N studies.

### 3. Limitations Honesty: Structural Walls and Transportability Cliffs
The limitations section is one of the strongest I have seen in a digital biomarker paper. 
*   **The Structural Wall:** The authors explicitly define the N≈94 sample size as a structural barrier, explaining why deep learning architectures underperform engineered features and why high-dimensional meta-stacks fail. The Pareto asymptote projection (0.5975) conclusively argues that more data alone will not break the ceiling without fundamentally new signal representations.
*   **The LOSO Transportability Cliff:** The manuscript is refreshingly blunt about the Leave-One-Site-Out (LOSO) transportability collapse. Openly displaying that T1 CCC drops from 0.7366 to 0.4564, and T3 drops from 0.3784 to a clinically unusable 0.150, inoculates the field against the illusion that internal LOOCV metrics equate to real-world deployment readiness.
*   **The Observability Ceiling:** The T3 oracle/Pareto bounds correctly identify that total UPDRS-III encompasses unobservable motor domains (rigidity, speech, facial expression). Acknowledging that gait IMUs are physically blind to these domains sets a necessary theoretical ceiling on predictive accuracy. 

### 4. Target-Construction Audit Narrative
The narrative detailing the `iter47` target-hygiene audit is the cornerstone of this paper’s scientific integrity. It is rare and commendable to see authors retract their own prior high watermark (CCC = 0.5227) because of upstream label-construction artifacts. 

The explanation is highly transparent: the authors reveal that standard data-handling practices (e.g., `skipna` summation) inadvertently converted all-missing item blocks into "zero severity" labels, and crucially, transformed clinical missing-data codes (the 9/9 on `NLS036` item 15) into an artificial 18-point severity inflation. Walking the reader through this invalid-code correction waterfall down to the true valid-range CCC of 0.3784 builds immense trust. It serves as a stark warning to the wider medical ML community about the silent dangers of automated label imputation in standard clinical datasets.

### 5. Scope of Transportability Claims: External Datasets
The authors display strict discipline in how they handle external datasets (FoG-STAR, COPS, TLVMC/DeFOG, PDFE). Rather than improperly blending these disparate datasets to artificially inflate internal WearGait-PD metrics, they correctly compartmentalize them as distinct transportability probes. By cleanly identifying them as Track A (zero-shot transfer) or Track B (clinical plus sensor transfer) analyses, the external data serves its proper function: highlighting the cross-protocol and cross-device generalization gap. This enforces the boundary that positive external sanity checks do not override the internal WearGait-PD headline, maintaining the purity of the primary benchmark.

### Conclusion
This paper is a landmark methodological contribution to the digital assessment of Parkinson's disease. By prioritizing auditability, target hygiene, and inductive strictness over inflated top-line metrics, the authors have provided a realistic, clinically honest roadmap for the field. I recommend acceptance. The manuscript sets a new standard for how digital phenotyping studies should report evaluation metrics and handle small-N tabular clinical data.
