export type HotelSearchResult = {
  name: string | null;
  property_token: string | null;
  price_per_night: number | null;
  rating: number | null;
  amenities: string[] | null;
  thumbnail?: string | null;
};

export type HotelSearchResponse = {
  search_query: string;
  check_in_date: string;
  check_out_date: string;
  result_count: number;
  properties: HotelSearchResult[];
};

export type HotelRevalidationRequest = {
  property_token: string;
  q: string;
  check_in_date: string;
  check_out_date: string;
  adults: number;
  children: number;
  currency: "USD";
  gl: "us";
  hl: "en";
  displayed_price_per_night?: number;
};

export type HotelRevalidationResponse = {
  property_token: string;
  hotel_name: string;
  check_in_date: string;
  check_out_date: string;
  adults: number;
  children: number;
  currency: "USD";
  number_of_nights: number;
  availability: "available";
  rate_rule: "lowest_eligible_provider_base_total";
  source: string;
  guest_capacity: number;
  current_price_per_night: number;
  provider_base_total: number;
  provider_total_with_taxes_fees: number | null;
  likehome_reservation_total: number;
  likehome_payment_amount: number;
  price_changed: boolean | null;
};

export type BookingRequest = {
  hotel_token: string;
  guest_full_name: string;
  guest_email: string;
  q: string;
  check_in_date: string;
  check_out_date: string;
  adults: number;
  children: number;
  currency: "USD";
  gl: "us";
  hl: "en";
  price_per_night: number;
  accepted_payment_amount: number;
};

export type BookingResponse = {
  user_id: number;
  hotel_id: number;
  room_type_id: number;
  reservation_id: number;
  payment_id: number;
};

export type RegisterUserRequest = {
  email: string;
  password: string;
  full_name?: string;
  phone?: string;
};

export type RegisterUserResponse = {
  user_id: number;
  email: string;
  full_name: string | null;
  phone: string | null;
};

export type LoginUserRequest = {
  email: string;
  password: string;
};

export type LoginUserResponse = {
  user_id: number;
  email: string;
  full_name: string | null;
  phone: string | null;
  access_token: string;
  token_type: string;
};

export type CurrentUserResponse = {
  message: string;
  user_id: number;
};

export type LogoutUserResponse = {
  status: boolean;
  message: string;
};

export type BookingListItem = {
  reservation_id: number;
  hotel_name: string;
  room_type_name: string;
  hotel_address: string;
  hotel_phone: string | null;
  hotel_description: string | null;
  room_description: string | null;
  check_in_date: string;
  check_out_date: string;
  price_per_night: number;
  total_price: number;
  status: "confirmed" | "cancelled" | "completed";
};

export type BookingListResponse = BookingListItem[];

export type BookingDetailItem = BookingListItem & {
  guest_full_name: string | null;
  guest_email: string | null;
};

export type BookingDetailResponse = BookingDetailItem | null;

export type CancellationResponse = {
  reservation_id: number;
  status: "cancelled";
  booking_payment_id: number;
  booking_payment_status: "refunded";
  cancellation_payment_id: number;
  cancellation_amount: number;
  cancellation_payment_status: "pending";
};
