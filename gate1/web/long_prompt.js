// A realistic app-sized prompt for speed/memory tests: instructions, a question,
// and 20 numbered sentences in the style of an OTC "Drug Facts" label
// (acetaminophen 500 mg, paraphrased). About 1,000 tokens with the chat template.
const SENTENCES = [
  "Active ingredient (in each caplet): acetaminophen 500 mg; purpose: pain reliever and fever reducer.",
  "Uses: temporarily relieves minor aches and pains due to the common cold, headache, backache, minor pain of arthritis, toothache, muscular aches, and premenstrual and menstrual cramps, and temporarily reduces fever.",
  "Liver warning: this product contains acetaminophen, and severe liver damage may occur if an adult takes more than 4,000 mg of acetaminophen in 24 hours.",
  "Severe liver damage may also occur if you take this product with other drugs containing acetaminophen, or if you have 3 or more alcoholic drinks every day while using this product.",
  "Allergy alert: acetaminophen may cause severe skin reactions, and symptoms may include skin reddening, blisters, or rash; if a skin reaction occurs, stop use and seek medical help right away.",
  "Do not use with any other drug containing acetaminophen (prescription or nonprescription); if you are not sure whether a drug contains acetaminophen, ask a doctor or pharmacist.",
  "Do not use if you are allergic to acetaminophen or any of the inactive ingredients in this product.",
  "Ask a doctor before use if you have liver disease.",
  "Ask a doctor or pharmacist before use if you are taking the blood thinning drug warfarin.",
  "Stop use and ask a doctor if pain gets worse or lasts more than 10 days, or if fever gets worse or lasts more than 3 days.",
  "Stop use and ask a doctor if new symptoms occur, or if redness or swelling is present, because these could be signs of a serious condition.",
  "If pregnant or breast-feeding, ask a health professional before use.",
  "Keep out of reach of children; in case of overdose, get medical help or contact a Poison Control Center right away, even if you do not notice any signs or symptoms.",
  "Directions: do not take more than directed, because taking more than the recommended dose (overdose) may cause liver damage.",
  "Adults and children 12 years and over: take 2 caplets every 6 hours while symptoms last.",
  "Do not take more than 6 caplets in 24 hours, unless directed by a doctor.",
  "Do not use for more than 10 days unless directed by a doctor.",
  "Children under 12 years: ask a doctor before use.",
  "Other information: store between 20 and 25 degrees C (68 and 77 degrees F), avoid excessive heat above 40 degrees C (104 degrees F), and do not use if the printed neck wrap or the foil inner seal imprinted with \"Sealed for your protection\" is broken or missing.",
  "Inactive ingredients: carnauba wax, corn starch, hypromellose, magnesium stearate, polyethylene glycol, povidone, pregelatinized starch, sodium starch glycolate, and titanium dioxide.",
];

export const LONG_PROMPT = [
  "You are MedLabel. Answer the question using ONLY the numbered sentences from the official drug label below.",
  "Rules: cite the sentence numbers you used in square brackets, like [3]. Quote the label's wording for any dose or warning.",
  "If the label does not answer the question, say \"The label does not say\" and suggest asking a pharmacist. Do not give advice that is not in the label.",
  "Write for a teenager or an older adult: short sentences, plain words, no more than 6 bullet points, and end with one line saying when to stop and call a doctor.",
  "",
  "Label: Acetaminophen 500 mg caplets (Drug Facts)",
  ...SENTENCES.map((s, i) => `[${i + 1}] ${s}`),
  "",
  "Question: I'm 45, I take warfarin every day, and since yesterday I've had a bad headache and a fever of about 38.5 C. I already took a cold medicine this morning but I don't remember what was in it. How many of these caplets can I take in a day, how long can I keep taking them, and is it OK with my warfarin and a couple of beers each night?",
].join("\n");
