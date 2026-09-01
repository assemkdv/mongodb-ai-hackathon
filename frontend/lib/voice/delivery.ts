import type { Delivery, Energy, Manner, Pace } from "./types";

const PACES: Pace[] = ["slow", "normal", "fast"];
const ENERGIES: Energy[] = ["flat", "warm", "sharp"];
const MANNERS: Manner[] = ["clipped", "measured", "dismissive"];

export const DEFAULT_DELIVERY: Delivery = {
  pace: "normal",
  energy: "flat",
  manner: "measured",
};

/** Leading `[pace|energy|manner]` tag, tolerant of spacing and case. */
const TAG = /^\s*\[\s*([a-z]+)\s*\|\s*([a-z]+)\s*\|\s*([a-z]+)\s*\]\s*/i;

/**
 * Splits a persona reply into its delivery tag and the words actually spoken,
 * so the transcript can show the line and its delivery separately. (The voice
 * mapping itself lives in the backend: server/app/agent/delivery.py.)
 */
export function parseDelivery(raw: string): { delivery: Delivery; line: string } {
  const match = raw.match(TAG);
  if (!match) {
    return { delivery: DEFAULT_DELIVERY, line: raw.trim() };
  }

  const [pace, energy, manner] = match.slice(1, 4).map((s) => s.toLowerCase());
  return {
    delivery: {
      pace: (PACES as string[]).includes(pace) ? (pace as Pace) : DEFAULT_DELIVERY.pace,
      energy: (ENERGIES as string[]).includes(energy) ? (energy as Energy) : DEFAULT_DELIVERY.energy,
      manner: (MANNERS as string[]).includes(manner) ? (manner as Manner) : DEFAULT_DELIVERY.manner,
    },
    line: raw.slice(match[0].length).trim(),
  };
}
