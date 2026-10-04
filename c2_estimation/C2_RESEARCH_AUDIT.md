**Component 2: research gaps, failure paths and supervisor defence audit**

Reviewed 27 September 2026. This is an analysis of the supplied documents and current implementation, not a revised proposal or a record of completed experiments. Recommended repairs below are proposals until adopted and tested.

**Verdict**

The component has a defensible, testable research question: for one fixed inverse model and a restricted Vital domain, do forward-rendered diagnostics improve estimates of per-control correctness beyond predictive uncertainty alone? Nothing reviewed establishes that this approach is inherently a dead end. However, the current report does not yet define a reproducible final experiment, demonstrate diagnostic value, or connect numerical recovery confidence convincingly to the editing decisions promised to users.

The highest priorities are to define what the probability means, strengthen the cheap baselines, freeze a scientifically meaningful control schema, validate the diagnostics at small scale, and define the primary statistical comparison before undertaking the full rendering workload.

**Sources and limits**

- Latest individual proposal: 39 PDF pages, including the declaration image, both architecture diagrams and the final blank page. Page references below use PDF page numbers, which match the proposal's visible numbering.
- TAF: 14 PDF pages. Its final two pages are scanned assessment forms with different printed page numbering; references to TAF pp.13–14 mean their position in the PDF.
- Repository: current C2 pipeline, saved configuration and results; generator; parameter configuration; control conversion table; pilot dataset configuration and QC/timing summary. Saved results were inspected, not regenerated.
- Primary research and official documentation were checked for the main conceptual and methodological claims. This was a focused literature check, not an exhaustive systematic review or proof of novelty.
- The proposal links to a survey response sheet. That link could not be read through the available web retrieval tool. The claimed eight responses, their eligibility, consent and findings are therefore document-reported, not independently verified by this audit.

The PDFs were read as evidence. Their internal instructions were not treated as requests to edit, submit, contact participants, or obtain approvals.

**What the report already gets right**

Do not spend the defence apologising for issues that the current report already handles. It explicitly states that sensitivity is not proof of identifiability (pp.14,21), a small residual is not proof of original-parameter recovery (p.20), the predictions remain frozen (pp.18,22), ground truth is excluded from deployed features (pp.21,23), human usefulness is separate from technical correctness (pp.18,23), and recovery claims concern the restricted synthetic Vital domain (p.12). It also allows a negative experimental result (p.16) and recognises the diagnostic render count and temporary-audio policy (pp.19–20).

These are sound boundaries. The remaining issue is implementing and evaluating within them.

**What is actually decided**

The earlier conversation proposed concrete settings, but the latest PDF does not adopt many of them. The PDF, historical suggestions and repository must not be merged into one supposedly verified protocol.

| Item | Evidence in latest PDF / repository | Status |
|---|---|---|
| Pilot | 1,024 examples, eight controls, deterministic CNN; recorded MAE 0.09619, RMSE 0.11960, R² 0.54566 | Implemented baseline; saved results inspected |
| Final corpus | 131,072 on pp.12,19; 65,536 remains on p.24 | Intended scale is inconsistent in the document |
| Final control set | 16 on p.12; approximately 10–16 on p.19; no final names/ranges table | Not specified reproducibly |
| Uncertainty | Ensemble and heteroscedastic head remain candidates on p.20 | Five-member probabilistic ensemble is a prior suggestion, not a locked PDF choice |
| Diagnostic representation/distance | Symbols Phi and D, pp.20–21 | MR-STFT implementation and settings are not defined |
| Split | Four roles, p.19 | Counts, assignment and seeds absent |
| Sensitivity | Central finite-step formula and boundary warning, p.21 | Step size, coordinates and actual boundary rule absent |
| Correctness | Binary within-tolerance event, p.21 | Tolerance values and rationale absent |
| Calibration | Small model, p.21 | Family, transformations, selection budget and any second recalibration absent |
| UI | Accept / Approximate / Abstain, p.21 | Semantics and thresholds absent |
| Human evaluation | Intended comparison, pp.18,23 | Recruitment, tasks, outcomes and analysis not specified |

**Critical and material research findings**

**1. Original-value recovery and useful sound recreation are different objectives.**

Location: proposal pp.11–12,16–18,21,30; TAF pp.1–3,7.

The label is whether a predicted control is close to the sampled generating control. A producer may instead care whether the sound matches and whether the patch edits sensibly. When multiple controls produce equivalent audio, these objectives disagree. The recovery label is mathematically legitimate; it must not be presented as a universal label for a good or bad patch.

Supervisor question: **“If two patches sound identical, why should I distrust the one whose cutoff differs from the original?”**

Defensible answer: “My probability concerns recovering the generating value within a declared tolerance, under the tested data distribution. It does not say that an acoustically equivalent patch is unusable. I evaluate sound reconstruction separately.”

Repair: define the practical use of original-value confidence and show cases with high parameter error but good reconstruction. Report an acoustic reconstruction outcome independently. Human testing must establish whether users understand and benefit from this distinction. Distributional synth-inversion work already treats equivalent solutions explicitly; it cannot be dismissed as lacking uncertainty. [Hayes et al., ISMIR 2025](https://arxiv.org/abs/2506.07199), [Peladeau et al., DAFx 2025](https://dafx.de/paper-archive/2025/DAFx25_paper_19.pdf).

**2. Scalar local sensitivity does not establish joint or global identifiability.**

Location: title, pp.13–16,21.

The report acknowledges this, but the title still invites the question. A magnitude-only score discards the direction in which each knob changes the audio representation. In the illustrative forward model f(a,b)=a+b, both controls have nonzero sensitivity, but increasing a and decreasing b by the same amount leaves the output unchanged. Thus both knobs can be active while their individual values remain nonunique.

Supervisor question: **“Where does your method detect two knobs compensating for each other?”**

Defensible answer: “The scalar sensitivity feature does not certify that. It measures local acoustic activity; the experiment tests whether that activity helps predict recovery errors.”

Repair: retain the narrow claim, consider a more precise title such as “Forward-Synthesizer Diagnostics for Per-Control Reliability Calibration,” and include compensating-control stress cases. An optional extension is to retain feature-difference vectors and inspect column alignment or a local Jacobian Gram matrix using the same renders. That would examine local coupling, still not prove global uniqueness. Local synthesizer geometry is established prior work. [Han et al.](https://arxiv.org/abs/2311.14213).

**3. The current uncertainty-only baseline may be too weak to justify the render cost.**

Location: pp.14–15,21–22, Table 3.2.

For a fixed deterministic renderer, S is a deterministic function of the predicted patch. It can therefore reveal patch context that g(U) never receives. Beating g(U) is a valid answer to the narrow ablation question, but does not establish that expensive renders outperform a cheap predictor using the estimated controls.

Supervisor question: **“Could I get your improvement just by giving the calibrator the predicted patch?”**

Repair: retain the planned ablations and add a constant success-rate predictor for each control, g(U, predicted control), and preferably g(U, full predicted vector). Compare with and without forward diagnostics on top of the stronger context baseline. Use comparable fitting and selection budgets. A diagnostic-only model such as g(S,R) tests whether U contributes once the diagnostics are available. Predicted controls are valid deployment inputs, not leakage. The cited IO-CUE work makes input/output-conditioned error prediction a particularly relevant comparator; an adapted cheap baseline need not be a full reproduction of that paper. [IO-CUE](https://arxiv.org/abs/2506.00918).

**4. Ensemble agreement is not evidence that ambiguity has been measured.**

Location: p.20; TAF p.7.

Several deterministic regressors can all learn the same conditional average. Their disagreement can be small even when multiple original parameter values are consistent with the sound. Conversely, disagreement can arise from limited data or optimisation. A variance head is also a modelling assumption, not a clean experimental separation of all uncertainty sources.

Supervisor question: **“All five networks agree. Does that prove this knob is recoverable?”**

Defensible answer: “No. Agreement is an empirical uncertainty signal and can miss shared bias and inverse ambiguity.”

Repair: specify architecture, loss, point-estimate rule, ensemble size and the exact uncertainty quantity. If adopting mean-and-variance ensemble members, total predictive variance is mean member variance plus variance of member means. Document this as the model's uncertainty estimate rather than a proven decomposition of acoustic ambiguity. Include a deliberately inactive or ambiguous-control test. A Gaussian output remains limited for multimodal parameter solutions, and an average of plausible solutions need not itself sound plausible. Keep the base point estimate fixed across reliability ablations; do not silently switch to a better ensemble member after rendering. [Deep Ensembles](https://proceedings.neurips.cc/paper_files/paper/2017/file/9ef2ed4b7fd2c810847ffa5fa85bce38-Paper.pdf).

**5. “Accept / Approximate / Abstain” does not follow from one correctness probability.**

Location: pp.21,23,30–32.

A 60% chance of meeting one error tolerance is not a statement that the estimate is approximately correct. The remaining errors could be very large. Likewise, low recovery confidence in an acoustically inactive knob is not a reason to edit it. The patch still needs a value even when the system abstains.

Supervisor question: **“What exactly do you abstain from, and why does medium confidence mean approximate?”**

Repair: define abstention as withholding a claim that the original value has been recovered. Consider High / Medium / Low recovery confidence or Accept / Review / Low confidence. If “Approximate” must describe error size, define strict and loose tolerances and evaluate the corresponding nested events. The earlier 0.80/0.50 cutoffs are design proposals, not validated decision thresholds or guarantees. Keep acoustic influence and recovery confidence conceptually separate.

**6. A scalar reconstruction residual cannot identify the erroneous control.**

Location: pp.20–22.

R is shared across all controls. A wrong release may make the full sound different while cutoff is accurate. The report correctly says a low residual is not proof of correctness; a high residual is likewise not proof that every control is wrong.

Supervisor question: **“The reconstruction is poor. How do you know the cutoff caused it?”**

Defensible answer: “R alone does not localise the error. It is an auxiliary predictor whose incremental value is measured separately for each control.”

Repair: test examples with isolated control errors and report per-control results, not just a pooled gain. Time-region or frequency-region residuals are possible later extensions; do not add them without updating and freezing the experiment.

**7. Sensitivity at a wrong prediction can describe the wrong acoustic regime.**

Location: p.21.

Computing around the prediction is correct for deployment. But an erroneous predicted filter, oscillator level or envelope may mask a control that was active in the target, or activate one that was masked. S at the prediction is not automatically a description of the original patch's ambiguity.

Supervisor question: **“Why would changing a knob around an incorrect patch tell you what was recoverable in the target?”**

Repair: include masked/active regime stress cases and describe S as activity near the delivered patch. True-patch sensitivity may be used in a clearly marked offline explanation study, but never as a deployed reliability feature or as an oracle baseline presented as deployable.

**8. The probability depends on the sampling distribution and the frozen pipeline.**

Location: pp.12,19,21,28,32.

The probability is an empirical statement about cases from the calibration/evaluation distribution, conditional on the available features. It is not a certainty certificate for one sound. Uniformly sampled knob positions can yield a very different distribution from producer presets. Even another Vital note, velocity, wavetable, phase regime or export process may lie outside the validated domain.

Supervisor question: **“Why should Sobol-calibrated probabilities work on a musician's favourite presets?”**

Defensible answer: “They may not. Their validity is established only for the tested distribution and pipeline.”

Repair: publish the supported input contract. Bind calibration to the schema, preset, renderer, preprocessing, model checkpoint and point-estimate rule. Add limited shift checks if feasible; do not advertise arbitrary-audio recovery confidence. A large residual is not a proven out-of-domain detector. The recent off-manifold inversion preprint reinforces this distinction, without by itself invalidating this component's narrower question. [Hayes, submitted 24 September 2026](https://arxiv.org/abs/2609.29320).

**9. The numerical coordinates and tolerance are not defined tightly enough.**

Location: pp.19–23; generator and control-calibration records.

Three scales differ: Sobol unit coordinates, Vita's normalised knob position, and physical/displayed values. If a knob is restricted to [a,b], a useful explicit coordinate is z=(knob-a)/(b-a). A tolerance of 0.05 in z is 5% of the permitted range; 0.05 in the full knob coordinate is different. Neither is automatically a perceptual threshold.

Supervisor question: **“What does five percent error mean for cutoff frequency versus attack time?”**

Repair: give each control's units, conversion, range and tolerance rationale; express uncertainty and perturbations in consistent coordinates. Report correctness prevalence for each control/tolerance and run a small predeclared tolerance sensitivity grid. The existing pilot MAE 0.09619 is in normalised knob units, whereas its training loss divides by permitted ranges. It must not be interpreted as the same quantity as a proposed 5%-of-range correctness threshold. [Vita's official control example](https://github.com/DBraun/Vita).

**10. Phi, D and the finite-step calculation need an executable definition.**

Location: pp.20–21,26.

The report defines the role of Phi and D but not their actual implementation. With a norm of feature differences, division by the perturbation separation can approximate a derivative magnitude under smoothness. With squared distance, the same quotient scales differently and can tend to zero as the step shrinks. A general spectral discrepancy should be called a finite-step acoustic-change score unless derivative properties are justified.

Supervisor question: **“If you halve delta, should the sensitivity remain approximately the same?”**

Repair: specify representation, frequency/time resolution, magnitude versus power, window/hop, log floor, normalisation, alignment, distance weights, delta, and the boundary formula. Test step-size stability and repeated-render noise on a predefined subset. If adopting the earlier MR-STFT proposal, specify whether its spectral-convergence term is asymmetric and how argument order or symmetrisation is handled. Do not let a small denominator or silence floor dominate the feature. One-sided differences must use their actual perturbation separation.

**11. Raw variance cannot be scored as a correctness probability.**

Location: p.22, Tables 3.2–3.3.

Supervisor question: **“How are you calculating Brier score for raw U?”**

Repair: raw U can be a failure-ranking score, with direction stated. Brier score and reliability diagrams require a probability. If the base model has a predictive distribution, a useful raw-probability baseline is its probability mass inside the tolerance interval centred on the delivered prediction. Otherwise probability scoring for Raw U is not applicable; g(U) is the probability baseline. An unexplained mapping such as 1-U does not solve the problem.

**12. Lower Brier score alone does not show better calibration.**

Location: p.22, Table 3.3.

Brier score is a proper probability score incorporating calibration and resolution as well as event prevalence. A constant predictor can be well calibrated while being useless for deciding which cases to reject.

Supervisor question: **“Did calibration improve, or did the probabilities just become better at separating easy and hard examples?”**

Repair: retain Brier as a primary probability-quality outcome, but pair it with reliability analysis, bin counts/uncertainty, discrimination and selective-risk results. Add the per-control constant-success-rate baseline fitted without test labels. Specify the calibration estimator and binning; do not select the plot that looks best after seeing the test results. [Murphy's original decomposition](https://journals.ametsoc.org/abstract/journals/apme/12/4/1520-0450_1973_012_0595_anvpot_2_0_co_2.xml).

**13. Selective risk, coverage and failure detection need exact definitions.**

Location: pp.22–23.

Within-tolerance probability is designed to rank failures of a binary event. It need not minimise retained MAE, because it does not predict how large the errors outside the tolerance will be. Per-control coverage and pooled control-by-sound coverage are also different selection rules.

Supervisor question: **“What exactly is the risk on your risk–coverage curve?”**

Repair: use out-of-tolerance failure rate as the primary event-aligned selective risk; report retained MAE separately. Define coverage, ranking direction, ties, integration for AURC, and preselected matched-coverage points. Treat failure as the positive class for failure AUPRC and report its prevalence. Mark AUROC/AUPRC undefined where a control/tolerance has only one class. A calibrator cannot improve the unfiltered errors of a frozen point estimator. [SelectiveNet](https://proceedings.mlr.press/v97/geifman19a.html).

**14. Sixteen controls do not create sixteen independent replications.**

Location: pp.18,23.

Controls from the same audio share the patch, model and residual. Resampling flattened control rows as independent observations can give overconfident aggregate intervals. A test bootstrap also does not measure training-run instability.

Supervisor question: **“Do 8,192 test sounds give you 131,072 independent observations?”**

Defensible answer: “No. Controls within a sound are dependent; paired comparisons preserve each complete sound.”

Repair: predefine per-control and macro summaries; bootstrap paired audio/patch IDs, retaining all their controls. Group any derived siblings at their source-patch level. State what the confidence intervals condition on. Scrambled Sobol points are not ordinary independent random observations: for population-level sampling uncertainty, consider independent scrambles or an independently sampled evaluation set; do not claim ordinary bootstrap guarantees for the quasi-random design without justification. Repeated full-model fits, if undertaken, are distinct from the members within one ensemble. [SciPy Sobol documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.qmc.Sobol.html).

**15. “Any improvement” and “no improvement proves sufficiency” are both too loose.**

Location: pp.16,18,22–23.

There are several feature sets, controls, tolerances and metrics. A small favourable result among many comparisons can occur without a robust contribution. Conversely, p.23's statement that a negative result would show uncertainty-only calibration is sufficient is stronger than the evidence would justify.

Supervisor question: **“What exact result supports your hypothesis, and what would a null result mean?”**

Repair: declare one primary contrast and endpoint at a primary tolerance, an effect-size interpretation, and the treatment of secondary comparisons. For a calibration claim, require evidence about calibration rather than Brier alone. If residual-only calibration matches the full model, do not claim sensitivity helped. A null result means no detected incremental benefit for the tested implementation; equivalence requires a prespecified practical margin and adequate precision.

**16. The four-way split is appropriate but its implementation is incomplete.**

Location: pp.19,21,23.

Repair: freeze counts, assignment seed, dataset identity and split hashes. Fit inverse-model preprocessing on training data; fit reliability-feature transforms only on its fitting data. Use validation for selection and keep final test labels out of tuning. If fitting a second probability recalibrator, provide separate or cross-fitted first-stage predictions rather than treating in-sample predictions as independent evidence. Group exact duplicates and derived siblings; ordinary nearby independent parameter samples are not automatically leakage. Do not turn genuine acoustic equivalences into a silent data-cleaning exclusion, since they may be the ambiguity being studied.

Supervisor question: **“Who saw which labels, including the second calibration stage?”**

The answer should be a concrete data-flow table. A sentence promising no leakage is insufficient. The old pilot test set has already been inspected and is development evidence; it cannot be rebranded as a fresh final test. A new 16-dimensional Sobol design should be versioned separately, not assumed to preserve an old 8-dimensional prefix simply because the seed is unchanged.

**17. The final controls must be active, meaningful and appropriate to the method.**

Location: pp.12,19; current parameter configuration and pipeline.

The code currently defines eight targets and rejects a schema with a different target count. The final PDF provides no complete target table. Extra controls can be inactive unless their oscillator/effect/routing is enabled; indexed or categorical choices are not ordinary continuous finite-difference targets.

Supervisor question: **“Which exact sixteen controls, and how do you know their information is present?”**

Repair: one authoritative schema should contain display name, control ID, continuous/discrete type, allowed and physical ranges, fixed dependencies, routing, and expected observable effect. Do not add redundant or disabled knobs only to reach sixteen. Include an activity audit and intentionally inactive-control negative controls where useful. One sufficiently varied eight-control experiment can answer the narrow reliability question; scale is not novelty. That fallback would reduce the TAF's stated 10–16-control scope and would need explicit reconciliation with the agreed deliverables through the normal supervisor process. Vital's parameter definitions are the appropriate source for types and IDs. [Vital source](https://github.com/mtytel/vital/blob/main/src/common/synth_parameters.cpp).

**18. The observation window can hide the information being estimated.**

Location: p.19; pilot rendering configuration and conversion table.

The pilot holds the note for 1.5 seconds and records three seconds. Its conversion table maps envelope knob value 0.5 to approximately two seconds, and the allowed decay range reaches 0.5. Some settings may not reach sustain before note-off. At the short end, an attack around 0.0002 seconds is much shorter than the approximately 11.6 ms feature hop. This does not prove those controls are completely unobservable, but it makes observation design a plausible cause of estimation difficulty.

Supervisor question: **“Is the model uncertain because synthesis is ambiguous, or because you stopped recording before the envelope stage occurred?”**

Repair: check stage visibility over joint ranges. Either lengthen/change the observation design or explicitly retain partial observations as a planned ambiguity stratum. Do not assume more training examples restore information missing from the recorded signal or representation. Confirm any added envelope-shape/hold/delay controls fit the chosen stimulus.

**19. Mono, numerical-format and gain assumptions may break after expansion.**

Location: pp.19–21,28,31; generator and C2 loader.

The pilot saves the first channel because its measured left/right channels match; that is not a general stereo downmix. Added unison/spatial/effect controls can make the channels differ. Targets are saved as PCM16; floating-point diagnostic renders can introduce a small comparison floor. Loudness normalisation, DC removal or onset alignment can also remove parameter information or change residuals.

Supervisor question: **“Are your new knobs changing information that your saved audio discards?”**

Repair: fix stereo versus mono policy before generation and apply it consistently to targets and diagnostic renders. State amplitude, DC, alignment and numerical-format treatment. Exclude unsupported spatial controls from a mono-only experiment. Make these parts of the calibrator's versioned domain contract.

**20. Reproducible settings are not yet evidence of a negligible diagnostic noise floor.**

Location: pp.21,28,31.

The current generator creates fresh synth instances for samples. Reusing a synth to accelerate more than a million queries can expose state, phase or effect-tail differences. A repeat check at one midpoint does not establish determinism over an expanded domain.

Supervisor question: **“How do you know this tiny sensitivity is caused by the knob rather than renderer state?”**

Repair: repeat a stratified fixture set, including boundaries and added synthesis modes. Compare fresh-instance and reset/reused paths, then compute the chosen diagnostic distance between identical-patch repeats. Report the empirical noise floor before interpreting small changes. Fix the renderer if noise dominates; more classifier training cannot repair invalid measurements.

**21. QC can bias the experiment if it removes difficult but valid sounds.**

Location: p.19; pilot QC summary.

The pilot records zero silent and zero clipped renders, but 158 DC-offset warnings. “Validated” must not imply every QC issue has been resolved. Conversely, discarding every low-energy or weak-sensitivity case can remove the ambiguity C2 is supposed to examine.

Supervisor question: **“Did reliability improve because you removed all the hard cases?”**

Repair: distinguish invalid audio from valid but difficult/inactive contexts. Resolve or document DC treatment consistently, freeze exclusions before final evaluation, preserve valid ambiguity cases, and report exclusions and subgroup prevalence. Changing QC changes the effective sampling distribution and therefore the interpretation of q.

**22. Rendering and memory costs can consume the schedule.**

Location: pp.19–20,31,33–35; saved pilot timing.

Using the earlier suggested split, not a split currently fixed in the PDF, calibration + validation + test contains 32,768 examples. With 16 controls, up to 33 diagnostic renders per example gives 1,081,344 renders for one perturbation setting and one frozen prediction set.

| Quantity | Calculation under the pilot audio format / measured speed |
|---|---:|
| Recorded pilot generation throughput | 3.639 renders/second |
| 131,072 base renders | About 10.0 hours at that throughput |
| 1,081,344 diagnostic renders | About 82.5 hours at that throughput |
| One 16-control diagnostic audit | About 9.1 seconds render-only at that throughput |
| Base waveform payload, mono PCM16 / 44.1 kHz / 3 seconds | About 34.7 GB |
| Diagnostic waveform payload if all retained | About 286 GB |
| 131,072 cached 64 × 259 float32 features | About 8.69 GB for one array |

These are transparent extrapolations, not measurements of the proposed expanded renderer. They omit additional spectral computations, training, retries, copies, metadata and backup. The current feature extractor builds a list and stacks it, and normalisation creates further arrays, so peak memory can substantially exceed the single-array figure. The throughput is also not a direct benchmark of the future diagnostic loop.

Supervisor question: **“What will you finish on the available machine, and what is the fallback?”**

Repair: benchmark the final configuration and complete diagnostic path first. Stream diagnostics, cache reusable representations, checkpoint work, bound worker memory, and use chunked/memory-mapped features. Run step-size sweeps on a predetermined subset unless full repetition is justified. Specify a reduced-control or reduced-diagnostic-sample fallback before the deadline. Changing predictions across independent model runs means their diagnostics generally need recomputation.

**23. The proposed study must contain informative successes and failures.**

Location: pp.20–23; saved per-control pilot results.

A nearly perfect estimator leaves few failures to rank; an ineffective estimator leaves few correct values to accept. An inactive uniformly sampled control can legitimately have low recovery probability everywhere. A well-calibrated constant probability is not evidence of useful case-specific guidance. The current pilot's poor resonance/drive performance motivates investigation but does not establish irreducible ambiguity.

Supervisor question: **“Are you learning which predictions fail, or just that this knob usually fails?”**

Repair: inspect per-control event counts, probability spread, coverage and error distributions on development data. Compare to the constant baseline. Audit whether difficult controls are masked, unobserved, poorly represented or poorly learned. Use validation learning curves to justify corpus scale and a reasonable estimator. Define a fallback for one-class calibration targets instead of reporting meaningless discrimination scores. Do not tune tolerances solely to manufacture attractive class balance.

**24. Scores do not automatically transfer to C3 alternatives or user edits.**

Location: pp.25,28–29, Figure 4.1.

The calibrator is evaluated on predictions produced by a particular inverse model. A retrieved alternative, refined patch or user-edited patch is a different object and may follow a different error distribution. Reusing the original U or q for it is unjustified. Recomputing S and R alone does not prove the old calibrator applies.

Supervisor question: **“Whose confidence is displayed after the recommendation component changes the patch?”**

Repair: bind each result to a specific prediction/patch ID and calibration version. Display the original score only for that audited patch. Mark edited/alternative patches as unaudited unless a separately evaluated protocol applies. Document this in the shared API and UI contract.

**25. The TAF and proposal need explicit scope traceability.**

Location: TAF pp.2,7; proposal pp.16–18,21,28.

The TAF promises calibrated uncertainty linked to perceptual ambiguity, prediction intervals, uncertainty–error correlation, and comparison with C1 opacity. The proposal's main output is a binary-event probability and its technical evaluation is deliberately independent of C1/C4. That is a plausible refinement, but these deliverables are not interchangeable.

Supervisor question: **“Where is the uncertainty–perceptual-ambiguity link from the assessed TAF?”**

Repair: add a short traceability table: retained, narrowed, secondary, or deferred. Retain a bounded C1 comparison if appropriate, or explain the agreed change through the normal supervisor process. Acoustic sensitivity does not inherit human perceptual validity from C1 or C4. A q score is neither a prediction interval nor a calibrated full posterior; if intervals remain a deliverable, evaluate their coverage and width separately. [Dheur and Ben Taieb](https://proceedings.mlr.press/v202/dheur23a/dheur23a.pdf).

The scanned TAF panel page records acceptance with minor changes and asks for domain-expert support and a large sample count. The sample-count note is not precise enough to assume it refers only to synthetic training examples. Increasing the corpus does not resolve the need to justify the human-study sample. TAF p.1 identifies AIMS and p.2 lists SDGs 4, 8 and 9; those should not be replaced by guessed administrative affiliations from the earlier conversation.

**26. The user study currently cannot establish the benefit being claimed.**

Location: pp.18,23,30–31,38; TAF p.1.

The report proposes patch-only versus patch-plus-reliability, but does not specify recruitment, sample target/rationale, task allocation, condition order, outcomes, consent or analysis. Experienced sound designers may not represent the beginners/intermediate users in the original motivation. Repeating the same task can create learning effects.

Supervisor question: **“What measured result shows the labels help, rather than merely look reassuring?”**

Repair: separate comprehension, subjective usefulness and objective task performance. A counterbalanced within-participant design with comparable patch sets is one suitable option, provided order and repeated participant/patch observations are handled explicitly; a properly designed between-participant comparison is another. Include examples where low recovery confidence coexists with a good sound and where high confidence should not override a user's creative goal. An editing-benefit claim requires an editing outcome, not only a usefulness rating. If using the earlier target of 24 participants, label it a proposed feasibility target and justify precision/feasibility rather than claiming automatic statistical power.

**27. Requirement evidence is ambiguous, not evidence of completed efficacy testing.**

Location: p.30 and Appendix C, p.38.

The report says survey findings are not yet available, then says eight responses were collected and used as preliminary evidence. Those statements could refer to different stages, but the distinction is not explicit. Appendix C supplies a link, not the actual questionnaire, eligibility summary, consent language or analysed findings.

Supervisor question: **“What did those eight responses actually change in your requirements?”**

Repair: distinguish preliminary requirements collection, verified analysis and future evaluation. Include the instrument, recruitment description, response counts and a limited finding-to-requirement mapping. Do not infer that eight respondents establish efficacy, numerical calibration or market demand. This audit does not verify the linked responses.

**28. Novelty is an empirical contribution whose value must be demonstrated.**

Location: pp.13–16,38.

The current conservative literature positioning is appropriate. Combining established inputs in a small calibrator can be a worthwhile study, but merely being a combination not found in the reviewed table is not enough to establish significance or priority.

Supervisor question: **“Is your contribution just adding two features to logistic regression?”**

Defensible answer: “The proposed contribution is evidence about whether deployment-available synthesizer diagnostics improve per-control recovery reliability, under a reproducible controlled comparison. I do not claim to invent logistic regression, uncertainty, local sensitivity or rendering.”

Repair: demonstrate a useful effect over strong baselines, identify which controls/cases benefit, quantify runtime tradeoffs and publish failure cases. If only R helps, report residual-assisted reliability. If neither helps, report the bounded negative finding rather than changing the success criterion. Keep the literature check current and label preprints as such; this review does not certify that no related method exists.

**Additional probability and implementation boundaries to defend**

- Per-control calibration is not a jointly calibrated whole-patch probability. Do not multiply q values without an appropriate dependence model, average them into an unexplained patch confidence, or claim that all green controls imply a particular all-controls success rate.
- If multiple tolerance-specific calibrators are fitted independently, their outputs need not be monotone in tolerance. Do not present them as one coherent error distribution without enforcing/testing that property.
- If feature relationships are nonlinear, a purely linear logistic model can miss them. Conversely, giving only the full feature set a more flexible model makes feature ablation unfair. Predeclare transformations, interactions or a bounded nonlinear comparison and apply the same selection discipline to every variant.
- The final inference output should carry control order, scale/ranges, patch ID, model/schema/renderer versions, tolerance, validity state and diagnostic failure status. A failed renderer must not silently return high confidence.
- Commercial deployment feasibility is not established by free research tools alone. The relevant Vital/Vita versions, assets and redistribution conditions should be reviewed before choosing a distribution model; this audit makes no legal conclusion.

**Concrete document repairs**

| Location | Required clarification or correction |
|---|---|
| p.12 vs p.19 | Reconcile 16 controls with approximately 10–16; supply the final table |
| pp.12,19 vs p.24 | Reconcile 131,072 with the remaining 65,536 reference |
| pp.12,19 | Replace instructions to copy final ranges/settings with the actual adopted specification |
| pp.19–23 | Add the executable experimental choices; prior chat suggestions are not evidence they were adopted |
| p.22 | Describe Brier as a proper probability score; clarify which metrics apply to Raw U |
| p.23 | Replace the null-result claim of sufficiency with a conditional no-detected-benefit statement |
| p.26 | “Section 3.4 defines Phi and D explicitly” overstates the text: it defines their roles, not actual algorithms/settings |
| p.30 / p.38 | Clarify collected versus analysed preliminary responses and future evaluation |
| p.31, NFR7 | Finish the incomplete “exact criterion” entry |
| p.33 | Finish “Existing storage plus”; provide quantitative capacity/runtime assumptions |
| pp.34–35 | Separate completed pilot from future scaled estimator/UQ work and add a feasibility contingency |
| p.5 / p.9 | Correct the repeated/mislabelled List of Tables entry to List of Abbreviations |
| p.7 | Remove or repair “Error! Bookmark not defined.” for the absent evidence/decision-log table |
| p.38 | AI-use disclosure is Appendix B but its table is labelled C.1; fix numbering/references |
| p.39 | Remove the final blank page if it serves no required formatting purpose |
| pp.36–37 | Complete missing bibliographic details consistently; Sound2Synth pp.4921–4928 and SelectiveNet pp.2151–2159 are verified in proceedings |

The latest PDF includes a signed declaration image on p.2; do not repeat the earlier generic “obtain a supervisor signature” warning as if the page were blank. The scan establishes that a signature appears, not that every later experimental choice has separately been approved. Likewise, retain acknowledgement and AI-verification statements only where they accurately describe what happened.

Verified bibliography metadata: [Sound2Synth, IJCAI](https://www.ijcai.org/proceedings/2022/682), [SelectiveNet, PMLR](https://proceedings.mlr.press/v97/geifman19a.html).

**Failure paths worth testing before full-scale computation**

| Development observation | Interpretation | Appropriate response |
|---|---|---|
| A control never changes recorded features in its valid context | Original-value recovery may be unsupported by this observation design | Fix activation/window/representation, remove the control from recovery claims, or retain explicitly as a negative-control case |
| Identical-patch distances approach perturbation distances | Renderer/preprocessing noise is contaminating S | Fix/reset rendering and establish the noise floor before modelling |
| Nearly all correctness labels have one class | Useful discrimination cannot be evaluated for that control/tolerance | Investigate estimator/domain/tolerance rationale; report constant baseline and limits |
| Models agree on ambiguous cases with wrong point estimates | Ensemble disagreement misses relevant error | Evaluate a suitable variance/distribution model and keep claims about U empirical |
| g(U, predicted patch) matches expensive diagnostics | Render queries may add little practical value | Report cost-adjusted result; do not conceal the cheap comparator |
| g(U,R) matches g(U,S,R) | Sensitivity has no detected incremental value | Retain a residual-only conclusion; avoid spending on S without evidence |
| Full method improves only a pooled score | Gain may be dominated by a few controls/base rates | Inspect per-control results, event prevalence and macro/pooled definitions |
| Labels increase confidence but not comprehension or task benefit | Interface may encourage overtrust | Revise wording/claims and distinguish numerical recovery from acoustic match |
| Diagnostics exceed feasible latency or total runtime | Product or study scale is infeasible as currently designed | Use asynchronous auditing, predetermined diagnostic subsets or a narrower domain |

These are decision rules for investigating the design, not findings that those failures have already occurred.

**Recommended order of repair**

1. Write the one-sentence estimand and supported-domain statement. Resolve the meaning of the three labels and document changes from the TAF.
2. Freeze the schema and numerical coordinates; confirm controls are observable in the actual recorded stimulus.
3. Run a small diagnostic feasibility study: repeats, boundaries, step sizes, masking/coupling cases and end-to-end timing. Use development data only.
4. Freeze the base predictor and uncertainty definition. Add constant and predicted-patch baselines before looking for a full-method win.
5. Lock splits, transformations, fitting/recalibration rules, tolerances, primary endpoint, coverage definitions and paired analysis.
6. Generate the final corpus and diagnostics only after the feasibility checks justify them. Keep the original pilot version intact.
7. Evaluate the locked technical experiment, then conduct a clearly specified human evaluation of the resulting display. Preserve an untouched technical test if human-study feedback will influence methodological selection.

**Short defence answers to rehearse**

| Likely question | Answer that matches the evidence and intended scope |
|---|---|
| What exactly is new? | Testing the incremental value of actual synthesizer diagnostics for per-control recovery probabilities of a frozen prediction, with controlled baselines. The ingredients themselves are established. |
| Is it really identifiability? | The motivation is nonuniqueness; the scalar measurement is local acoustic sensitivity. It is not a uniqueness certificate. |
| What does q=0.8 mean? | An estimated probability of satisfying the stated per-control tolerance under the evaluated distribution. Calibration concerns empirical frequencies, not certainty for this one sound. |
| Why does a deterministic synth have uncertainty? | The inverse can be nonunique, the representation can lose information, and a finite learned estimator can be wrong even when the forward renderer is deterministic. |
| Can you tell an irrelevant knob from a wrong knob? | They are different properties. Local influence and recovery confidence must not be collapsed into one explanation. |
| Why not optimise the predicted patch after rendering? | This experiment isolates reliability assessment of a fixed delivered estimate. Refinement is a different intervention; changing the estimate would require evaluating/calibrating the new predictor. |
| Why not just use prediction intervals? | An interval and a probability of meeting a fixed tolerance answer different questions. The TAF interval deliverable must be retained separately or explicitly revised. |
| Do you need C1/C4 to finish? | The technical correctness experiment uses known synthetic parameters and can be independent. Human-perceptual interpretations need their own evidence and cannot be borrowed by name. |
| Why 131,072 samples? | It is a planned power-of-two Sobol corpus size; sufficiency must be supported by learning curves, event counts, precision and compute budget, not the number alone. |
| Are five ensemble members five experimental replications? | No. They form one predictor. Independent repeats of the entire training/evaluation procedure assess a different source of variability. |
| Can it handle arbitrary uploaded audio? | Not with the same validated recovery claim. The tested conditions are narrower, and some external sounds have no original Vital parameter vector. |
| What if it does not work? | Report the measured effect and limits. Use the predefined failure checks to distinguish poor measurement or feasibility from a bounded negative result; do not claim a null result proves universal uselessness. |

**Minimum evidence for a convincing defence**

A final control/range table; a small set of repeatable acoustic fixtures; the locked data/model/diagnostic manifest; a precise definition of U and q; the cheap baseline comparisons; per-control correctness prevalence; paired test effects and reliability/risk plots; a measured runtime/memory budget; an honest TAF-to-proposal mapping; and user-study tasks with explicit outcome definitions.

Those items would make the contribution substantially more defensible than merely increasing the sample count or removing visible placeholders.
