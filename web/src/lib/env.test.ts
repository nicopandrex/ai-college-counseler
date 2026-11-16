import { describe, expect, it } from "vitest";
import { readEnv } from "./env";

describe("readEnv", () => {
  it("defaults the solver URL", () => {
    expect(readEnv({}).SOLVER_URL).toBe("http://localhost:8000");
  });

  it("rejects a malformed solver URL", () => {
    expect(() => readEnv({ SOLVER_URL: "not a url" })).toThrow();
  });
});
