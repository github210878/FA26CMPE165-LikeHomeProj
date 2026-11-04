
"use client";

import { useCallback, useState } from "react";
import ReservationChangeForm from "@/components/ReservationChangeForm";
import ReservationChangeConfirmation from "@/components/ReservationChangeConfirmation";
import type {
    ReservationChangeConfirmRequest,
    ReservationChangeQuoteResponse,
} from "@/lib/api-types";

type Props = {
    reservationId: number;
    checkInDate: string;
    checkOutDate: string;
    enableConfirmation?: boolean;
    onRefreshCurrent?: (reservationId: number) => Promise<void>;
};

export default function ReservationChangeFlow({
                                                  reservationId,
                                                  checkInDate,
                                                  checkOutDate,
                                                  enableConfirmation = false,
                                                  onRefreshCurrent,
                                              }: Props) {
    const [reviewedQuote, setReviewedQuote] =
        useState<ReservationChangeQuoteResponse | null>(null);

    const handleQuoteReady = useCallback(
        (quote: ReservationChangeQuoteResponse | null) => {
            setReviewedQuote(quote);
        },
        []
    );

    const validQuote =
        reviewedQuote?.reservation_id === reservationId
            ? reviewedQuote
            : null;

    const acceptedRequest: ReservationChangeConfirmRequest | null =
        validQuote
            ? {
                check_in_date: validQuote.quote.check_in_date,
                check_out_date: validQuote.quote.check_out_date,
                quote_id: validQuote.quote_id,
                accept_quote: true,
                price_per_night: validQuote.quote.current_price_per_night,
                accepted_payment_amount:
                validQuote.quote.likehome_payment_amount,
            }
            : null;

    return (
        <div className="space-y-4">
            <ReservationChangeForm
                reservationId={reservationId}
                checkInDate={checkInDate}
                checkOutDate={checkOutDate}
                onQuoteReady={handleQuoteReady}
            />

            {validQuote && !enableConfirmation && (
                <p className="text-sm text-slate-600" role="status">
                    Your new reservation price is available for review.
                    Confirmation is not enabled yet. Your existing booking
                    has not been changed.
                </p>
            )}

            {enableConfirmation && validQuote && acceptedRequest && (
                <ReservationChangeConfirmation
                    reservationId={reservationId}
                    reviewedQuote={validQuote}
                    acceptedRequest={acceptedRequest}
                    onRefreshCurrent={onRefreshCurrent}
                />
            )}
        </div>
    );
}
