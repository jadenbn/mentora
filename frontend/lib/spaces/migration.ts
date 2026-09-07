import { createSpace } from "@/lib/api/api";
import type { ProblemContext, Space } from "@/types/domain";

const LEGACY_KEY = "mentora:spaces";

interface LegacySpace {
  id: string;
  courseId: string;
  title?: string;
  problem?: ProblemContext;
}

function readLegacySpaces(): LegacySpace[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(LEGACY_KEY) ?? "null");
    if (!Array.isArray(value)) return [];
    return value.filter(
      (space): space is LegacySpace =>
        typeof space === "object" &&
        space !== null &&
        typeof space.id === "string" &&
        typeof space.courseId === "string",
    );
  } catch {
    return [];
  }
}

function removeLegacySpaces(ids: Set<string>): void {
  if (ids.size === 0) return;
  try {
    const remaining = readLegacySpaces().filter((space) => !ids.has(space.id));
    if (remaining.length === 0) {
      localStorage.removeItem(LEGACY_KEY);
    } else {
      localStorage.setItem(LEGACY_KEY, JSON.stringify(remaining));
    }
  } catch {
    // Storage failure must not prevent server-backed spaces from loading.
  }
}

export function legacySpaceIds(courseId: string): string[] {
  return readLegacySpaces()
    .filter((space) => space.courseId === courseId)
    .map((space) => space.id);
}

export function clearLegacySpaces(courseId: string): void {
  removeLegacySpaces(new Set(legacySpaceIds(courseId)));
}

export async function migrateLegacySpaces(
  courseId: string,
  serverSpaces: Space[],
): Promise<{ spaces: Space[]; failed: number }> {
  const known = new Set(serverSpaces.map((space) => space.id));
  const migratedIds = new Set<string>();
  const result = [...serverSpaces];
  let failed = 0;

  for (const legacy of readLegacySpaces().filter((space) => space.courseId === courseId)) {
    if (known.has(legacy.id)) {
      migratedIds.add(legacy.id);
      continue;
    }
    try {
      const space = await createSpace(courseId, {
        space_id: legacy.id,
        title: legacy.title,
        problem_id: legacy.problem?.id,
      });
      result.push(space);
      known.add(space.id);
      migratedIds.add(legacy.id);
    } catch {
      failed += 1;
    }
  }

  removeLegacySpaces(migratedIds);
  return { spaces: result, failed };
}

export async function migrateLegacySpace(spaceId: string): Promise<Space | null> {
  const legacy = readLegacySpaces().find((space) => space.id === spaceId);
  if (!legacy) return null;
  try {
    const space = await createSpace(legacy.courseId, {
      space_id: legacy.id,
      title: legacy.title,
      problem_id: legacy.problem?.id,
    });
    removeLegacySpaces(new Set([legacy.id]));
    return space;
  } catch {
    return null;
  }
}
