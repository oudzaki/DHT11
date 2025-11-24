import { Navigate } from "react-router-dom";
import { getTokens } from "../api/client";

type Props = { children: React.ReactNode };

export default function ProtectedRoute({ children }: Props) {
  const tk = getTokens();
  if (!tk?.access) return <Navigate to="/login" replace />;
  return <>{children}</>;
}
