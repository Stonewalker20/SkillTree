// Global Vitest setup for component-rendering tests (jsdom environment).
// Pure-function unit tests (avatarPresets, headerTheme, rewardsSummary) don't need any of this,
// but page-level smoke tests render real component trees and pull in Radix UI + recharts, both
// of which expect browser APIs that jsdom does not implement out of the box.

import "@testing-library/jest-dom/vitest";

if (typeof window !== "undefined") {
  if (!window.matchMedia) {
    window.matchMedia = (query: string) =>
      ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList;
  }

  if (!("ResizeObserver" in window)) {
    class ResizeObserverStub {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    // @ts-expect-error - test-only polyfill, jsdom has no ResizeObserver
    window.ResizeObserver = ResizeObserverStub;
  }

  if (!("IntersectionObserver" in window)) {
    class IntersectionObserverStub {
      observe() {}
      unobserve() {}
      disconnect() {}
      takeRecords() {
        return [];
      }
    }
    // @ts-expect-error - test-only polyfill, jsdom has no IntersectionObserver
    window.IntersectionObserver = IntersectionObserverStub;
  }
}
