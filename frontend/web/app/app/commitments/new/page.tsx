import { NewCommitment } from "../../../../features/commitments/Commitments";
export default async function Page({ searchParams }: { searchParams: Promise<{ connection?: string }> }) { const { connection } = await searchParams; return <NewCommitment selected={typeof connection === "string" ? connection : ""} />; }
