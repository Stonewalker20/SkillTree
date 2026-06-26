import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";

vi.mock("../app/context/AuthContext", () => ({
  useAuth: () => ({
    user: { id: "admin-1", username: "owner", role: "owner" },
    isLoading: false,
    isAuthenticated: true,
    login: vi.fn(),
    signup: vi.fn(),
    logout: vi.fn(),
    refreshUser: vi.fn(),
  }),
}));

vi.mock("../app/services/api", () => ({
  api: {
    getAdminSummary: vi.fn().mockResolvedValue({}),
    listAdminUsers: vi.fn().mockResolvedValue([]),
    listAdminJobs: vi.fn().mockResolvedValue([]),
    listAdminSkills: vi.fn().mockResolvedValue([]),
    listAdminHelpRequests: vi.fn().mockResolvedValue([]),
    updateAdminUserRole: vi.fn().mockResolvedValue({}),
    deactivateAdminUser: vi.fn().mockResolvedValue({}),
    moderateAdminJob: vi.fn().mockResolvedValue({}),
    updateAdminHelpRequest: vi.fn().mockResolvedValue({}),
    deleteSkill: vi.fn().mockResolvedValue({}),
  },
}));

import { Admin } from "../app/pages/Admin";

describe("Admin page", () => {
  it("renders the admin workspace heading once data has loaded, without crashing", async () => {
    render(
      <MemoryRouter>
        <Admin />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/Owner and team control center/i)).toBeInTheDocument();
  });
});
