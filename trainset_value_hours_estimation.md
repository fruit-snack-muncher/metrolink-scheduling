# Estimating `TRAINSET_DAYS_PER_DEADHEAD_HOUR`

The deadheading model in `src/preformulation.py` maximizes

```
sum_ij (1 - d_ij * K) x_ij  =  (number of chainings) - (total deadhead hours) * K
```

over the arcs of the chaining DAG, where `d_ij` is the deadhead duration in hours and
`K = TRAINSET_DAYS_PER_DEADHEAD_HOUR`. Each chaining removes one trainset, so it is worth
**1**; the empty run it requires costs `d_ij * K`. `K` is therefore the **fraction of a
trainset consumed per hour of empty running**, and its reciprocal the *break-even
deadhead*: the longest light move worth making rather than adding a set to service.

```
        marginal cost of one deadhead train-hour       ~$665 / h
  K  =  ----------------------------------------  =  --------------  ~  0.17
        marginal cost of one trainset-day            ~$4,030 / day
```

## Numerator: what an hour of deadheading costs

| Input | Value | Source |
| --- | --- | --- |
| Annual fuel burn | **8.0M gal/yr** | Derived from [LAist, 15 Apr 2022](https://laist.com/news/climate-environment/las-metrolink-is-off-petroleum-switching-to-fully-renewable-diesel): renewable diesel is "8 cents per gallon cheaper," saving ~$640,000/yr → $640,000 ÷ $0.08 |
| Average system speed | **37.9 mph** with stops | [Metrolink Quarterly Fact Sheet, Q2 FY22-23](https://metrolinktrains.com/globalassets/about/agency/facts-and-numbers/quarterly-fact-sheet-q2-fy-2022-2023.pdf) |
| Annual revenue train-hours | **70,305** | Computed from this repo's GTFS: every non-Arrow trip active on each day of calendar 2027 |
| Diesel price | **$4.85/gal** CA retail 2025 ($4.93 in 2024) | [EIA, California No. 2 ULSD annual retail](https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=pet&s=emd_epd2dxl0_pte_sca_dpg&f=a) |
| Crew wage rate | **$97.9/train-hour** for a two-person crew | BLS OES means below, loaded at 1.45 and divided by 2,080 h |

70,305 train-hours at 37.9 mph is **2.66M revenue train-miles**, so the fleet burns
**3.00 gallons per train-mile**, or **113.8 gallons per train-hour**. The only external
check is a comparable operator: Caltrain — diesel push-pull on a similarly stop-dense
corridor — used **3–3.25 gal/mile** across 2016–2020, per its 2021 Sustainability Report
as reported by [M. Gonzalez, Stanford PH240, 2023](http://large.stanford.edu/courses/2023/ph240/gonzalez1/)
(coursework, but it cites Caltrain's figures and shows the arithmetic) — a consistency
check, not independent confirmation. Metrolink buys in bulk and pays no road tax, so at
**$3.50–4.85/gal** an hour of running costs **$400–550** in fuel alone, or $500–825
after a quarter-to-half equipment-wear adder.

A light move between two revenue trips usually eats layover the crew is already paid for, 
costing nothing at the margin; it bites only when the empty run stretches the block's paid 
span or tips the assignment into overtime. Bracketing it at **$0–98/h** and taking half the
rate centrally gives **$500–923 per deadhead train-hour, central ~$665**.

## Denominator: what a trainset-day costs

A standard consist is taken as one locomotive, one cab car and four cabin cars.

| Input | Value | Source |
| --- | --- | --- |
| EMD F125 locomotive | **~$7.0–7.5M** | [Wikipedia, EMD F125](https://en.wikipedia.org/wiki/EMD_F125): $150M base order for 20 units; ~$280M across the 40-unit fleet |
| Hyundai Rotem car | **~$2.03M** | Base contract $176.3M ÷ 87 cars |
| Useful life | **39 years** | [FTA Default Useful Life Benchmark](https://www.transit.dot.gov/TAM/ULBcheatsheet), commuter rail locomotive (RL) and passenger coach (RP) |
| CA locomotive engineer | **$68,880/yr** mean | [BLS OES 53-4011, May 2023](https://www.bls.gov/oes/2023/may/oes534011.htm) |
| CA railroad conductor | **$71,550/yr** mean | [BLS OES 53-4031, May 2023](https://www.bls.gov/oes/2023/may/oes534031.htm) |

Capital comes to **$17.5M** per set: $449k/yr straight-line over the 39-year benchmark, or
$767k/yr at a 3% real cost of capital, spread across the 255 weekdays the peak fleet must
show up for — **$1,760–3,010 per day**. Crew wages of $140,430 loaded at 1.45 come to
$204k/yr, or **$800 per assignment-day** (a block spanning two shifts needs two); daily
inspection, cleaning and fuelling labour add **$200–400**.

Revenue fuel is excluded: revenue miles are invariant in the number of trainsets active on
a given weekday. What does belong is the fuel an idle set burns just by being in service — 
warm-up, layover idling, end-of-day hostling. The EPA puts locomotive idling at
[**3 to 5 gallons per hour**](https://www.epa.gov/ports-initiative/rail-facility-best-practices-improve-air-quality);
at 4–10 idle hours per set-day and $3.50–4.85/gal that is **$42–243/day, central ~$130**
— an upper-ish bound, since Metrolink runs an idle-reduction programme (claimed 35%
system-wide, 50% at CMF) and the Tier 4s have automatic stop-start. All told the
marginal set costs **$2,800–5,250 per day, central ~$4,030**.

## Result

$665/h over $4,030/day is **K ≈ 0.165 trainset-days per deadhead train-hour**, rounded to
**0.17** in the code, with a defensible range of **0.10–0.33** — a break-even deadhead of
**6 hours**, range 3.0–10.0 h (a five-unit consist gives K ≈ 0.18). Two consequences:

**At this value the penalty never forbids an arc.** The longest deadhead this network
offers is 4.32 h — Oceanside and Lancaster are far apart, but not six hours apart. At
K = 0.17 that worst arc costs 0.73 of a trainset against the 1.0 it saves, so the weights
only *order* solutions that chain equally many trips; they never rule one out. Above
**K = 0.232** — inside the upper half of the range quoted — the longest arcs turn
net-negative and the model refuses them outright. That does not change the answer here
(the five deadheads used are all under 1.5 h), but "never forbids" is a fact about this
K, not the range.

**The fleet size does not depend on K.** Sweeping the solver:

| K | break-even | fleet | deadheads | deadhead h |
| --- | --- | --- | --- | --- |
| 2.0 | 0.5 h | 35 | 0 | 0 |
| 1.0 | 1.0 h | 34 | 1 | 0.84 |
| 0.5 – 0.385 | 2.0 – 2.6 h | 32 | 3 | 3.47 |
| **0.37 – 1e-7** | **2.7 h – 1e7 h** | **31** | **5** | **6.15** |
| 1e-8 | 1e8 h | 31 | 37 | 58.41 |

Every value in the plausible economic range falls inside the flat band, so grounding the
constant in cost data strengthens the justification without moving the answer. The margin
is not enormous: the top of the range, K = 0.33, sits just under the 0.37 at which the
model starts trading trainsets for mileage — charge crew at the full rate, assume a
shorter consist, and take the low end of the capital estimate together, and the answer
would begin to move. Below 1e-7 the coefficients collapse into CBC's tolerance, the
tie-break is lost entirely, and the solver returns an arbitrary optimal matching. What
actually keeps the model on the right side of the band is not K but
`assert(fleet_size == 31)` in `src/zero_depot_deadheading.py` — 31 is the unweighted
optimum, so it fires the moment a penalty outbids a chaining. Its five deadheads:

| Duration | Move |
| --- | --- |
| 1.45 h | Riverside – Downtown → L.A. Union Station |
| 1.36 h | Riverside – Downtown → Laguna Niguel / Mission Viejo |
| 1.31 h | Laguna Niguel / Mission Viejo → L.A. Union Station |
| 1.18 h | Vista Canyon → L.A. Union Station |
| 0.84 h | Chatsworth → L.A. Union Station |

Four of the five terminate at Union Station, where the Central Maintenance Facility is.
The solution is not deadheading *past* a maintenance opportunity; it is deadheading
*into* one.

## Assumptions, not sources

- **Half the crew rate** charged against deadhead hours. Whether a light move extends
  paid time or is absorbed by layover is something the model cannot know arc by arc; the
  honest bracket is $0–98/h and the midpoint is a convenience. The least defensible
  number here, and the one most worth revisiting — it moves K by ±0.013 alone.
- **The equipment-wear adder** of 25–50% on fuel; **$200–400/day** for daily servicing;
  **4–10 idle hours per set-day** (the EPA gal/h figure is sourced, how long a set
  actually idles is not, and the idle-reduction programme favours the low end).
- **One to two crew assignments** per marginal block, and the **1.45** load factor on BLS
  wages. The wage figures appear in both halves of the ratio, once as a daily assignment
  cost and once as an hourly rate; distinct quantities, not a double count.
- **The consist** (one locomotive, one cab, four cabin cars — Metrolink runs shorter sets
  on lighter lines) and **255 weekdays** for capital recovery, i.e. the peak fleet is
  charged only against the days it is required.
- The **8.0M gallons covers all consumption** — deadheads, yard moves and idling — while
  it is divided here by *revenue* train-miles. That inflates the per-revenue-mile rate,
  arguably the right direction for costing a deadhead but not a like-for-like ratio.

## Sourcing caveats

- The **FTA National Transit Database profile for SCRRA** (NTD ID 90151) returns HTTP 403
  to direct fetches, so its 2023 figures (VOMS 195, $908.43/vehicle revenue hour,
  $25.11/vehicle revenue mile) were seen only in search summaries and are deliberately
  **not** used above.
- The **Rotem and F125 prices are contract-announcement figures**, not delivered cost;
  the F125 programme in particular ran years late.
- SCRRA's **budget books encode their line-item tables in subsetted fonts** that resist
  text extraction, so Fuel and Equipment Maintenance could not be read directly, and the
  [FY2024 audited Metrolink Program report](https://libraryarchives.metro.net/DB_Attachments/FY24%20Consolidated%20Audit%20-%20Vasquez/SCRRA%20-%20Metrolink%20Audit%20Report%20FY%202024%20-%20Final.pdf)
  rolls up to four categories only — operating expenses **$284,114,985**, of which train
  operations and services **$166,663,603**. Fuel had to be reached through gallons.
