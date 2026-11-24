const SEASONS: Record<string, string> = { SP: "Spring", SU: "Summer", FA: "Fall", WI: "Winter" };

/** "2027SP" -> "Spring 2027"; anything else is shown as given. */
export function termName(term: string): string {
  const match = /^(\d{4})(SP|SU|FA|WI)$/.exec(term);
  return match ? `${SEASONS[match[2]!]} ${match[1]}` : term;
}
