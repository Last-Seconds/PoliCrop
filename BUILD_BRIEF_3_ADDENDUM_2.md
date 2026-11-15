# Addendum 2 to build brief 3: ranking fixes, map layers, small improvements

Written 2026-11-15. Time is very short. Do section A first, then B, then C only if time remains. Finish the step you are on before starting. Each item is small; if one turns out large, skip it and report.

## A. Fixes to how options are ranked and described

Seen on a real field (winter wheat, winter wheat, spring canola; 16% slope): all three options and all three "more" options were built on winter peas, each with "winter-kill risk in 7 of 15 years", and the headline called Option A "at least as good on all four measures" although its least-protected winter drops from about 4,300 to about 2,400 lb/acre of residue.

**A1. Serious cautions count.** Mark these cautions as serious: winter-kill (W6), "may be too dry here", and heat during chickpea flowering (W5) when it fires in 5 or more of 15 years (`assumed`).

- Order options with no serious caution ahead of options with one, before any other ordering.
- Never describe an option with a serious caution as "at least as good" or "better than now" in the headline without naming the caution in the same sentence.
- Never hide a serious caution behind "more" on a card or a row. Show a warning symbol on the option's row in the comparison list.

**A2. The assumed-value rule works one way only.** It may turn "better" into "about the same". It must not turn "worse" into "about the same". When the central values say worse but an assumed value is involved, show "probably worse", count it as worse for ordering and dominance, and keep the note that an assumed figure is involved.

**A3. Winter-kill counts snow.** Daymet's single-pixel service also returns snow water equivalent (`swe`, kg/m²) with the same request. Count a winter as risky only when a night at or below the threshold came with `swe` under 10 kg/m² (`assumed`: little or no snow). Word it as "cold enough to kill, with little snow, in N of 15 winters", and say the snow figure is a modelled estimate. For reference, on the field above the counts were: any cold night 7 of 15; with little snow 5; on bare ground 1.

**A4. Options that differ.** Among the three options shown, at most two may introduce the same new crop. Fill the third place with the best-ordered option that does not.

Tests: an option with a serious caution is never first when one without exists; "worse" involving an assumed value shows "probably worse"; the three options on the example fields do not all share one new crop.

## B. Field layers on the main map

Today the slope map and other field evidence sit inside closed sections. Put them on the map, where a farmer looks first.

- Keep the map visible on the field screen (beside the results on a wide screen, above them on a phone, collapsible), showing the field outline.
- Add a small layer control with one layer on at a time: satellite photo (default), crop map, slope with steep ground highlighted, and soil drainage if the soil data already gives it per map unit.
- Reuse what already exists: the slope image and the crop-map overlay endpoints. Do not build a county-wide slope layer; the field's own area is enough.
- Each layer has a one-line legend in plain words, for example "red: steeper than 15%, where winter cover matters most".
- When an option is opened, keep the layers available so the farmer can see where on the field its soil-protection verdict matters.

## C. Small improvements, only if time remains

In order of value for a demonstration:

1. **Instant example fields.** Pre-warm every example field's data so each opens in a second or two.
2. **Honest loading.** While a field loads, show what is being read and what is already done, section by section.
3. **Tap a verdict to see why.** Tapping "better" or "worse" on a row shows the one sentence behind it, without opening the whole card.
4. **Copy link.** A control that copies the page address for the current field, so it can be reopened or shown to someone.
5. **A two-field tour.** One control on the first screen: "see how a dry field and a wet field differ", opening the LaCrosse and Pullman examples in turn. This is the clearest way to show what the tool does.

## Report

Add to your report which items of A, B and C you did, and for A3 the winter-kill counts before and after on the example fields.
