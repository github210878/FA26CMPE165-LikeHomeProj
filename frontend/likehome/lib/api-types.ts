export type RegisterRequest = {
  email: string;
  password: string;
  full_name: string | null;
  phone: string | null;
};

export type RegisterResponse = {
  user_id: number;
  email: string;
  full_name: string | null;
  phone: string | null;
};

export type HotelRate = {
  lowest: string | null;
  extracted_lowest: number | null;
  before_taxes_fees: string | null;
  extracted_before_taxes_fees: number | null;
};

export type HotelSearchResult = {
  name: string | null;
  property_token: string | null;
  price_per_night: number | null;
  rating: number | null;
  amenities: string[] | null;
  hotel_class: string | null;
  overall_rating: number | null;
  reviews: number | null;
  rate_per_night: HotelRate | null;
  total_rate: HotelRate | null;
  thumbnail: string | null;
  link: string | null;
  gps_coordinates: Record<string, unknown> | null;
};

export type HotelSearchResponse = {
  search_query: string;
  check_in_date: string;
  check_out_date: string;
  result_count: number;
  properties: HotelSearchResult[];
};
