# PillProof

**Your medicine labels, explained — on your device.** WAICY 2026 AI Showcase, High School.

PillProof is a web app for people who manage several daily medicines, especially older adults. You add your medicines, and then ask questions by typing or by voice, such as "Can I drink grapefruit juice with atorvastatin?" or "What if I miss a dose?". A small language model that we fine-tuned runs **inside your browser**. For each medicine question it may only do two things: point to the exact sentences in that medicine's FDA label and restate them plainly, or say the label doesn't cover it and suggest asking a pharmacist. Every quote shown is copied from the real label by code, never written by the model. The app also shows what changed in a medicine's safety label over time, old text beside new. Your medicine list and questions stay on your device.

> **Not medical advice.** PillProof shows information from FDA labels and other public sources. It can be wrong. It never tells you to change a dose or stop a medicine. Always ask your pharmacist or doctor. In an emergency call 911 or Poison Help at 1-800-222-1222.

## Try it

**Live app: https://mattjunior039.github.io/pillproof/**

1. Open it in **desktop Chrome or Edge** (version 113 or newer) on a computer with a GPU. The answer model needs **WebGPU**. Safari 26 and newer also have WebGPU. Firefox support depends on the platform. Without WebGPU the app still works, but shows the matching label sentences instead of a written answer.
2. On **Medicines**, add a medicine (for example *atorvastatin*) and pick the product.
3. On **Ask**, press **Download model** once, then ask a question.

| Model | Used on | First download | First load (fresh browser) |
|---|---|---|---|
| `r1-ft` (Qwen3.5 2B, fine-tuned, 4-bit) | computers | about 1.0 GB | about 98 s |
| `lite-r1-ft` (Qwen3.5 0.8B, fine-tuned, 4-bit) | phones; also selectable on computers in Settings | about 433 MB | about 40 s |

Times were measured in Chrome on an M5 Pro Mac on home internet; slower connections take longer. After the first load the model is cached and the app works offline. Phones always get the 0.8B model (the 2B runs out of memory on phones).

**What works on the public site:** the label answers, other FDA labels for the same medicine, the FDA food-and-drink pages, the DDInter drug–food database, label-change history, voice input, and the calendar file. **Web search is turned off** on the public site because a static site cannot hold the search API key; it is available in the local version. See [docs/app.md § Public site](docs/app.md#public-site-github-pages).

## How it works

1. **You pick the exact product** from RxNorm (the US drug-name database). The app downloads its FDA label from openFDA and splits it into numbered sentences.
2. **Routing.** Emergency words get a fixed Poison Help / 911 message. Schedule questions ("what's next today?") are answered by ordinary code. Only label questions reach the model.
3. **Retrieval.** Hybrid keyword + embedding search finds the label sentences closest to your question. If a key word of your question (for example "grapefruit") is not in the label at all, the app says so instead of guessing.
4. **Fine-tuned model.** Qwen3.5 (2B or 0.8B), LoRA fine-tuned by us on FDARxBench label questions, replies with the sentence numbers that answer the question plus one plain restatement, or "NOT IN LABEL". It runs in the browser with WebLLM.
5. **Checks.** Code checks every number, unit and drug name in the restatement against the cited sentences, and blocks answers that drop a warning. If a check fails, you see only the label quotes.
6. **Backup sources**, only when your own label doesn't answer: other FDA labels with the same ingredients, FDA consumer pages, then DDInter 2.0. Each answer from them is clearly marked "Not on your label".

More: [docs/app.md](docs/app.md) (the app), [docs/plan.md](docs/plan.md) (project plan), [docs/gate2.md](docs/gate2.md) (fine-tuning and checks), [docs/release.md](docs/release.md) (models on Hugging Face).

## Results

Final test-set results: [docs/final-eval.md](docs/final-eval.md).

On the development set, the fine-tuned 2B model with checks gave about a third as many wrong answers as the same base model given the same label passages (14.0% vs 40.6% wrong on phone-size prompts; [docs/gate2.md](docs/gate2.md)). Label-change detection is described in [docs/label-changes.md](docs/label-changes.md).

## Models

- 2B: https://huggingface.co/mattjunior/PillProof-Qwen3.5-2B-r1-q4f16_1-MLC
- 0.8B: https://huggingface.co/mattjunior/PillProof-Qwen3.5-0.8B-r1-q4f16_1-MLC

## Team

Matthew Flowerhill, Albert Toy, Tiyaan Kini, Advait Gowda, Neil Gupta.

## AI assistance

We used AI tools, and we say where:
- **Code and documentation** were written with AI coding agents (Anthropic Claude models in the GitHub Copilot app) working under our direction. We chose the idea, the design and the evaluation rules, and reviewed and tested the results.
- **Training data.** The plain-language answer lines in the training (not evaluation) data were simplified by Claude Sonnet 5.5 under automatic number, unit and drug checks ([docs/data.md](docs/data.md)). The FDARxBench questions themselves were generated by its authors with GPT-4o-mini.
- **Audits.** A first-pass audit of training rows was done by an AI assistant and then checked by hand on a sample ([docs/data.md](docs/data.md)).
- **The model in the app** is our fine-tune of the open Qwen3.5 models. No commercial chatbot is used when you ask a question.

## Licences

- **Code:** MIT ([LICENSE](LICENSE)).
- **Data in this repository** keeps its own licence; see [NOTICE](NOTICE). In short: FDA label text and FDA pages are US government works (public domain); FDARxBench is Apache-2.0; `app/data/ddinter_food.json` is adapted from DDInter 2.0 and is **CC BY-NC-SA 4.0** (attribution, non-commercial, share-alike), so PillProof is non-commercial while it is included.
- **Models:** Apache-2.0 (Qwen3.5 base licence), see the Hugging Face model cards.

## Run it locally

```sh
cd app
npm install
npm run dev      # http://localhost:5173 (web search works if TAVILY_API_KEY is set in ~/waicy-work/.env)
npm test
```

The local version can also serve locally built models; see [docs/app.md](docs/app.md#run).
