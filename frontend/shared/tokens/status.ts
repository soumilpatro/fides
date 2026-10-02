export const statusColors = {
  VERIFIED: { text: "#16624D", background: "#E8F5F0", border: "#89C8B5" },
  PENDING: { text: "#8A5A00", background: "#FFF4D6", border: "#F0C86E" },
  DISPUTED: { text: "#9D2E3B", background: "#FCEBED", border: "#E9A0AA" },
  OVERDUE: { text: "#9A3F15", background: "#FFF0E6", border: "#E7A178" },
  CLOSED: { text: "#59616B", background: "#F0F2F4", border: "#CDD2D7" },
} as const;
export type SemanticStatus = keyof typeof statusColors;
