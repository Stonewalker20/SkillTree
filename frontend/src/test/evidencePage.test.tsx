import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";

vi.mock("../app/context/AuthContext", () => ({
  useAuth: () => ({
    user: { id: "user-1", username: "tester", role: "user" },
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
    listEvidence: vi.fn().mockResolvedValue([]),
    listSkills: vi.fn().mockResolvedValue([]),
    getRewardsSummary: vi.fn().mockResolvedValue(null),
    analyzeEvidence: vi.fn().mockResolvedValue({}),
    createSkill: vi.fn().mockResolvedValue({}),
    updateEvidence: vi.fn().mockResolvedValue({}),
    createEvidence: vi.fn().mockResolvedValue({}),
    confirmProfileSkills: vi.fn().mockResolvedValue({}),
    deleteEvidence: vi.fn().mockResolvedValue({}),
  },
}));

import { Evidence } from "../app/pages/Evidence";

describe("Evidence page", () => {
  it("renders the evidence library heading without crashing", async () => {
    render(
      <MemoryRouter>
        <Evidence />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/Your proof of work, organized and skill-linked\./i)).toBeInTheDocument();
  });
});
