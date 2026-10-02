import { notFound } from "next/navigation";
import { Button, EmptyState } from "../../../components/ui";
const destinations: Record<string, string> = { overview: "Overview", connections: "Connections", activity: "Activity", notifications: "Notifications", profile: "Profile / Settings" };
export default async function Destination({ params }: { params: Promise<{ destination: string }> }) {
  const { destination } = await params;
  if (!Object.hasOwn(destinations, destination)) notFound();
  const title = destinations[destination];
  return <><p className="eyebrow">FIDES</p><h1>{title}</h1><EmptyState title="Your account is ready." message="This destination is reserved for a future release." />{destination === "overview" && <div className="button-row"><Button disabled>Create commitment · future release</Button></div>}</>;
}
