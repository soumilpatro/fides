import Image from "next/image";

export function Brand() {
  return <span className="brand-lockup" aria-label="Fides">
    <Image className="brand-mark" src="/brand/record-loop.svg" alt="" width={40} height={36} priority />
    <span className="brand-name">Fides</span>
  </span>;
}
