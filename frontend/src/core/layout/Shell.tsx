import Header from "./Header";
import Sidebar from "./Sidebar";
import "./shell.css";

export default function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="shell">
      <Sidebar />
      <div className="shell-main">
        <Header />
        <main className="shell-content">{children}</main>
      </div>
    </div>
  );
}
