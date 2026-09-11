# Learning Log

The daily improvement loop. After each apply round, Sid says how the list quality was and what was wrong. Each correction becomes a standing lesson that the shortlist (Step 2) reads BEFORE scoring, so the system gets more accurate every day.

## Standing lessons (active - applied every run)
- Domain scope is ALL industries where quality/process skills fit, not aerospace only. Rank by sponsorship odds + skills fit. (Set 2026-06-17.)
- Visa is a hard gate: ITAR / US-person / citizenship / clearance / "no sponsorship" -> drop. Read the JD, do not infer. (2026-06-17.)
- Demote staffing-agency reposts (Actalent, Insight Global, DSJ, Addison, MOHR, etc.) - hidden employer, often no sponsorship signal, frequent duplicates. (2026-06-17.)
- Freshness is a HARD 3-day cap (24h preferred) for LinkedIn/Apify rows; anything older is gated at fetch. ATS rows (`source: ats:*`) are exempt (listed = open; 7-day window) per `P1_06 §3.7` exception. Replaces the old 30-day rule. (Set 2026-06-18 per Sid; source wiring for the retired Indeed/ZipRecruiter/Dice connectors removed 2026-07-14 — Apify + free ATS are the only sources now.)
- Pull the full JD for every serious candidate before a final Keep (Indeed get_job_details / board description). Title-only scoring is provisional. (2026-06-17.)
- LinkedIn/board `seniorityLevel` and clean metadata are unreliable for BOTH visa and seniority - confirm against JD text. Aerospace/defense COMPOSITE and SEALING suppliers (Albany Engineered Composites, Trelleborg, Hexcel, Spirit, fuel-nozzle JVs, etc.) are ITAR/US-person at a high base rate; treat as VISA RISK until the JD explicitly clears them. (Set 2026-06-23 after Albany QE I (81) and Trelleborg x2 were caught US-person-only at JD pull.)
- ORBITAL LAUNCH / SPACE VEHICLE manufacturers (Relativity, Vast, SpaceX, Rocket Lab, etc.) are inherently ITAR/USML-controlled even when the JD omits an explicit US-person clause -> default Skip per profile. Vast states it outright ("items subject to U.S. export control"); Relativity omits it in-text but the product gates it anyway. (Set 2026-07-01 after the Day-1 space-board pull.)
- NEVER write the specific target company name or explicit role-pinning phrasing anywhere in the resume. Keep the common, natural phrasing targeting the broader industry/discipline. (Set 2026-08-13 per Sid; broadened from \section{Summary} to document-wide on 2026-08-18, when the Summary section was deleted from all base tracks — it read as AI-generated and kept overrunning its line budget.)
- Do NOT add bloated/AI-generated-sounding skills (e.g. "quality metrics and reporting", "audit readiness", "internal quality audits") unless explicitly backed by experience; shorten "standard operating procedures" to "SOPs". Keep skills grounded, concise, and authentic. (Set 2026-08-13 per Sid.)
- DEDUPLICATION MUST BE TWO-TIERED & ROOT-NORMALIZED: Never rely solely on exact URL match. Match against both normalized company+title signatures (stripping legal suffixes LLC/Inc/Corp/Healthcare/Dimatix and level/shift qualifiers like I/II/E1/1st/2nd/3rd Shift) AND the live Supabase `applications` database. Both Fetch and Rank must hard-drop previously applied roles even if reposted under fresh URLs. (Set 2026-09-03 per Sid after Cummins, AMAT, and FUJIFILM duplicates were caught).
- INTERNATIONAL POSTINGS MUST BE ENGLISH & SPONSORABLE: In Pass 4, postings written in non-English languages (Dutch, German, French, Italian, Spanish, etc.), or requiring native/fluent local language or local residency/citizenship only ("residents only", "woonachtig in"), are hard-gated out. Drop local European staffing agencies (e.g. Madison Recruitment, Jobster, Trio Personalmanagement) that do not sponsor international work permits. (Set 2026-09-03 per Sid after Madison Recruitment Belgium drop).

## Daily entries

### 2026-07-20 (Day — 3-track Daily Run + resume batch)
- Fetch: free ATS (59 rows, 11 portals) + Apify T1 ($0.20 cap, Tesla/Micron/AMAT/Intel/KLA — surfaced Samsung/Lam/Micron/SambaNova/Semtech, not the pinned 5 companies directly; LinkedIn quoted-company search still drifts to a broader semiconductor feed) + T2 ($0.10 cap, Joby/AST — 0 results both companies) + T3 ($0.15 cap, open QMS keyword — 20 rows). Total Apify spend ≤$0.45/$0.50.
- Key finding: **all 3 fresh Robert Bosch postings pulled today carry an explicit no-sponsorship clause** ("Indefinite U.S. work authorized individuals only"), upgrading the 2026-07-06 CAUTION/mixed intel to a SKIP. SmartRecruiters' public read API (`api.smartrecruiters.com/v1/companies/{co}/postings/{id}`) and Workday's CXS job-detail endpoint (`POST .../wday/cxs/{tenant}/{site}/job/{path}`) both return full JD JSON without a browser — useful for ATS-row JD pulls that `ats_scan.mjs` doesn't fetch (title/location only). Recommend wiring one of these into a lightweight ATS JD-pull helper next time an ATS survivor needs gating, rather than relying on WebFetch/rag-browser (both failed against Workday's JS-rendered page).
- Scoring: 18 visa-clean survivors scored, only 1 cleared 80 (Micron NCG Process Integration, 89) — a single-referral day is a valid outcome per the rubric, not a sourcing failure.
- Sid dropped 6 direct-apply picks at Gate A after reading the scored table (Enovis, Samsung CMP, TeDan, Elbit, Covestro, Infosoft) — kept 11 direct-apply + skipped networking on the Micron referral since a 6-month referral (Sushant Mahat) is already on file for that contact, so Sid reaches out directly instead of running Finder/Drafter again.
- Built and compiled 12 tailored one-page resumes inline (guardrail #8): Track1 x5 (Micron, Samsung, SambaNova, BorgWarner, Semtech), Track2 x1 (Beta Technologies), Track3 x6 (ISCHEBECK, ELYON, Form Energy, OMEC Medical, RBC Bearings, Creation Technologies).
- Flagged but not gated (Sid's call preserved via CAUTION notes in Lane2_Tracker.md): OMEC Medical NV JD is actually a senior FDA-RA-ownership role (510(k) submissions, ISO 13485/14971, 4-7yr) once the full JD was read — the Dom=10/medical-device score didn't capture how thin the real skills overlap is. Worth a scoring-rubric note: T3 medical-device rows should get a second look at RA-specific language, not just device/QMS keyword density.
- Files changed: seen_jobs.csv (+65 rows), Lane2_Tracker.md (+12 rows, ja-07-58..69), company_intel.md (Bosch SKIP upgrade), 12 new resume .tex/.pdf pairs in `Job_Applications_Resumes/2026-07-20/`.

### 2026-07-14 (audit — loop restart)
- The end-of-day learning loop lapsed after 2026-07-01. Runs on Jul 2, Jul 6, and the Jul 13 hand-sourced session were recorded in `daily_log/`, `daily_run/`, and `Lane2_Tracker.md` but never distilled into a standing lesson here. The audit (AUDIT_REPORT_A_2026-07-14.md, A-015) flagged this.
- Lesson: DAILY_RUN Step 9's closing question is not optional — every run, ad-hoc included, ends with one line here. The loop is the point.
- Files changed this session (audit fix batch): P1_06 (freshness exception §3.7 + overrides §3.1 + sponsor-band note), P1_04/portals.json (intel-SKIP annotations on GM/Cat/Eaton), P1_05 (rewritten to the feed-JSON contract), profile.md/README.md (current reality + store map), seen_jobs.csv (Jul-13 backfill + status normalize), and the base resume toolchain (fullpage → inline margins).

### 2026-06-23 (Day 3 - Tue run)
- Fetch: free (Indeed native all stale -> gated; ZipRecruiter ~6 viable) + Greenhouse 8 slugs (0 fresh entry-level Keeps; all Sr/Mgr/ITAR or >3d) + Apify LinkedIn (100 fresh @ ~$0.10). Weekly Apify spend ~$0.10/$5.
- Visa catches from JD pull (key value-add): Albany International (AEC, Salt Lake City) scored 81 but JD = "DoD Contractor ... US Persons ... Visa sponsorship is not being offered" -> gated. Trelleborg Sealing (Fort Wayne + El Segundo) = ITAR US-person -> gated. Phillips Medisize + Advanced Atomization also US-person/no-sponsorship. All logged to company_intel.md.
- Seniority catches: Toshiba Mfg Eng and Integer Mfg Process Eng both require 5+ yrs in JD despite "Associate"/unlabeled metadata -> dropped.
- Lesson reinforced: LinkedIn `seniorityLevel` and clean metadata are NOT reliable for visa OR seniority - the JD is the only source of truth. Pull JD before any final Keep, especially for aerospace-composites suppliers (high ITAR base rate) and "Associate"-tagged roles.
- New standing lesson added below: treat aerospace/defense composite & sealing SUPPLIERS as ITAR-likely until JD clears them.
- Net Keeps after gating: 10 visa-clean, then a 2nd Apify pull (broad keywords) added 4 more (Penumbra, Standard Motor Products, Avery Dennison, Zimmer Biomet) for 14 total. The broad "Manufacturing Engineer" keyword surfaced many explicit no-sponsorship roles (Daikin, Stanley Black & Decker) and US-person export roles (Microchip) - JD gate caught them all.
- Quality rating (Sid): Good, minor notes (no specific correction given). Applied to 12/14; Tesla held for referral (not applied); CNH Plant Quality Engineer left shortlisted (not applied). Networking handoff skipped per Sid.
- Files changed: company_intel.md (5 new rows), seen_jobs.csv (19 new rows + status updates: 14 applied / 17 shortlisted / 5 visa-itar / 2 seniority dropped), learning_log.md.

### 2026-06-18 (Day 2)
- Quality rating (Sid): freshness was wrong - shortlist surfaced roles a month old.
- What was wrong: Greenhouse boards only expose `updated_at`, and the rubric's 30-day stale gate let April/May roles (Beta May cluster, Brose Jun 04, GM May 07) into the recommended Keeps.
- Lessons derived: HARD 3-day freshness cap (24h preferred); filter at the source for every connector; gate >3 days everywhere. See updated standing lesson above.
- Other findings to fold into intel/targets (pending Sid's OK): (1) Archer Aviation currently NOT sponsoring - every open req says "unable to provide work visa sponsorship"; target doc lists STRONG, downgrade to FLAG. (2) Re:Build Manufacturing composites/quality roles are export-controlled (US citizen/PR) - was MODERATE, downgrade to FLAG. (3) LG Electronics / LG Magna e-Powertrain "will not sponsor applicants for work visa". (4) Vast US-person export bar confirmed (already FLAG).
- Files changed: P1_06_scoring_rubric.md (gate #7 + recency axis), profile.md (run settings), P1_01_workflow.md (fetch freshness + source wiring), learning_log.md.

### 2026-06-17 (Day 1)
- Feedback from Sid during the run (not a formal end-of-day review yet):
  - Donaldson -> not hiring OPT (contact). Logged in `company_intel.md` (SKIP).
  - GE Vernova Wilmington roles -> ITAR. Logged (CAUTION, verify per role). Note: Aero Alliance JV is separate and civil - keep.
  - Young & Franklin Tactair -> US-person only in practice despite softer board wording. Logged (SKIP). Lesson: trust Sid's insider read over JD boilerplate.
  - Open keyword search returned ~50% off-domain noise. Lesson: use structured filters (industry / experience level / function) and the rubric's staffing demotion. -> rubric + fetch updated.
  - Postings felt many days old. -> freshness lesson above.
- Files changed: company_intel.md, P1_06_scoring_rubric.md, P1_01_workflow.md, profile.md.

<!-- Template for future days:
### YYYY-MM-DD (Day N)
- Quality rating (Sid): {great / ok / poor}
- What was wrong: {Sid's words}
- Lessons derived: {concrete rule}
- Files changed: {company_intel.md / P1_06_scoring_rubric.md / fetch keywords / etc.}
-->

### 2026-07-01 (Day 1 - new cockpit+agent system)
- First run of the referral-first system. Plugin (Networking Agent v0.8.0) blended: DB migrated v4->v9 (old dev DB backed up), preflight green, Serper 100 / Apify 40 free quota live.
- Fetch: ZipRecruiter free (5-result cap -> thin, mostly staffing/technician/1 defense prime) + Greenhouse free public API x8 boards (67 fresh matches, concentrated at space cos Relativity + Vast).
- Gating: Vast SQE + Mfg-Structures = explicit export-control -> VISA RISK. Relativity Mfg Eng II (all) = orbital launch inherent ITAR -> Skip. New standing lesson added (space/launch ITAR).
- Scoring: 0 roles cleared the 85 gate. Top visa-clear = Beta CMM Programmer ~73 (Good). June's best legit roles were 81-82; 85 may be too strict + fresh-only + ITAR gating = frequent zero-target days. DECISION PENDING: gate 85 vs 80 (recommend 80) + broaden sourcing (fix Joby/Archer GH slugs, add Indeed-native + LinkedIn-Apify).
- Engine validation: ran Finder on Beta (real Serper), 6 contacts saved, 2 Serper/1 Apify spent. Discovery precision noisy (1 contact actually at Lockheed, 1 garbage title, 2 Canadian) -> reconfirms roadmap's "Finder unaudited" gap; human selection gate is the filter. Pipeline mechanics sound end-to-end.
- Full day record: daily_log/2026-07-01.md.
- CORRECTION (same day): initial pass used only free sources (ZipRecruiter 5-cap + Greenhouse free API) and wrongly concluded "0 >=85". Sid flagged Apify is the PRIMARY scraper. Fired curious_coder/linkedin-jobs-scraper (95 fresh roles, ~$0.006) -> real shortlist: Beta SQE 90, Copeland SQE Assoc 87 (OPT-positive), Magna QE 81, Joby Composite Production Eng 80. Airbus + Rolls-Royce gated (JD "does not/unable to sponsor"). LESSON: fire Apify LinkedIn scraper FIRST every run; free connectors are supplements, not the source.
- Networking-pipeline lesson: the Apify job record's `jobPosterName`/`jobPosterProfileUrl` is the recruiter/HM who posted the req (e.g. Beta SQE -> Alice Clifford, TA) = a VERIFIED correct-company contact. Use it as the primary referral seed. The agent's Serper discovery is noisy (Copeland -> 6 surname "Copeland" namesakes at other companies, 0 at the company; Beta -> 1 contact actually at Lockheed). Feed job-posters via /network-import; treat Serper discovery as supplement + always run the human selection gate.

<!-- DROP-REVIEWS:START -->
## Dropped-application reviews (auto-synced from the tracker)
_Sid's own reason for each drop, pulled from the Pipeline note field in the tracker. Read before scoring like any standing lesson; promote recurring patterns into a standing lesson above, then the drop can be forgotten. Regenerated by refresh.py every run — edit notes in the tracker, not here._

- **John Holland — Quality Engineer** (`ja-0908-06`, found 2026-09-08): [Broad-Fit Direct Apply] 45-Day Sprint — Resume resume_John_Holland_Quality_Engineer compiled.
- **CMC — Rolling Mill Process Engineer** (`ja-0908-11`, found 2026-09-08): [Curated Target Lane] 45-Day Sprint — Resume resume_CMC_Rolling_Mill_Process_Engineer compiled.
- **Porex — Process Quality Engineer** (`ja-0904-06`, found 2026-09-04): [Broad-Fit Direct Apply] 45-Day Sprint — Resume resume_Porex_Process_Quality_Engineer compiled.
- **Cummins Inc. — Quality Technician - 3rd Shift** (`ja-0903-02`, found 2026-09-03): Already applied in prior run (Cummins Quality Tech)
- **Applied Materials — New Product Transition (NPT) Manufacturing Engineer** (`ja-0903-03`, found 2026-09-03): Already applied in prior run (Applied Materials Mfg Eng)
- **Applied Materials — Manufacturing Engineer** (`ja-0903-04`, found 2026-09-03): Already applied in prior run (Applied Materials Mfg Eng)
- **FUJIFILM Dimatix, Inc. — Process Engineer I** (`ja-0903-13`, found 2026-09-03): Already applied in prior run (FUJIFILM Process Engineer I)
- **Madison Recruitment — Quality Engineer** (`ja-0903-10`, found 2026-09-03): Dropped: Belgium residents only + Dutch language requirement
- **ES Foundry — Assistant Process Engineer** (`ja-0901-05`, found 2026-09-01): [Broad-Fit Direct Apply] 45-Day Sprint — Resume resume_ES_Foundry_Assistant_Process_Enginee compiled.
- **Cummins Inc. — Product Engineer** (`ja-0901-11`, found 2026-09-01): [Broad-Fit Direct Apply] 45-Day Sprint — Resume resume_Cummins_Inc_Product_Engineer compiled.
- **BAE Systems, Inc. — Quality Engineering Assistant** (`ja-0831-03`, found 2026-08-31): [Broad-Fit Direct Apply] 45-Day Sprint — Resume resume_BAE_Systems_Inc_Quality_Engineering_Assis compiled.
- **Crane Company — Manufacturing Engineer** (`ja-0831-06`, found 2026-08-31): [Broad-Fit Direct Apply] 45-Day Sprint — Resume resume_Crane_Company_Manufacturing_Engineer compiled.
- **MacDermid Alpha Electronics Solutions — Process Engineer I** (`ja-0831-09`, found 2026-08-31): [Broad-Fit Direct Apply] 45-Day Sprint — Resume resume_MacDermid_Alpha_Electronics_Solutions_Process_Engineer_I compiled.
- **Westinghouse Electric Company — Quality Engineer** (`ja-0819-06`, found 2026-08-19): Resume ready - Sid applies.
- **Husco — Supplier Quality Engineer** (`ja-0819-09`, found 2026-08-19): Resume ready - Sid applies.
- **CNH Industrial — Plant Quality Engineer (1st Shift)** (`ja-0818-01`, found 2026-08-18): Resume ready - Sid applies. Top score of the day; QMS ownership + MRB + supplier RCA. Networking recommended post-apply.
- **Porex (Filtration Group) — Process Quality Engineer** (`ja-0812-08`, found 2026-08-12): Resume ready - Sid applies.
- **Mack Molding Co. Inc. — Quality Engineer** (`ja-0811-07`, found 2026-08-11): Resume ready - Sid applies.
- **CSL Plasma — Quality Specialist** (`ja-0810-17`, found 2026-08-10): Resume ready - Sid applies.
- **Cytiva (Danaher) — Supplier Quality Operations Specialist** (`ja-0810-16`, found 2026-08-10): Resume ready - Sid applies.
- **Forvia — Quality Engineer** (`ja-0810-12`, found 2026-08-10): Resume ready - Sid applies.
- **Mazda Toyota Mfg — Specialist, Quality Engineering** (`ja-0810-11`, found 2026-08-10): Resume ready - Sid applies.
- **ConMet — Quality Engineer** (`ja-0810-07`, found 2026-08-10): Resume ready - Sid applies.
- **Century Arms — Supplier Quality Engineer** (`ja-0805-06`, found 2026-08-05): needs gun control act, cant work
- **GE Vernova — Rotor Assembly - Product Quality Engineer** (`ja-0803-01`, found 2026-08-03): Contact-Finder still to run for Greenville, SC.
- **TEC1003 (employer unresolved, UltiPro) — Quality Engineer** (`ja-0803-07`, found 2026-08-03): confidence: low - employer + location unresolved. Resolve before applying.
- **Joby Aviation — Materials Engineer** (`ja-07-104`, found 2026-07-29): Reposted Posting, not worth applying as it is a good fit.
- **Micron Technology — Shift Equipment Engineer ID1** (`ja-07-102`, found 2026-07-29): Its a Completely Equipment Handling and Chemicals stuff not a good fit
- **IPG Photonics — Quality Engineer** (`ja-07-113`, found 2026-07-29): Resume ready - Sid applies. No stable job URL captured (LinkedIn search-result only).
- **Joby Aviation — Mid/Senior MRB Liaison Engineer** (`ja-07-97`, found 2026-07-28): Check 2026-06-17 hold-referral row (same role family/city, different job_url) before treating as wholly new lead
- **Redbock — an NES Fircroft company — Manufacturing Engineer II** (`ja-07-100`, found 2026-07-28): 12-month staffing contract; work closer to PMO/capital-project than QE
- **Micron Technology — Engineer, Metals Adv DRAM** (`ja-0725-05`, found 2026-07-25): Its not a good match, its not even related to Quality
- **GKN Aerospace — Manufacturing Engineer - Quality Engineering** (`ja-0725-03`, found 2026-07-25): CAUTION: aero export-control, confirm visa status before applying/outreach.
- **HANWHA Q CELLS USA — Process Engineer** (`ja-0724-20`, found 2026-07-24): The site is not working
- **TI Automotive — Process Engineer** (`ja-0724-19`, found 2026-07-24): Resume ready - Sid applies.
- **Rivian — Service Supplier Development Engineer** (`ja-0724-18`, found 2026-07-24): Not a good fit
- **Astemo Ltd. — Production Engineer** (`ja-0724-13`, found 2026-07-24): This role says "We cannot sponsor new hires or transfer H1-B visas at this time."
- **Ford Motor Company — Engineering Specialist, Process** (`ja-0724-12`, found 2026-07-24): Visa sponsorship is not available for this position.
- **Parker Aerospace — Quality Engineer 2** (`ja-0724-09`, found 2026-07-24): Its a ITAR position and senior
- **RBC Bearings — Quality Engineer** (`ja-07-68`, found 2026-07-20): Resume ready - Sid applies.
- **OMEC Medical NV — QA/RA Engineer** (`ja-07-67`, found 2026-07-20): Resume ready - Sid applies. CAUTION: full JD reads as a senior FDA/RA-ownership role (510(k), ISO 13485/14971, 4-7yr) -- thinner real fit than the score line suggests.
- **ELYON International — CAPA Quality Engineer** (`ja-07-65`, found 2026-07-20): Resume ready - Sid applies.
- **ISCHEBECK USA — Quality Assurance Engineer** (`ja-07-64`, found 2026-07-20): Resume ready - Sid applies.
- **Semtech — Quality Process Engineer - Semiconductor Manufacturing** (`ja-07-63`, found 2026-07-20): Resume ready - Sid applies.
- **BorgWarner — Manufacturing Engineer II** (`ja-07-62`, found 2026-07-20): Resume ready - Sid applies.
- **SambaNova — Process/Quality Engineer** (`ja-07-61`, found 2026-07-20): Resume ready - Sid applies.
- **NOV — Quality Engineer** (`ja-07-56`, found 2026-07-16): Resume ready — Sid applies.
- **Toray Advanced Composites — Process Engineer III** (`ja-07-54`, found 2026-07-16): Resume ready — Sid applies.
- **AUTOKINITON — Quality Engineer I** (`ja-07-52`, found 2026-07-16): Resume ready — Sid applies.
- **Lucid Motors — Sr. Technical QE Specialist, Chassis & Safety Restraints** (`ja-07-46`, found 2026-07-16): Drafted — shared Lucid pool.
- **Lucid Motors — QMS Auditor II** (`ja-07-45`, found 2026-07-16): Drafted — shared Lucid pool.
- **Micron Technology — FAB Engineer, Wet Process** (`ja-07-44`, found 2026-07-16): Drafted — shared Micron pool. Micron guardrail: best-fit only.
- **Joby Aviation — Quality Engineer - Composites (2nd Shift)** (`ja-07-36`, found 2026-07-13): Hand-scouted. No contact sourced — needs sourcing pass. Local JD, URL TBD.
- **Joby Aviation — Quality Engineer (base)** (`ja-07-37`, found 2026-07-13): Hand-scouted. Alum request sent 2026-07-15; 24-contact Joby QE pool queued. Local JD, URL TBD.
- **Joby Aviation — Quality Assurance Engineer** (`ja-07-38`, found 2026-07-13): Hand-scouted. Outreach sent 2026-07-15 (Kenneth K., Jon C. QC Mgr, Josh Overton recruiter). Local JD, URL TBD.
- **Joby Aviation — Quality Engineer, Airframe Assembly** (`ja-07-33`, found 2026-07-13): Outreach sent 2026-07-15 (7 cold notes + warm DM).
- **Qcells North America — Quality Engineer (Cell)** (`ja-07-27`, found 2026-07-06): Not yet networked (Path B). Grace expired.
- **GTI Fabrication — Quality Engineer** (`ja-07-26`, found 2026-07-06): Not yet networked (Path B). Grace expired.
- **Quantum Global Technologies — Customer Quality Engineer** (`ja-07-25`, found 2026-07-06): Not yet networked (Path B). Grace expired.
- **PROENERGY — Quality Engineer** (`ja-07-24`, found 2026-07-06): Not yet networked (Path B). Grace expired.
- **Kratos Defense and Security Solutions — Quality Engineer** (`ja-07-23`, found 2026-07-06): Not yet networked (Path B). Grace expired.
- **Slate Auto — Supplier QE, Safety & Restraints** (`ja-07-22`, found 2026-07-06): Not yet networked (Path B). Grace expired.
- **Clark Schaefer Hackett — Supplier Quality Engineer** (`ja-07-21`, found 2026-07-06): Not yet networked (Path B). Grace expired.
- **NXP Semiconductors — Industrial Engineer** (`ja-07-20`, found 2026-07-06): Not yet networked (Path B). Grace expired.
- **Dauch — Quality Engineer** (`ja-07-18`, found 2026-07-06): Not yet networked (Path B). Grace expired.
- **Medline — Supplier Quality Engineer** (`ja-07-17`, found 2026-07-06): Not yet networked (Path B). Grace expired.
- **Schaeffler — Supplier Quality Engineer** (`ja-07-16`, found 2026-07-06): Contacts discovered + linked (8); drafted note ready. Grace expired.
- **MANN+HUMMEL — Quality Engineer** (`ja-07-28`, found 2026-07-06): Not yet networked (Path B). Grace expired.
- **Panelmatic — Quality Engineer** (`ja-07-31`, found 2026-07-06): Not yet networked (Path B). Grace expired.
- **Flex-N-Gate — Quality Engineer** (`ja-07-30`, found 2026-07-06): Not yet networked (Path B). Grace expired.
- **Komatsu — Supplier Quality Engineer - VOC** (`ja-07-29`, found 2026-07-06): Not yet networked (Path B). Grace expired.
- **Arrow Electronics — Quality Engineer** (`ja-07-15`, found 2026-07-06): Contacts discovered + linked (8); drafted note ready. Grace expired.
- **CentroMotion — Supplier Quality Engineer** (`ja-07-14`, found 2026-07-06): Contacts discovered + linked (7); drafted note ready. Grace expired.
- **Allegion — Manufacturing Quality Engineer** (`ja-07-13`, found 2026-07-06): Contacts discovered + linked (8); drafted note ready. Grace expired.
- **Cerebras — Senior Quality Engineer** (`ja-07-12`, found 2026-07-06): Contacts discovered + linked (8); drafted note ready. Grace expired.
- **Stellantis — Plant Quality Engineer** (`ja-07-10`, found 2026-07-06): Contacts discovered + linked (8); drafted note ready. Grace expired.
- **Tesla — Materials Engineer, Cell Electrode** (`ja-07-08`, found 2026-07-06): Contacts discovered + linked (8); drafted note ready. Grace expired.
- **Tesla — Materials Engineer, Cell Electrode** (`ja-07-07`, found 2026-07-06): Contacts discovered + linked (8); drafted LinkedIn note ready. Grace expired.
- **Gulfstream Aerospace — Supplier QA Engineer 2 - Metallurgy** (`ja-07-06`, found 2026-07-02): 7 contacts discovered + linked. Grace expired.
- **Copeland — Supplier Quality Engineer Associate** (`ja-07-03`, found 2026-07-01): Serper returned namesakes (0 real); needs poster/Chrome seed. Grace expired.
- **Joby Aviation — Composite Production Engineer** (`ja-07-05`, found 2026-07-01): Was held on gate=80 decision; never fed to agent. Grace expired.
<!-- DROP-REVIEWS:END -->
