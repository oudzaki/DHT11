import { useEffect, useMemo, useState } from "react";
import { getAllReadings, getLatest } from "../../api/readings";
import type { Reading } from "../../types";
import MetricCard from "../../components/MetricCard";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import "dayjs/locale/fr"; // pour avoir "il y a 2 minutes" en français
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, CartesianGrid,
} from "recharts";

const SENSOR = "esp8266-1";
dayjs.extend(relativeTime);
dayjs.locale("fr");

export default function Dashboard() {
  const [latest, setLatest] = useState<Reading | null>(null);
  const [list, setList] = useState<Reading[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [lt, all] = await Promise.all([getLatest(SENSOR), getAllReadings()]);
        setLatest(lt);
        // on limite à 200 derniers côté front (tri backend déjà -created_at)
        setList(all.slice(0, 200));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const chartData = useMemo(() => {
    return [...list].reverse().map(r => ({
      time: dayjs(r.created_at).format("HH:mm"),
      temperature: r.temperature,
      humidity: r.humidity,
    }));
  }, [list]);

  // helpers au-dessus du composant (ou dans le composant avant le return)
	function niceDomain(values: number[], hardPad = 0, percentPad = 0.1): [number, number] {
	if (!values.length) return [0, 1];
	let min = Math.min(...values);
	let max = Math.max(...values);
	if (min === max) {
		// si toutes les valeurs sont =, on écarte un peu pour voir la ligne
		min -= Math.max(hardPad, 1);
		max += Math.max(hardPad, 1);
	} else {
		const pad = (max - min) * percentPad + hardPad;
		min -= pad;
		max += pad;
	}
	return [Math.floor(min), Math.ceil(max)];
	}
	const thSticky: React.CSSProperties = {
  position: "sticky",
  top: 0,
  background: "#fff",
  textAlign: "left",
  padding: 8,
  borderBottom: "1px solid #e5e7eb",
  zIndex: 1,
};


  return (
    <div style={{ minHeight: "100vh", background: "#f7fafc" }}>
      <header style={{
        background: "#fff", borderBottom: "1px solid #e5e7eb",
        padding: "12px 20px", display: "flex", justifyContent: "space-between"
      }}>
        <div style={{ fontWeight: 700 }}>DHT Dashboard</div>
        <div style={{ fontSize: 13, opacity: .7 }}>Capteur: {SENSOR}</div>
      </header>

      <main style={{ maxWidth: 1100, margin: "0 auto", padding: 20 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
          <MetricCard label="Température" unit="°C" value={latest?.temperature ?? null} />
          <MetricCard label="Humidité" unit="%" value={latest?.humidity ?? null} />
          {/* <MetricCard label="Dernière mesure" value={latest ? dayjs(latest.created_at).format("YYYY-MM-DD HH:mm:ss") : "—"} /> */}
			 <MetricCard
				label="Dernière mesure"
				value={
					latest
						? dayjs(latest.created_at).format("YYYY-MM-DD HH:mm:ss")
						: "—"
				}
				unit={
					latest
						? `(${dayjs(latest.created_at).fromNow()})`
						: ""
				}
				/>

        </div>

        <div style={{ marginTop: 20, background: "#fff", border: "1px solid #e5e7eb", borderRadius: 16, padding: 16 }}>
          <h3 style={{ marginTop: 0 }}>Historique (les 200 dernières mesures)</h3>
          <div style={{ width: "100%", height: 320 }}>
  <ResponsiveContainer>
    <LineChart data={chartData}>
      <CartesianGrid strokeDasharray="3 3" />

      {/* domaines dynamiques, formatage des ticks */}
      <XAxis dataKey="time" minTickGap={20} />
      <YAxis
        yAxisId="left"
        domain={niceDomain(list.map(r => r.temperature), 1)}  // temp: ± marge
        tickFormatter={(v) => `${v}°C`}
      />
      <YAxis
        yAxisId="right"
        orientation="right"
        domain={niceDomain(list.map(r => r.humidity), 2)}     // hum: ± marge
        tickFormatter={(v) => `${v}%`}
      />

      <Tooltip
        formatter={(value: any, name: any) => {
          if (name === "temperature") return [`${value} °C`, "Température"];
          if (name === "humidity") return [`${value} %`, "Humidité"];
          return [value, name];
        }}
      />
      <Legend />

      {/* Couleurs distinctes */}
      <Line
        type="monotone"
        dataKey="temperature"
        name="température"
        yAxisId="left"
        stroke="#ef4444"     // rouge (Tailwind red-500)
        dot={false}
        strokeWidth={2}
        activeDot={{ r: 4 }}
      />
      <Line
        type="monotone"
        dataKey="humidity"
        name="humidité"
        yAxisId="right"
        stroke="#3b82f6"     // bleu (Tailwind blue-500)
        dot={false}
        strokeWidth={2}
        activeDot={{ r: 4 }}
      />
    </LineChart>
  </ResponsiveContainer>
</div>

        </div>

       <div style={{ marginTop: 20, background: "#fff", border: "1px solid #e5e7eb", borderRadius: 16, padding: 16 }}>
  <h3 style={{ marginTop: 0 }}>Table des mesures</h3>
  {loading ? (
    <div>Chargement...</div>
  ) : (
    <div
      style={{
        overflowY: "auto",
        maxHeight: 380,             // << hauteur fixe : rend la table scrollable
        borderRadius: 12,
        border: "1px solid #f1f5f9",
      }}
    >

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={thSticky}>Date</th>
            <th style={thSticky}>Température (°C)</th>
            <th style={thSticky}>Humidité (%)</th>
            <th style={thSticky}>Capteur</th>
          </tr>
        </thead>
        <tbody>
          {list.map((r) => (
            <tr key={r.id}>
              <td style={td}>{dayjs(r.created_at).format("YYYY-MM-DD HH:mm:ss")}</td>
              <td style={td}>{r.temperature.toFixed(1)}</td>
              <td style={td}>{r.humidity.toFixed(1)}</td>
              <td style={td}>{r.sensor}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )}
</div>

      </main>
    </div>
  );
}

// const th: React.CSSProperties = { textAlign: "left", padding: 8, borderBottom: "1px solid #e5e7eb" };
const td: React.CSSProperties = { padding: 8, borderBottom: "1px solid #f1f5f9", fontSize: 14 };
