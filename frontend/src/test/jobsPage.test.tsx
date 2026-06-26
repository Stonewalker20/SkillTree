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
    listJobMatchHistory: vi.fn().mockResolvedValue([]),
    listResumeSnapshots: vi.fn().mockResolvedValue([]),
    listEvidence: vi.fn().mockResolvedValue([]),
    ingestJob: vi.fn().mockResolvedValue({}),
    matchJob: vi.fn().mockResolvedValue({}),
    previewTailoredResume: vi.fn().mockResolvedValue({}),
    downloadTailoredDocx: vi.fn().mockResolvedValue({}),
    getJobMatchHistoryDetail: vi.fn().mockResolvedValue({}),
    deleteJobMatchHistory: vi.fn().mockResolvedValue({}),
    reanalyzeJobMatchHistory: vi.fn().mockResolvedValue({}),
    listSkills: vi.fn().mockResolvedValue([]),
    createSkill: vi.fn().mockResolvedValue({}),
    confirmSkill: vi.fn().mockResolvedValue({}),
    unconfirmSkill: vi.fn().mockResolvedValue({}),
    getRewardsSummary: vi.fn().mockResolvedValue(null),
  },
}));

import { Jobs } from "../app/pages/Jobs";

describe("Jobs page", () => {
  it("renders the default job-fit analysis prompt without crashing", async () => {
    render(
      <MemoryRouter>
        <Jobs />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/Run a grounded job-fit analysis/i)).toBeInTheDocument();
  });
});
