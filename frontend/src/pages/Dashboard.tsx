import { Link } from "react-router";
import { CircularProgress } from "../components/CircularProgress";
import { Award, TrendingUp, AlertCircle, CheckCircle, Clock } from "lucide-react";

export default function Dashboard() {
  const topSkills = [
    "SQL",
    "Python",
    "NumPy",
  ];
  
  const recentProjects = [
    "Project A",
    "Project B",
    "Project C",
  ];
  
  const recommendedActions = [
    "Add Evidence for SQL",
    "Analyze a Job Posting",
    "Learn Pandas",
  ];
  
  const latestJobAnalyses = [
    { jobTitle: "Data Analyst", company: "XYZ Corp", match: "78%", id: "5" },
    { jobTitle: "Web Developer", company: "ABC Inc", match: "65%", id: "2" },
  ];
  
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-8">
          <h1 className="mb-2">Dashboard</h1>
          <p className="text-gray-600">Your portfolio overview and recent activity</p>
        </div>
        
        {/* Desktop: 3 columns, Mobile: stack */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
          {/* Summary Card */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <h3 className="mb-4">Summary</h3>
            <div className="space-y-4">
              <div>
                <p className="text-sm text-gray-600 mb-1">Match Score: 78%</p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Evidence Coverage:</p>
                <p className="text-lg font-semibold text-[var(--color-navy)]">12/15 Skills</p>
              </div>
            </div>
          </div>
          
          {/* Top Skills Card */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <h3 className="mb-4">Top Skills</h3>
            <ul className="space-y-2">
              {topSkills.map((skill, index) => (
                <li key={index} className="flex items-center gap-2 text-gray-700">
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-navy)]"></span>
                  {skill}
                </li>
              ))}
            </ul>
          </div>
          
          {/* Recommended Actions Card */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <h3 className="mb-4">Recommended Actions</h3>
            <ul className="space-y-2">
              {recommendedActions.map((action, index) => (
                <li key={index} className="flex items-center gap-2 text-gray-700">
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-navy)]"></span>
                  {action}
                </li>
              ))}
            </ul>
          </div>
        </div>
        
        {/* Desktop: 2 columns, Mobile: stack */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Recent Projects Card */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <h3 className="mb-4">Recent Projects</h3>
            <ul className="space-y-2">
              {recentProjects.map((project, index) => (
                <li key={index} className="flex items-center gap-2 text-gray-700">
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-navy)]"></span>
                  {project}
                </li>
              ))}
            </ul>
          </div>
          
          {/* Latest Job Analyses Card */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <h3 className="mb-4">Latest Job Analyses</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200">
                    <th className="text-left py-2 text-gray-600 font-medium">Job Title</th>
                    <th className="text-left py-2 text-gray-600 font-medium">Company</th>
                    <th className="text-left py-2 text-gray-600 font-medium">Match</th>
                  </tr>
                </thead>
                <tbody>
                  {latestJobAnalyses.map((job, index) => (
                    <tr key={index} className="border-b border-gray-100 last:border-0">
                      <td className="py-3">
                        <Link to={`/match/${job.id}`} className="text-[var(--color-navy)] hover:text-[var(--color-navy-light)]">
                          {job.jobTitle}
                        </Link>
                      </td>
                      <td className="py-3 text-gray-700">{job.company}</td>
                      <td className="py-3 text-gray-700">{job.match}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}