"""Testers – usability tab: one row per test session, with the System Usability Scale (SUS,
Brooke 1996; 'system' replaced by 'app'). Only a first name or code and an age band are recorded."""

from .tasks import OUT

TAB = "Testers – usability"
CSV = OUT / "usability.csv"
N_ROWS = 20
IDS = [f"U-{i:02d}" for i in range(1, N_ROWS + 1)]
DONE = ["yes", "no", "with help"]
FIVE = ["1", "2", "3", "4", "5"]
AGE = ["under 18", "18-39", "40-59", "60-69", "70-79", "80+"]
STEPS = [("pick_medicine", "Scan or pick a medicine", "Find your medicine in the app: scan the box or pick it from the list."),
         ("dose_question", "Ask a dose question", "Ask the app how much of it to take."),
         ("food_question", "Ask a food or drink question", "Ask whether you can have it with coffee, grapefruit or alcohol."),
         ("change_alert", "Read a label-change alert", "Open the label-change alert and tell me in your words what changed."),
         ("voice", "Use voice", "Ask any question about the medicine by speaking to the app.")]
SUS = ["I think that I would like to use this app frequently.",
       "I found the app unnecessarily complex.",
       "I thought the app was easy to use.",
       "I think that I would need the support of a technical person to be able to use this app.",
       "I found the various functions in this app were well integrated.",
       "I thought there was too much inconsistency in this app.",
       "I would imagine that most people would learn to use this app very quickly.",
       "I found the app very cumbersome to use.",
       "I felt very confident using the app.",
       "I needed to learn a lot of things before I could get going with this app."]

# (column, choices or None, width)
COLUMNS = ([("name", None, 14), ("tester", None, 14), ("age_band", AGE, 11), ("phone", None, 16), ("date", None, 12)]
           + [c for k, _, _ in STEPS for c in ((f"{k}_done", DONE, 12), (f"{k}_minutes", None, 10),
                                                 (f"{k}_comment", None, 30))]
           + [(f"sus_{i}", FIVE, 7) for i in range(1, 11)] + [("sus_score", None, 10)]
           + [("would_use", FIVE, 11), ("what_confused_you", None, 35), ("anything_unsafe_or_wrong", None, 35)])
CHOICES = {c: ch for c, ch, _ in COLUMNS if ch}
INPUTS = [c for c, _, _ in COLUMNS if c != "sus_score"]

WHAT = ("For the person running a test session: one row per session. Read the script below, then fill in a free "
        "row (U-01, U-02, ...). Type your own first name in 'name' and only the tester's first name or a code in "
        "'tester'. sus_score fills itself in.")
SCRIPT = "\n".join(
    [("SCRIPT. Say: \"We're testing the app, not you. Please think aloud. There are no wrong answers, and you can "
     "stop at any time.\" Use the demo medicines; don't record any health details. If they ask about their own "
     "medicines, suggest they ask their pharmacist."),
     ("Give each task without showing how. If they are stuck for about a minute, help and mark 'with help'. Note the "
     "minutes for each task.")]
    + [f"{i}. {name}: \"{say}\"" for i, (_, name, say) in enumerate(STEPS, 1)]
    + [("Then read these 10 statements (columns sus_1 to sus_10) and record 1 = strongly disagree to "
       "5 = strongly agree:")]
    + [f"   sus_{i}: {s}" for i, s in enumerate(SUS, 1)]
    + ["Last, ask: Would you use it (1–5)? What confused you? Did anything feel unsafe or wrong?"])


def sus_score(row: dict) -> str:
    try:
        v = [int(row[f"sus_{i}"]) for i in range(1, 11)]
    except (KeyError, ValueError):
        return ""
    return f"{(sum(x - 1 for x in v[0::2]) + sum(5 - x for x in v[1::2])) * 2.5:g}"
