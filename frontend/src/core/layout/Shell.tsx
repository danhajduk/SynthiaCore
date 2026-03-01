import Header from "./Header";
import Sidebar from "./Sidebar";
import "./shell.css";

export default function Shell({ children, isAdmin }: { children: React.ReactNode; isAdmin: boolean }) {
  return (
    <div className="shell">
      <Sidebar isAdmin={isAdmin} />
      <div className="shell-main">
        <Header />
        <main className="shell-content">{children}</main>
      </div>
    </div>
  );
}
