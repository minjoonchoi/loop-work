# Writing for people and agents

Write the conclusion first, then the evidence needed to use it. Match the user's
language and technical level. Preserve precise terms, constraints and uncertainty;
explain an unfamiliar term briefly when needed. Simplicity must not change the facts.

## Korean vault records

Write authored task titles, tracking summaries/findings and knowledge `summary`,
`why`, `details`, `uncertainty` in Korean. Preserve proper names, API names and exact
technical terms. An explicitly requested foreign-language deliverable remains in
that language; keep its separate harness tracking summary in Korean.
Never translate or alter original user input, quotations, evidence, code, commands,
paths, hashes, references or machine JSON keys/enums. Existing English stored facts
are not permission to invent a translated replacement. Do not reject a literal input
or impose a Hangul-character validator: this is an authoring policy, not new authority
or a content-quality shortcut. Assess conclusions against the actual source.

## Record shape

| Record | Required content | Optional content |
| --- | --- | --- |
| Execution status | goal, actual stage, result/evidence, next agent action or blocker | latest material finding |
| Knowledge topic | one conclusion, scope, status, source references, source dependencies | why it matters, up to five distinct details, uncertainty, decision boundary |
| Completed work | delivered result, output reference, each criterion and its evidence | new supported knowledge |

Use `summary` for the conclusion; `why` only for a useful implication; `details` for
distinct supporting facts; `uncertainty` for an actual limit. Omit unused fields rather
than writing "none", boilerplate, or a second summary. Keep each authored summary,
finding and optional topic point on one line, at most 280 characters. Task titles are
at most 120; common goal outcome/deliverable fields at most 400. Put a longer explanation
in the requested deliverable and link it. Never cut evidence to fit a summary.

## Before saving or reporting

1. State what changed or what the evidence establishes. Delete intent announcements,
   praise, repeated recaps, and closers such as "let me know if you need anything".
2. Use one idea per sentence. Name the affected behavior and cause. Avoid abstract
   claims such as "improved robustness" without the actual observable change.
3. Keep source paths, commands and results exact. Distinguish fact, decision, inference
   and unknown; do not replace uncertainty with confidence or invent time estimates.
4. Show at most five items per visible group, with a count and route to the rest.
   Order actual steps; use a table for comparisons. Preserve all underlying evidence.
5. Give the agent's next action only while work remains. Do not turn it into a new
   instruction for the user unless a real user-owned choice is pending before start.

Use an analogy only if it clarifies an unfamiliar mechanism. Do not force childlike
language, medical assumptions, emojis, a fixed recap, or an unnecessary question into
every output. Explanations may be as long as the requested understanding requires;
the bounded fields are navigation records, not a limit on the deliverable itself.

## Progress and interim deliverables

Progress updates identify a new result, blocker or next check condition. If a host
requires an update during unchanged waiting, state that no new result is available
and name the pending check; do not present the same unfinished state as new progress.
A stage fraction describes the recorded workflow stage, not a test pass rate or an
acceptance completion percentage unless those quantities were actually measured.

For an interim evaluation, retain its cutoff date, source access limits, unresolved
findings and historical verification units. Separate observations, reported facts and
improvement hypotheses. Add later execution results in a dated section without
replacing the earlier stop history; corrections identify their date, claim and evidence.
Distinguish portable documents from unavailable local audit artifacts and past results
from checks executed for the present task. Do not claim an unmeasured time or quality gain.

## Storage and maintenance

SQLite and development state JSON are authoritative records. Markdown views are
generated deterministically from them, without a second model-written paraphrase.
Update the same topic ID when evidence changes. Do not create daily narrative copies,
repeat task history inside every topic, or save an unchanged fact as a new revision.
If nothing was learned, the task result is enough. Keep obsolete versions in history.

`context` refreshes applicability from dependencies; it never verifies a fact just by
reading it. A topic document's confirmed label is not a freshness guarantee: use the
current context view. `knowledge get` and `work context` regenerate derived views if
needed. Do not hand-edit generated Markdown to change task status or facts.

The scripts reject blank/placeholder-only, oversized or multiline summaries, repeated
topic fields and duplicate evidence references. These checks prevent common bloat;
the agent still checks factual accuracy and useful wording. A word blacklist cannot
establish writing quality, and readability is not another review loop.

## Obsidian reports

Use the single `~/.loop-work/vault` as a derived document workspace. Group reports by
human-readable project/task names plus stable IDs, with Korean current/interim/final
labels and content-digest snapshots. Retain existing managed paths, including edited
or missing paths; never create a fresh copy to bypass an ownership conflict or deletion.
Indexes may link legacy files. Frozen path mappings do not rename on title changes. SQLite and
development JSON remain authoritative. A report named final is not a completion gate;
show blocked, stopped or unverified work as incomplete and preserve earlier failures.
A later result supplements the dated interim record rather than erasing its cutoff.

Preserve human-authored notes and existing `.obsidian` settings. Generated-file ownership
and pins determine which reports may be refreshed; do not overwrite edited or unowned
files. A vault edit alone never grants approval, completes QA or promotes a worker draft.
Export errors are document-delivery problems: retain the committed task result and
continue authorized work while reporting the failed view separately. Distinguish local
`.loop` audit links from portable evidence; never imply that unavailable local logs
were copied into a shareable report.

## References

Adapted principles, not installed hooks or runtime dependencies:

- [ELI5](https://github.com/DreambigOu/ELI5/blob/main/skills/eli5/SKILL.md): audience-appropriate vocabulary, purpose before mechanism, progressive explanation. Read blob `b0644b6cbc4839749aeecf0b340074be9e88f475`.
- [i-have-adhd](https://github.com/ayghri/i-have-adhd/blob/main/skills/i-have-adhd/SKILL.md): visible state/action, small groups, no tangents or repeated recap. Read blob `6c42757ffae37e442adfb52fbba2a8609f1cff00`.

The harness retains exact evidence, its question policy and the user's requested
depth. It does not adopt a five-year-old default audience or unsupported estimates.
