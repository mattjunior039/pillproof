# PillProof showcase: selected answers from the final evaluation

**These are selected examples, not typical results.** They were picked by hand from the single frozen final-evaluation run (tag `freeze-2026-11-25`), for the slides and the video. Each test set was run once; nothing here was chosen from reruns. Examples 1–9 were each graded acceptable by the AI grader: *correct*, *useful-correct* on T6, or, for #6, *declined* on a question the label does not cover. Example 10 is label-change data, not a graded answer. The overall numbers, including where PillProof loses, are in [final-eval.md](final-eval.md). On the consumer-phrased T3 questions, the full app gave an acceptable answer to 55% of questions (2B) and 53% (0.8B). A general chatbot with no label scored 97%.

Every answer is quoted exactly as the app shows it (`shown_text`). Raw outputs are in `~/waicy-work/data/build/final/app/` and the grades in `.../final/grades/`.

- **F2b** is the full app on desktop: fine-tuned Qwen3.5-2B (r1), label first, then backup sources and web search.
- **F08** is the same on phone settings, with the 0.8B "lite" model.
- **C** is the label-only app.

Unless noted, the phone (F08) answer got the same grade.

---

## 1. Grapefruit on a statin: T3-016 (Lipitor label)

**Question:** "I love grapefruit juice in the morning. Can I still have it with Lipitor?"

**App (F2b; F08 and C on both tiers also correct):**
> Your label says: Avoid drinking more than 1.2 liters of grapefruit juice each day. Plasma LIPITOR concentrations are lower (approximately 30% for Cmax and AUC) following evening drug administration compared with morning. Intervention: Avoid intake of large quantities of grapefruit juice, more than 1.2 liters daily, when taking LIPITOR. This is information from the FDA label, not medical advice for you.

This is the label's own sentence, quoted word for word. One extra sentence about evening dosing is true but off-topic.

## 2. A dose limit from a drug interaction: T3-007 (Norvasc label)

**Question:** "I also take simvastatin for my cholesterol. Is that a problem with amlodipine?"

**App (F2b):**
> Taking simvastatin with amlodipine raises the amount of simvastatin in your body (systemic exposure). So the dose of simvastatin should be limited to 20 mg daily. The label says: Co-administration of simvastatin with amlodipine increases the systemic exposure of simvastatin. Limit the dose of simvastatin in patients on amlodipine to 20 mg daily [see Clinical Pharmacology (12.3) ] . This is information from the FDA label, not medical advice for you.

The number check confirmed that "20 mg" appears in the cited sentence before the plain-language version was shown.

## 3. Crushing a tablet: T3-110 (Xarelto label)

**Question:** "I can't swallow my Xarelto pill. Can I crush it?"

**App (F2b):**
> Yes, you can crush the Xarelto tablet. You can crush it and mix it with applesauce right before you take it. The label says: For adult patients who are unable to swallow whole tablets, XARELTO tablets (all strengths) may be crushed and mixed with applesauce immediately prior to use and administered orally. This is information from the FDA label, not medical advice for you.

## 4. A missed dose: T3-028 (Plavix label)

**Question:** "I forgot my Plavix this morning and it's now evening. Do I take it?"

**App (F2b):**
> If you forget your Plavix, take it as soon as you remember. If it is almost time for your next dose, skip the missed dose. Take your next dose at your regular time. The label says: If you miss a dose, take Plavix as soon as you remember. If it is almost time for your next dose, skip the missed dose. This is information from the FDA label, not medical advice for you.

The grader noted that the label's "don't take two doses at once" line was left out.

## 5. Possible emergency: T3-067 (Zestril label)

**Question:** "My face and lips are swelling up. I take Zestril. What should I do?"

**App (F2b):**
> Tell someone right away if you have signs of angioedema (swelling under the skin), such as swelling of the face, arms, eyes, lips, tongue, or trouble swallowing or breathing. The label says: Tell patients to report immediately any signs or symptoms suggesting angioedema (swelling of face, extremities, eyes, lips, tongue, difficulty in swallowing or breathing) and to take no more drug until they have consulted with the prescribing physician. This is information from the FDA label, not medical advice for you.

## 6. A decline done well: T3-111 (Xarelto label; the label does not cover this)

**Question:** "Can I have a glass of wine with my Xarelto?"

**App (F2b, after checking other labels, the FDA food pages, DDInter and the web):**
> Your label doesn't answer this. None of the sources we checked mention “alcohol” and “glass” with this medicine. Ask your pharmacist. This is information from the FDA label, not medical advice for you.

It does not guess "a little is fine" for a blood thinner. The app also links the MedlinePlus rivaroxaban page.

## 7. Web answer with a source badge: T6-11 (Synthroid; the label is silent on coffee)

**Question:** "Can I drink my morning coffee right after I take my thyroid pill?"

**App (F2b and F08: useful-correct; label-only C: correct but unhelpful):**
> Your label doesn't answer this. From the web (Patient.info). not your label, may be wrong. It says: Take levothyroxine on an empty stomach with water and wait at least 30–60 minutes before drinking coffee or other beverages. Drinking coffee at the same time as taking levothyroxine can significantly reduce the amount of medicine your body absorbs. Do not take calcium tablets, iron supplements, or multivitamins at the same time as levothyroxine. Ask your pharmacist about this. …

Source badge: *From the web (Patient.info), not your label, may be wrong*. It links to https://patient.info/medication-interactions/levothyroxine-and-coffee-interaction.

**Known flaw, not fixed because the app is frozen:** the app's standard footer still says "This is information from the FDA label" under web answers.

## 8. Web answer for a food interaction: T3-142 (warfarin; the label does not mention cranberry)

**Question:** "Is cranberry juice OK with warfarin?"

**App (F2b and F08: correct; label-only C declined):**
> The label does not mention “cranberry juice”. That does not mean it is safe or unsafe. From the web (Medsafe (New Zealand)). not your label, may be wrong. No, you should avoid cranberry products because they may interact with warfarin. If you take warfarin, you should have more frequent INR (blood clotting) checks. It says: Patients should avoid cranberry products due to a possible interaction with warfarin. Consider more frequent INR monitoring for any patient taking warfarin and regular cranberry juice. Ask your pharmacist about this. This is information from the FDA label, not medical advice for you.

Source: https://www.medsafe.govt.nz/profs/PUArticles/December2022/Warfarin-eat-drink-and-be-wary.html (the same footer flaw as #7).

## 9. A short, direct label answer: T6-16 (Zoloft label)

**Question:** "Can I have a beer now and then while I'm on Zoloft?"

**App (F2b, F08 and label-only C, all useful-correct):**
> Your label says: Do not drink alcohol while you take ZOLOFT. This is information from the FDA label, not medical advice for you.

## 10. Label-change alert: Lipitor missed-dose advice, April 2024

The source is `app/data/label_changes.json`, shown in the app's **Label changes** view with the old sentence on the left and the new one on the right. The update dated 2024-04-08 (label version 4 → 5, effective 2024-04-15) changed what to do after a missed dose:

| | Before (v4) | After (v5) |
|---|---|---|
| removed `cec43e7bcc2` | If you miss a dose of LIPITOR, take it as soon as you remember. | — |
| removed `cf3a8c0bf3d` | Do not take LIPITOR if it has been more than 12 hours since you missed your last dose. | — |
| altered `ca114ed2058` | Wait and take the next dose at your regular time. | If you miss a dose of LIPITOR, wait and take the next dose at your regular time. |
| added `c4f9abb1fb7` | — | If a dose is missed, advise patients not to take the missed dose and resume with the next scheduled dose. |

Someone who learned the old rule ("take it if it's under 12 hours") would now be doing the opposite of the label. The Today screen flags this as "Label updates in the past year". The shipped alert data marks changes with the similarity rule (`judged_by: baseline`). It has no model-written explanations, so none is shown here; see the T5 results in [final-eval.md](final-eval.md#t5-label-change-detection).
