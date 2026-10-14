# Issue 草稿（可直接提交到 deepan-alve/F1-model）

> 标题建议：
> **`Lapped` finishers are flagged as DNF — this corrupts the training target and inflates the reported Spearman**

---

## Summary

`Lapped` finishers (classified, ran the full distance, just a lap down) are being
treated as DNFs. Their `FinishPosition` is overwritten to `21`, which does three things:

1. inflates the reported Spearman correlation,
2. gives the ranker a wrong training target,
3. corrupts the DNF-derived features.

This is not a logic error in the usual sense — the regex was **correct when it was
written**. FastF1 changed how it represents lapped finishers in 2023, so the code has
been silently wrong for every season since.

---

## Where

`src/data_pipeline.py:163` and the duplicated block at `src/data_pipeline.py:258`:

```python
# Add DNF flag: classified finishers include "Finished" and "+N Lap(s)"
merged["DNF"] = ~merged["Status"].str.match(r"^(Finished|\+\d+ Laps?)$", na=True)

# Encode finish position: DNFs get position 21
merged["FinishPosition"] = merged["Position"].copy()
merged.loc[merged["DNF"], "FinishPosition"] = 21
```

The comment states the intent exactly right. The regex doesn't implement it:
**`Lapped` never matches `^(Finished|\+\d+ Laps?)$`**, so every lapped-but-classified
finisher is flagged as a DNF and gets `FinishPosition = 21`.

---

## Why it used to work

FastF1 changed the `Status` value for lapped finishers:

| Season | Lapped finisher `Status` |
|---|---|
| 2018–2022 | `+1 Lap`, `+2 Laps`, `+3 Laps`, … |
| **2023–2026** | **`Lapped`** |

I verified this against a full 2018–2026 results database: **406 rows carry
`Status = 'Lapped'`, and every single one falls in 2023–2026**
(70 / 138 / 89 / 109).

His `test_years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]` — **4 of the 7 evaluated
seasons are affected**, and since `train = df[df.Year < test_year]`, the training sets
for 2024–2026 are affected too.

---

## Impact

### 1. Reported accuracy is inflated

Same predictions, two targets, 2026 R1–R15 (the 15 races present in
`data/results/2026_*.json`):

| Target | Spearman |
|---|---:|
| current (`Lapped` tied at 21.0) | **0.6898** |
| correct classification | **0.6559** |

**172 of 330 entries (52.1%)** in those files are tied at `21.0`. Ties remove those
drivers from the ordering task entirely — Spearman is then computed on a much smaller,
much easier subset (the front of the field, which grid position already solves).
It's effectively grading only half the paper.

> To be explicit: this is **not** a claim that the numbers are fabricated. I recomputed
> the `spearman` field in each of the 15 JSON files and reproduced them to 0.0000 — the
> arithmetic is right, the target variable is wrong.

### 2. The training target is wrong

`backtest.py:64` builds the label from this column:

```python
y = (21 - data["FinishPosition"].values).astype(int)
```

A driver who finished the race one lap down gets the same relevance label (`0`) as a
driver who retired on lap 3. The ranker is being taught that **"slow but running" ==
"out of the race"** — which is precisely the distinction a race-pace model should be
sharpest at.

### 3. The DNF features are wrong

`DNF` isn't only used for the target. It flows into the feature pipeline:
`driver_dnf_rate` and `constructor_reliability` are both derived from it, so from 2023
onwards they systematically over-count DNFs. The DNF classifier is also trained on this
same flag.

---

## Suggested fix

FastF1 already exposes the official classification, so the regex isn't needed at all:

```python
merged["ClassifiedPosition"] = pd.to_numeric(merged["ClassifiedPosition"], errors="coerce")
merged["FinishPosition"] = merged["ClassifiedPosition"].fillna(21)
```

`ClassifiedPosition` is **numeric for every classified finisher** (including `Lapped`)
and `R` / `W` / `D` for those not classified. Verified present and correctly populated
in 2018, 2021, 2022, 2024 and 2026.

This also handles an edge case the regex can't: in 2026 R1, **STR has `Position = 17`
but `ClassifiedPosition = R`** — lapped *and* outside 90% of the race distance, so not
officially classified. The patched regex would still call him a finisher.

If you'd rather keep the regex, one alternative branch fixes it:

```diff
- merged["DNF"] = ~merged["Status"].str.match(r"^(Finished|\+\d+ Laps?)$", na=True)
+ merged["DNF"] = ~merged["Status"].str.match(r"^(Finished|Lapped|\+\d+ Laps?)$", na=True)
```

Either way, worth extracting into a single helper — the same expression currently
appears in two branches, which is part of why this survived unnoticed.

---

## How I verified

I cross-checked his `actuals` against an independent 2018–2026 database:

> **The number of entries with a real (non-`21.0`) `FinishPosition` in his JSON files
> equals the number of rows with `Status = 'Finished'` in mine — 15/15 races, exactly**
> (6, 8, 17, 10, 4, 15, 5, 8, 16, 17, 7, 7, 15, 8, 15).

That's the signature of the regex, not of FastF1. FastF1 returns a real `Position` for
lapped finishers; they're being overwritten downstream.

---

## Two notes, in the interest of being fair

- **The direction of the fix is in your favour.** A correct target doesn't just lower
  the reported number — it gives the ranker a *better* signal, especially for
  `driver_dnf_rate` / `constructor_reliability`. The 0.6559 above is measured with the
  current model, so it's the floor, not the ceiling.
- **Your `regulation_confidence` feature and the REG CHANGE tracking in `backtest.py`
  are the right instinct** — the same discontinuity shows up independently in my own
  project: on 2026 the pre-qualifying blend is *worse* with Elo than without it
  (0.6372 → 0.6491), because Elo carries pre-2026 car performance into a season where
  the pecking order was reshuffled.

Happy to open a PR for the `ClassifiedPosition` version if that's the direction you'd
prefer.
