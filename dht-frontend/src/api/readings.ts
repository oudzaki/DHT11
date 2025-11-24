// utilise `pub` pour les endpoints publics
import { pub } from "./client";
import type { Reading } from "../types";

export async function getLatest(sensorName: string): Promise<Reading | null> {
  const { data } = await pub.get<Reading>(`/api/readings/latest/${sensorName}/`);
  return data ?? null;
}
export async function getAllReadings(): Promise<Reading[]> {
  const { data } = await pub.get<Reading[]>("/api/readings/");
  return data;
}
