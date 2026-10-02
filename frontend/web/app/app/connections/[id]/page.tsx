import { ConnectionDetail } from "../../../../features/connections/Connections";
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params; return <ConnectionDetail key={id} id={id} />;
}
