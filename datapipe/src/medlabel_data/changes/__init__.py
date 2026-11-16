"""Label-change pipeline (plan section 5, "How label changes are found").

extract  -> safety-section sentences per label version
align    -> candidate changed sentences between consecutive versions
baseline -> text-similarity rule (meaning changed / reworded)
build    -> runs both for the 25 T3/T5 drugs
sample   -> development sample, T5 marking sheet, pharmacist subset
judge    -> model-judging harness (MLX) and scoring against the T5 marks
appdata  -> small JSON shipped with the app
"""
