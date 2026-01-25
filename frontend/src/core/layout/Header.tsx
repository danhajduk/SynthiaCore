export default function Header() {
  return (
    <header
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 16px",
        borderBottom: "1px solid rgba(255,255,255,0.08)",
        background: "rgba(0,0,0,0.2)",
        backdropFilter: "blur(10px)",
      }}
    >
      <div style={{ fontWeight: 700 }}>Synthia</div>
      <div style={{ opacity: 0.7, fontSize: 12 }}>Core shell + Addons</div>
    </header>
  );
}
