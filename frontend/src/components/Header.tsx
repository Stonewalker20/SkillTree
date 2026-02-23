import { Link, useLocation } from "react-router";
import { GraduationCap } from "lucide-react";

export function Header() {
  const location = useLocation();
  
  const navLinks = [
    { path: "/", label: "Dashboard" },
    { path: "/skills", label: "Skills" },
    { path: "/evidence", label: "Evidence" },
    { path: "/jobs", label: "Jobs" },
  ];
  
  return (
    <header className="bg-white border-b border-gray-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-16">
          <Link to="/" className="flex items-center gap-2">
            <div className="w-10 h-10 bg-[var(--color-navy)] rounded-lg flex items-center justify-center">
              <GraduationCap className="w-6 h-6 text-[var(--color-gold)]" />
            </div>
            <span className="text-xl font-bold text-[var(--color-navy)]">SkillBridge</span>
          </Link>
          
          <nav className="hidden md:flex gap-6">
            {navLinks.map((link) => (
              <Link
                key={link.path}
                to={link.path}
                className={`px-3 py-2 rounded-md transition-colors ${
                  location.pathname === link.path
                    ? "text-[var(--color-navy)] bg-blue-50"
                    : "text-gray-600 hover:text-[var(--color-navy)] hover:bg-gray-50"
                }`}
              >
                {link.label}
              </Link>
            ))}
          </nav>
          
          {/* Mobile menu */}
          <nav className="flex md:hidden gap-4">
            {navLinks.map((link) => (
              <Link
                key={link.path}
                to={link.path}
                className={`text-sm px-2 py-1 rounded ${
                  location.pathname === link.path
                    ? "text-[var(--color-navy)] bg-blue-50"
                    : "text-gray-600"
                }`}
              >
                {link.label}
              </Link>
            ))}
          </nav>
        </div>
      </div>
    </header>
  );
}