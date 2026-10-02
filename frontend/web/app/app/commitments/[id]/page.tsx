import { CommitmentDetail } from "../../../../features/commitments/Commitments";
export default async function Page({ params }: { params: Promise<{ id: string }> }) { const { id } = await params; return <CommitmentDetail key={id} id={id} />; }
