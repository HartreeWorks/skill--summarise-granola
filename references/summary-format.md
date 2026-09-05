# Summary format

Create comprehensive, chronological summaries that help the user re-envision and remember the conversation. The chronological structure is key—it allows details not explicitly in the summary to be recalled by following the flow.

## Document structure

```markdown
# Meeting summary: [Title]

**Date:** YYYY-MM-DD

**Participants:** [Full names with roles if relevant]

---

## Summary

- [First key point from the call.]
- [Second key point from the call.]
- [Third key point from the call.]
- [Fourth key point from the call, if needed.]

---

## Part 1: [Opening topic/context]

[Chronological narrative of this phase of the conversation...]

---

## Part 2: [Next major topic]

[Continue chronologically...]

---

## Part N: The path forward / Next steps

[Clear statement of decisions and actions decided upon]

**Specific actions agreed:**
1. First action
2. Second action
3. ...

**[Person]'s next step:**
[Immediate action to take]

---

## Appendix 1: Open questions

- Question 1
- Question 2

---

## Appendix 2: Key quotes

| Speaker | Quote | Context |
|---------|-------|---------|
| Name | "Quote text" | Brief context |

---

## Appendix 3: Underlying dynamics

[Optional—include when there are important subtext, emotional dynamics, or strategic considerations worth noting. Skip if not applicable.]

**[Dynamic 1]:** Explanation...

**[Dynamic 2]:** Explanation...
```

## Formatting guidelines

**Lists:**
- Use **numbered lists** when items might be referred to later (options, action items, decisions)
- Use **lettered lists (a, b, c)** when you don't want to imply prioritisation
- Use **bullet lists** only for items that won't need to be referenced
- Always put each list item on its own line (no inline numbered lists)

**Top summary section:**
- The `## Summary` section must be a bullet list of 3-5 key points, not a continuous paragraph.
- Keep this bullet-list treatment to the `## Summary` section only. Later `## Part...` sections should remain chronological prose unless a local list is genuinely useful.
- Each summary bullet should cover one major point from the call. Prefer one short sentence; use 2-3 short sentences when the point needs more detail.
- Avoid long compound sentences in the summary bullets. Split them so each sentence is easy to scan.

**Quotations:**
- Use inline "quotation marks" for short, key phrases within prose
- Use block quotes (>) for longer or particularly important statements
- Preserve exact wording for:
  - Expressions of certainty/uncertainty
  - Commitments and decisions
  - Memorable or distinctive phrasing
  - Insights and realisations

**Structure:**
- Use `---` horizontal rules to separate major sections
- Bold speaker names when attributing quotes or positions
- Use tables for structured comparisons (e.g., concept assessments)

## Content guidelines

**Depth:** Match depth to the richness of the conversation. A substantive 45-minute strategy discussion warrants 150-200+ lines; a brief check-in might need only 50.

**Chronological narrative:** Tell the story of how the conversation unfolded and how conclusions were reached. This helps the user mentally reconstruct the call.

**Capture insights:** Don't just list decisions—capture the reasoning, realisations, and shifts in thinking that led to them.

**Appendices:**
- **Open questions** (Appendix 1): Almost always include; usually first appendix
- **Key quotes** (Appendix 2): Include when there are memorable or important phrasings
- **Underlying dynamics** (Appendix 3): Include when there's important subtext (emotional state, strategic considerations, relationship dynamics); skip when not applicable

## Example part structure

```markdown
## Part 2: Diagnosing the problem

Jane asked a pivotal question: "Is this a brief issue or an execution of the brief issue?"

This opened up a crucial realisation. Jane introduced the "new aesthetics" framing—an emerging visual language for the project.

The user's reaction was immediate recognition:
> "We should be at the front of that. In my dream world, if I was leading this, I would have put a lot into trying to be at the front of that."

**The diagnosis crystallised:** The brief hadn't communicated this ambition. The user admitted: "It definitely wasn't pitched that ambitiously."

This explained the expectation gap: The user was unconsciously hoping for something revolutionary while the agency was delivering competent-but-safe work as briefed.
```
