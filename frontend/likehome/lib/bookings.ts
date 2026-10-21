import { ApiError, getAuthorizedJson, postAuthorizedJson } from "./api.ts";
import type { AdjustmentDetailResponse, AdjustmentSettlementRequest, AdjustmentSettlementResponse, BookingDetailItem, BookingDetailResponse, BookingListItem, BookingListResponse, BookingRequest, BookingResponse, CancellationResponse, HotelRevalidationResponse, PaymentResponse, ReservationChangeConfirmRequest, ReservationChangeQuoteResponse, ReservationChangeReceiptAdjustment, ReservationChangeReceiptResponse, ReservationChangeReviewRequest, ReservationFinancialSummary } from "./api-types.ts";
import { validateSearchInputs } from "./search-validation.mjs";
import { getAccessToken } from "./token-storage.ts";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isBookingResponse(value: unknown): value is BookingResponse {
  return isRecord(value) &&
    Number.isInteger(value.user_id) && (value.user_id as number) > 0 &&
    Number.isInteger(value.hotel_id) && (value.hotel_id as number) > 0 &&
    Number.isInteger(value.room_type_id) && (value.room_type_id as number) > 0 &&
    Number.isInteger(value.reservation_id) && (value.reservation_id as number) > 0 &&
    Number.isInteger(value.payment_id) && (value.payment_id as number) > 0 &&
    typeof value.booking_reference === "string" && /^LH-\d{8,}$/.test(value.booking_reference) &&
    value.status === "confirmed";
}

function isPaymentResponse(value: unknown): value is PaymentResponse {
  return isRecord(value) &&
    Number.isInteger(value.payment_id) && (value.payment_id as number) > 0 &&
    Number.isInteger(value.reservation_id) && (value.reservation_id as number) > 0 &&
    typeof value.amount === "number" && Number.isFinite(value.amount) && value.amount >= 0 &&
    (value.payment_type === "booking" || value.payment_type === "cancellation") &&
    ["pending", "paid", "failed", "refunded"].includes(value.payment_status as string);
}

export async function getPaymentDetails(paymentId: number): Promise<PaymentResponse | null> {
  if (!Number.isSafeInteger(paymentId) || paymentId <= 0) throw new Error("Invalid payment ID");
  const token = getAccessToken();
  if (!token) throw new ApiError(401);
  const response = await getAuthorizedJson<unknown>(`/bookings/get-payment-details/${paymentId}`, token);
  if (response === null) return null;
  if (!isPaymentResponse(response) || response.payment_id !== paymentId) {
    throw new Error("Payment details returned an unexpected response");
  }
  return response;
}

export async function getMyPayments(): Promise<PaymentResponse[]> {
  const token = getAccessToken();
  if (!token) throw new ApiError(401);
  const response = await getAuthorizedJson<unknown>("/bookings/get-all-payments", token);
  if (!Array.isArray(response) || !response.every(isPaymentResponse)) {
    throw new Error("Payments returned an unexpected response");
  }
  return response;
}

export async function payBookingPayment(paymentId: number): Promise<PaymentResponse> {
  if (!Number.isSafeInteger(paymentId) || paymentId <= 0) throw new Error("Invalid payment ID");
  const token = getAccessToken();
  if (!token) throw new ApiError(401);
  const response = await postAuthorizedJson<unknown>(`/bookings/pay/${paymentId}`, token);
  if (!isPaymentResponse(response) || response.payment_id !== paymentId ||
      response.payment_type !== "booking" || response.payment_status !== "paid") {
    throw new Error("Payment returned an unexpected response");
  }
  return response;
}

export async function createBooking(request: BookingRequest): Promise<BookingResponse> {
  const token = getAccessToken();
  if (!token) throw new ApiError(401);
  const response = await postAuthorizedJson<unknown, BookingRequest>("/bookings/create", token, request);
  if (!isBookingResponse(response)) throw new Error("Booking creation returned an unexpected response");
  return response;
}

function isBookingListItem(value: unknown): value is BookingListItem {
  return isRecord(value) &&
    Number.isInteger(value.reservation_id) && (value.reservation_id as number) > 0 &&
    typeof value.hotel_name === "string" &&
    typeof value.room_type_name === "string" &&
    typeof value.hotel_address === "string" &&
    isNullableString(value.hotel_phone) &&
    isNullableString(value.hotel_description) &&
    isNullableString(value.room_description) &&
    typeof value.check_in_date === "string" && /^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(value.check_in_date) &&
    typeof value.check_out_date === "string" && /^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(value.check_out_date) &&
    typeof value.price_per_night === "number" && Number.isFinite(value.price_per_night) &&
    typeof value.total_price === "number" && Number.isFinite(value.total_price) &&
    (value.status === "confirmed" || value.status === "cancelled" || value.status === "completed");
}

function isBookingDetailItem(value: unknown): value is BookingDetailItem {
  if (!isRecord(value)) return false;
  const fields = value;
  return isBookingListItem(value) &&
    isNullableString(fields.guest_full_name) &&
    isNullableString(fields.guest_email);
}

export async function getMyBookings(): Promise<BookingListResponse> {
  const token = getAccessToken();
  if (!token) throw new ApiError(401);

  const response = await getAuthorizedJson<unknown>("/bookings/get-all-bookings", token);
  if (!Array.isArray(response) || !response.every(isBookingListItem)) {
    throw new Error("Bookings returned an unexpected response");
  }
  return response;
}

export async function getBookingDetails(reservationId: number): Promise<BookingDetailResponse> {
  if (!Number.isInteger(reservationId) || reservationId <= 0) {
    throw new Error("Invalid reservation ID");
  }
  const token = getAccessToken();
  if (!token) throw new ApiError(401);

  const response = await getAuthorizedJson<unknown>(
    `/bookings/get-booking-details/${reservationId}`,
    token,
  );
  if (response === null) return null;
  if (!isBookingDetailItem(response)) {
    throw new Error("Booking details returned an unexpected response");
  }
  return response;
}

function isCancellationResponse(value: unknown): value is CancellationResponse {
  return isRecord(value) &&
    Number.isInteger(value.reservation_id) && (value.reservation_id as number) > 0 &&
    value.status === "cancelled" &&
    Number.isInteger(value.booking_payment_id) && (value.booking_payment_id as number) > 0 &&
    (value.booking_payment_status === "pending" || value.booking_payment_status === "refunded") &&
    Number.isInteger(value.cancellation_payment_id) && (value.cancellation_payment_id as number) > 0 &&
    typeof value.cancellation_amount === "number" && Number.isFinite(value.cancellation_amount) && value.cancellation_amount >= 0 &&
    value.cancellation_payment_status === "pending";
}

export async function cancelBooking(reservationId: number): Promise<CancellationResponse> {
  if (!Number.isInteger(reservationId) || reservationId <= 0) {
    throw new Error("Invalid reservation ID");
  }
  const token = getAccessToken();
  if (!token) throw new ApiError(401);

  const response = await postAuthorizedJson<unknown>(
    `/bookings/cancel-booking/${reservationId}`,
    token,
  );
  if (!isCancellationResponse(response) || response.reservation_id !== reservationId) {
    throw new Error("Cancellation returned an unexpected response");
  }
  return response;
}

export async function cancelBookingAndRefresh(
  reservationId: number,
  onCancelled: (response: CancellationResponse) => void,
): Promise<{ kind: "refreshed"; bookings: BookingListResponse } | { kind: "refresh-error"; error: unknown }> {
  const cancellation = await cancelBooking(reservationId);
  onCancelled(cancellation);
  try {
    return { kind: "refreshed", bookings: await getMyBookings() };
  } catch (error: unknown) {
    return { kind: "refresh-error", error };
  }
}

function isPositiveSafeId(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function isFinancialAmount(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function isAwareSettlementTimestamp(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.exec(value);
  if (!match || !Number.isFinite(Date.parse(value))) return false;
  const [, year, month, day] = match;
  const calendar = new Date(`${year}-${month}-${day}T00:00:00Z`);
  return calendar.getUTCFullYear() === Number(year) &&
    calendar.getUTCMonth() + 1 === Number(month) && calendar.getUTCDate() === Number(day);
}

function isFinancialPayment(
  value: unknown, reservationId: number, kind: PaymentResponse["payment_type"],
): value is PaymentResponse {
  return isPaymentResponse(value) && isPositiveSafeId(value.payment_id) &&
    value.reservation_id === reservationId && value.payment_type === kind &&
    (kind === "cancellation" || value.amount > 0);
}

function isFinancialAdjustment(
  value: unknown, reservationId: number, role: AdjustmentDetailResponse["entry_role"],
): value is AdjustmentDetailResponse {
  if (!isRecord(value) || !isPositiveSafeId(value.adjustment_id) || !isPositiveSafeId(value.change_id) ||
      value.reservation_id !== reservationId || value.currency !== "USD" || value.entry_role !== role ||
      (value.kind !== "charge" && value.kind !== "credit") || !isFinancialAmount(value.amount) || value.amount <= 0 ||
      (value.settled_at !== null && !isAwareSettlementTimestamp(value.settled_at))) return false;

  if (role === "cancellation_reconciliation") {
    return isPositiveSafeId(value.reconciles_adjustment_id) &&
      value.reconciles_adjustment_id !== value.adjustment_id &&
      value.status === "recorded" && value.settled_at === null;
  }
  if (value.reconciles_adjustment_id !== null) return false;
  if (value.kind === "credit") return value.status === "recorded" && value.settled_at === null;
  return ["pending", "paid", "failed", "voided"].includes(value.status as string) &&
    (value.status === "paid" ? value.settled_at !== null : value.settled_at === null);
}

function isReservationFinancialSummary(value: unknown, reservationId: number): value is ReservationFinancialSummary {
  if (!isRecord(value) || value.reservation_id !== reservationId || value.currency !== "USD" ||
      typeof value.reservation_revision !== "number" || !Number.isInteger(value.reservation_revision) ||
      value.reservation_revision < 0 || value.reservation_revision > 4294967295 ||
      !["confirmed", "cancelled", "completed"].includes(value.reservation_status as string) ||
      (value.latest_change_id !== null && !isPositiveSafeId(value.latest_change_id)) ||
      !isFinancialAmount(value.current_reservation_total) || value.current_reservation_total <= 0 ||
      !isFinancialAmount(value.current_booking_obligation) || value.current_booking_obligation <= 0 ||
      !isFinancialPayment(value.original_booking_payment, reservationId, "booking")) return false;

  const aggregates = ["paid_additional_charges", "pending_additional_charges", "failed_additional_charges",
    "recorded_internal_credits", "outstanding_additional_amount", "voided_additional_charges",
    "reconciliation_credits", "reconciliation_debits", "outstanding_cancellation_amount", "outstanding_booking_amount"];
  if (!aggregates.every((key) => isFinancialAmount(value[key])) ||
      !Array.isArray(value.adjustments) ||
      !value.adjustments.every((entry) => isFinancialAdjustment(entry, reservationId, "price_change")) ||
      !Array.isArray(value.cancellation_reconciliations) ||
      !value.cancellation_reconciliations.every((entry) => isFinancialAdjustment(entry, reservationId, "cancellation_reconciliation"))) return false;

  // Check declared history links without recomputing the backend's financial ledger.
  const adjustments = value.adjustments as AdjustmentDetailResponse[];
  const reconciliations = value.cancellation_reconciliations as AdjustmentDetailResponse[];
  const ids = [...adjustments, ...reconciliations].map((entry) => entry.adjustment_id);
  if (new Set(ids).size !== ids.length ||
      (value.latest_change_id === null && ids.length > 0) ||
      new Set(reconciliations.map((entry) => entry.reconciles_adjustment_id)).size !== reconciliations.length ||
      !reconciliations.every((entry) => adjustments.some((parent) =>
        parent.adjustment_id === entry.reconciles_adjustment_id && parent.change_id === entry.change_id &&
        parent.kind !== entry.kind && parent.amount === entry.amount &&
        (parent.kind === "credit" || parent.status === "paid")))) return false;

  if (value.reservation_status !== "cancelled") {
    return value.cancellation_payment === null && reconciliations.length === 0;
  }
  return isFinancialPayment(value.cancellation_payment, reservationId, "cancellation") &&
    value.cancellation_payment.payment_id !== value.original_booking_payment.payment_id &&
    ["pending", "refunded"].includes(value.original_booking_payment.payment_status);
}

export async function getReservationFinancialSummary(reservationId: number): Promise<ReservationFinancialSummary> {
  if (!isPositiveSafeId(reservationId)) throw new Error("Invalid reservation ID");
  const token = getAccessToken();
  if (!token) throw new ApiError(401);
  const response = await getAuthorizedJson<unknown>(`/bookings/${reservationId}/financial-summary`, token);
  if (!isReservationFinancialSummary(response, reservationId)) {
    throw new Error("Reservation financial summary returned an unexpected response");
  }
  return response;
}

function normalizeReservationChangeReview(value: unknown): Required<ReservationChangeReviewRequest> {
  const fields = ["check_in_date", "check_out_date", "q", "adults", "children", "currency", "gl", "hl"];
  if (!isRecord(value) || Object.keys(value).some((key) => !fields.includes(key)) ||
      typeof value.check_in_date !== "string" || typeof value.check_out_date !== "string" ||
      value.check_in_date.length !== 10 || value.check_out_date.length !== 10 ||
      typeof value.q !== "string" || !value.q.trim() || [...value.q].length > 255 ||
      typeof value.adults !== "number" || !Number.isInteger(value.adults) || value.adults < 1 || value.adults > 20 ||
      typeof value.children !== "number" || !Number.isInteger(value.children) || value.children < 0 || value.children > 20 ||
      (value.currency !== undefined && value.currency !== "USD") ||
      (value.gl !== undefined && value.gl !== "us") || (value.hl !== undefined && value.hl !== "en")) {
    throw new Error("Invalid reservation change review");
  }
  const errors = validateSearchInputs({
    checkIn: value.check_in_date, checkOut: value.check_out_date, guests: String(value.adults),
  });
  if (Object.keys(errors).length > 0) throw new Error("Invalid reservation change review");

  // Copy only the backend's review context; property identity and prices come from the server.
  return {
    check_in_date: value.check_in_date, check_out_date: value.check_out_date, q: value.q.trim(),
    adults: value.adults, children: value.children, currency: "USD", gl: "us", hl: "en",
  };
}

function isPositiveQuoteAmount(value: unknown): value is number {
  return isFinancialAmount(value) && value > 0;
}

function isRevalidatedChangeQuote(
  value: unknown, request: Required<ReservationChangeReviewRequest>,
): value is HotelRevalidationResponse {
  if (!isRecord(value)) return false;
  const nights = (Date.parse(request.check_out_date) - Date.parse(request.check_in_date)) / 86400000;
  return typeof value.property_token === "string" && !!value.property_token.trim() &&
    [...value.property_token].length <= 255 &&
    typeof value.hotel_name === "string" && !!value.hotel_name.trim() && [...value.hotel_name].length <= 255 &&
    value.check_in_date === request.check_in_date && value.check_out_date === request.check_out_date &&
    value.adults === request.adults && value.children === request.children && value.currency === request.currency &&
    isPositiveSafeId(value.number_of_nights) && value.number_of_nights === nights &&
    value.availability === "available" && value.rate_rule === "lowest_eligible_provider_base_total" &&
    typeof value.source === "string" && !!value.source.trim() &&
    isPositiveSafeId(value.guest_capacity) && value.guest_capacity >= request.adults + request.children &&
    isPositiveQuoteAmount(value.current_price_per_night) && isPositiveQuoteAmount(value.provider_base_total) &&
    (value.provider_total_with_taxes_fees === null || isPositiveQuoteAmount(value.provider_total_with_taxes_fees)) &&
    isPositiveQuoteAmount(value.likehome_reservation_total) && isPositiveQuoteAmount(value.likehome_payment_amount) &&
    (value.price_changed === null || typeof value.price_changed === "boolean");
}

function isReservationChangeQuote(
  value: unknown, reservationId: number, request: Required<ReservationChangeReviewRequest>,
): value is ReservationChangeQuoteResponse {
  return isRecord(value) && value.reservation_id === reservationId &&
    typeof value.quote_id === "string" && !!value.quote_id.trim() && [...value.quote_id].length <= 16384 &&
    isAwareSettlementTimestamp(value.expires_at) && value.expires_at.trim() === value.expires_at &&
    Date.parse(value.expires_at) > Date.now() &&
    isRevalidatedChangeQuote(value.quote, request);
}

export async function getReservationChangeQuote(
  reservationId: number, request: ReservationChangeReviewRequest,
): Promise<ReservationChangeQuoteResponse> {
  if (!isPositiveSafeId(reservationId)) throw new Error("Invalid reservation ID");
  const review = normalizeReservationChangeReview(request);
  const token = getAccessToken();
  if (!token) throw new ApiError(401);
  const response = await postAuthorizedJson<unknown, Required<ReservationChangeReviewRequest>>(
    `/bookings/${reservationId}/change-quote`, token, review,
  );
  if (!isReservationChangeQuote(response, reservationId, review)) {
    throw new Error("Reservation change quote returned an unexpected response");
  }
  return response;
}

function hasConfirmationFields(value: unknown, fields: string[]): value is Record<string, unknown> {
  return isRecord(value) && Object.keys(value).length === fields.length &&
    fields.every((key) => Object.prototype.hasOwnProperty.call(value, key));
}

function isConfirmationStay(checkIn: unknown, checkOut: unknown): boolean {
  if (typeof checkIn !== "string" || typeof checkOut !== "string" || checkIn.length !== 10 || checkOut.length !== 10) return false;
  // Validate calendar/order only. Exact committed retries must reach the backend
  // even after stay dates or quote expiry; unconsumed requests are checked there.
  return Object.keys(validateSearchInputs({ checkIn, checkOut, guests: "1" }, "0001-01-01")).length === 0;
}

function reservationChangeConfirmation(value: unknown): ReservationChangeConfirmRequest {
  if (!hasConfirmationFields(value, ["check_in_date", "check_out_date", "quote_id", "accept_quote", "price_per_night", "accepted_payment_amount"]) ||
      typeof value.check_in_date !== "string" || typeof value.check_out_date !== "string" ||
      !isConfirmationStay(value.check_in_date, value.check_out_date) || value.accept_quote !== true ||
      typeof value.quote_id !== "string" || !value.quote_id.trim() || [...value.quote_id].length > 16384 ||
      !isPositiveQuoteAmount(value.price_per_night) || value.price_per_night > 99999999.99 ||
      !isPositiveQuoteAmount(value.accepted_payment_amount) || value.accepted_payment_amount > 99999999.99) {
    throw new Error("Invalid reservation change confirmation");
  }
  // Copy accepted values exactly: no trimming tokens, rounding prices, default
  // acceptance, current-date checks, JWT decoding, or replacement quote requests.
  return {
    check_in_date: value.check_in_date, check_out_date: value.check_out_date, quote_id: value.quote_id,
    accept_quote: value.accept_quote, price_per_night: value.price_per_night,
    accepted_payment_amount: value.accepted_payment_amount,
  };
}

function isReceiptMoney(value: unknown, signed = false): value is string {
  return typeof value === "string" && value.trim() === value &&
    (signed ? /^-?[0-9]+\.[0-9]{2}$/ : /^[0-9]+\.[0-9]{2}$/).test(value);
}

function isReceiptAdjustment(value: unknown): value is ReservationChangeReceiptAdjustment {
  return hasConfirmationFields(value, ["adjustment_id", "kind", "amount", "status"]) &&
    isPositiveSafeId(value.adjustment_id) && isReceiptMoney(value.amount) &&
    ((value.kind === "charge" && value.status === "pending") || (value.kind === "credit" && value.status === "recorded"));
}

function isReservationChangeReceipt(
  value: unknown, reservationId: number, request: ReservationChangeConfirmRequest,
): value is ReservationChangeReceiptResponse {
  return hasConfirmationFields(value, ["change_id", "reservation_id", "revision", "room_type_id", "check_in_date", "check_out_date",
    "reservation_total", "payment_obligation", "previous_payment_obligation", "payment_difference", "booking_payment_id", "booking_payment_status", "adjustment"]) &&
    value.reservation_id === reservationId && isPositiveSafeId(value.change_id) &&
    isPositiveSafeId(value.room_type_id) && isPositiveSafeId(value.booking_payment_id) &&
    isPositiveSafeId(value.revision) && value.revision <= 4294967295 &&
    value.check_in_date === request.check_in_date && value.check_out_date === request.check_out_date &&
    ["reservation_total", "payment_obligation", "previous_payment_obligation"].every((key) => isReceiptMoney(value[key])) &&
    isReceiptMoney(value.payment_difference, true) &&
    (value.booking_payment_status === "pending" || value.booking_payment_status === "paid") &&
    (value.adjustment === null || isReceiptAdjustment(value.adjustment));
}

export async function confirmReservationChange(
  reservationId: number, request: ReservationChangeConfirmRequest,
): Promise<ReservationChangeReceiptResponse> {
  if (!isPositiveSafeId(reservationId)) throw new Error("Invalid reservation ID");
  const confirmation = reservationChangeConfirmation(request);
  const token = getAccessToken();
  if (!token) throw new ApiError(401);
  const response = await postAuthorizedJson<unknown, ReservationChangeConfirmRequest>(
    `/bookings/${reservationId}/change-confirm`, token, confirmation,
  );
  if (!isReservationChangeReceipt(response, reservationId, confirmation)) {
    throw new Error("Reservation change confirmation returned an unexpected response");
  }
  return response;
}

function adjustmentSettlementRequest(value: unknown): AdjustmentSettlementRequest {
  const fields = ["accepted_amount", "reservation_revision", "accept_payment"];
  if (!isRecord(value) || Object.keys(value).length !== fields.length ||
      Object.keys(value).some((key) => !fields.includes(key)) || value.accept_payment !== true ||
      !isFinancialAmount(value.accepted_amount) || value.accepted_amount <= 0 || value.accepted_amount > 99999999.99 ||
      typeof value.reservation_revision !== "number" || !Number.isInteger(value.reservation_revision) ||
      value.reservation_revision < 0 || value.reservation_revision > 4294967295) {
    throw new Error("Invalid adjustment settlement request");
  }
  return { accepted_amount: value.accepted_amount, reservation_revision: value.reservation_revision, accept_payment: value.accept_payment };
}

function settlementCents(value: number): bigint {
  // Match Decimal(str(value)).quantize(0.01, ROUND_HALF_UP) for positive JSON
  // numbers, including exponent notation. Only comparison uses these integers;
  // neither the accepted request nor returned numeric amount is rewritten.
  const [coefficient, exponent = "0"] = String(value).toLowerCase().split("e");
  const [whole, fraction = ""] = coefficient.split(".");
  const digits = BigInt(whole + fraction);
  const shift = Number(exponent) - fraction.length + 2;
  if (shift >= 0) return digits * BigInt(10) ** BigInt(shift);
  const divisor = BigInt(10) ** BigInt(-shift);
  return (digits + divisor / BigInt(2)) / divisor;
}

function isAdjustmentSettlement(
  value: unknown, reservationId: number, adjustmentId: number, acceptedAmount: number,
): value is AdjustmentSettlementResponse {
  const fields = ["adjustment_id", "change_id", "reservation_id", "currency", "entry_role",
    "reconciles_adjustment_id", "kind", "amount", "status", "settled_at"];
  return isRecord(value) && Object.keys(value).length === fields.length &&
    fields.every((key) => Object.prototype.hasOwnProperty.call(value, key)) &&
    value.adjustment_id === adjustmentId && value.reservation_id === reservationId && isPositiveSafeId(value.change_id) &&
    value.currency === "USD" && value.entry_role === "price_change" && value.kind === "charge" && value.status === "paid" &&
    (value.reconciles_adjustment_id === null || isPositiveSafeId(value.reconciles_adjustment_id)) &&
    isFinancialAmount(value.amount) && value.amount > 0 && settlementCents(value.amount) === settlementCents(acceptedAmount) &&
    isAwareSettlementTimestamp(value.settled_at) && value.settled_at.trim() === value.settled_at && !value.settled_at.startsWith("0000-");
}

export async function payReservationChangeAdjustment(
  reservationId: number, adjustmentId: number, request: AdjustmentSettlementRequest,
): Promise<AdjustmentSettlementResponse> {
  if (!isPositiveSafeId(reservationId)) throw new Error("Invalid reservation ID");
  if (!isPositiveSafeId(adjustmentId)) throw new Error("Invalid adjustment ID");
  const acknowledgement = adjustmentSettlementRequest(request);
  const token = getAccessToken();
  if (!token) throw new ApiError(401);
  const response = await postAuthorizedJson<unknown, AdjustmentSettlementRequest>(
    `/bookings/${reservationId}/adjustments/${adjustmentId}/pay`, token, acknowledgement,
  );
  if (!isAdjustmentSettlement(response, reservationId, adjustmentId, acknowledgement.accepted_amount)) {
    throw new Error("Adjustment settlement returned an unexpected response");
  }
  return response;
}
