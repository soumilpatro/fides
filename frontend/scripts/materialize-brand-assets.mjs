import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot=resolve(dirname(fileURLToPath(import.meta.url)),"..");
const sources=resolve(frontendRoot,"brand","runtime");
const assets=[
 {name:"lockup",sha256:"96241a43e68c2963a7032533eb8a8835b85f78a7e024d5a450d9f62ea8597319",targets:["web/public/brand/fides-record-loop-horizontal-512x171.png","mobile/assets/fides-record-loop-horizontal-512x171.png"]},
 {name:"app-icon",sha256:"48ed724de3e68381ebb91b98f8f05b480ffe68f22296013c3761a0fa7f168e9c",targets:["mobile/assets/fides-app-icon-indigo-1024x1024.png"]},
 {name:"splash",sha256:"4d81bdbd08257305fb7f8f471c8c81416a1f4eac7621d59eb89d137fb1aa0a00",targets:["mobile/assets/fides-splash-portrait-1170x2532.png"]},
];

for(const asset of assets){
 const folder=resolve(sources,asset.name);
 const files=(await readdir(folder)).filter(name=>name.endsWith(".b64")).sort();
 if(!files.length)throw new Error("Missing locked Fides brand data for "+asset.name);
 const encoded=(await Promise.all(files.map(name=>readFile(resolve(folder,name),"utf8")))).join("").replace(/\s+/g,"");
 const bytes=Buffer.from(encoded,"base64");
 const digest=createHash("sha256").update(bytes).digest("hex");
 if(digest!==asset.sha256)throw new Error("Locked Fides asset checksum mismatch for "+asset.name);
 for(const target of asset.targets){
  const output=resolve(frontendRoot,target);
  await mkdir(dirname(output),{recursive:true});
  await writeFile(output,bytes);
 }
}
