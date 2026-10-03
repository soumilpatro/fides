import { CommitmentsList } from "../../../features/commitments/Commitments";
import { Summary } from "../../../features/dashboard/Dashboard";
import { DueSummaryOverview } from "../../../features/dashboard/DueSummarySections";
export default function Page(){return <div className="commitments-feature"><h1>Overview</h1><Summary/><DueSummaryOverview/><CommitmentsList dashboard/></div>;}
