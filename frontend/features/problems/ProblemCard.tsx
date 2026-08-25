import katex from "katex";
import type { ProblemContext } from "@/types/domain";

export type ProblemSegment =
  | { kind: "text"; value: string }
  | { kind: "math"; value: string; display: boolean; source: string };

function isEscaped(value: string, index: number): boolean {
  let slashes = 0;
  for (let cursor = index - 1; cursor >= 0 && value[cursor] === "\\"; cursor -= 1) {
    slashes += 1;
  }
  return slashes % 2 === 1;
}

function nextDollar(value: string, from: number): number {
  for (let cursor = from; cursor < value.length; cursor += 1) {
    if (value[cursor] === "$" && !isEscaped(value, cursor)) return cursor;
  }
  return -1;
}

function closingDelimiter(value: string, from: number, display: boolean): number {
  for (let cursor = from; cursor < value.length; cursor += 1) {
    if (value[cursor] !== "$" || isEscaped(value, cursor)) continue;
    if (display ? value[cursor + 1] === "$" : value[cursor + 1] !== "$") return cursor;
  }
  return -1;
}

function readableText(value: string): string {
  return value.replace(/\\\$/g, "$");
}

function escapeLatexText(value: string): string {
  const escaped = value.replace(/[\\{}#$%&_~^]/g, (character) => {
    switch (character) {
      case "\\":
        return "\\textbackslash{}";
      case "~":
        return "\\textasciitilde{}";
      case "^":
        return "\\^{}";
      default:
        return `\\${character}`;
    }
  });
  return escaped.split("\n").join("} \\\\ \\text{");
}

function parseDelimitedPrompt(prompt: string): ProblemSegment[] {
  const segments: ProblemSegment[] = [];
  let cursor = 0;
  while (cursor < prompt.length) {
    const opening = nextDollar(prompt, cursor);
    if (opening < 0) {
      segments.push({ kind: "text", value: readableText(prompt.slice(cursor)) });
      break;
    }
    const display = prompt[opening + 1] === "$";
    const delimiterLength = display ? 2 : 1;
    const contentStart = opening + delimiterLength;
    const closing = closingDelimiter(prompt, contentStart, display);
    if (closing < 0) {
      segments.push({ kind: "text", value: readableText(prompt.slice(cursor)) });
      break;
    }
    if (opening > cursor) {
      segments.push({ kind: "text", value: readableText(prompt.slice(cursor, opening)) });
    }
    const source = prompt.slice(opening, closing + delimiterLength);
    const math = prompt.slice(contentStart, closing);
    segments.push(
      math.trim()
        ? { kind: "math", value: math, display, source }
        : { kind: "text", value: source },
    );
    cursor = closing + delimiterLength;
  }
  return segments;
}

/** Accept raw TeX from providers that omit dollar delimiters. */
function parseRawMathPrompt(prompt: string): ProblemSegment[] | null {
  const marker = /\\[a-zA-Z]+|[A-Za-z0-9)\]}][_^]/g;
  const match = marker.exec(prompt);
  if (!match) return null;

  // In a sentence such as "... function f(x) = e^{3x} \\cos(x^2).", keep
  // the prose in the browser font but render the complete mathematical clause.
  const equals = prompt.lastIndexOf("=", match.index);
  const leftHandSide =
    equals >= 0
      ? /([A-Za-z][A-Za-z0-9]*(?:\s*\([^()\n]*\))?\s*=\s*)$/.exec(
          prompt.slice(0, equals + 1),
        )
      : null;
  const start = leftHandSide?.index ?? (equals >= 0 ? equals + 1 : match.index);
  let end = prompt.length;
  for (const punctuation of [".", "?", "!"]) {
    const candidate = prompt.indexOf(punctuation, match.index);
    if (candidate >= 0) end = Math.min(end, candidate);
  }
  const math = prompt.slice(start, end).trim();
  if (!math) return null;
  const prefixEnd = start + prompt.slice(start).search(/\S/);
  const prefix = prompt.slice(0, prefixEnd);
  const suffixStart = start + prompt.slice(start).indexOf(math) + math.length;
  return [
    ...(prefix ? [{ kind: "text", value: readableText(prefix) } as const] : []),
    { kind: "math", value: math, display: false, source: math },
    ...(suffixStart < prompt.length
      ? [{ kind: "text", value: readableText(prompt.slice(suffixStart)) } as const]
      : []),
  ];
}

export function parseProblemPrompt(prompt: string): ProblemSegment[] {
  const delimited = parseDelimitedPrompt(prompt);
  if (delimited.some((segment) => segment.kind === "math")) return delimited;
  return parseRawMathPrompt(prompt) ?? delimited;
}

function promptAsLatex(segments: ProblemSegment[]): string {
  return segments
    .map((segment) => {
      if (segment.kind === "text") {
        return segment.value ? `\\text{${escapeLatexText(segment.value)}}` : "";
      }
      return segment.display
        ? `{\\displaystyle ${segment.value}}`
        : segment.value;
    })
    .join("");
}

function MathSegment({ segment }: { segment: Extract<ProblemSegment, { kind: "math" }> }) {
  let markup: string | null = null;
  try {
    markup = katex.renderToString(segment.value, {
      displayMode: segment.display,
      throwOnError: true,
      trust: false,
      strict: "warn",
    });
  } catch {
    markup = null;
  }
  if (markup !== null) {
    const Element = segment.display ? "div" : "span";
    return (
      <Element
        className={segment.display ? "my-3 overflow-x-auto py-1" : "inline-math"}
        dangerouslySetInnerHTML={{ __html: markup }}
      />
    );
  }
  return (
    <code
      className={segment.display ? "my-3 block overflow-x-auto rounded bg-stone-100 px-2 py-1 font-mono text-[0.9em]" : "rounded bg-stone-100 px-1 font-mono text-[0.9em]"}
      data-math-error
    >
      {segment.source}
    </code>
  );
}

export function ProblemBody({ prompt }: { prompt: string }) {
  const segments = parseProblemPrompt(prompt);
  let markup: string | null = null;
  try {
    markup = katex.renderToString(promptAsLatex(segments), {
      displayMode: false,
      throwOnError: true,
      trust: false,
      strict: "warn",
    });
  } catch {
    // Preserve the readable per-segment fallback for malformed provider math.
  }

  if (markup !== null) {
    return (
      <div
        className="problem-katex whitespace-pre-wrap text-[clamp(1.05rem,1.8vw,1.45rem)] leading-relaxed text-[#202620]"
        dangerouslySetInnerHTML={{ __html: markup }}
      />
    );
  }

  return (
    <div className="whitespace-pre-wrap text-[clamp(1.05rem,1.8vw,1.45rem)] leading-relaxed text-[#202620]">
      {segments.map((segment, index) =>
        segment.kind === "math" ? (
          <MathSegment key={`${index}-${segment.source}`} segment={segment} />
        ) : (
          <span key={`${index}-${segment.value}`}>{segment.value}</span>
        ),
      )}
    </div>
  );
}

export function ProblemCard({ problem }: { problem: ProblemContext }) {
  return <ProblemBody prompt={problem.prompt} />;
}
