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
    // `available: false` keeps the experiment/run-detail follow-up effects from firing,
    // so they don't need their own mocks for this smoke test to stay crash-free.
    getAdminMlflowOverview: vi.fn().mockResolvedValue({
      available: false,
      experiment_count: 0,
      registered_model_count: 0,
      latest_run_started_at: null,
      tracking_uri: "",
      experiments: [],
    }),
    listAdminMlflowDatasets: vi.fn().mockResolvedValue([]),
    listAdminMlflowJobs: vi.fn().mockResolvedValue([]),
    getAdminMlflowLocalOptions: vi.fn().mockResolvedValue({
      available_inference_modes: [],
      embedding_models: [],
      zero_shot_models: [],
      rewrite_models: [],
      default_inference_mode: "",
      default_embedding_model: "",
      default_zero_shot_model: "",
      default_rewrite_model: "",
      presets: [],
    }),
    listAdminMlflowExperimentRuns: vi.fn().mockResolvedValue([]),
    getAdminMlflowRunDetail: vi.fn().mockResolvedValue(null),
    launchAdminMlflowExperiment: vi.fn().mockResolvedValue({}),
    launchAdminMlflowDatasetExport: vi.fn().mockResolvedValue({}),
  },
}));

import { AdminMlflow } from "../app/pages/AdminMlflow";

describe("AdminMlflow page", () => {
  it("renders the model operations heading once data has loaded, without crashing", async () => {
    render(
      <MemoryRouter>
        <AdminMlflow />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/Model operations workspace/i)).toBeInTheDocument();
  });
});
