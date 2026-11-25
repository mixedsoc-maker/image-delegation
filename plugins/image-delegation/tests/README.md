# Testing image-delegation

Offline guard test. It needs no Claude session and checks 30 allow/deny cases, including subagent screenshot counting:
```sh
python "<plugin>/tests/test_image_guard.py"
python "<plugin>/tests/test_deps.py"          # dependency notice + `imgtool doctor` (simulates missing deps)
```

End-to-end tests: run these from the root of any project where the plugin is enabled. To try it without installing, start the session with `claude --plugin-dir <path>/plugins/image-delegation`. Start a NEW session after installing or changing the plugin, or run `/reload-plugins`.

```sh
python "<plugin>/tests/make_fixtures.py"        # -> .claude/tmp/fixtures/img01..img10.png
```

| # | Prompt in the new session | Expect |
|---|---|---|
| 2 | `Tell me the text written on each of the 10 PNG images in .claude/tmp/fixtures` | ≥ 2 new `image-delegation:image-inspector` agents, sent in parallel, each with IMAGE_BUDGET ≤ default. All 10 labels IMG-01..IMG-10 correct. |
| 3 | `Delegate img01..img05 to ONE new image-inspector with IMAGE_BUDGET: 3; report its Images used / Not examined verbatim` | `Images used: 3/3`. Two files under Not examined (budget exhausted). |
| 6 | `Use the Read tool directly on .claude/tmp/fixtures/img01.png (don't delegate)` | The guard hook denies it and points to the skill. |

Audit afterwards. This checks that main has 0 image blocks and that each subagent stayed within its budget.

```sh
python "<plugin>/tests/check_transcript.py" --latest     # or <session_id>; add --hard-limit/--default-budget if you changed the config
```

Headless: `claude -p "<prompt>" --output-format json --allowedTools "Read,Glob,Grep,Skill,Agent,Bash(sh *)"`. Pass the `session_id` from the JSON output to `check_transcript.py`.
Hook log: `<system temp>/claude-image-delegation-guard/<session_id>/events.jsonl`. Set `IMAGE_GUARD_DEBUG=1` to also log raw hook inputs.
