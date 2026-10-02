import { RepaymentDetail } from "../../../../features/repayments/Repayments";
export default async function Page({params}:{params:Promise<{id:string}>}) {const {id}=await params;return <RepaymentDetail key={id} id={id}/>;}
