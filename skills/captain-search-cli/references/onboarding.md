# Captain Search Onboarding

Use this flow when someone wants to start using the CLI quickly without sitting through every possible provider and install option first.

## Recommended flow

1. Start with the smallest working path.
   - If the user already has this repo checked out, stay in the checkout and use `uv run csearch ...`.
   - If they do not have the repo and there is no published package yet, have them clone the repo and run `uv sync`.
   - Only prefer `uv tool install captain-search` or `uvx --from captain-search ...` after a real package release exists.
   - If they want a reusable agent workflow from this checkout, install the skill with `uv run csearch skill install --scope user` before moving on.
2. Ask only for credentials that matter right now.
   - Do not ask for every provider key up front.
   - For a first web-search smoke test, no web key is strictly required if the default runtime still has keyless `exa_mcp` enabled.
   - Ask for one web-search key only when the user wants a specific provider or more redundancy.
   - Ask for `MORPH_API_KEY` only when repo-local Morph search matters.
   - Ask for `JINA_API_KEY` or `PARALLEL_API_KEY` only when webpage extraction quality matters.
3. Prove the install with one command before explaining advanced options.
4. Expand to `fetch` and `code` only after the first command works.
5. Persist environment variables or env-file usage only after smoke tests pass.

## Minimal smoke-test sequence

From a repo checkout:

```bash
uv sync
uv run csearch skill install --scope user
uv run csearch web "github actions cache" --max-results 5
uv run csearch fetch https://github.com/mnm-matin/captain-search/blob/main/README.md
uv run csearch code "search_web" --repo mnm-matin/captain-search --format json
```

## Best default onboarding script

1. Ask whether the user wants one-off usage from this checkout, a persistent local install, or MCP setup.
2. If the answer is CLI use, stay in CLI mode and avoid MCP instructions.
3. Get one successful `web` command on screen.
4. Then ask whether they also need code search, webpage extraction, provider-specific tuning, or MCP server setup.
5. Only after that, explain additional provider keys, logs, and persistent installs.

## What not to do

1. Do not lead with a long API-key checklist.
2. Do not explain every supported entrypoint before the first successful result.
3. Do not mix CLI onboarding with MCP client setup unless the user explicitly asks for both.
4. Do not assume `code` or `fetch` require the same credentials as `web`.

## Troubleshooting order

1. Run `uv run csearch doctor`.
2. Retry the smallest failing command.
3. Inspect `~/.captain-search/logs` if the output is empty, partial, or rate-limited.
4. Add provider-specific keys only after confirming which provider path is actually failing.