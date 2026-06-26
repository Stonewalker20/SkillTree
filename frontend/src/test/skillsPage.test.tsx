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

vi.mock("../app/services/api", () => ({
  api: {
    listSkills: vi.fn().mockResolvedValue([]),
    getProfileConfirmation: vi.fn().mockResolvedValue(null),
    listEvidence: vi.fn().mockResolvedValue([]),
    confirmSkill: vi.fn().mockResolvedValue({}),
    unconfirmSkill: vi.fn().mockResolvedValue({}),
    setSkillProficiency: vi.fn().mockResolvedValue({}),
    createSkill: vi.fn().mockResolvedValue({}),
  },
}));

import { Skills } from "../app/pages/Skills";

describe("Skills page", () => {
  it("renders the skills toolbar without crashing", async () => {
    render(
      <MemoryRouter>
        <Skills />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Add Skill")).toBeInTheDocument();
  });
});
