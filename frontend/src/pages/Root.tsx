import { Outlet } from "react-router";
import { Header } from "../components/Header";

export default function Root() {
  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <Outlet />
    </div>
  );
}
