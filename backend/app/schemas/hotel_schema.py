from pydantic import BaseModel, Field


class HotelSearchRequest(BaseModel):
    q: str = Field(..., description="Destination / search text, e.g. 'San Jose hotels'")
    check_in_date: str = Field(..., description="YYYY-MM-DD")
    check_out_date: str = Field(..., description="YYYY-MM-DD")
    adults: int = Field(default=2, ge=1, le=20)
    children: int = Field(default=0, ge=0, le=20)
    currency: str = Field(default="USD", max_length=10)
    gl: str = Field(default="us", max_length=5, description="Country code for SerpApi")
    hl: str = Field(default="en", max_length=5, description="Language code for SerpApi")


class HotelRate(BaseModel):
    lowest: str | None = None
    extracted_lowest: float | None = None
    before_taxes_fees: str | None = None
    extracted_before_taxes_fees: float | None = None


class HotelSearchResult(BaseModel):
    """
    A single lightly-shaped property from SerpApi's raw response.
    Full mapping into LikeHome's hotel/property models happens in task 3.1.3.
    """

    name: str | None = None
    property_token: str | None = None
    hotel_class: str | None = None
    overall_rating: float | None = None
    reviews: int | None = None
    rate_per_night: HotelRate | None = None
    total_rate: HotelRate | None = None
    amenities: list[str] | None = None
    thumbnail: str | None = None
    link: str | None = None
    gps_coordinates: dict | None = None


class HotelSearchResponse(BaseModel):
    search_query: str
    check_in_date: str
    check_out_date: str
    result_count: int
    properties: list[HotelSearchResult]
