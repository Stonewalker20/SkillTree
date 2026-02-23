import { useState } from "react";
import { FileText, ExternalLink, Tag, Plus, Upload } from "lucide-react";

interface EvidenceItem {
  id: string;
  title: string;
  type: "Resume" | "Paper" | "Project";
  excerpt: string;
  skills: string[];
  uploadDate: string;
  url?: string;
}

export default function Evidence() {
  const [selectedType, setSelectedType] = useState("All");
  
  const evidenceItems: EvidenceItem[] = [
    {
      id: "1",
      title: "Software Engineering Resume",
      type: "Resume",
      excerpt: "Experienced software engineer with 3+ years in Python, React, and cloud technologies. Built scalable web applications...",
      skills: ["Python", "React", "AWS", "SQL", "Git"],
      uploadDate: "2024-02-01",
    },
    {
      id: "2",
      title: "Machine Learning Research Paper",
      type: "Paper",
      excerpt: "This paper presents a novel approach to sentiment analysis using deep learning techniques. We implemented the model using TensorFlow and NumPy...",
      skills: ["Machine Learning", "Python", "NumPy", "TensorFlow", "Data Analysis"],
      uploadDate: "2024-01-15",
      url: "https://example.com/paper.pdf",
    },
    {
      id: "3",
      title: "E-Commerce Web App",
      type: "Project",
      excerpt: "Full-stack e-commerce platform built with React frontend and Node.js backend. Implemented user authentication, payment processing...",
      skills: ["React", "JavaScript", "Node.js", "MongoDB", "Docker"],
      uploadDate: "2024-01-28",
      url: "https://github.com/example/ecommerce",
    },
    {
      id: "4",
      title: "Data Analytics Portfolio",
      type: "Project",
      excerpt: "Collection of data analysis projects using Python and SQL. Includes customer segmentation, sales forecasting, and visualization dashboards...",
      skills: ["Python", "SQL", "Pandas", "Data Visualization", "Tableau"],
      uploadDate: "2024-02-05",
      url: "https://github.com/example/analytics",
    },
  ];
  
  const types = ["All", "Resume", "Paper", "Project"];
  
  const filteredEvidence = selectedType === "All" 
    ? evidenceItems 
    : evidenceItems.filter(item => item.type === selectedType);
  
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
  
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-8 gap-4">
          <div>
            <h1 className="mb-2">Evidence</h1>
            <p className="text-gray-600">Manage your uploaded artifacts and skill evidence</p>
          </div>
          <button className="flex items-center gap-2 px-4 py-2 bg-[var(--color-navy)] text-white rounded hover:bg-[var(--color-navy-light)] transition-colors">
            <Upload className="w-4 h-4" />
            Upload Evidence
          </button>
        </div>
        
        {/* Filter Tabs */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-2 mb-6 flex flex-wrap gap-2">
          {types.map((type) => (
            <button
              key={type}
              onClick={() => setSelectedType(type)}
              className={`px-4 py-2 rounded transition-colors ${
                selectedType === type
                  ? "bg-[var(--color-navy)] text-white"
                  : "bg-white text-gray-600 hover:bg-gray-50"
              }`}
            >
              {type}
            </button>
          ))}
        </div>
        
        {/* Evidence List */}
        <div className="space-y-4">
          {filteredEvidence.map((item) => (
            <div
              key={item.id}
              className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 hover:border-[var(--color-navy-light)] transition-colors"
            >
              <div className="flex flex-col lg:flex-row gap-4">
                {/* Left Section - Icon and Type */}
                <div className="flex-shrink-0">
                  <div className="w-12 h-12 bg-blue-50 rounded-lg flex items-center justify-center">
                    <FileText className="w-6 h-6 text-[var(--color-navy)]" />
                  </div>
                </div>
                
                {/* Middle Section - Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-start justify-between gap-2 mb-2">
                    <h3 className="text-lg">{item.title}</h3>
                    <span className={`px-3 py-1 rounded-full text-sm font-medium ${getTypeColor(item.type)}`}>
                      {item.type}
                    </span>
                  </div>
                  
                  <p className="text-gray-600 text-sm mb-3 line-clamp-2">
                    {item.excerpt}
                  </p>
                  
                  <div className="flex flex-wrap items-center gap-4 text-sm text-gray-500">
                    <span>Uploaded: {new Date(item.uploadDate).toLocaleDateString()}</span>
                    {item.url && (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1 text-[var(--color-navy)] hover:text-[var(--color-navy-light)]"
                      >
                        <ExternalLink className="w-3 h-3" />
                        View Source
                      </a>
                    )}
                  </div>
                </div>
                
                {/* Right Section - Skills */}
                <div className="lg:w-64 flex-shrink-0">
                  <div className="flex items-center gap-2 mb-2">
                    <Tag className="w-4 h-4 text-gray-400" />
                    <p className="text-sm font-medium text-gray-700">Extracted Skills ({item.skills.length})</p>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {item.skills.map((skill, index) => (
                      <span
                        key={index}
                        className="inline-block px-2 py-1 bg-blue-50 text-[var(--color-navy)] rounded text-xs"
                      >
                        {skill}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
        
        {filteredEvidence.length === 0 && (
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-12 text-center">
            <FileText className="w-12 h-12 text-gray-300 mx-auto mb-4" />
            <p className="text-gray-500 mb-4">No evidence items found.</p>
            <button className="inline-flex items-center gap-2 px-4 py-2 bg-[var(--color-navy)] text-white rounded hover:bg-[var(--color-navy-light)] transition-colors">
              <Plus className="w-4 h-4" />
              Upload Your First Evidence
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
