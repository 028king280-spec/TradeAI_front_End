import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatINR(val: number, includeDecimals = true): string {
  if (isNaN(val)) return "₹0.00";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: includeDecimals ? 2 : 0,
    maximumFractionDigits: includeDecimals ? 2 : 0,
  }).format(val);
}

export function formatPercent(val: number, includeSign = true): string {
  if (isNaN(val)) return "0.00%";
  const formatted = val.toFixed(2) + "%";
  if (includeSign && val > 0) {
    return `+${formatted}`;
  }
  return formatted;
}

export function formatNumberIN(val: number): string {
  return new Intl.NumberFormat("en-IN").format(val);
}

export function formatVolume(num: number): string {
  if (num >= 10000000) {
    return `${(num / 10000000).toFixed(2)}Cr`;
  }
  if (num >= 100000) {
    return `${(num / 100000).toFixed(2)}L`;
  }
  if (num >= 1000) {
    return `${(num / 1000).toFixed(1)}k`;
  }
  return num.toString();
}

export function getISTTimestamp(): string {
  return "03 Sep 2026, 10:42 AM IST";
}
