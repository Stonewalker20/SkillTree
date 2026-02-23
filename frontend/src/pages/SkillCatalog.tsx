import { useState } from "react";
import { Search, Tag } from "lucide-react";

interface Skill {
  id: string;
  name: string;
  category: string;
  aliases: string[];
}

export default function SkillCatalog() {
  const [selectedCategory, setSelectedCategory] = useState("All");
  const [searchQuery, setSearchQuery] = useState("");
  
  const categories = ["All", "Programming Languages", "Data Science", "Web Development", "Cloud & DevOps", "Tools"];
  
  const skills: Skill[] = [
    { id: "1", name: "Python", category: "Programming Languages", aliases: ["py", "python3"] },
    { id: "2", name: "SQL", category: "Data Science", aliases: ["structured query language", "database"] },
    { id: "3", name: "NumPy", category: "Data Science", aliases: ["numpy", "numerical python"] },
    { id: "4", name: "Pandas", category: "Data Science", aliases: ["pd", "dataframes"] },
    { id: "5", name: "React", category: "Web Development", aliases: ["reactjs", "react.js"] },
    { id: "6", name: "JavaScript", category: "Programming Languages", aliases: ["js", "es6", "ecmascript"] },
    { id: "7", name: "AWS", category: "Cloud & DevOps", aliases: ["amazon web services", "cloud"] },
    { id: "8", name: "Docker", category: "Cloud & DevOps", aliases: ["containers", "containerization"] },
    { id: "9", name: "Git", category: "Tools", aliases: ["version control", "github", "gitlab"] },
    { id: "10", name: "Machine Learning", category: "Data Science", aliases: ["ml", "ai", "artificial intelligence"] },
  ];
  
  const filteredSkills = skills.filter(skill => {
    const matchesCategory = selectedCategory === "All" || skill.category === selectedCategory;
    const matchesSearch = searchQuery === "" || 
      skill.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      skill.aliases.some(alias => alias.toLowerCase().includes(searchQuery.toLowerCase()));
    return matchesCategory && matchesSearch;
  });
  
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-8">
          <h1 className="mb-2">Skill Catalog</h1>
          <p className="text-gray-600">Browse the canonical list of skills recognized by SkillBridge</p>
        </div>
        
        {/* Filters */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Search */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Search Skills
              </label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search by name or alias..."
                  className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded focus:ring-2 focus:ring-[var(--color-navy-light)] focus:border-transparent outline-none"
                />
              </div>
            </div>
            
            {/* Category Filter */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Filter by Category
              </label>
              <select
                value={selectedCategory}
                onChange={(e) => setSelectedCategory(e.target.value)}
                className="w-full px-4 py-2 border border-gray-300 rounded focus:ring-2 focus:ring-[var(--color-navy-light)] focus:border-transparent outline-none"
              >
                {categories.map((category) => (
                  <option key={category} value={category}>
                    {category}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
        
        {/* Results Count */}
        <div className="mb-4">
          <p className="text-sm text-gray-600">
            Showing {filteredSkills.length} skill{filteredSkills.length !== 1 ? 's' : ''}
          </p>
        </div>
        
        {/* Skills Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredSkills.map((skill) => (
            <div
              key={skill.id}
              className="bg-white rounded-lg shadow-sm border border-gray-200 p-5 hover:border-[var(--color-navy-light)] transition-colors"
            >
              <div className="flex items-start justify-between mb-3">
                <h3 className="text-lg">{skill.name}</h3>
                <Tag className="w-4 h-4 text-[var(--color-gold)] flex-shrink-0 mt-1" />
              </div>
              
              <div className="mb-3">
                <span className="inline-block px-3 py-1 bg-blue-50 text-[var(--color-navy)] rounded-full text-sm">
                  {skill.category}
                </span>
              </div>
              
              {skill.aliases.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-gray-500 mb-2">Aliases:</p>
                  <div className="flex flex-wrap gap-1">
                    {skill.aliases.map((alias, index) => (
                      <span
                        key={index}
                        className="inline-block px-2 py-0.5 bg-gray-100 text-gray-600 rounded text-xs"
                      >
                        {alias}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
        
        {filteredSkills.length === 0 && (
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-12 text-center">
            <p className="text-gray-500">No skills found matching your criteria.</p>
          </div>
        )}
      </div>
    </div>
  );
}
