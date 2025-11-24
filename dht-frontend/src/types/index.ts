export type Reading = {
  id: number;
  sensor: string;          // slug "esp8266-1"
  temperature: number;
  humidity: number;
  created_at: string;      // ISO
};

export type TokenPair = {
  access: string;
  refresh: string;
};
