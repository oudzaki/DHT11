type Props = {
  label: string;
  value?: string | number | null;
  unit?: string;
  icon?: React.ReactNode;
};

export default function MetricCard({ label, value, unit, icon }: Props) {
  return (
    <div style={{
      border: "1px solid #e5e7eb",
      borderRadius: 16,
      padding: 16,
      background: "#fff",
      boxShadow: "0 6px 24px rgba(0,0,0,.06)"
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ fontSize: 22 }}>{icon}</div>
        <div>
          <div style={{ opacity: .7, fontSize: 13 }}>{label}</div>
          <div style={{ fontSize: 24, fontWeight: 700 }}>
				{value ?? "—"}
				{unit && unit.startsWith("(")
					? <div style={{ fontSize: 14, opacity: .7 }}>{unit}</div>
					: <span style={{ fontSize: 14, marginLeft: 6 }}>{unit}</span>
				}
				</div>
        </div>
      </div>
    </div>
  );
}
