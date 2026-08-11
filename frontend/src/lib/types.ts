export type Board = "MAINBOARD" | "SME";
export type IpoStatus = "UPCOMING" | "OPEN" | "CLOSED" | "LISTED";
export type ChannelName = "EMAIL" | "TELEGRAM" | "WEBPUSH" | "INAPP";

export interface GmpPoint {
  captured_at: string;
  gmp_value: number | null;
  gmp_pct: number | null;
  estimated_listing_price: number | null;
  source: string;
}

export interface SubscriptionPoint {
  captured_at: string;
  category: string;
  shares_offered: number | null;
  shares_bid: number | null;
  times_subscribed: number | null;
}

export interface ScoreComponent {
  key: string;
  label: string;
  raw: number | null;
  score: number;
  weight: number;
  detail: string;
}

export interface Score {
  score: number | null;
  confidence: number;
  components: ScoreComponent[];
  notes: string[];
}

export interface Ipo {
  id: number;
  symbol: string;
  company_name: string;
  board: Board;
  status: IpoStatus;
  exchange: string;
  open_date: string | null;
  close_date: string | null;
  allotment_date: string | null;
  listing_date: string | null;
  price_band_min: number | null;
  price_band_max: number | null;
  lot_size: number | null;
  issue_size: number | null;
  registrar: string | null;
  days_to_close: number | null;
  is_last_day: boolean;
  min_investment: number | null;
  subscription: Record<string, number | null>;
  gmp: GmpPoint | null;
  estimated_listing_price: number | null;
  expected_gain_pct: number | null;
  score: Score | null;
  watchlisted: boolean;
}

export interface IpoDetail extends Ipo {
  subscription_history: SubscriptionPoint[];
  gmp_history: GmpPoint[];
}

export interface User {
  id: number;
  email: string;
  timezone: string;
}

export interface AlertRule {
  id: number;
  rule_type: string;
  ipo_id: number | null;
  threshold: number | null;
  channels: string[];
  fire_hours_ist: number[];
  board_filter: Board | null;
  watchlist_only: boolean;
  active: boolean;
}

export interface NotificationChannel {
  id: number;
  channel: ChannelName;
  destination: string;
  verified_at: string | null;
  is_active: boolean;
}

export interface AppNotification {
  id: number;
  ipo_id: number | null;
  channel: ChannelName;
  title: string;
  body: string;
  url: string | null;
  status: string;
  read_at: string | null;
  created_at: string;
}

export interface ServerConfig {
  channels: Record<ChannelName, boolean>;
  vapid_public_key: string | null;
  gmp_provider: string;
}
