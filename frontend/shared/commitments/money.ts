// Exact input conversion only; no interest totals, allocation, FX or aggregation.
function hundredths(value: string, maximum: number, label: string) {
  if (!/^[0-9]+(?:\.[0-9]{1,2})?$/.test(value)) throw new Error(label + ": use a decimal with at most two fractional digits.");
  const [whole, fraction = ""] = value.split(".");
  const amount = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
  if (amount <= 0n || amount > BigInt(maximum)) throw new Error(label + " is outside the supported range.");
  return Number(amount);
}
export const parseMinor = (value: string) => hundredths(value, 1_000_000_000_000, "Amount");
export const parseBps = (value: string) => hundredths(value, 10000, "Interest percentage");
export const percentText = (bps: number) => (Math.floor(bps / 100) + "." + String(bps % 100).padStart(2, "0")) + "%";
