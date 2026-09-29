/** Presentation only, no balances, aggregation, FX or financial calculations. */
export function formatMoney(
  minor: number,
  currency: string,
  locale = "en-IN",
): string {
  if (!Number.isSafeInteger(minor))
    throw new RangeError("Money must be a safe integer in minor units");
  if (!/^[A-Z]{3}$/.test(currency))
    throw new RangeError("Currency must be explicit ISO text");
  const formatter = new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    currencyDisplay: "code",
  });
  const digits = formatter.resolvedOptions().maximumFractionDigits ?? 2;
  // A decimal string avoids losing paise at the upper safe-integer boundary.
  const magnitude = BigInt(minor < 0 ? -minor : minor)
    .toString()
    .padStart(digits + 1, "0");
  const decimal = `${minor < 0 ? "-" : ""}${digits ? magnitude.slice(0, -digits) + "." + magnitude.slice(-digits) : magnitude}`;
  return formatter.format(decimal as unknown as number);
}
