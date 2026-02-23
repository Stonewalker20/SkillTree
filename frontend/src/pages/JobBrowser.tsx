import { useState } from "react";
import { Briefcase, MapPin, Building2, ChevronRight, Search } from "lucide-react";
import { Link } from "react-router";

interface Job {
  id: string;
  title: string;
  company: string;
  location: string;
  postedDate: string;
  requiredSkills: string[];
  descriptionExcerpt: string;
}

export default function JobBrowser() {
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  
  const jobs: Job[] = [
    {
      id: "1",
      title: "Data Scientist",
      company: "Tech Corp",
      location: "San Francisco, CA",
      postedDate: "2024-02-05",
      requiredSkills: ["Python", "SQL", "Machine Learning", "Pandas", "NumPy", "TensorFlow"],
      descriptionExcerpt: "We're looking for a talented Data Scientist to join our analytics team. You'll work on building predictive models, analyzing large datasets, and delivering insights that drive business decisions. Experience with Python, SQL, and modern ML frameworks is required.",
    },
    {
      id: "2",
      title: "Full Stack Developer",
      company: "Startup Inc",
      location: "Remote",
      postedDate: "2024-02-07",
      requiredSkills: ["React", "JavaScript", "Node.js", "MongoDB", "Docker", "AWS"],
      descriptionExcerpt: "Join our fast-growing startup as a Full Stack Developer. You'll be responsible for building scalable web applications using modern technologies. Strong experience with React, Node.js, and cloud platforms is essential.",
    },
    {
      id: "3",
      title: "Machine Learning Engineer",
      company: "AI Solutions",
      location: "New York, NY",
      postedDate: "2024-02-03",
      requiredSkills: ["Python", "Machine Learning", "PyTorch", "AWS", "Docker", "Kubernetes"],
      descriptionExcerpt: "We're seeking a Machine Learning Engineer to develop and deploy ML models at scale. You'll work on cutting-edge AI projects and collaborate with cross-functional teams to bring ML solutions to production.",
    },
    {
      id: "4",
      title: "Frontend Developer",
      company: "Design Studio",
      location: "Austin, TX",
      postedDate: "2024-02-06",
      requiredSkills: ["React", "JavaScript", "TypeScript", "CSS", "Git"],
      descriptionExcerpt: "Looking for a creative Frontend Developer to build beautiful, responsive web applications. You'll work closely with designers to bring mockups to life using React and modern CSS frameworks.",
    },
    {
      id: "5",
      title: "Data Analyst",
      company: "Finance Group",
      location: "Chicago, IL",
      postedDate: "2024-02-04",
      requiredSkills: ["SQL", "Python", "Tableau", "Excel", "Data Visualization"],
      descriptionExcerpt: "Join our finance team as a Data Analyst. You'll be responsible for analyzing financial data, creating dashboards, and providing insights to senior management. Strong SQL and visualization skills required.",
    },
  ];
  
  const filteredJobs = searchQuery === ""
    ? jobs
    : jobs.filter(job =>
        job.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        job.company.toLowerCase().includes(searchQuery.toLowerCase()) ||
        job.requiredSkills.some(skill => skill.toLowerCase().includes(searchQuery.toLowerCase()))
      );
  
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-8">
          <h1 className="mb-2">Job Browser</h1>
          <p className="text-gray-600">Browse job postings and analyze your skill match</p>
        </div>
        
        {/* Search */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-6">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by job title, company, or required skills..."
              className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded focus:ring-2 focus:ring-[var(--color-navy-light)] focus:border-transparent outline-none"
            />
          </div>
        </div>
        
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Job List */}
          <div className="lg:col-span-1 space-y-3 max-h-[800px] overflow-y-auto">
            {filteredJobs.map((job) => (
              <div
                key={job.id}
                onClick={() => setSelectedJob(job)}
                className={`bg-white rounded-lg shadow-sm border p-4 cursor-pointer transition-all ${
                  selectedJob?.id === job.id
                    ? "border-[var(--color-navy)] ring-2 ring-[var(--color-navy-light)] ring-opacity-50"
                    : "border-gray-200 hover:border-[var(--color-navy-light)]"
                }`}
              >
                <div className="flex items-start justify-between mb-2">
                  <h3 className="text-base font-medium text-gray-900 line-clamp-1">{job.title}</h3>
                  <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0" />
                </div>
                
                <div className="space-y-1 mb-3">
                  <div className="flex items-center gap-2 text-sm text-gray-600">
                    <Building2 className="w-3 h-3" />
                    <span className="line-clamp-1">{job.company}</span>
                  </div>
                  <div className="flex items-center gap-2 text-sm text-gray-600">
                    <MapPin className="w-3 h-3" />
                    <span className="line-clamp-1">{job.location}</span>
                  </div>
                </div>
                
                <div className="flex items-center justify-between text-xs text-gray-500">
                  <span>{job.requiredSkills.length} skills required</span>
                  <span>{new Date(job.postedDate).toLocaleDateString()}</span>
                </div>
              </div>
            ))}
            
            {filteredJobs.length === 0 && (
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-8 text-center">
                <p className="text-gray-500">No jobs found matching your search.</p>
              </div>
            )}
          </div>
          
          {/* Job Details */}
          <div className="lg:col-span-2">
            {selectedJob ? (
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                <div className="mb-6">
                  <div className="flex items-start justify-between mb-4">
                    <div>
                      <h2 className="mb-2">{selectedJob.title}</h2>
                      <div className="flex flex-wrap items-center gap-4 text-gray-600">
                        <div className="flex items-center gap-2">
                          <Building2 className="w-4 h-4" />
                          <span>{selectedJob.company}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <MapPin className="w-4 h-4" />
                          <span>{selectedJob.location}</span>
                        </div>
                      </div>
                    </div>
                    <Link
                      to={`/match/${selectedJob.id}`}
                      className="px-4 py-2 bg-[var(--color-navy)] text-white rounded hover:bg-[var(--color-navy-light)] transition-colors whitespace-nowrap"
                    >
                      Analyze Match
                    </Link>
                  </div>
                  
                  <div className="text-sm text-gray-500 mb-4">
                    Posted: {new Date(selectedJob.postedDate).toLocaleDateString('en-US', { 
                      year: 'numeric', 
                      month: 'long', 
                      day: 'numeric' 
                    })}
                  </div>
                </div>
                
                {/* Required Skills */}
                <div className="mb-6">
                  <h3 className="mb-3">Required Skills ({selectedJob.requiredSkills.length})</h3>
                  <div className="flex flex-wrap gap-2">
                    {selectedJob.requiredSkills.map((skill, index) => (
                      <span
                        key={index}
                        className="px-3 py-1.5 bg-blue-50 text-[var(--color-navy)] rounded-full text-sm font-medium"
                      >
                        {skill}
                      </span>
                    ))}
                  </div>
                </div>
                
                {/* Description Excerpt */}
                <div>
                  <h3 className="mb-3">Job Description</h3>
                  <p className="text-gray-700 leading-relaxed">
                    {selectedJob.descriptionExcerpt}
                  </p>
                </div>
              </div>
            ) : (
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-12 text-center">
                <Briefcase className="w-12 h-12 text-gray-300 mx-auto mb-4" />
                <p className="text-gray-500">Select a job posting to view details</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
