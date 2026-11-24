# Degree Planner (V0)

Upload a UVM DegreeWorks audit, then plan Spring 2027 by chatting: "no classes before 10,
Fridays off, macro but not with Rodrigues". The schedules, conflicts and requirement credit
all come from a CP-SAT solver and the audit; the LLM only translates what you type.

## Run it locally

Needs Python 3.12–3.13, [uv](https://docs.astral.sh/uv/), Node 18+ and a Gemini API key.

```bash
make install
```

```bash
export LLM_PROVIDER=gemini LLM_API_KEY=your-gemini-key LLM_CACHE_MODE=record LLM_CACHE_DIR=fixtures/private/llm-cache
```

```bash
make dev
```

Open http://localhost:3000 and upload your audit PDF. The first upload reads the audit with two
Flash calls (up to a minute); each chat message is one Flash call. Repeats are cached in
`fixtures/private/llm-cache` (gitignored) and cost nothing. `LLM_MAX_LIVE_CALLS` (default 30)
caps paid calls per uploaded audit.

The audit PDF is read from a temporary file and deleted; sessions live in memory and end when
the server stops.

Terminal version: `uv run planner chat --audit path/to/audit.pdf`.

## Tests

```bash
make test
```

Committed tests use synthetic data only. Never commit `fixtures/private/`.
