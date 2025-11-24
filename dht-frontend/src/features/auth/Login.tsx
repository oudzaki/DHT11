import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login } from "../../api/auth";

export default function Login() {
  const nav = useNavigate();
  const [username, setU] = useState("");
  const [password, setP] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setLoading(true);
    try {
      await login(username, password);
      nav("/", { replace: true });
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? "Échec de connexion");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{
      minHeight: "100vh", display: "grid", placeItems: "center",
      background: "#f7fafc"
    }}>
      <form onSubmit={onSubmit} style={{
        width: 360, background: "#fff", padding: 24, borderRadius: 16,
        border: "1px solid #e5e7eb", boxShadow: "0 6px 24px rgba(0,0,0,.06)"
      }}>
        <h1 style={{ margin: 0, marginBottom: 16 }}>Connexion</h1>
        <label style={{ display: "block", fontSize: 13, opacity: .7 }}>Nom d’utilisateur</label>
        <input value={username} onChange={(e)=>setU(e.target.value)} required
               style={{ width: "100%", padding: 10, marginTop: 6, marginBottom: 12, borderRadius: 10, border: "1px solid #e5e7eb" }} />
        <label style={{ display: "block", fontSize: 13, opacity: .7 }}>Mot de passe</label>
        <input type="password" value={password} onChange={(e)=>setP(e.target.value)} required
               style={{ width: "100%", padding: 10, marginTop: 6, marginBottom: 16, borderRadius: 10, border: "1px solid #e5e7eb" }} />
        {err && <div style={{ color: "#b91c1c", fontSize: 13, marginBottom: 8 }}>{err}</div>}
        <button disabled={loading} style={{
          width: "100%", padding: 10, borderRadius: 10, border: "1px solid #e5e7eb",
          background: "#0ea5e9", color: "#fff", cursor: "pointer"
        }}>
          {loading ? "Connexion..." : "Se connecter"}
        </button>
      </form>
    </div>
  );
}
