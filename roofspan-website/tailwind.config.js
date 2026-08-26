/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,jsx}", "./components/**/*.{js,jsx}", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        navy: { DEFAULT: "#0B1B3A", 900: "#081228", 700: "#12244a" },
        brand: { DEFAULT: "#1E63C8", 600: "#1a56ad", 400: "#4f8ee0" },
        slate: { ink: "#0f172a", body: "#334155", muted: "#64748b", line: "#e2e8f0", soft: "#f1f5f9" },
        safety: { DEFAULT: "#F26A1B", 600: "#d95a12" },
      },
      fontFamily: {
        sans: ["var(--font-ibm)", "system-ui", "sans-serif"],
        display: ["var(--font-manrope)", "system-ui", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(11,27,58,.06), 0 8px 24px -12px rgba(11,27,58,.18)",
        lift: "0 20px 60px -24px rgba(11,27,58,.45)",
      },
      borderRadius: { xl2: "1.25rem" },
      maxWidth: { content: "1180px" },
    },
  },
  plugins: [],
};
