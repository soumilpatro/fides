import { NewExtension } from "../../../../../../features/extensions/Extensions";
export default async function Page({params}:{params:Promise<{id:string}>}){const {id}=await params;return <NewExtension key={id} id={id}/>;}
