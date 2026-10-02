import { connectionUuid } from "./connections";
export function isAllowedApiRoute(method: string, path: string[]) {
  if (!path.length || path.some(part => !/^[a-zA-Z0-9-]+$/.test(part))) return false;
  const endpoint = path.join("/");
  if (method === "GET" && ["me", "summary"].includes(endpoint)) return true;
  if (method === "POST" && ["auth/otp/request", "auth/otp/verify", "auth/refresh", "auth/logout"].includes(endpoint)) return true;
  if (method === "PATCH" && endpoint === "me") return true;
  if (method === "POST" && endpoint === "me/deactivate") return true;
  if (path[0] === "notifications") return path.length === 1 ? method === "GET" : path.length === 3 && connectionUuid.test(path[1]) && path[2] === "read" && method === "POST";
  if (path[0] === "extension-requests") return path.length === 3 && connectionUuid.test(path[1]) && ["accept","reject"].includes(path[2]) && method === "POST";
  if (path[0] === "commitments") {
    if (path.length === 1) return method === "GET" || method === "POST";
    if (!connectionUuid.test(path[1])) return false;
    if (path.length === 2) return method === "GET";
    return path.length === 3 && (method === "GET" ? ["terms", "installments", "repayments", "ledger", "extension-requests"].includes(path[2]) :
      method === "POST" && ["confirm", "reject", "cancel", "repayments", "extension-requests"].includes(path[2]));
  }
  if (path[0] === "repayments") {
    if (!connectionUuid.test(path[1] ?? "")) return false;
    if (path.length === 2) return method === "GET";
    return path.length === 3 && (method === "GET" ? path[2] === "verification-history" : method === "POST" && ["verify","dispute"].includes(path[2]));
  }
  if (path[0] !== "connections") return false;
  if (path.length === 1) return method === "GET" || method === "POST";
  if (!connectionUuid.test(path[1])) return false;
  if (path.length === 2) return method === "GET" || method === "DELETE";
  return path.length === 3 && method === "POST" && ["accept", "reject", "block"].includes(path[2]);
}

// F5 read query allowlist; all earlier routes retain their existing contracts.
export function isAllowedApiQuery(path:string[],query:URLSearchParams){
 if(path.length===1&&path[0]==="summary")return query.size===0;
 if(path[0]==="me"||path[0]==="extension-requests"||path[0]==="notifications"&&path.length>1||path[0]==="commitments"&&path[2]==="extension-requests")return query.size===0;
 if(!(path.length===1&&path[0]==="notifications")&&(path.length!==3||path[0]!=="commitments"||path[2]!=="ledger"))return true;
 for(const [key,value] of query){
  if(query.getAll(key).length!==1)return false;
  if(key==="limit"){if(!/^[0-9]+$/.test(value)||Number(value)<1||Number(value)>100)return false;}
  else if(key==="cursor"){if(!value.length||value.length>512||/[\u0000-\u001f\u007f]/.test(value))return false;}
  else return false;
 }
 return true;
}
