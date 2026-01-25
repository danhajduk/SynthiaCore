import Header from "./Header";
import Sidebar from "./Sidebar";

export default function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", height: "100vh" }}>
      <Sidebar />
      <div style={{ display: "grid", gridTemplateRows: "56px 1fr" }}>
        <Header />
        <main style={{ padding: 16, overflow: "auto" }}>{children}</main>
      </div>
    </div>
  );
}
