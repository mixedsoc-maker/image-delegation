# Delegation prompt template (image-delegation:image-inspector)

Copy it and fill in every field. Use absolute paths. Leave out conversational context the inspector does not need.

```
GOAL: <the main agent's end goal, 1-2 sentences: why this check matters>
QUESTION:
- [ ] <concrete item 1, e.g. "exact text of the error banner">
- [ ] <item 2, e.g. "is the Submit button visible and enabled-looking? color?">
FILES (N images):
- <abs path 1>
- <abs path 2>
IMAGE_BUDGET: <n>   (total image Reads incl. re-reads/crops; n <= HARD_LIMIT; never exceed)
HARD_LIMIT: <HARD_LIMIT from the session-start context>
CONTEXT: <expected values/text, what changed, summary of earlier batches; "none" if none>
OUTPUT: Use your fixed report format (Answer / Images used / Per-image findings / Not examined / Uncertainties).
```

Agent call: `subagent_type: "image-delegation:image-inspector"`, short `description` (e.g. "Inspect batch 1/2"), `prompt` = the block above.
