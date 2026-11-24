# Degree Planner (V0)

Upload a UVM DegreeWorks audit, then plan Spring 2027 by chatting: "no classes before 10,
Fridays off, macro but not with Rodrigues". The schedules, conflicts and requirement credit
all come from a CP-SAT solver and the audit; the LLM only translates what you type.

## Run it locally (Windows, Mac or Linux)

You need [Node.js](https://nodejs.org) (LTS) and [uv](https://docs.astral.sh/uv/), which also
installs the right Python for you. On Windows, install uv from PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then close and reopen your terminal. In the project folder:

1. Copy `.env.example` to `.env` and paste your Gemini API key into it (`.env` is never committed).
2. Install everything once:

```bash
npm install
```

```bash
npm run setup
```

3. Start the app (API and web together; Ctrl+C stops both):

```bash
npm run dev
```

Open http://localhost:3000 and upload your audit PDF. The first upload reads the audit with two
Flash calls (up to a minute); each chat message is one Flash call. Repeats are cached in
`fixtures/private/llm-cache` (gitignored) and cost nothing. `LLM_MAX_LIVE_CALLS` in `.env` caps
paid calls per uploaded audit.

The audit PDF is read from a temporary file and deleted; sessions live in memory and end when
the server stops.

Terminal version: `uv run planner chat --audit path/to/audit.pdf`.

## Tests

```bash
npm test
```

Committed tests use synthetic data only. Never commit `fixtures/private/`.
