# Product Positioning

*(Formerly `docs/SIH_Pitch.md` — this project started as a Smart India Hackathon 2026 submission (problem statement SIH26192) but is no longer being developed or presented as one; this doc was rewritten to drop that framing while keeping the underlying positioning, competitive analysis, and stakeholder Q&A, which are still genuinely useful for anyone evaluating the product on its own merits.)*

## One-line positioning

**Girivarsha is a hyper-local last-mile disaster intelligence layer** — it takes regional forecasting and satellite data that already exists and turns it into village-level, explainable, actionable warnings for the hilly settlements that existing systems can't resolve down to.

We are not building a weather dashboard, not claiming to replace IMD/CWC/NDMA/ISRO, and not reducing the problem to a single "flood / no flood" number.

## Why existing systems leave a gap

| System | What it does well | Where the gap is for a hill village |
|---|---|---|
| IMD South Asia Flash Flood Guidance | Regional flash-flood guidance | Not village/ward-resolution, not terrain-aware at micro-catchment scale |
| CWC flood forecasting | River-stage forecasting on major rivers | Sparse coverage on small hill streams/nullahs |
| C-FLOOD | Flood forecasting | Regional/river-basin scale, not last-mile |
| NDMA SACHET | Common alerting, multi-agency dissemination | A dissemination platform, not a hyper-local prediction/explanation engine |
| ISRO/NRSC/NDEM, GSI landslide systems | Authoritative terrain/hazard mapping | Static/periodic hazard maps, not a real-time fused risk score with lead time |
| Google Flood Hub | River flood forecasting at global scale | River-basin scale; not micro-catchment, not IoT-fused, not evacuation-routed |

**Our claim is narrow and defensible:** existing regional intelligence, fused with local terrain and IoT observations, can be turned into village-level actionable decisions — with explicit hazard/exposure/vulnerability/action separation, confidence estimation, sensor-failure fallback, and evacuation routing. That fusion + last-mile layer is the product, not a new national forecasting system.

## The five things worth remembering about this system

1. **Micro-catchment-aware, not per-village-independent.** A village downstream of a fast-changing upstream catchment gets different risk than one outside that flow path.
2. **Hybrid risk engine.** A transparent, auditable weighted baseline always runs; an ML layer (XGBoost/Random Forest) adds power where labelled data supports it — never black-box-only.
3. **Confidence is a first-class output**, not an afterthought — every risk score ships with a confidence % and visible sensor health, and degrades gracefully (never silently) when a source fails.
4. **Explainable by construction.** "Why is this village at risk?" is a real feature backed by feature importance/SHAP, with a technical view for authorities and a plain view for citizens.
5. **Ends in a decision, not a number.** Affected villages, evacuation priority, safe routes, nearest shelters — decision support for authorized personnel, never an autonomous evacuation order.

## Walkthrough script (target: under 5 minutes)

1. Normal state — map shows pilot villages, all green.
2. Rainfall rises (What-If Simulator or live IoT).
3. Soil moisture rises (IoT/simulated).
4. Upstream water level rises → risk recalculates.
5. Risk crosses into ORANGE.
6. Risk crosses into RED.
7. Lead-time estimate appears (labelled as a prototype metric).
8. Click **"Why is this village at risk?"** — explanation panel.
9. Click into evacuation view — priority, shelter, route.
10. Disable a sensor live — watch confidence drop, fallback source kick in.
11. Run **Historical Event Replay** for a past scenario.
12. Close on the differentiation table (above) and the limitations doc — stating your own limitations plainly, unprompted, builds more trust than omitting them.

## Stakeholder Q&A

**"How is this different from IMD?"**
IMD (and GFS/GPM) is one of our *inputs*, not a competitor — we consume regional rainfall products and add terrain-aware, catchment-scale, IoT-corrected local risk estimation with explainability and evacuation routing on top, at a resolution IMD's public products don't target.

**"How is this different from C-FLOOD?"**
C-FLOOD operates at river-basin/regional scale. We operate at micro-catchment/village scale, fusing local IoT and terrain data that a national river-forecasting system isn't designed to ingest.

**"Where did your data come from?"**
Every reading is tagged `real`, `simulated`, or `derived` end to end (see `docs/Data_Sources.md`). We name exactly which parts are real public data, which are simulated for the pilot demo, and never blur the two.

**"How do you handle missing sensors?"**
A documented fallback hierarchy: local sensor → satellite/regional estimate → antecedent-rainfall proxy → reduced confidence, always shown explicitly on the dashboard (see `docs/Architecture.md`, "Sensor-failure / fallback hierarchy"). As of the real-regional-data fallback follow-up, `GET /sensors` itself now surfaces a real Open-Meteo regional estimate — clearly labelled, never conflated with a live device reading — when a sensor has no reading of its own, rather than showing nothing.

**"How do you validate the model?"**
Temporal train/test splitting, cross-validation where appropriate, and reporting precision/recall/F1/ROC-AUC/false-alarm rate — not accuracy alone, because dangerous events are rare. If there isn't enough labelled historical event data for a statistically defensible model, we say so explicitly and treat the ML layer as a research/prototype component rather than an operational one (see `docs/ML_Methodology.md`).

**"What happens if there are false alarms?"**
Thresholds are configurable, not hard-coded, specifically so they can be tuned against observed false-alarm/false-negative rates during a pilot rather than locked in at build time.

**"How do you estimate lead time?"**
A transparent prototype estimator from upstream distance, catchment/flow characteristics, and water-level change — explicitly labelled as an estimated prototype metric, not an operational guarantee (see `docs/Architecture.md`).

**"Can this scale?"**
The pilot is deliberately one small Uttarakhand valley (5-10 villages, since extended to a second pilot valley — see `docs/Future_Work.md`'s Chamoli sensor network entry) so the architecture — adapter-pattern data sources, catchment-based modelling, modular pipeline — can be validated before extending to more districts/states, rather than claiming national coverage up front.

**"What is the biggest current limitation?"**
Sparse historical event labels for Himalayan flash floods/landslides, and reliance on simulated IoT streams outside the live-demo sensors (now partly mitigated by the real-regional-data fallback — see above). Both are stated plainly in `docs/Limitations.md`, along with what closes each gap.

**"Would the government actually be able to deploy this?"**
Not as-is — it needs field calibration, longer-term validation, data-sharing agreements with the agencies whose data it consumes, and sign-off from disaster-management authorities. It's built to be the kind of prototype that makes that next step credible, not to claim it's already there.
