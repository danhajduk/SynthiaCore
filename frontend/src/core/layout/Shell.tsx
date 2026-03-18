import Sidebar from "./Sidebar";
import "./shell.css";

export default function Shell({
  children,
  isAdmin,
  chromeless = false,
}: {
  children: React.ReactNode;
  isAdmin: boolean;
  chromeless?: boolean;
}) {
  if (chromeless) {
    return (
      <div className="shell shell-chromeless">
        <main className="shell-content shell-content-chromeless">{children}</main>
      </div>
    );
  }

  return (
    <div className="shell">
      <Sidebar isAdmin={isAdmin} />
      <div className="shell-main">
        <main className="shell-content">{children}</main>
      </div>
    </div>
  );
}
