import "@testing-library/jest-dom";

// jsdom lacks IntersectionObserver (used by scroll-reveal components like TerritoryBanner). Provide a
// no-op polyfill so full-page renders work in tests.
if (typeof global.IntersectionObserver === "undefined") {
  global.IntersectionObserver = class {
    constructor() {}
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() { return []; }
  };
}
