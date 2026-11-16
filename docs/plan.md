# WAICY 2026 plan: label-grounded medication assistant with label-change alerts

Approved November 15. Working title only; you are choosing the name later. Track: AI Showcase, High School, solo. Everything is done from home. Form closes **Sunday November 29, 5:00 pm ET (2:00 pm PT)**. Plan to submit Saturday November 28.

## 1. The idea in one paragraph

An older adult types in their medications and schedule. They can then ask, by text or by voice, things like "what should I take my levothyroxine with?" or "what's next today?". A small open-weight language model that you fine-tune runs inside their browser. For medication questions it may only do two things: point to the exact sentences in that drug's FDA label and restate them plainly, or say the label does not cover it and suggest asking a pharmacist. The app also compares each drug's current label with earlier versions and shows what changed in the safety sections, old text beside new. Questions and the medication list stay on the device, and it costs nothing to run.

**The claim we will test:** on medication questions, the fine-tuned, label-restricted model gives fewer wrong answers and declines more appropriately than the same model without the label and without fine-tuning.

**The second, smaller claim:** the app separates real changes in a label's safety text from rewording and reformatting better than a simple text-similarity rule.

**The claim we will not make:** first, only, safe, or a replacement for a pharmacist. Reminder apps, interaction alerts (Medisafe, Apple Health), general AI health assistants, and research prototypes of label-grounded chatbots already exist. For label changes, FDA has a tool for its own reviewers (LabelComp) and a public list of safety label changes; I found no patient-facing version, but my search was keyword-based and is not proof.

## 2. What you decided

| Topic | Your decision |
|---|---|
| Relation to Adhera | Completely new and standalone; no Adhera code or name |
| Team | Solo |
| Product | Web app for phone and laptop, installable to the home screen |
| Medication entry | Typing with drug-name autocomplete only |
| Schedule features | Today timeline only. Dose logging and in-app reminders were cut on November 15 to make room for label-change alerts |
| Reminders | Downloadable calendar file; the phone's calendar does the reminding |
| Label-change alerts | Added November 15 as the freshest piece |
| Fieldwork | None. Everything is done from home |
| Interactions between their own drugs | Answer only when asked; no automatic flagging |
| AI core | Fine-tune a small open-weight model to quote the label or decline; run it in the browser |
| Compute | M5 Pro Mac, Kaggle/Colab, paid GPU rental if needed |
| Weak devices | Fall back to showing the matching label passage without AI wording |
| Voice | Tap or hold a microphone button; answer shown as text and read aloud |
| Main user | Older adults managing several daily medications themselves |
| Language | English only; Spanish as future work |
| People | A pharmacist or clinician reviewer, and a few older adult testers |
| Question scope | Drugs on their list, plus "can I take X with it?" answered from the listed drug's label |
| Judging | Present live online December 4 to 6 |
| Openness | Public code on GitHub, fine-tuned model on Hugging Face |

## 3. What I decided for you (veto any of these)

1. **Schedule questions are answered by ordinary code, not the model.** "What's next?" is a lookup in the stored schedule. The model cannot get a time wrong if it never produces one.
2. **The model picks sentence numbers; code copies the quote.** Each label passage is split into numbered sentences. The model outputs which sentences answer the question plus a plain-language restatement. The app copies those sentences from the label itself, so a displayed quote is always real label text.
3. **A number check guards the restatement.** Any number, unit, or drug name in the plain-language answer must also appear in the selected sentences. If not, the app shows only the quote.
4. **Speech recognition also runs in the browser** with an open-weight model (Whisper or Moonshine builds exist under Apache-2.0 and MIT). The browser's built-in speech service is reported to send audio to Google or Apple servers, which would break the privacy claim.
5. **Read-aloud uses the device's built-in voice.** It is free and needs no download.
6. **Everything is stored in the browser.** No accounts, no server database, no analytics.
7. **Emergency words trigger a fixed message, not the model.** "Took too much", "overdose", "can't breathe" show Poison Help and 911.
8. **Which label is used.** The user picks ingredient, strength, and form from RxNorm autocomplete. The app fetches labels for that exact product from openFDA, prefers one with a patient section, takes the most recent, and shows the manufacturer and label date. The user can switch to the manufacturer on their bottle.
9. **Calendar file titles say "Medication time" by default**, with an option to include drug names, since calendars sync to other services.
10. **Testers use a fictional medication list**, so nobody shares their own health information.
11. **AI coding help is disclosed** in the AI-usage explanation, separately from what you designed, trained, and evaluated.
12. **One large commercial chatbot is included as a reference point** in the evaluation. It costs a few dollars and is the first thing cut if time runs short.
13. **For label changes, code finds the changed sentences and the model only judges and explains them.** Code lines up the old and new versions section by section. The model says whether a changed sentence means something different or is just reworded, and writes one plain sentence. Both the old and new sentences are copied from the labels by code, and the number check applies.
14. **Label changes are worked out ahead of time for a fixed set of about 25 drugs**, the same ones as test set T3, and shipped with the app as a small file. This avoids a server and avoids relying on the browser reaching the label archive, which I have not tested.
15. **Only safety sections are compared:** boxed warning, contraindications, warnings and precautions, drug interactions, and the patient sections.
16. **A change is never presented as a reason to stop a medication.** Each one carries the line "ask your pharmacist or doctor before changing anything".

## 4. Features

**Must have**
- Add a medication with autocomplete; set dose times; edit and delete.
- Today timeline.
- Chat: label questions answered with highlighted source sentences, label section name, and label date.
- Label changes: for each listed drug, a dated list of changes to the safety sections, old sentence beside new, with one plain-language line.
- A clear "the label does not cover this" response with a pharmacist prompt.
- Voice in and read-aloud out, with the heard text shown and correctable.
- Passage-only fallback for devices that cannot run the model.
- Works offline after first load; labels cached when a drug is added.
- Calendar file export.
- Large text, high contrast, big touch targets.

**Cut on November 15:** dose logging, dose history questions, in-app reminders.

**Stretch, in this order**
- "Can I take X with it?" for common over-the-counter drugs, using a small hand-checked list that maps brand to ingredient to class (Advil, ibuprofen, NSAID). The automatic class lookup I tested returned messy results for ibuprofen, so a curated list is safer.
- A smaller "lite" model for phones.
- A printable medication list for doctor visits.

## 5. How a question flows through the system

1. **Hear.** Speech model transcribes. Drug names are corrected by matching what was heard against the handful of names on the user's own list. The corrected text is shown.
2. **Route.** Simple rules plus a small classifier sort the question: emergency, schedule, label question, or out of scope.
3. **Retrieve.** For label questions, the drug's label sections are searched with keyword search plus a small embedding model, and the top few passages are kept. The browser build of the model has a 4,096-token window, so passages must be compact; the median label passage in the training data is about 455 characters.
4. **Read.** The fine-tuned model sees the question and numbered sentences. It returns either "not in label" or sentence numbers plus a restatement.
5. **Check.** Code verifies the sentence numbers exist, copies the quotes, and runs the number check.
6. **Show and speak.** Plain answer first, quoted sentences beneath, section and label date, and a standing line that this is label information, not personal medical advice.

### How label changes are found

This runs once on your computer before release, not in the user's browser.

1. **Fetch versions.** DailyMed lists every published version of a label and lets each one be downloaded. I tested this on three drugs and it worked.
2. **Split by section.** Each label file marks its sections with standard codes, so the same section can be compared across versions.
3. **Line up sentences.** Within a section, match each new sentence to its closest old sentence. Unmatched or altered sentences are the candidates.
4. **Judge.** The model labels each candidate as a change in meaning or a rewording, and writes one plain sentence for the real changes.
5. **Check and store.** The number check runs, and the result is saved in a small file shipped with the app.

**What my test showed.** History depth varies a lot: Xarelto had 60 versions back to 2011, Eliquis 29 back to 2013, but Lipitor only 7 back to 2024 and Singulair 5 back to 2021. A naive sentence comparison flagged many changes that were only reformatting, so steps 3 and 4 are where the work is. The comparison did surface real additions, such as a Jardiance sentence about withholding the drug before surgery.

## 6. The model

**Candidates, all Apache-2.0, all with existing browser builds in WebLLM**

| Model | Browser download | Memory WebLLM lists | Role |
|---|---|---|---|
| Qwen3.5-2B | 1.08 GB | about 2.2 GB | Primary |
| Qwen3.5-0.8B | 0.45 GB | about 1.6 GB | Lite tier for phones |
| Qwen3.5-4B | 2.39 GB | about 3.9 GB | Comparison only |

Pick the smallest model whose wrong-answer rate on the development set is close to the larger one. The size-versus-accuracy chart is itself good evidence of understanding.

**Training data: FDARxBench** (Apache-2.0). The repository holds 17,207 items over 685 labels: 9,875 factual, 3,398 multi-step, 3,934 where the right response is to decline. I audited it, and four things shape how we use it:

- Most source passages are clinical-trial and drug-metabolism sections. About 2,000 factual items come from sections a patient would ask about. Weight training toward those.
- The "decline" questions follow an obviously artificial template. A model could learn the template instead of the skill. Build realistic ones by taking an answerable question and removing the passage that holds the answer. This is done by code.
- Only 11% of reference answers are word-for-word label text, though they overlap heavily (median 96% of words). Derive the sentence numbers by aligning each reference answer to label sentences, and drop items where the alignment is weak.
- One sample I read had an answer that did not match its question. Spot-check 100 items before training and report the error rate you find.

Split by active ingredient, so no drug appears in both training and test. FDARxBench was published as an evaluation benchmark; say plainly that you trained on part of it and held out the rest, and that your scores are not comparable to the paper's.

Optional: rewrite a share of training questions into everyday wording using a large model. Disclose it. Never do this to a test set.

**Training.** LoRA fine-tuning, either on the M5 Pro with MLX-LM (Qwen3.5 MLX builds exist) or on Kaggle/Colab with standard PyTorch tools. Train on training ingredients, tune on development ingredients, and do not look at test ingredients.

**Getting it into the browser.** MLC's documented route for a fine-tuned variant: merge the adapter, run `mlc_llm convert_weight` and `gen_config`, upload to Hugging Face, and reuse the base model's existing browser library. MLC has a Qwen3.5 model type. I have not run this end to end, so it is the first thing to test.

## 7. Evaluation

**Test sets**

| Set | What it is | Size | Why |
|---|---|---|---|
| T1 | FDARxBench, held-out ingredients | about 20% of ingredients | Large, same style as training |
| T2 | MedicationQA (CC BY 4.0): real consumer questions whose reference answers come from DailyMed | up to 290 of 690 | Real wording and typos; never trained on |
| T3 | Your own set on about 25 drugs common among older adults, written before seeing any model output; about 30% deliberately not answerable from the label | about 120 | Matches the actual use; pharmacist-checked |
| T4 | Recorded spoken questions from you and testers | about 150 | Drug-name hearing accuracy |
| T5 | Changed-sentence pairs from old and new label versions of the 25 drugs, each marked by you as "meaning changed" or "reworded" before the model sees them | about 150 | Tests the label-change piece; pharmacist checks about 30 |

**Systems compared**

| | System | What it shows |
|---|---|---|
| A | Small model, no label | What a small chatbot "knows" |
| B | Same model plus label passages, not fine-tuned | What retrieval alone buys |
| C | Fine-tuned model plus quote and number checks | Yours |
| D | Passage-only fallback | How good the weak-device mode is |
| E | One large commercial chatbot, no label | Honest reference point |

**Measures**
- Each answer graded correct, wrong, or declined. The headline is the wrong-answer rate.
- Declined when it should have answered; answered when it should have declined.
- Whether the selected sentences are the right ones.
- How often the number check blocked a restatement.
- Pharmacist-rated potential for harm on a sample.
- Retrieval: how often the right passage is in the top few.
- Reading grade level of answers. A BMJ study found chatbot drug answers hard to read.
- Speed and memory on the M5 Pro and on a phone.
- Voice: drug-name accuracy before and after list-based correction.
- Label changes (T5): how often real changes are caught and how often rewording is wrongly flagged, for three methods: a text-similarity rule, the untuned model, and your model. Also how many of the plain-language lines the pharmacist marks as accurate.

**Grading**
- You grade T3 without knowing which system wrote each answer.
- The pharmacist grades a sample of about 40; report how often you agree.
- An automatic grader is used only for the large T1 set, and only after checking it against your own grades on 100 items. One 2026 study found only fair agreement between an automatic judge and experts.

**Rules**
- Freeze the test sets and the system, then run the final evaluation once.
- Report uncertainty by resampling whole drugs, not single questions.
- Report every result, including if fine-tuning does not beat B, or if E is more accurate.

**Expect this:** a large commercial chatbot may well score higher on answerable questions. One 2026 study found label-grounded answers did not beat plain GPT-4o. The defensible advantages are fewer unsupported answers, correct declining, visible sources, privacy, offline use, and zero cost. Say that directly.

## 8. Safety and honesty

- Label information only. Never tells anyone to take, skip, or change a dose beyond quoting the label.
- "The label does not mention it" is never presented as "it is safe".
- Labels vary by manufacturer and can lag practice. The label source and date are always visible.
- A label change is not an instruction. The app never suggests stopping or changing a medication because its label changed.
- Label history is incomplete for some drugs, because a label can restart its version count when the company changes. The app shows how far back its comparison goes.
- Be exact about privacy. Questions, the medication list, and the model stay on the device. Adding a drug does download its label from FDA's public service, which reveals that drug name to that service.
- FDA's guidance treats simple reminders and patient reference information as outside active oversight, while software that gives patients recommendations is treated differently. Keep the wording as reference information. This is not legal advice.
- Speech recognition is known to mishear drug names, and is worse for some older speakers. Hence the visible transcript, correction against the list, and text always available.
- Usability sessions are informal feedback on a prototype, with consent, a fictional medication list, and no names published. Tell testers not to rely on it.
- Ask the pharmacist's permission before naming them.

## 9. Schedule

| Date | Work | Gate |
|---|---|---|
| Mon Nov 16 | Run base model in browser on Mac and phone. Tiny fine-tune, convert, load in browser. Contact pharmacist and testers today. | |
| Tue Nov 17 | Finish conversion test. Start label fetching and sentence splitting. | **Gate 1:** fine-tuned weights answer in the browser |
| Wed Nov 18 | Training data: split, alignment, realistic decline examples, 100-item audit. Write T3 and lock it. | |
| Thu Nov 19 | Fine-tune. Build retrieval and measure it. | |
| Fri Nov 20 | Quote and number checks. Send pharmacist the T3 reference answers. | **Gate 2:** C beats B on the development set |
| Sat Nov 21 | Label changes: download versions for the 25 drugs, line up sections and sentences, mark the T5 pairs by hand, then run the three methods. | **Gate 3:** fewer than about 1 in 5 flagged changes are only reformatting |
| Sun Nov 22 to Mon Nov 23 | App: entry, timeline, chat with citations, label-change view, fallback, calendar file, offline. | |
| Tue Nov 24 | Voice, name correction, read-aloud, recordings. Freeze. Send pharmacist system outputs, including about 30 change explanations. | |
| Wed Nov 25 | Final evaluation run. | |
| Thu Nov 26 | Thanksgiving: usability sessions if relatives are willing. | |
| Fri Nov 27 | Analysis, charts, slides, written description. | |
| Sat Nov 28 | Record both videos, assemble Drive folder, submit. | |
| Sun Nov 29 | Buffer only. | Form closes 2 pm PT |

**If Gate 1 fails**, try in order: Qwen3-1.7B (text-only, also prebuilt for the browser); a transformers.js build; the untuned prebuilt model with your retrieval and checks, with fine-tuning results reported from the notebook.

**If Gate 2 fails**, spend at most one more day, then ship the better of B and C and report the comparison as it is.

**If Gate 3 fails**, ship label changes without explanations: show the date each safety section last changed and the old and new text, and report the measured results as they are.

**Cut order if behind:** commercial chatbot reference; lite phone model; "can I take X with it?"; read-aloud polish; plain-language lines on label changes. Never cut: the evaluation, the quote check, the fallback, the two videos.

## 10. Submission

Folder `Main_High_<Name>` containing:
- `..._Presentation.pdf`
- `..._Description.pdf`: description (250 words maximum) and AI-usage explanation (250 words maximum)
- `..._PresentationVideo.mp4` (3 minutes maximum)
- `..._DemoVideo.mp4` (3 minutes maximum)
- `..._AdditionalMaterials`: evaluation report, links to code and model, model card

The web form asks for a 200-word description, so write a shorter version for it.

**Demo order:** add three medications; show the timeline; ask a "take with" question by voice; show the highlighted label sentence; show a misheard name being corrected; ask something the label does not cover and show it decline; switch to airplane mode and ask again; open a drug's label changes and show old text beside new; end on the results chart.

**How it meets the rubric**

| Criterion | Points | What covers it |
|---|---|---|
| AI understanding | 25 | Speech (perception), retrieval and evidence selection (reasoning), fine-tuning with held-out drugs (learning), voice and plain language (interaction), limits and privacy (society) |
| Technical skills | 25 | Your own fine-tuned model running in a browser; five-way comparison; honest results |
| Problem | 10 | Older adults, many medications, hard-to-read labels |
| Design | 10 | Large type, voice, sources visible, works offline |
| Ethics | 10 | Section 8, including what happens when it fails |
| Presentation | 10 | Demo order above; prepared answers on what is new and what you built |
| Originality | 10 | A narrow, stated contribution with existing work credited. Label-change alerts for patients are the freshest part |

**Statistics safe to use**
- 85.0% of US adults 60 and older used a prescription drug in the past 30 days (CDC/NCHS Data Brief 334, 2015 to 2016).
- Adverse drug events cause more than 1.5 million emergency visits a year (CDC).
- In a pharmacist-run test, free ChatGPT gave satisfactory answers to 10 of 39 drug questions (ASHP, 2023).
- Do not use "125,000 deaths a year" or "50% non-adherence"; their origins are weak or narrower than usually quoted.

## 11. What I could not verify

- The fine-tune to browser conversion for Qwen3.5 has not been run. MLX-LM's documentation lists Qwen2 by name; Qwen3.5 fine-tuning there is untested.
- Phone speed figures come from blogs, not measurements. Measure your own.
- That browser built-in speech sends audio to servers comes from a search summary citing MDN, not from MDN directly.
- The Poison Help number (1-800-222-1222): the official HRSA page blocked my request. Confirm it before shipping.
- A 2025 paper describing a label-grounded chatbot (Koppula et al., MDPI) was blocked. Read it before writing the originality statement.
- The accuracy studies were read as abstracts only.
- WAICY publishes no rule on AI coding help or on what counts as original work. Disclosing is the safe course; you could also email info@waicy.org.
- Label version download and section splitting were tested on three drugs only, with a rough parser.
- Whether a browser can fetch old label versions directly is untested, which is why changes are worked out ahead of time.
- FDA's public list of safety label changes exists, but I could not get records out of it automatically. You can look up individual drugs there by hand to check T5.
- "No patient-facing label-change tool exists" rests on keyword searches of papers, the App Store, and GitHub, plus one web search. A web search suggested Drugs.com sends alerts for a saved medication list; I did not confirm what those cover. Check before writing the originality statement.
- FDA's LabelComp tool was seen as a paper title and abstract only.

## 12. Still needed from you

- The name.
- Who the pharmacist or clinician is, and whether they are free around Thanksgiving. They are needed November 20 to 25.
- Which older adults can test on or near November 26.

## 13. Sources

- Guidebook: https://waicy-cdn.wholeren.cn/wp-content/uploads/2026/10/WAICY-2026-Guidebook-2.pdf
- Rubric: https://www.waicy.org/rubrics/
- openFDA drug labels: https://open.fda.gov/apis/drug/label/ (public domain, CC0: https://open.fda.gov/license/)
- RxNorm: https://www.nlm.nih.gov/research/umls/rxnorm/overview.html
- FDARxBench: https://github.com/xiongbetty/FDARxBench and https://arxiv.org/abs/2603.19539
- MedicationQA: https://github.com/abachaa/Medication_QA_MedInfo2019
- WebLLM: https://github.com/mlc-ai/web-llm ; custom models: https://llm.mlc.ai/docs/deploy/webllm.html
- MLX-LM: https://github.com/ml-explore/mlx-lm
- CDC prescription use: https://www.cdc.gov/nchs/products/databriefs/db334.htm
- CDC medication safety: https://www.cdc.gov/medication-safety/about/index.html
- ASHP ChatGPT study: https://news.ashp.org/News/ashp-news/2023/12/05/study-finds-chatgpt-provides-inaccurate-responses-to-drug-questions
- FDA mobile medical apps guidance: https://www.fda.gov/media/80958/download
- FDA clinical decision support guidance: https://www.fda.gov/media/109618/download
- Apple Health medications: https://support.apple.com/guide/iphone/learn-more-about-your-medications-iph2fcefa8d6/ios
- Medisafe features: https://medisafeapp.com/features/
- DailyMed web services, including label version history: https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm
- FDA Drug Safety-related Labeling Changes: https://www.accessdata.fda.gov/scripts/cder/safetylabelingchanges/
- LabelComp (FDA tool for finding adverse-event changes in labeling, 2024): https://doi.org/10.1007/s40264-024-01468-8
