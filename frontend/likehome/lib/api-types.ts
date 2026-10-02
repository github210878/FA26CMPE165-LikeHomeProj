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
