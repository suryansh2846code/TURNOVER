# Measuring, and the Health agent — the contract

> Written alongside the code, per `/CLAUDE.md`. Spans `metrics.py`,
> `connectors/`, `agents/` and the prompt.

## 1. What was wrong

The Health agent's own brief told it to *"review honestly rather than
encouragingly"*. It had nothing to review and no way to count.

* **No measurements.** A weight, an hour of sleep, a session done — all went
  into the brain as prose, in the same pile as the user's email. The only way
  back was recall, so *"am I actually gaining?"* was answered by a model reading
  a handful of retrieved sentences and estimating. The repo already had the rule
  written down for the Inbox agent: **a number you estimated is a number you made
  up.** Health was the agent that most needed it and the one that did not have it.
* **No arithmetic.** No `run_python`. Weekly volume, protein totals, rate of
  change — all in the model's head.
* **No files.** Every gym app and food tracker exports CSV, and it could not
  open one.
* **One sentence of boundary.** *"You are not a clinician; say so when a
  question needs one."* True, and nowhere near enough for the questions this
  agent gets asked.

Rated as a product it was a good conversation with a memory. It could not
measure, compute or verify anything, which is the whole second half of its job.

## 2. Measurements are their own store, not the brain

`lodestone/metrics.py`. Three reasons, and the first is decisive:

* **Recall is linear in memory count.** `store.search()` runs on *every* agent
  turn at ~0.05 ms per memory (`docs/SCALING.md`). One Apple Health export is
  tens of thousands of readings. Filed as memories they would put about a
  second onto every turn of every agent, permanently, to answer questions
  nobody asks by similarity.
* **The access pattern is a range, not a search.** "Weight, last ninety days"
  is an index lookup. Nothing here is ever retrieved by meaning.
* **Claims supersede; readings accumulate.** *"Their goal weight is 60 kg"* is a
  claim and belongs in `brain/canonical`. *"They weighed 78.4 kg on Tuesday"* is
  not superseded by Wednesday — both happened, and the series is the point.

It is `metrics.py` and not `health.py` deliberately: the shape is a numeric
series over time and the Money agent wants exactly the same thing. One store
both can use beats two that drift apart.

### One unit per metric, converted on the way in

A series with kilograms and pounds mixed into it is not a series, and every
average over it is wrong. So each metric has a canonical unit, input is accepted
in the usual spellings, and **an unrecognised unit is refused rather than
assumed** — a silent assumption turns 170 lb into 170 kg, which is not a
rounding error, it is a different person.

`convert()` always accepts a metric's own unit. That is a structural guarantee
rather than an entry in each `accepts` map, because the entry was missing for
`steps` and every daily total from Apple Health was refused on the way in —
quietly, which is how it survived being written. `test_metrics.py` pins the
property for every metric.

### The trend is smoothed, and says so

Body weight moves a kilo or two a day on water alone. `last - first` over two
readings is mostly noise and reads as a result — *"you gained a kilo
overnight"* is the most common wrong thing said in this entire subject.

So `summarise()` reports the raw change **and** a trend built from 7-day
averages at each end, with a per-week rate and a line naming what it was based
on. Under about ten days of data the trend is **not reported at all** rather
than reported badly, and the payload says why.

### A refused row is named, never dropped

`log_many` returns `{stored, refused}` and the connector surfaces every reason.
One malformed reading must not kill an import of twenty thousand — but an import
that quietly stores two thirds of a file looks exactly like one that worked, and
nothing in the result would say which third is missing.

### A wrong reading can be removed

`forget_measurement` — scoped to manually-logged readings. A fat-fingered `780`
otherwise sits in the series forever, poisoning every average, visible to the
user and fixable by nobody. Device readings are corrected by re-importing, not
by the agent deciding to delete them.

## 3. Apple Health: the export, because there is no API

HealthKit is iOS-only. The Health app does not exist on macOS and nothing on a
Mac can query it. The one sanctioned path is the export the Health app itself
offers — *Health → your picture → Export All Health Data* — and reading a file
the user handed us is the most local-first thing in the product: nothing leaves
the machine, no account is involved.

| decision | why |
|---|---|
| **Streamed with `iterparse`, straight out of the zip** | A few years of an Apple Watch is commonly 300 MB of XML and can pass a gigabyte. The tree is cleared as it goes, or the parser retains everything and peak memory is the file size again. |
| **Cumulative metrics summed per day** | Steps arrive as hundreds of samples a day. Nobody asks how many steps fell between 14:05 and 14:09. |
| **Point metrics kept individually** | Weight, resting heart rate, VO2 max — there are few and each one matters. |
| **`auto_sync = False`** | The file only changes when the user exports a new one. Re-parsing a gigabyte every thirty minutes to find nothing is the opposite of what the background loop is for. |
| **Dedup on (metric, at, source)** | The user points at a fresh export in three months, overlapping the old one entirely. A second import upserts; it does not double a year of data. |

Three readings that are wrong without looking wrong, and are pinned:

* **`InBed` is not sleep.** Apple records time in bed alongside the asleep
  stages; counting it adds an hour of lying awake to every night.
* **Body fat arrives as a fraction in some exports and a percentage in others.**
  Nobody has 1% body fat and nobody has 90%, so the ranges do not overlap and
  reading `0.184` as `18.4%` is a safe read rather than a guess.
* **`count/min` is Apple's spelling of bpm**, and `mL/min·kg` of VO2 max.

No new endpoint: `POST /api/connectors/apple_health/sync` with
`{"params": {"path": "…/export.zip"}}` already works, and the chosen file is
remembered in `connector_state` the way the Files connector remembers folders.
An unzipped `export.xml` is accepted too — somebody will unzip it first, and
refusing that would be refusing the same data for the shape of its wrapper.

## 4. What the agent got

| tool | for |
|---|---|
| `whats_tracked` | what data actually exists. **Called before saying anything about progress.** |
| `measurement_history` | one metric over time, with the arithmetic already done |
| `log_measurement` | recording a reading, in the unit the user said it in |
| `forget_measurement` | correcting one that was wrong |

Plus `run_python` — it lives on arithmetic — and the file tools, because the
rest of the numbers are in a CSV some other app exported.

`needs=[]`, deliberately. It works on the first day with no connectors at all:
the user says a number and it records it. Apple Health makes it better, not
possible.

## 5. The boundary follows the capability, not the template

`prompt._health_safety(tools)` attaches the block to any agent holding the
measurement tools, rather than writing it into the Health template's prose.

That is the whole point: a user who assembles their own *"Nutrition coach"* out
of the same tools is the agent **most** likely to be asked something it should
not answer, and it inherits no prose from a shipped template. Deriving it from
capability means it cannot be forgotten. Chief of Staff holds every tool, so it
gets the boundary too — which is correct, not incidental.

What it says:

* **Not a clinician.** Never diagnose, never name a dose, never tell someone to
  start, stop or change a medication. Conditions, pregnancy, medication, a
  recent injury → say plainly it needs their doctor, say what it *can* still
  help with, move on.
* **Red flags stop the conversation**: chest pain, fainting, blood, sudden
  unexplained weight change, numbness, an injury that is not improving.
* **Restriction is named once.** If a goal would mean severe undereating,
  very fast loss, or training through real pain — say so **once**, plainly,
  without lecturing, offer the sustainable version, then help with that. A
  disclaimer repeated every turn is one the user learns to skip, which is the
  same as not having said it. And it does **not** refuse ordinary training and
  nutrition work because the topic is food.
* **Say what is unsettled.** Nutrition and training science disagrees with
  itself constantly; presenting one protocol as fact is how people end up
  certain about something wrong.
* **Never present a remembered number as a measurement.** A weight is a fact
  only if it came back from `measurement_history` or `whats_tracked`.

## 6. Deliberately still open

* **No food database.** "I ate two eggs" does not become 140 kcal; the user or
  another app supplies the number. A calorie table is a data problem, not an
  agent one, and a wrong one is worse than none.
* **No exercise-specific logging.** Sets, reps and load per lift are richer
  than one number a day and want their own shape. `workout_minutes` and `rpe`
  cover the training *load* question in the meantime.
* **Strava, Whoop, Oura, MyFitnessPal.** All have real APIs. Each is a
  connector that writes into the same store — the store was built general for
  this reason.
* **No proactive check-in.** "You have not logged a weight in two weeks" is a
  routine, and routines run on `scheduler.py`, which is the least-tested code in
  the repo (`docs/AUDIT.md` A12). That is its own task.
