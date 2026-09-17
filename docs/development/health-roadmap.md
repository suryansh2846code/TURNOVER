# Health & Fitness — what is built, and what is next

> The running record for this agent. What shipped is in
> [`health.md`](health.md); this is the ranked list of what has not, with the
> reasoning that produced the order, so the next session does not re-derive it.
>
> Last rated **8.5 / 10**.

## Where it stands

| | |
|---|---|
| **Knows what happened** | Apple Health and Google Fit exports, manual logging, a full training log |
| **Counts instead of guessing** | volume, smoothed trends and 1RM estimates are arithmetic; `run_python` for the rest |
| **Will not fabricate** | told never to present a remembered number as a measurement, and given `whats_tracked` so that is followable |
| **Knows where it stops** | the clinical boundary follows the capability, so an agent the user assembles inherits it |
| **Says what is noise** | no trend under ~10 days, two weeks is not a trend, an estimate names its formula |
| **Works on day one** | `needs=[]` — no accounts, no export, you say a number and it records it |

---

## 1. A plan to review against — **the biggest gap**

The *actuals* side is built thoroughly and the *intended* side does not exist.
`lift_progress` can say volume rose 12%. Nothing can say whether that is what
was **supposed** to happen, because a programme only exists as prose in a file
or a chat message.

So "am I following the plan?" means the agent re-reading prose and eyeballing it
against the log — exactly the estimation this whole build removed everywhere
else. It is the difference between a dashboard and a coach.

**Shape:** the same one `training.py` already has, twice over. A programme is
blocks with *target* sets/reps/weight on a schedule; adherence is then exact
arithmetic against the log rather than an impression. `log_workout`'s editable
card is the pattern for accepting one.

**Cost:** low — the pattern exists and is tested twice. **Value:** highest of
anything left.

## 2. Nutrition input

`energy_in`, `protein`, `energy_total` can all be *stored*, and nothing can turn
*"two eggs and rice"* into any of them. Half of "train, eat and recover" only
works for someone already logging in another app.

**Two routes, and the order matters.** Import from Cronometer / MyFitnessPal
exports first: real numbers the user already trusts, no maintenance burden, and
`ExportConnector` makes it one `_read`. A bundled food database second, or
never — a calorie table is a data problem with a long tail, and a wrong one is
worse than none.

**Cost:** low for the importer, high for the database.

## 3. HRV, carbs, fat, water — **about ten lines**

Recovery is currently sleep and RPE. HRV is sitting in the Apple Health export
right now (`HKQuantityTypeIdentifierHeartRateVariabilitySDNN`) and is not
mapped. Carbs and fat matter as much as protein for a bulk or a cut, and are
not there beside it.

```
hrv    ms    HKQuantityTypeIdentifierHeartRateVariabilitySDNN
carbs  g     HKQuantityTypeIdentifierDietaryCarbohydrates
fat    g     HKQuantityTypeIdentifierDietaryFatTotal
water  ml    HKQuantityTypeIdentifierDietaryWater
```

Four entries in `METRICS`, four in `QUANTITIES`. Deliberately held back from
the Google Fit change to keep that one about Google Fit.

**Cost:** trivial. Do it alongside anything.

## 4. Proactivity — blocked on the scheduler

*"You have not logged a weight in two weeks"* is a routine, and routines run on
`scheduler.py` — 30% coverage, `AUDIT.md` A12. A coach that never speaks first
is missing the main mechanism of coaching.

**Owned elsewhere.** Not to be picked up here without checking.

## 5. Exercise-specific depth

Per-lift progression works. What is missing is anything richer than
sets × reps × weight: tempo, rest, unilateral work, supersets, drop sets. Each
is a column or a flag and none of them is asked for yet.

**Wait for a real request.** Adding fields nobody fills is how a log becomes one
nobody keeps.

## 6. More sources

`ExportConnector` made the second importer cheap and will make the third
cheaper. In rough order of how many people would use them:

| source | route | notes |
|---|---|---|
| **Strava** | real OAuth API | the one major fitness source with a live, open API. Rate-limited, documented, no ban risk. |
| **Fitbit** | Google Health API (the former Fitbit Web API) | live and supported — and it is *Fitbit* data, not Google Fit |
| **Whoop / Oura** | OAuth APIs | both have real APIs; both are subscription devices, so smaller audiences |
| **Cronometer / MyFitnessPal** | export | see §2 |
| **Garmin** | export, or a partner API | the partner programme is not open to small developers |

Worth saying once: several of these already have MCP servers. A user can
connect one today and the Health agent reaches it through the connector
category under the existing permission gate — which may be the whole answer for
the long tail, at no cost to us.

---

## Decisions already taken, so they are not re-litigated

* **Measurements are not memories.** Recall is linear in memory count; one
  export filed as memories costs every agent about a second per turn, forever.
* **One unit per metric, unknown units refused.** A silent assumption turns
  170 lb into 170 kg.
* **Trends are smoothed and say what they are based on.** Body weight moves a
  kilo a day on water.
* **`energy_out` and `energy_total` never mix.** Apple reports active energy;
  Google Fit reports the total including basal metabolism. They are different
  numbers and a combined series would be meaningless for anyone who changed
  device.
* **Min heart rate is not resting heart rate.** Google Fit's daily summary has
  no resting HR column, and the near-miss is not imported.
* **No exercise taxonomy.** Names match case-insensitively; the user's spelling
  is what shows.
* **Data entry the model interpreted lands on an editable card**; a plain
  number does not. The test is how much interpretation sits between what was
  said and what gets stored.
* **No live Google Fit API is coming.** Deprecated 1 May 2024, closed to new
  signups the same day, shutting down; Health Connect is Android-only and
  on-device; the Google Health API is Fitbit's. The export is the path.
