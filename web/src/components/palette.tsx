/** One color + one geometric mark per course, shared by the calendar, cards and catalog. */
const STYLES = [
  "bg-red text-white",
  "bg-blue text-white",
  "bg-yellow text-ink",
  "bg-ink text-paper",
  "bg-[#E4712A] text-ink",
  "bg-[#7FA6D6] text-ink",
  "bg-[#5E7D3A] text-white",
] as const;

export type ShapeKind = "circle" | "square" | "triangle";
const SHAPES: ShapeKind[] = ["circle", "square", "triangle"];

export function courseStyle(index: number): string {
  return STYLES[((index % STYLES.length) + STYLES.length) % STYLES.length]!;
}

export function courseShape(index: number): ShapeKind {
  return SHAPES[((index % SHAPES.length) + SHAPES.length) % SHAPES.length]!;
}

/** A small solid shape in the current text color. */
export function Shape({ kind, className = "h-2.5 w-2.5" }: { kind: ShapeKind; className?: string }) {
  if (kind === "circle") return <span aria-hidden className={`inline-block rounded-full bg-current ${className}`} />;
  if (kind === "square") return <span aria-hidden className={`inline-block bg-current ${className}`} />;
  return (
    <span
      aria-hidden
      className={`inline-block bg-current ${className}`}
      style={{ clipPath: "polygon(50% 0, 100% 100%, 0 100%)" }}
    />
  );
}

/** The brand mark: circle, square, triangle in the three primaries. */
export function Mark({ size = "h-4 w-4" }: { size?: string }) {
  return (
    <span className="flex items-center gap-1" aria-hidden>
      <Shape kind="circle" className={`${size} text-red`} />
      <Shape kind="square" className={`${size} text-blue`} />
      <Shape kind="triangle" className={`${size} text-yellow`} />
    </span>
  );
}
