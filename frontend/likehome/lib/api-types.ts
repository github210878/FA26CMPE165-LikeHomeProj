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
  next_page_token?: string | null;
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

export type PaymentResponse = {
  payment_id: number;
  reservation_id: number;
  amount: number;
  payment_type: "booking" | "cancellation";
  payment_status: "pending" | "paid" | "failed" | "refunded";
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
  booking_payment_status: "pending" | "refunded";
  cancellation_payment_id: number;
  cancellation_amount: number;
  cancellation_payment_status: "pending";
};

// Internal ledger entries are separate from refunds, cash balances, and rewards.
export type AdjustmentDetailResponse = {
  adjustment_id: number;
  change_id: number;
  reservation_id: number;
  currency: "USD";
  entry_role: "price_change" | "cancellation_reconciliation";
  reconciles_adjustment_id: number | null;
  kind: "charge" | "credit";
  amount: number;
  status: "pending" | "paid" | "failed" | "recorded" | "voided";
  settled_at: string | null;
};

export type ReservationFinancialSummary = {
  reservation_id: number;
  reservation_revision: number;
  reservation_status: "confirmed" | "cancelled" | "completed";
  currency: "USD";
  latest_change_id: number | null;
  current_reservation_total: number;
  current_booking_obligation: number;
  original_booking_payment: PaymentResponse;
  paid_additional_charges: number;
  pending_additional_charges: number;
  failed_additional_charges: number;
  recorded_internal_credits: number;
  outstanding_additional_amount: number;
  adjustments: AdjustmentDetailResponse[];
  voided_additional_charges: number;
  cancellation_reconciliations: AdjustmentDetailResponse[];
  reconciliation_credits: number;
  reconciliation_debits: number;
  cancellation_payment: PaymentResponse | null;
  outstanding_cancellation_amount: number;
  outstanding_booking_amount: number;
};

export type ReservationChangeReviewRequest = {
  check_in_date: string;
  check_out_date: string;
  q: string;
  adults: number;
  children: number;
  currency?: "USD";
  gl?: "us";
  hl?: "en";
};

// A temporary review artifact; receiving it does not confirm a reservation change.
export type ReservationChangeQuoteResponse = {
  reservation_id: number;
  quote_id: string;
  expires_at: string;
  quote: HotelRevalidationResponse;
};

// The public receipt request allows past stay dates for exact committed retries.
export type ReservationChangeConfirmRequest = {
  check_in_date: string;
  check_out_date: string;
  quote_id: string;
  accept_quote: true;
  price_per_night: number;
  accepted_payment_amount: number;
};

export type ReservationChangeReceiptAdjustment = {
  adjustment_id: number;
  kind: "charge" | "credit";
  amount: string;
  status: "pending" | "recorded";
};

// Historical confirmation result; money stays in canonical decimal strings and
// adjustment status describes confirmation, rather than current settlement.
export type ReservationChangeReceiptResponse = {
  change_id: number;
  reservation_id: number;
  revision: number;
  room_type_id: number;
  check_in_date: string;
  check_out_date: string;
  reservation_total: string;
  payment_obligation: string;
  previous_payment_obligation: string;
  payment_difference: string;
  booking_payment_id: number;
  booking_payment_status: "pending" | "paid";
  adjustment: ReservationChangeReceiptAdjustment | null;
};

export type AdjustmentSettlementRequest = {
  accepted_amount: number;
  reservation_revision: number;
  accept_payment: true;
};

// Settlement retains the numeric adjustment contract, unlike historical receipts.
export type AdjustmentSettlementResponse = AdjustmentDetailResponse & {
  entry_role: "price_change";
  kind: "charge";
  status: "paid";
  settled_at: string;
};
