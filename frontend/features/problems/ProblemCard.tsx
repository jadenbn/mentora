import katex from "katex";
import type { Problem } from "@/types/domain";

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
    if (value[cursor] === "$" && !isEscaped(value, cursor)) {
      return cursor;
    }
  }
  return -1;
}

function closingDelimiter(
  value: string,
  from: number,
  display: boolean,
): number {
  for (let cursor = from; cursor < value.length; cursor += 1) {
    if (value[cursor] !== "$" || isEscaped(value, cursor)) {
      continue;
    }
    if (display ? value[cursor + 1] === "$" : value[cursor + 1] !== "$") {
      return cursor;
    }
  }
  return -1;
}

function readableText(value: string): string {
  return value.replace(/\\\$/g, "$");
}

/** Split a safe, deliberately small plain-text + dollar-math format. */
export function parseProblemPrompt(prompt: string): ProblemSegment[] {
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
      segments.push({
        kind: "text",
        value: readableText(prompt.slice(cursor, opening)),
      });
    }

    const source = prompt.slice(opening, closing + delimiterLength);
    const math = prompt.slice(contentStart, closing);
    if (math.trim()) {
      segments.push({ kind: "math", value: math, display, source });
    } else {
      segments.push({ kind: "text", value: source });
    }
    cursor = closing + delimiterLength;
  }

  return segments.length > 0 ? segments : [{ kind: "text", value: "" }];
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
    // Fall through to the readable source expression below.
  }

  if (markup !== null) {
    const Element = segment.display ? "div" : "span";
    return (
      <Element
        className={segment.display ? "my-2 overflow-x-auto py-1" : "inline-math"}
        dangerouslySetInnerHTML={{ __html: markup }}
      />
    );
  }

  return (
    <code
      className={
        segment.display
          ? "my-3 block overflow-x-auto rounded bg-stone-100 px-2 py-1 font-mono text-[0.9em]"
          : "rounded bg-stone-100 px-1 font-mono text-[0.9em]"
      }
      data-math-error
    >
      {segment.source}
    </code>
  );
}

export function ProblemBody({ prompt }: { prompt: string }) {
  return (
    <div className="whitespace-pre-wrap text-[clamp(1rem,1.55vw,1.3rem)] leading-relaxed text-[#202620]">
      {parseProblemPrompt(prompt).map((segment, index) =>
        segment.kind === "math" ? (
          <MathSegment key={`${index}-${segment.source}`} segment={segment} />
        ) : (
          <span key={`${index}-${segment.value}`}>{segment.value}</span>
        ),
      )}
    </div>
  );
}

export function ProblemCard({ problem }: { problem: Problem }) {
  return (
    <section
      aria-labelledby="workspace-problem-heading"
      className="shrink-0 border-b border-[#d9d6cc] bg-[#f5f2e9] px-4 py-3 sm:px-6 sm:py-4"
    >
      <div className="mx-auto max-h-[32dvh] max-w-5xl overflow-y-auto rounded-2xl border border-[#d8d3c6] border-l-[6px] border-l-[#607d6c] bg-[#fffdf8] px-5 py-4 shadow-[0_10px_30px_rgba(48,58,48,0.08)] sm:px-8 sm:py-5">
        <p
          className="mb-2 text-[0.7rem] font-bold uppercase tracking-[0.2em] text-[#607d6c]"
          id="workspace-problem-heading"
        >
          Problem
        </p>
        <ProblemBody prompt={problem.prompt} />
      </div>
    </section>
  );
}
