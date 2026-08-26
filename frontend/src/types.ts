export type Location = {
  code: string;
  city_fa: string;
  city_en: string;
  airport_fa: string;
  airport_en: string;
  aliases: string[];
};

export type HotelDestination = {
  code: string;
  city_fa: string;
  city_en: string;
  country_fa: string;
  country_en: string;
  aliases: string[];
};

export type AlertRecord = {
  id: string;
  status: "active" | "cancelled" | "expired";
  criteria: {
    trip_type: "one_way" | "round_trip";
    origin: string;
    destination: string;
    outbound_dates: { start: string; end: string };
    return_dates?: { start: string; end: string };
  };
  expires_at: string;
  next_run_at: string;
  created_at: string;
};

export type HotelAlertRecord = {
  id: string;
  status: "active" | "cancelled" | "expired";
  criteria: {
    destination: string;
    checkin_dates: { start: string; end: string };
    nights: number;
    rooms: number;
    occupancy: { adults: number; children: number };
  };
  expires_at: string;
  next_run_at: string;
  created_at: string;
};

export type TelegramWebApp = {
  initData: string;
  colorScheme: "light" | "dark";
  ready: () => void;
  expand: () => void;
  close: () => void;
  HapticFeedback?: {
    notificationOccurred: (type: "success" | "error" | "warning") => void;
  };
};

declare global {
  interface Window {
    Telegram?: { WebApp: TelegramWebApp };
  }
}

