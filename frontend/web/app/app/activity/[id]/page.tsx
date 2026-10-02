import { SelectedHistory } from "../../../../features/dashboard/Dashboard";
export default async function Page({params}:{params:Promise<{id:string}>}){const {id}=await params;return <SelectedHistory key={id} id={id}/>;}
