import { SpaceWorkspace } from "@/features/spaces/SpaceWorkspace";

export default async function SpacePage({
  params,
}: {
  params: Promise<{ spaceId: string }>;
}) {
  const { spaceId } = await params;

  return <SpaceWorkspace spaceId={spaceId} />;
}
