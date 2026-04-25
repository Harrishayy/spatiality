/** @type {import('tailwindcss').Config} */
export default {
  // Scope the JIT scan to files that actually emit JSX. SplatViewer.tsx is
  // the heavy one; if it lived in a non-jsx subdir we'd exclude it. As-is,
  // we still need it scanned for its 39 className attrs, but excluding the
  // PLY parser body would be ideal — if SplatViewer is split later, narrow
  // this glob to ./app/{components,scenes,hooks}/**/*.tsx and ./app/*.tsx.
  content: ["./app/**/*.tsx"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0a0a0c",
          900: "#111114",
          800: "#1a1a20",
          700: "#26262e",
          600: "#3a3a46",
          500: "#5c5c6e",
          400: "#8d8da0",
          300: "#bcbcd0",
          200: "#dedeea",
          100: "#f3f3f8",
        },
        accent: {
          500: "#7c5cff",
          400: "#9b85ff",
          300: "#beb3ff",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      keyframes: {
        pulse: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.4" },
        },
        slide: {
          from: { transform: "translateY(8px)", opacity: "0" },
          to: { transform: "translateY(0)", opacity: "1" },
        },
      },
      animation: {
        "slide-in": "slide 200ms ease-out",
      },
    },
  },
  plugins: [],
};
