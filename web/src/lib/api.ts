import { z } from "zod";

/** Shapes returned by planner_api (ChatSession.view()). Parsed, never trusted blindly. */
const Meeting = z.object({ days: z.string(), start: z.number(), end: z.number() });

const Section = z.object({
  id: z.string(),
  course: z.string(),
  title: z.string(),
  credits: z.number(),
  instructors: z.array(z.string()),
  when: z.string(),
  online: z.boolean(),
  meetings: z.array(Meeting),
  counts_toward: z.array(z.string()),
  warnings: z.array(z.string()),
});

const Progress = z.object({
  title: z.string(),
  needed: z.number().nullable(),
  unit: z.enum(["credits", "courses"]).nullable(),
  planned: z.number(),
  courses: z.array(z.string()),
});

export const ViewSchema = z.object({
  term: z.string(),
  rules: z.array(
    z.object({
      id: z.string(),
      text: z.string(),
      must: z.boolean(),
      said: z.string(),
      default: z.boolean(),
      removable: z.boolean(), // the full-time band can be changed, not removed
    }),
  ),
  status: z.enum(["ok", "infeasible"]).nullable(),
  schedules: z.array(
    z.object({
      credits: z.number(),
      sections: z.array(Section),
      missed_rules: z.array(z.string()), // "if possible" requests this plan doesn't meet
      progress: z.array(Progress), // what this plan adds to each open requirement
    }),
  ),
  conflict_ids: z.array(z.string()),
  conflict: z.array(z.string()),
  why: z.array(z.string()),
  fixes: z.array(z.object({ number: z.number(), text: z.string(), unlocks: z.number() })),
  questions: z.array(z.object({ question: z.string(), options: z.array(z.string()) })),
  // ways to fit a newly asked-for course into the plan on screen; answered by number
  choices: z.array(z.object({ number: z.number(), text: z.string() })),
  requirements: z.array(
    z.object({
      title: z.string(),
      needed: z.number().nullable(),
      unit: z.enum(["credits", "courses"]).nullable(),
    }),
  ),
  facts: z.object({
    credits_earned: z.number().nullable(),
    credits_in_progress: z.number().nullable(),
    standing: z.string().nullable(),
    in_progress: z.array(z.string()),
  }),
});

export type View = z.infer<typeof ViewSchema>;
export type ScheduleSection = z.infer<typeof Section>;
export type RequirementProgress = z.infer<typeof Progress>;

const CatalogSchema = z.object({
  total: z.number(),
  courses: z.array(
    z.object({
      code: z.string(),
      title: z.string(),
      credits: z.number(),
      status: z.enum(["open", "taken", "blocked", "check"]),
      notes: z.array(z.string()),
      counts_toward: z.array(z.string()),
      sections: z.array(
        z.object({
          id: z.string(),
          component: z.string(),
          when: z.string(),
          instructors: z.array(z.string()),
          online: z.boolean(),
          seats_open: z.number().nullable(),
        }),
      ),
    }),
  ),
});
export type Catalog = z.infer<typeof CatalogSchema>;
export type CatalogCourse = Catalog["courses"][number];

const TurnSchema = z.object({ reply: z.string(), view: ViewSchema });
const StartedSchema = TurnSchema.extend({ id: z.string() });
export type Turn = z.infer<typeof TurnSchema>;
export type Started = z.infer<typeof StartedSchema>;

async function call<T>(schema: z.ZodType<T>, url: string, init: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const body: unknown = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = (body as { detail?: unknown }).detail;
    throw new Error(typeof detail === "string" ? detail : `Request failed (${response.status})`);
  }
  return schema.parse(body);
}

export function startSession(pdf: File): Promise<Started> {
  return call(StartedSchema, "/api/sessions", {
    method: "POST",
    headers: { "content-type": "application/pdf" },
    body: pdf,
  });
}

/** `plan`: the schedule on screen, so "add X" edits that one. */
export function sendMessage(session: string, text: string, plan = 0): Promise<Turn> {
  return call(TurnSchema, `/api/sessions/${session}/messages`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text, plan }),
  });
}

export function dropRule(session: string, rule: string): Promise<Turn> {
  return call(TurnSchema, `/api/sessions/${session}/rules/${encodeURIComponent(rule)}`, {
    method: "DELETE",
  });
}

/** Course search over this term's data (no LLM). An empty query lists what counts toward you. */
export function searchCatalog(session: string, query: string, signal?: AbortSignal): Promise<Catalog> {
  const q = encodeURIComponent(query);
  return call(CatalogSchema, `/api/sessions/${session}/catalog?q=${q}`, { signal });
}
