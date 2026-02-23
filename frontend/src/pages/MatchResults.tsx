import { useParams, Link } from "react-router";
import { CheckCircle, AlertTriangle, FileText, ArrowLeft, TrendingUp } from "lucide-react";

interface MatchResult {
  jobId: string;
  jobTitle: string;
  company: string;
  matchScore: number;
  matchedSkills: MatchedSkill[];
  missingSkills: string[];
}

interface MatchedSkill {
  name: string;
  evidenceItems: EvidenceReference[];
}

interface EvidenceReference {
  id: string;
  title: string;
  type: string;
  excerpt: string;
}

export default function MatchResults() {
  const { jobId } = useParams();
  
  // Mock data - in real app, this would be fetched based on jobId
  const matchResult: MatchResult = {
    jobId: jobId || "1",
    jobTitle: "Data Scientist",
    company: "Tech Corp",
    matchScore: 75,
    matchedSkills: [
      {
        name: "Python",
        evidenceItems: [
          {
            id: "1",
            title: "Software Engineering Resume",
            type: "Resume",
            excerpt: "Experienced software engineer with 3+ years in Python...",
          },
          {
            id: "2",
            title: "Machine Learning Research Paper",
            type: "Paper",
            excerpt: "We implemented the model using TensorFlow and NumPy with Python...",
          },
        ],
      },
      {
        name: "SQL",
        evidenceItems: [
          {
            id: "1",
            title: "Software Engineering Resume",
            type: "Resume",
            excerpt: "Built scalable web applications with SQL databases...",
          },
          {
            id: "4",
            title: "Data Analytics Portfolio",
            type: "Project",
            excerpt: "Collection of data analysis projects using Python and SQL...",
          },
        ],
      },
      {
        name: "Machine Learning",
        evidenceItems: [
          {
            id: "2",
            title: "Machine Learning Research Paper",
            type: "Paper",
            excerpt: "This paper presents a novel approach to sentiment analysis using deep learning techniques...",
          },
        ],
      },
      {
        name: "NumPy",
        evidenceItems: [
          {
            id: "2",
            title: "Machine Learning Research Paper",
            type: "Paper",
            excerpt: "We implemented the model using TensorFlow and NumPy...",
          },
        ],
      },
    ],
    missingSkills: ["Pandas", "TensorFlow", "AWS"],
  };
  
  const getTypeColor = (type: string) => {
    switch (type) {
      case "Resume":
        return "bg-blue-100 text-blue-800";
      case "Paper":
        return "bg-purple-100 text-purple-800";
      case "Project":
        return "bg-green-100 text-green-800";
      default:
        return "bg-gray-100 text-gray-800";
    }
  };
  
  const getScoreColor = (score: number) => {
    if (score >= 80) return "text-green-600";
    if (score >= 60) return "text-yellow-600";
    return "text-red-600";
  };
  
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <Link
            to="/jobs"
            className="inline-flex items-center gap-2 text-[var(--color-navy)] hover:text-[var(--color-navy-light)] mb-4"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Job Browser
          </Link>
          <h1 className="mb-2">Match Results</h1>
          <p className="text-gray-600">
            {matchResult.jobTitle} at {matchResult.company}
          </p>
        </div>
        
        {/* Match Score Card */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
          <div className="flex flex-col md:flex-row items-center md:items-start gap-6">
            <div className="flex-shrink-0 text-center">
              <div className="w-32 h-32 rounded-full border-8 flex items-center justify-center" 
                   style={{ borderColor: matchResult.matchScore >= 70 ? 'var(--color-success)' : 'var(--color-warning)' }}>
                <div>
                  <div className={`text-4xl font-bold ${getScoreColor(matchResult.matchScore)}`}>
                    {matchResult.matchScore}%
                  </div>
                  <div className="text-xs text-gray-500 mt-1">Match</div>
                </div>
              </div>
            </div>
            
            <div className="flex-1">
              <h2 className="mb-4">Overall Match Score</h2>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div className="bg-green-50 rounded-lg p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <CheckCircle className="w-5 h-5 text-[var(--color-success)]" />
                    <span className="font-medium text-gray-700">Matched Skills</span>
                  </div>
                  <div className="text-2xl font-bold text-[var(--color-success)]">
                    {matchResult.matchedSkills.length}
                  </div>
                </div>
                
                <div className="bg-red-50 rounded-lg p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <AlertTriangle className="w-5 h-5 text-[var(--color-danger)]" />
                    <span className="font-medium text-gray-700">Missing Skills</span>
                  </div>
                  <div className="text-2xl font-bold text-[var(--color-danger)]">
                    {matchResult.missingSkills.length}
                  </div>
                </div>
                
                <div className="bg-blue-50 rounded-lg p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <TrendingUp className="w-5 h-5 text-[var(--color-navy)]" />
                    <span className="font-medium text-gray-700">Evidence Items</span>
                  </div>
                  <div className="text-2xl font-bold text-[var(--color-navy)]">
                    {matchResult.matchedSkills.reduce((sum, skill) => sum + skill.evidenceItems.length, 0)}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
        
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Matched Skills with Evidence */}
          <div className="space-y-6">
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
              <div className="flex items-center gap-2 mb-4">
                <CheckCircle className="w-5 h-5 text-[var(--color-success)]" />
                <h2>Matched Skills ({matchResult.matchedSkills.length})</h2>
              </div>
              
              <div className="space-y-4">
                {matchResult.matchedSkills.map((skill, index) => (
                  <div key={index} className="border-l-4 border-[var(--color-success)] pl-4">
                    <h3 className="text-base mb-3">{skill.name}</h3>
                    
                    <div className="space-y-2">
                      <p className="text-xs font-medium text-gray-500 uppercase">
                        Evidence ({skill.evidenceItems.length})
                      </p>
                      {skill.evidenceItems.map((evidence, eIndex) => (
                        <div
                          key={eIndex}
                          className="bg-gray-50 rounded p-3 hover:bg-gray-100 transition-colors"
                        >
                          <div className="flex items-start gap-2 mb-2">
                            <FileText className="w-4 h-4 text-gray-400 flex-shrink-0 mt-0.5" />
                            <div className="flex-1 min-w-0">
                              <div className="flex items-start justify-between gap-2 mb-1">
                                <p className="text-sm font-medium text-gray-900 line-clamp-1">
                                  {evidence.title}
                                </p>
                                <span className={`text-xs px-2 py-0.5 rounded-full flex-shrink-0 ${getTypeColor(evidence.type)}`}>
                                  {evidence.type}
                                </span>
                              </div>
                              <p className="text-xs text-gray-600 line-clamp-2">
                                {evidence.excerpt}
                              </p>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
          
          {/* Missing Skills (Gaps) */}
          <div>
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
              <div className="flex items-center gap-2 mb-4">
                <AlertTriangle className="w-5 h-5 text-[var(--color-danger)]" />
                <h2>Missing Skills ({matchResult.missingSkills.length})</h2>
              </div>
              
              <p className="text-sm text-gray-600 mb-4">
                These skills are required for the job but not found in your evidence. Consider adding evidence or learning these skills.
              </p>
              
              <div className="space-y-2">
                {matchResult.missingSkills.map((skill, index) => (
                  <div
                    key={index}
                    className="flex items-center justify-between p-3 bg-red-50 rounded border border-red-100"
                  >
                    <div className="flex items-center gap-2">
                      <AlertTriangle className="w-4 h-4 text-[var(--color-danger)]" />
                      <span className="font-medium text-gray-900">{skill}</span>
                    </div>
                    <Link
                      to="/evidence"
                      className="text-sm text-[var(--color-navy)] hover:text-[var(--color-navy-light)]"
                    >
                      Add Evidence
                    </Link>
                  </div>
                ))}
              </div>
              
              <div className="mt-6 p-4 bg-blue-50 rounded-lg">
                <h4 className="font-medium text-gray-900 mb-2">Recommendations</h4>
                <ul className="space-y-1 text-sm text-gray-700">
                  <li className="flex items-start gap-2">
                    <span className="text-[var(--color-navy)] mt-1">•</span>
                    <span>Upload projects or coursework demonstrating these skills</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-[var(--color-navy)] mt-1">•</span>
                    <span>Complete online courses or certifications</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-[var(--color-navy)] mt-1">•</span>
                    <span>Build sample projects to demonstrate competency</span>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
