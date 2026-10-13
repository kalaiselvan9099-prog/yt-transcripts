---
name: structured-note-making
description: "Turn any source (lecture, transcript, article, docs, book, meeting) into organised topic→subtopic study or reference notes built for recall, with verification."
license: MIT
---

# Structured Note-Making

Goal: notes a reader can **learn from and revise from**, not a shorter copy of the source.
Every rule below exists because of a known failure: copying instead of processing, flat bullet dumps,
dropped numbers, uneven depth on long sources, and notes that can't be used for self-testing.

## Evidence this skill is built on (why the rules exist)

- **Re-processing beats copying.** Verbatim transcription produces shallower learning than notes in your own words
  (Mueller & Oppenheimer 2014; later replications found a smaller effect, but the direction holds).
  → Rewrite every point in plain words. Quote only definitions, exact figures, syntax and official wording.
- **Self-testing and spacing are the two highest-value study techniques. Summarising, highlighting and
  re-reading alone are low value** (Dunlosky et al. 2013).
  → Every section ends with recall questions. Summaries exist, but never as the only layer.
- **Explaining why works.** Elaborative interrogation and self-explanation are rated moderate value.
  → Each concept gets a "why / when" line, not just a "what".
- **Cue column + summary (the Cornell method)** turns notes into a self-test.
  → Each section has cue questions and a 1–3 line summary.
- **Structure shows relationships.** Outlines, comparison tables and diagrams make hierarchy and contrast
  visible; flat lists hide them.

## Step 0: Scope (decide, don't interrogate)

Work out from the request, or default:

| Question | Default |
|---|---|
| Purpose | exam prep (if a certification or course is mentioned), else reference |
| Depth | comprehensive: never silently shorten kept content |
| Order | logical (concepts before what depends on them), each point keeping its source reference |
| Output | the user's stated destination. If none: a shareable document artifact; Notion if asked |
| Exclusions | housekeeping (intros, sponsor reads, scheduling, "like and subscribe"), unless asked |

Apply the user's standing formatting preferences (e.g. bullets over prose, fonts) on top of this skill.

## Step 1: Read everything before writing (anti-drift)

- Read the whole source in sequential chunks. Keep a **reading ledger**: chunk, range covered,
  topics found. Notes start only after the ledger covers 100%.
- For long sources, write a **topic inventory** while reading: every named concept, number, threshold,
  limit, date, URL, example, warning ("be careful", "common mistake", "exam loves") and Q&A item,
  each with its location (timestamp, page or section).

## Step 2: Build the topic map (hierarchy first, prose later)

- Group the inventory into **Topic → Subtopic → Concept**. Three levels at most; deeper means split the topic.
- Merge duplicates: the same concept mentioned in three places becomes one entry with three source refs.
- Order topics by dependency. Put cross-cutting material (glossary, comparisons, traps) in its own sections.
- Sanity check: no topic with a single subtopic, no subtopic with 15+ unrelated bullets
  (split it), and the names are nouns a reader would search for.

## Step 3: Write each concept in a fixed shape

Use the parts that apply; skip empty ones. Don't pad.

```
### <Concept>
- What: one-line definition in plain words (quote the official definition only if wording matters)
- Why / when: the problem it solves; when to choose it over alternatives
- How: steps, mechanism, configuration path, or syntax (code block if exact)
- Numbers: limits, defaults, thresholds, versions, dates, kept EXACT
- Example: one concrete example (prefer the source's own)
- Contrast: what it is commonly confused with, and the deciding difference
- Gotcha: the trap, failure mode, or exam distractor
- Source: [mm:ss] / p.N / §N
```

Formatting rules:
- One idea per bullet, and at most ~25 words per bullet. Bold only the key term, never whole sentences.
- **Tables** for any comparison of 2+ items on shared attributes (A vs B, options, editions, limits).
- **Numbered lists** for sequences and processes; bullets for unordered facts.
- **Diagrams** (Mermaid or ASCII) for flows, hierarchies and architectures when the destination renders them.
- Mark uncertainty explicitly: `⚠️ verify`. Mark source errors as `Correction:` with the right fact and its source.

## Step 4: The retrieval layer (what makes notes worth having)

At the end of every subtopic or topic:

```
**Recall** (answer without looking)
1. <question testing understanding, not wording>
2. <scenario question: "A user needs X but not Y; which feature?">
3. <contrast question: "Difference between A and B?">
**Summary:** 1–3 lines: the idea a reader must keep.
```

At document level add:
- **Overview:** what's covered, a topic map or table of contents, and the weighting or priority if known
  (e.g. exam domain %).
- **Cheat sheet:** the highest-value facts, numbers and rules on one screen.
- **Traps / confusables table:** | Looks like | Actually | How to tell |.
- **Glossary** of terms and acronyms, especially those the source uses without defining.
- **Revision plan (optional):** spaced reviews (e.g. day 1, 3, 7, 14), driven by the recall questions.

## Step 5: Verify before delivering

1. **Coverage:** every item in the Step 1 inventory appears in the notes, or is consciously excluded.
   Check numbers, named entities and URLs one by one. A missing number is a real gap.
2. **Even depth:** compare section lengths against source lengths. A long source section with thin notes
   means it was sampled; go back and re-read.
3. **Accuracy:** for facts that change (product limits, release names, deprecations, prices, laws), check
   current official documentation when tools allow. Never silently "fix" a fact; add a `Correction:` line.
4. **Usability:** headings are scannable, every section has recall questions, and nothing is a long paragraph.
5. **Exclusions:** search the output for excluded material, again after every revision.

## Anti-patterns

- Transcript-shaped notes: following the speaker's rambling order, or keeping filler and repetition.
- Copying sentences verbatim instead of re-expressing them.
- Bullet dumps: 30 bullets under one heading with no hierarchy.
- Rounding or dropping numbers ("about 50k" when the source said 50,000).
- Strong first sections, thin later ones (sampling drift).
- Summary-only notes with no questions, contrasts or examples.
- Inventing structure the source doesn't support, or adding facts with no source or check.

## Final checklist

- [ ] Reading ledger at 100%
- [ ] Topic → subtopic → concept hierarchy, in dependency order
- [ ] Concept shape applied; comparisons in tables; numbers exact; sources referenced
- [ ] Recall questions and a summary per section; cheat sheet, traps table and glossary at the end
- [ ] Coverage, depth, accuracy and exclusion checks done; uncertainties flagged
- [ ] Delivered to the agreed destination in the user's preferred format