# PillProof web app

The app from plan §4 ("Must have"). It is a static PWA in `app/` built with Vite, Preact and TypeScript. There are no accounts, no server and no analytics: medicines, labels, settings and chat stay in the browser (IndexedDB and localStorage). It works offline after the first load.

## Run

```sh
cd app
npm install
npm run dev                  # http://localhost:5173
npm test                     # node --test tests/ (app logic, answer pipeline, backup sources)
npm run build                # tsc + vite build -> dist/ (service worker precaches everything)
HTTPS=1 CERTS_DIR=~/waicy-work/certs/app npx vite preview --host --port 4443   # phone testing on the LAN
```

The model weights are served by the dev and preview servers from `~/waicy-work/models/mlc/<dir>` and `~/waicy-work/models/libs/*.wasm`, in the same layout as the Gate 1 page (`/models/<dir>/resolve/main/<file>`). Set `MODELS_DIR` to use a different place. Nothing is uploaded to Hugging Face.

## Models

`app/models.json` sets the default key for each size (`default["2B"]`, `default["0.8B"]`) and maps each key to its MLC directory and dev metrics. The app never hard-codes a round. Swapping models means editing that file. The file comes from the Gate 2 branch (`train/scripts/app_models.py`); defaults are r1-ft / lite-r1-ft, and r2/r3 are offered in Settings. Settings shows the dev metrics for the device's prompt set (phone or desktop). The lite-r3 4-bit build can repeat "1000000…" on some prompts; the number check blocks it (the unit test covers restatement, citation and bare-reply forms), so the user sees label sentences instead. The qualifier check also blocks a short answer that drops a warning or limit from the cited sentences, or starts with an unqualified "Yes"/"It is safe" (for example "Yes, you can drink grapefruit juice." over "Avoid drinking more than 1.2 liters…"). The user then sees the cited label sentences. See [gate2.md § Qualifier check](gate2.md#qualifier-check) for the rule and its dev false-block rate.

## Screens

| Screen | What it does |
|---|---|
| **Today** | Today's dose times and the next dose, computed by code from the times the user set (not the model). |
| **Medicines** | Add a medicine with RxNorm autocomplete. Single-ingredient oral products rank first, and combination products show their full ingredient list before saving. Set dose times, edit, or delete. On add, the openFDA label is fetched and cached: the app prefers a label with a patient section and takes the most recent. The screen shows the maker and label date, and the user can switch maker. |
| **Ask** | The chat (see below). |
| **Voice** | One large hold-to-ask button. Speech is recognised in the browser by Moonshine (tiny on phones, base on desktop) through transformers.js, never by the browser's cloud speech service. Answers are spoken. Typing always works. |
| **Changes** | Label-change history from `app/data/label_changes.json`: the old sentence beside the new one, how far back the history goes, and "ask your pharmacist or doctor before changing anything". |
| **Settings** | Text size, high contrast, answer mode (model or passages only), model download/delete, smart search (bge-small embeddings), backup sources, web search (with the note "Your question is sent to a search service."), and calendar export. |

The UI has large text (three sizes), a high-contrast theme and big touch targets (52 px buttons, 64 px tabs).

The calendar export is an `.ics` file. Events are titled "Medication time" unless the user turns on drug names.

## Answering a question

1. **Router** (`lib/router.ts`):
   - Emergency words get a fixed message: Poison Help 1-800-222-1222 and 911, plus 988 for self-harm. The model never sees these questions.
   - Schedule questions are answered by code.
   - Label questions go to retrieval and the model.
   - Anything else is out of scope.
   - Poison Help is confirmed at poisonhelp.hrsa.gov and 988 at 988lifeline.org.
2. **Relevance gate** (`answer.ts` `coverage`, `query.ts` `concepts`):
   - The question's content concepts (grapefruit, alcohol, pregnancy, …) must appear in the label. Generic words like take, drink, use and can don't count.
   - If a concept is missing, the reply is: "The label does not mention X. That does not mean it is safe or unsafe." plus the pharmacist prompt.
   - **Near-miss terms are never merged.** "grape juice" does not match "grapefruit juice", and the reply says so: "The label does not mention “grape juice”. It does mention “grapefruit juice”, which is different." (`query.ts` `nearMisses`).
3. **Retrieval and prompt.** These are the Gate 2 hybrid retrieval and SENTENCES prompt format, shared from `core/`, with the phone and desktop presets.
4. **Model.** WebLLM runs in a worker.
5. **Checks.** The JS quote, number and drug-name checks from Gate 2 run on the reply.
6. **Display.**
   - The plain answer comes first, then only the cited sentences, highlighted, with an unhighlighted lead-in where a list item needs one.
   - At most 3 quotes are shown.
   - Each quote shows its section name; the caption gives the maker, the label date and a DailyMed link.
   - Every answer ends with the standing line "This is information from the FDA label, not medical advice for you."
   - **Over-declining.** If the model says NOT IN LABEL but the relevance gate found sentences matching every concept in the question, the app shows "Your label says:" with the top 1 to 3 sentences (extractive, no model text). Unrelated sentences are never shown (Accord atorvastatin + grapefruit → "Avoid drinking more than 1.2 liters of grapefruit juice each day.").
   - **Unreliable model text is dropped and the quotes stay:** an answer cut off mid-sentence keeps only its complete sentences; an abbreviation spelled out differently from the label ("premature menstruation (PMDD)") shows quotes only; near-duplicate label sentences are quoted once.
   - **Phone tier, "what is it for".** The 0.8B model's plain-language glosses of indication lists were wrong in 3 of our dev questions ("a statin (a type of cholesterol)", "sleepiness" for "sleeplessness"), so on phones this question shows the label's own sentences.
   - **Dosing tables** become sentences ("For <row header>: <cells>") in `datapipe/sentences.py` and the JS port, so retrieval and the model can use them. Numbering stays in parity, and the T1 gold refs still resolve.
7. **Passage-only fallback.** On devices without WebGPU, with the model off, or after a crash, the app shows the best matching label sentences under "please read it yourself".

**iPhone guards** (docs/gate1.md):
- Phones only ever get the 0.8B model.
- On phones the context window is 2048 tokens and max_tokens is 128.
- A reload during generation is recorded as a crash. That device then stays in passage-only mode until the user retries.

## Backup sources (when the label doesn't answer)

This is a separate feature, on by default in the app (Settings → "check other trusted sources"). It is **never used by the frozen evaluation**: T1 to T5 and systems A to E stay label-only, because the evaluation calls the label pipeline directly.

**When it runs.** Only when the user's own label gives no usable answer:
- the topic is "not mentioned";
- the model declined;
- or retrieval found no passages.

**Fallback rule.** The sources are checked one at a time, and the app stops at the first that answers:

1. **The user's label.** Unchanged.
2. **Other FDA labels with exactly the same active ingredients.** These are other makers' versions and Rx labels, from openFDA. They go through the same relevance gate, retrieval, SENTENCES prompt, model and checks as the user's own label, one label at a time (up to 2 on a phone, 3 on desktop). If the model declines, the label doesn't count as an answer.
3. **FDA consumer pages on food and drink.** They are prebuilt in `app/data/fda_food.json` with each page's URL, content date and access date. They are US government work in the public domain.
   - [Grapefruit Juice and Some Drugs Don't Mix](https://www.fda.gov/consumers/consumer-updates/grapefruit-juice-and-some-drugs-dont-mix) (content dated 2021-07-01).
   - [Drug Interactions: What You Should Know](https://www.fda.gov/drugs/resources-drugs/drug-interactions-what-you-should-know) (2013). It is co-branded with the Council on Family Health and covers pain relievers with alcohol, and caffeine.
   - Each page is split into groups of exact sentences, one group per named drug. The builder checks each sentence against the live page text.
4. **DDInter 2.0 drug–food interactions.** Stored in `app/data/ddinter_food.json` (857 rows, 726 drugs). Used for single-ingredient products only, and a route qualifier like "(ophthalmic)" must match.
5. **The web** (see "Web search" below), if the setting is on.
6. **If nothing answers:** "None of the sources we checked mention X with this medicine. Ask your pharmacist." This is followed by the list of sources checked and a MedlinePlus link (see below).

**Rules:**
- **Exact ingredients.** A source is used only if it names every active ingredient of the confirmed product. Salts are stripped (atorvastatin calcium → atorvastatin), metal names are kept (ferrous sulfate), and DDInter synonyms are applied (aspirin → acetylsalicylic acid). So a combination such as Goody's (acetaminophen + aspirin) only matches the FDA pain-reliever group, which names both, and never matches DDInter.
- **Badges and links.**
  - Every backup answer has a badge, for example: "Not on your label — from the FDA label for Lisinopril (Maker), dated …", "Not on your label — from FDA: Grapefruit Juice and Some Drugs Don't Mix (page dated 2021-07-01)", or "Not on your label — from DDInter 2.0, a drug interaction database written for health professionals".
  - Each quote links to its source: DailyMed, an FDA text fragment link, or the DDInter drug page.
- **Curated sources and model declines.** The model (trained on labels) sometimes declines curated sources. An FDA page group or DDInter row is about this drug by construction, and the relevance gate has already matched the topic. So in that case the app still shows the sentences that name the drug, under "please read it yourself".
- **Never "safe".** Silence is never presented as safety. The label line always says "That does not mean it is safe or unsafe", and the none-found reply only says that the sources don't mention it.
- **Phone limits.** Sources are run one at a time with the same phone retrieval budget (about 400 prompt tokens plus the template), the 2048 context window and max_tokens 128.
- **Offline.** The FDA and DDInter files are bundled and precached. Other labels need the internet; offline, that step is listed as "not checked: no internet".

**Licenses:**
- **DDInter 2.0** (ddinter2.scbdd.com). The [terms page](https://ddinter2.scbdd.com/terms/) (read 2026-11-16, local time) says: *"The DDInter data is made available under a Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International license."*
  - So redistribution in a free, non-commercial app with attribution is allowed.
  - The adapted file `ddinter_food.json` must stay CC BY-NC-SA 4.0. It carries the license, the citation (Xiong G et al., *Nucleic Acids Res* 2025;53(D1):D1356–D1364) and the access date, and the app shows the credit line under every DDInter answer.
  - The site footer also says "© … All Rights Reserved". We follow the explicit data license on the terms page.
  - The project must stay non-commercial while this file is included.
  - The text is written for health professionals ("Patients should be counseled …") and cites Cerner Multum. The badge says so.
- **FDA pages.** US federal government work, in the public domain. The source and date are shown.
- **MedlinePlus.** Link only, through MedlinePlus Connect by RxCUI (the title and URL from the JSON service, or the Connect page if offline). Their text is not copied, as their terms require.

**Code:**
- `app/src/lib/backup.ts`: orchestration, ingredient matching and wording.
- `openfda.ts` `otherLabels`.
- `ui/Reply.tsx` `BackupAnswer`.
- Data builder: `cd datapipe && uv run python -m medlabel_data.backup_sources`. It verifies FDA sentences against the live pages and caches raw DDInter pages under the data cache.
- Tests: `app/tests/backup.test.ts`.

**Demo** (Mac, real labels, r1-ft 2B in Chrome):

| Medicine (user's label) | Question | Result |
|---|---|---|
| fexofenadine (Aurohealth) | Can I drink grapefruit juice? | Label silent → FDA grapefruit page: "Some antihistamines, such as Allegra (fexofenadine)." and "Grapefruit juice can cause less fexofenadine to enter the blood…" |
| atorvastatin (Accord) | Can I drink grapefruit juice? | Label model declined (r1) → FDA grapefruit page: "Some statin drugs … such as Zocor (simvastatin) and Lipitor (atorvastatin)." |
| simvastatin (Aphena) | Can I drink grapefruit juice? | Answered from the user's own label. |
| lisinopril (RemedyRepack) | Can I drink alcohol? | Label silent → DDInter: "Some authorities recommend avoiding alcohol in patients receiving vasodilating antihypertensive drugs." |
| rosuvastatin (Torrent) | Can I drink grapefruit juice? | No source names rosuvastatin with grapefruit → "None of the sources we checked mention “grapefruit juice” with this medicine. Ask your pharmacist." plus the MedlinePlus link. |
| atorvastatin | Can I drink kombucha? | "None of the sources we checked mention “kombucha” …" plus the MedlinePlus link. |

## Web search (last step before "none of the sources")

A separate, optional step, on by default in the app (Settings → "If those don't answer either, search the web", with the note "Your question is sent to a search service, with only the medicine's ingredient name."). **Off for the frozen evaluation**: T1 to T5 and systems A to E stay label-only.

**Method:**
- **Proxy.** The browser posts only `{ingredients, question}` to `/api/search`. Nothing else from the medicine list is sent. The proxy (`app/server/search.js`) adds the Tavily key and calls Tavily. The key is read from `~/waicy-work/.env` (`TAVILY_API_KEY`) by the Vite dev and preview servers. It is never logged, committed or sent to the browser. If the key is missing, the step is skipped and the reply lists the web as "not set up on this server".
- **Search.** `search_depth: "advanced"`, raw page text included, 15 s timeout with one retry, and a "Searching the web…" status. The first search is limited to consumer health sites (MedlinePlus, NHS, FDA, Mayo Clinic, Cleveland Clinic, drugs.com, …). If fewer than 3 come back, an open search over any site is added. That is 2 Tavily credits per question, or 4 with the open search.
- **Ranking and filtering** (`app/src/lib/web.ts`, `backup.ts`):
  - Consumer and government sites first, then other sites, then research papers (PubMed etc.), which are only used if nothing else answers.
  - The top pages' text is split into sentences and goes through the same retrieval and relevance gate as labels; every concept in the question must be covered.
  - Dropped: sentences naming other drugs, sentences about other dose forms (suspension, injection, extended-release for an immediate-release user), questions, "X + Y" pair pages unless the user named Y, and extended-release pages for immediate-release users.
- **Answering.** The model answers from the best sentences of one page at a time in the usual SENTENCES format; the number/name and qualifier checks apply. If its wording strays from the quotes (less than 60% of its words supported), or it declines on relevant sentences, the matching sentences are quoted instead. Each quote links to its page.

**Display.** The site name is shown in large text on every web answer, with the badge "From the web (site) — not your label, may be wrong". Sites not on the known list also get "Unverified website", forums are labelled "(discussion forum)", and research papers are labelled "research paper — technical". Nothing is ever presented as "safe" because a source is silent.

**Cache and limits.** Results are cached on disk per (ingredients, question) in `~/waicy-work/cache/web-search.json`, so repeat questions cost nothing. The rate limit is 12 searches per client per minute and 300 a day; the free plan has 1,000 credits a month.

**Public deployment (not done yet).** `app/worker/` is a Cloudflare Worker version of the same proxy, using the Cache API for 30 days. To deploy: `npx wrangler secret put TAVILY_API_KEY`, set `ALLOWED_ORIGIN` in `wrangler.toml`, run `npx wrangler deploy`, and build the app with `VITE_SEARCH_URL=https://<worker>/api/search`. Without it, the static site has no web step.

**Limits:**
- Web pages can be wrong or out of date, and the badge says so. Attributed quotes may themselves say "generally considered safe" (for example Medical News Today on atorvastatin + ibuprofen). That is the site's wording, shown as a quote, never ours.
- Results depend on what the search returns that day; the cache keeps repeats stable.
- It needs the internet; offline, the step is listed as "not checked: no internet".

## Answer quality on everyday questions (dev only)

We wrote 41 everyday questions of our own (none from T1 to T5) over 9 medicines: atorvastatin (Accord), ibuprofen, amoxicillin, prednisone, cetirizine, metformin, lisinopril, sertraline and Tylenol PM. They cover what it's for, how to take it, missed dose, dose, side effects, alcohol, grapefruit vs grape juice, an unusual food, splitting/crushing, pregnancy, use with another common drug, a combination OTC product, and questions with no good answer. Each answer was hand-graded as useful and correct / correct but unhelpful / wrong / dangerous. Harness: Playwright on the real app in Chrome, with backup sources and web search on.

| Run | Useful & correct | Unhelpful | Wrong | Dangerous |
|---|---|---|---|---|
| Before (label-only app, first 20 questions) | about 9/20 | | | 0 |
| Desktop, r1-ft (2B), final | 37/41 (90%) | 4 | 0 | 0 |
| Phone tier, lite-r1-ft (0.8B, iPhone user agent, phone guards), final | 37/41 (90%) | 4 | 0 | 0 |

**Remaining unhelpful answers:** amoxicillin + milk (the only web match is an NHS sentence about mixing it with a baby's milk); prednisone "cut in half" (the label only says "scored"); cetirizine + grapefruit and metformin "crush" (correctly "none of the sources", because the only pages found were pair pages or extended-release pages). Phone "what is it for" answers are correct but in label wording.

Web answers: 4 per run, all from medical or consumer sites (Drugs.com, MedlinePlus, NHS, Medical News Today); none from unverified sites. Tavily usage while building and evaluating: 25 credits of 1,000.

## Known limits

- r1 sometimes declines on the user's label even though the label covers the topic (the atorvastatin grapefruit case above). The app then falls back to the backup sources. Newer rounds can be swapped in through `models.json`.
- Speech recognition downloads Moonshine once, on first use. Until it has loaded, typing is the input.
