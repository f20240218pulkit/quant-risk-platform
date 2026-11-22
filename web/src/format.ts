const wholeAmount = new Intl.NumberFormat("en-AU");
const dateFormat = new Intl.DateTimeFormat("en-AU", { dateStyle: "medium", timeZone: "UTC" });
export const money = (value: string, signed = false) => {
  // The API emits fixed-point strings. Round cents without converting money
  // through a binary floating-point value.
  const negative = value.startsWith("-");
  const [whole, fraction = ""] = (negative ? value.slice(1) : value).split(".");
  const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0").slice(0, 2));
  const rounded = fraction.length > 2 && fraction[2] >= "5" ? cents + 1n : cents;
  const sign = rounded === 0n ? "" : negative ? "-" : signed ? "+" : "";
  return sign + "$" + wholeAmount.format(rounded / 100n) + "." + String(rounded % 100n).padStart(2, "0");
};
export const day = (value: string) => dateFormat.format(new Date(value));
