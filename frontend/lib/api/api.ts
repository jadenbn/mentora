import { TutorAnnotation } from "@/types/annotations";

export const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

export async function testAnnotation(
  request: TutorAnnotation,
): Promise<TutorAnnotation> {
  const response = await fetch(`${apiBaseUrl}/api/testing`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error("req failed");
  }

  return response.json();
}
