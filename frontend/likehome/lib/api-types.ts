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
