import Image from "next/image";

export function Brand() {
  return <span className="brand-lockup" aria-label="Fides">
    <Image className="brand-lockup-image" src="/brand/fides-record-loop-horizontal-512x171.png" alt="" width={128} height={43} priority />
  </span>;
}
