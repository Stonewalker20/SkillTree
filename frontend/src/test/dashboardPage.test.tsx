import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";

// Page-level smoke test: mock every context hook and API method the page touches on mount,
// then assert the page renders its first stable heading without throwing. This intentionally
// does not exercise interactive flows (buttons, dialogs) - it only guards against the page
// crashing outright when real (but empty/default-shaped) data comes back from the backend.

vi.mock("../app/context/AuthContext", () => ({
  useAuth: () => ({
    user: {
      id: "user-1",
      username: "tester",
      role: "user",
      is_new_user: false,
      onboarding: { started_at: "2024-01-01T00:00:00Z" },
    },
    isLoading: false,
    isAuthenticated: true,
    login: vi.fn(),
    signup: vi.fn(),
    logout: vi.fn(),
    refreshUser: vi.fn(),
  }),
}));

vi.mock("../app/context/ActivityContext", () => ({
  useActivity: () => ({
    activities: [],
    recordActivity: vi.fn(),
    clearActivities: vi.fn(),
  }),
}));

vi.mock("../app/context/AccountPreferencesContext", () => ({
  useAccountPreferences: () => ({
    preferences: {
      startPage: "/app",
      sidebarItems: ["dashboard", "skills", "analytics", "evidence", "jobs", "quickActions", "admin"],
      gradientMode: "full",
      panelStyle: "tinted",
      showWelcomeHero: true,
      showRecentActivity: true,
      showPortfolioInsights: true,
      showNextAchievementCard: true,
      reducedMotion: false,
    },
    updatePreferences: vi.fn(),
    resetPreferences: vi.fn(),
  }),
}));

vi.mock("../app/services/api", () => ({
  api: {
    getDashboardSummary: vi.fn().mockResolvedValue({}),
    listSkills: vi.fn().mockResolvedValue([]),
    getProfileConfirmation: vi.fn().mockResolvedValue(null),
    listTailoredResumes: vi.fn().mockResolvedValue([]),
    getRewardsSummary: vi.fn().mockResolvedValue(null),
    updateMyOnboarding: vi.fn().mockResolvedValue({}),
  },
}));

import { Dashboard } from "../app/pages/Dashboard";

describe("Dashboard page", () => {
  it("renders the welcome heading once data has loaded, without crashing", async () => {
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/Welcome back/i)).toBeInTheDocument();
  });
});
