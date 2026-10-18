# Limits

What obelize does not do today, so you can judge a result before you trust it.

- It keeps model names as they are. Google and OpenAI retire models on published schedules
  ([Gemini](https://ai.google.dev/gemini-api/docs/deprecations),
  [OpenAI](https://platform.openai.com/docs/deprecations)), so check each name your calls use.
- It reads the code cells of notebooks (`.ipynb`) and finds those that use the old SDK but does not
  migrate them, and while one does, the old dependency line stays. Migrate the notebook by hand, or
  list it under `exclude` in `.obelize.yml` and the rest migrates and the pin moves; the notebook
  then loses the old SDK, so fix it by hand.
- It does not find every use. Code that reaches the SDK through a function's return value, a star
  import in another file or a container is missed, and the benchmark counts those misses.
- On Windows, the test suite on GitHub's runner is all that has run. A real console, a OneDrive
  folder and a path longer than 260 characters are untried.
- It handles the migrations its bundled packs describe. There is no pack registry, hosted service,
  dashboard, GitHub App or automatic pull request.
- For `openai` it rewrites seven calls and no other. A repository that uses the module in a way the
  pack lists is left as it was, with each place in the report;
  [KNOWN_ISSUES.md](KNOWN_ISSUES.md#the-openai-pack) says which ways it does not see.

[Known issues](KNOWN_ISSUES.md) lists what I know about and have chosen not to fix yet, and the
[roadmap](ROADMAP.md) says what comes next.
