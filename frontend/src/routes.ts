import { createBrowserRouter } from "react-router";
import Root from "./pages/Root";
import Dashboard from "./pages/Dashboard";
import SkillCatalog from "./pages/SkillCatalog";
import Evidence from "./pages/Evidence";
import JobBrowser from "./pages/JobBrowser";
import MatchResults from "./pages/MatchResults";
import Admin from "./pages/Admin";
import NotFound from "./pages/NotFound";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: Root,
    children: [
      { index: true, Component: Dashboard },
      { path: "skills", Component: SkillCatalog },
      { path: "evidence", Component: Evidence },
      { path: "jobs", Component: JobBrowser },
      { path: "match/:jobId", Component: MatchResults },
      { path: "admin", Component: Admin },
      { path: "*", Component: NotFound },
    ],
  },
]);