import type { Room } from "@/types/domain";

/**
 * Rooms are hardcoded until the room API exists.
 *
 * Ids stay prefixed `course_` on purpose: they are the backend's actual
 * `course_id` values (see docs/TUTOR_AGENT.md), not a frontend label, and
 * `course_demo` is the one the chain-rule lecture was ingested under, so it
 * is the room where grounding actually works today. Renaming these strings
 * would silently break retrieval.
 */
export const ROOMS: Room[] = [
  {
    id: "course_demo",
    name: "MATH 101",
    description: "Calculus I — limits, derivatives, the chain rule.",
  },
  {
    id: "course_linear",
    name: "MATH 221",
    description: "Linear algebra — vectors, matrices, eigenvalues.",
  },
];

export function getRoom(roomId: string): Room | undefined {
  return ROOMS.find((room) => room.id === roomId);
}
