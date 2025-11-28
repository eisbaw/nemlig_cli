# Nemlig.com API Documentation

## Authentication Flow

The login process requires 3 sequential API calls:

1. **Get XSRF Token** (`/webapi/AntiForgery`)
2. **Get Bearer Token** (`/webapi/Token`)
3. **Login** (`/webapi/login`)

---

## Step 1: Get XSRF Token

Fetches an anti-forgery token required for subsequent requests.

### Request

```http
GET https://www.nemlig.com/webapi/AntiForgery
```

### Headers

```
Accept: application/json, text/plain, */*
Content-Type: application/json
User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36
Device-Size: desktop
Platform: web
Version: 11.201.0
X-Correlation-Id: <uuid4>
```

### Response

```json
{
  "Header": "X-XSRF-TOKEN",
  "Value": "<xsrf-token-value>"
}
```

### Cookies Set

- `XSRF-TOKEN` - Use this value in `X-XSRF-TOKEN` header for login request
- `XSRF-COOKIE-TOKEN` - HttpOnly cookie

---

## Step 2: Get Bearer Token

Fetches a JWT bearer token for authorization.

### Request

```http
GET https://www.nemlig.com/webapi/Token
```

### Headers

Same as Step 1.

### Response

```json
{
  "upgraded": false,
  "access_token": "<jwt-token>",
  "expires_in": 300,
  "refresh_expires_in": 0,
  "token_type": "Bearer",
  "not-before-policy": 0
}
```

**Note:** The JWT token expires in 300 seconds (5 minutes).

---

## Step 3: Login

Authenticates the user with email and password.

### Request

```http
POST https://www.nemlig.com/webapi/login
Content-Type: application/json
```

### Headers

```
Accept: application/json, text/plain, */*
Content-Type: application/json
User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36
Device-Size: desktop
Platform: web
Version: 11.201.0
X-Correlation-Id: <uuid4>
X-XSRF-TOKEN: <value-from-step-1>
Authorization: Bearer <access_token-from-step-2>
Referer: https://www.nemlig.com/login?returnUrl=%2F
```

### Request Body

```json
{
  "Username": "user@example.com",
  "Password": "password123",
  "CheckForExistingProducts": true,
  "DoMerge": true,
  "AppInstalled": false,
  "SaveExistingBasket": false
}
```

### Response (Success - 200)

```json
{
  "RedirectUrl": "/",
  "MergeSuccessful": true,
  "ZipCodeDiffers": false,
  "TimeslotUtc": "2025112816-60-180",
  "DeliveryZoneId": 1,
  "GdprSettings": {
    "NewslettersIntegrationId": 2979713,
    "RecipesIntegrationId": 0,
    "SmsNotificationsIntegrationId": 0,
    "NemligAdsOnSearchEnginesIntegrationId": 2979716,
    "NemligAdsOnOtherSitesIntegrationId": 2979717,
    "SurveysIntegrationId": 2979718
  },
  "IsExternalLogin": false,
  "IsFirstLogin": false,
  "SaveExistingBasket": false,
  "RemovedMealBoxes": []
}
```

### Cookies Set on Successful Login

| Cookie | Purpose | Expiry |
|--------|---------|--------|
| `IVCookieBasketKey` | Basket identifier (UUID) | Session |
| `IVCookieBasketKeyId` | Basket ID (numeric) | Session |
| `.ASPXAUTH` | Authentication cookie | 1 year |
| `XSRF-TOKEN` | New XSRF token for authenticated requests | Session |
| `XSRF-COOKIE-TOKEN` | HttpOnly XSRF cookie | Session |

---

## Example: Python Script

```python
import requests
import uuid

BASE_URL = "https://www.nemlig.com"

def get_common_headers():
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Device-Size": "desktop",
        "Platform": "web",
        "Version": "11.201.0",
        "X-Correlation-Id": str(uuid.uuid4()),
    }

def login(email: str, password: str) -> requests.Session:
    session = requests.Session()
    headers = get_common_headers()

    # Step 1: Get XSRF token
    resp = session.get(f"{BASE_URL}/webapi/AntiForgery", headers=headers)
    resp.raise_for_status()
    xsrf_data = resp.json()
    xsrf_token = xsrf_data["Value"]

    # Step 2: Get Bearer token
    headers["X-Correlation-Id"] = str(uuid.uuid4())
    resp = session.get(f"{BASE_URL}/webapi/Token", headers=headers)
    resp.raise_for_status()
    token_data = resp.json()
    bearer_token = token_data["access_token"]

    # Step 3: Login
    headers["X-Correlation-Id"] = str(uuid.uuid4())
    headers["X-XSRF-TOKEN"] = xsrf_token
    headers["Authorization"] = f"Bearer {bearer_token}"
    headers["Referer"] = f"{BASE_URL}/login?returnUrl=%2F"

    login_payload = {
        "Username": email,
        "Password": password,
        "CheckForExistingProducts": True,
        "DoMerge": True,
        "AppInstalled": False,
        "SaveExistingBasket": False,
    }

    resp = session.post(f"{BASE_URL}/webapi/login", headers=headers, json=login_payload)
    resp.raise_for_status()

    print("Login successful!")
    print(f"Redirect URL: {resp.json().get('RedirectUrl')}")

    return session

if __name__ == "__main__":
    session = login("user@example.com", "password123")

    # Session now contains auth cookies for subsequent requests
    # Example: Get basket
    resp = session.get(f"{BASE_URL}/webapi/basket/GetBasket")
    print(resp.json())
```

---

## Other Useful Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/webapi/user/GetCurrentUser` | GET | Get current user info |
| `/webapi/basket/GetBasket` | GET | Get shopping basket |
| `/webapi/Order/DeliverySpot` | GET | Get delivery time slots |
| `/webapi/v2/AppSettings/Website` | GET | Get app settings |

---

## Search API

The search functionality uses a separate API gateway at `webapi.prod.knl.nemlig.it`.

### Quick Search (Autocomplete)

Returns search suggestions and category matches as user types.

#### Request

```http
GET https://webapi.prod.knl.nemlig.it/searchgateway/api/quick?query=<search-term>&correlationId=<correlation-id>
```

#### Headers

```
Accept: application/json, text/plain, */*
Authorization: Bearer <access_token>
X-Correlation-Id: <uuid4>
Referer: https://www.nemlig.com/
User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36
```

#### Query Parameters

| Parameter | Description |
|-----------|-------------|
| `query` | Search term |
| `correlationId` | Sitecore correlation ID (from app settings) |

#### Response

```json
{
  "SearchQuery": "cocio",
  "Categories": [
    {
      "Name": "Cocio",
      "Url": "/dagligvarer/brands/cocio"
    }
  ],
  "Suggestions": ["cocio", "cocopops", "coconut"]
}
```

---

### Full Search

Returns detailed product results with pagination, facets, and recipes.

#### Request

```http
GET https://webapi.prod.knl.nemlig.it/searchgateway/api/search?query=<search-term>&take=20&skip=0&recipeCount=3&timestamp=<timestamp>&timeslotUtc=<timeslot>&deliveryZoneId=<zone>&includeFavorites=<user-id>&TimeSlotId=<slot-id>
```

#### Headers

Same as Quick Search.

#### Query Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `query` | Search term | `cocio` |
| `take` | Number of results per page | `20` |
| `skip` | Pagination offset | `0` |
| `recipeCount` | Number of recipes to include | `3` |
| `timestamp` | Combined products/Sitecore timestamp | `j0gWvnwu-IP-Qx3wu` |
| `timeslotUtc` | Delivery timeslot | `2025120216-180-1020` |
| `deliveryZoneId` | Delivery zone ID | `1` |
| `includeFavorites` | User ID for favorites | `<user-id>` |
| `TimeSlotId` | Time slot ID | `2111891` |

#### Response

```json
{
  "Products": {
    "Products": [
      {
        "Id": "5070417",
        "Name": "Cocio kakaomælk (dåse)",
        "Brand": "Cocio",
        "Category": "Drikke",
        "SubCategory": "Kakaomælk",
        "Url": "cocio-kakaomaelk-daase-5070417",
        "Price": 119.0,
        "UnitPriceCalc": 9.92,
        "UnitPriceLabel": "kr/stk",
        "Description": "12 x 0,25 l / Classic",
        "PrimaryImage": "https://nemlig.com//scommerce/images/cocio-kakaomaelk-daase.jpg?i=dbnbFqFc/5070417",
        "Availability": {
          "IsDeliveryAvailable": true,
          "IsAvailableInStock": true
        },
        "DiscountItem": false,
        "Favorite": false,
        "Labels": [],
        "Campaign": null
      }
    ],
    "Start": 0,
    "NumFound": 4
  },
  "Facets": {
    "NumFound": 4,
    "SortingList": [
      {"Title": "Ingen valgt", "UrlName": "default", "IsSelected": true},
      {"Title": "Billigst", "UrlName": "price", "IsSelected": false}
    ],
    "FacetGroups": [...]
  },
  "Recipes": [
    {
      "Id": "fd79688d-0b8b-4d63-98f9-57fe94073e29",
      "Name": "Cocioshake med topping",
      "Url": "/opskrifter/cocioshake-topping-98003783",
      "TotalTime": "10 min",
      "NumberOfPersons": 2
    }
  ]
}
```

---

## Basket API

### Add to Basket

Adds a product to the shopping basket.

#### Request

```http
POST https://www.nemlig.com/webapi/basket/AddToBasket
Content-Type: application/json
```

#### Headers

```
Accept: application/json, text/plain, */*
Content-Type: application/json
Authorization: Bearer <access_token>
X-XSRF-TOKEN: <xsrf-token>
X-Correlation-Id: <uuid4>
Device-Size: desktop
Platform: web
Version: 11.201.0
Referer: https://www.nemlig.com/
```

#### Request Body

```json
{
  "ProductId": "701025",
  "quantity": 1,
  "AffectPartialQuantity": false,
  "disableQuantityValidation": false
}
```

| Field | Type | Description |
|-------|------|-------------|
| `ProductId` | string | Product ID (from search results) |
| `quantity` | number | Quantity to add |
| `AffectPartialQuantity` | boolean | For partial quantity items |
| `disableQuantityValidation` | boolean | Skip quantity validation |

#### Response (Success - 200)

Returns the full basket with all items:

```json
{
  "BasketGuid": "e34fc914-f300-46e3-a980-464b0a8e8fe4",
  "InvoiceAddress": {
    "FirstName": "Anders",
    "StreetName": "Vesterbrogade",
    "PostalCode": 1620,
    "PostalDistrict": "København V"
  },
  "DeliveryAddress": { ... },
  "Lines": [
    {
      "Id": "701025",
      "Name": "Cocio kakaomælk",
      "Brand": "Cocio",
      "Quantity": 1,
      "ItemPrice": 23.75,
      "Price": 23.75,
      "PrimaryImage": "https://www.nemlig.com/scommerce/images/cocio-kakaomaelk.jpg?i=ypu7z8Rf/701025",
      "Description": "0,60 l / Classic",
      "Campaign": {
        "MinQuantity": 3,
        "TotalPrice": 68.00,
        "Type": "ProductCampaignMixOffer"
      }
    }
  ],
  "Recipes": []
}
```

---

### Get Basket

Retrieves the current shopping basket with all items and addresses.

#### Request

```http
GET https://www.nemlig.com/webapi/basket/GetBasket
```

#### Headers

Same as Add to Basket.

#### Response (Success - 200)

```json
{
  "BasketGuid": "e34fc914-f300-46e3-a980-464b0a8e8fe4",
  "Id": null,
  "OrderNumber": null,
  "PreviousOrderNumber": null,
  "PreviousBasketGuid": "00000000-0000-0000-0000-000000000000",
  "PreviousBasketId": 0,
  "InvoiceAddress": {
    "FirstName": "Anders",
    "MiddleName": null,
    "LastName": "And",
    "StreetName": "Vesterbrogade",
    "HouseNumber": 42,
    "HouseNumberLetter": "",
    "Floor": "2.",
    "Side": "TV",
    "Door": "",
    "PostalCode": 1620,
    "PostalDistrict": "København V",
    "CompanyName": null,
    "MobileNumber": "+4512345678",
    "PhoneNumber": null,
    "ContactPerson": null,
    "IsEmptyAddress": false,
    "Name": "Anders And"
  },
  "DeliveryAddress": { ... },
  "AddressesAreEqual": false,
  "Recipes": [],
  "Lines": [
    {
      "Id": "5064654",
      "Name": "Black Coffee Blend Supreme",
      "Brand": "Black Coffee Roasters",
      "Category": "Drikke",
      "SubCategory": "Hele kaffebønner",
      "Url": "black-coffee-blend-supreme-5064654",
      "Quantity": 1,
      "ItemPrice": 99.95,
      "Price": 99.95,
      "UnitPrice": "249,87",
      "UnitPriceCalc": 249.88,
      "UnitPriceLabel": "kr./Kg.",
      "Description": "400 g / hele bønner / Black Coffee Roasters",
      "PrimaryImage": "https://www.nemlig.com/scommerce/images/black-coffee-blend-supreme.jpg?i=_wXk7Acc/5064654",
      "DiscountItem": false,
      "DiscountSavings": 0.0,
      "Favorite": false,
      "Labels": ["Produceret i Danmark"],
      "MainGroupName": "Drikke",
      "CategoryPath": "0700000000#Drikke;0701000000#Kaffe, te, kakao;0701000008#Kaffe, hele bønner",
      "ProductSubGroupNumber": "0701000008",
      "ProductSubGroupName": "Kaffe, hele bønner",
      "ProductCategoryGroupNumber": "0701000000",
      "ProductCategoryGroupName": "Kaffe, te, kakao",
      "ProductMainGroupNumber": "0700000000",
      "ProductMainGroupName": "Drikke",
      "ProductAddedTimestamp": 638998494955098908,
      "CampaignAttribute": "Fast mixtilbud",
      "Campaign": {
        "MinQuantity": 2,
        "MaxQuantity": 0,
        "TotalPrice": 180.0,
        "CampaignPrice": 180.0,
        "CampaignUnitPrice": null,
        "Type": "ProductCampaignBuyXForY",
        "Code": "KF",
        "DiscountSavings": 0.0,
        "IntervalStart": "2025-11-30T23:00:00Z",
        "IntervalEnd": "2025-12-07T22:59:59Z",
        "ShowCampaignInterval": false
      },
      "CheckoutHistoricalRecord": {
        "AvailabilityStatus": 0,
        "OrderedQuantity": 0,
        "AdjustedToQuantity": 0,
        "HasAlternativeProducts": false
      },
      "AlternativeProducts": [],
      "RemainingStock": null,
      "BundleItems": [],
      "Score": 10630785.0,
      "ReplacementType": null,
      "SaleBeforeLastSalesDate": 0
    }
  ]
}
```

#### Line Item Fields

| Field | Type | Description |
|-------|------|-------------|
| `Id` | string | Product ID |
| `Name` | string | Product name |
| `Brand` | string | Brand name |
| `Category` | string | Main category |
| `SubCategory` | string | Sub-category |
| `Quantity` | number | Quantity in basket |
| `ItemPrice` | number | Price per item |
| `Price` | number | Total price (quantity × item price) |
| `UnitPriceCalc` | number | Price per unit (kg, liter, etc.) |
| `UnitPriceLabel` | string | Unit label (e.g., "kr./Kg.") |
| `DiscountItem` | boolean | Whether item is discounted |
| `DiscountSavings` | number | Amount saved from discount |
| `Campaign` | object | Campaign/offer details if applicable |
| `Labels` | array | Product labels (e.g., "Øko", "Vegansk") |
| `ProductAddedTimestamp` | number | When item was added to basket |

#### Cookies Set

| Cookie | Purpose |
|--------|---------|
| `IVCookieBasketKey` | Basket GUID identifier |
| `IVCookieBasketKeyId` | Basket numeric ID |

---

### Search Example: Python

```python
def search_products(session: requests.Session, query: str, bearer_token: str) -> dict:
    """Search for products on nemlig.com"""

    # Get app settings for timestamps
    settings_resp = session.get(f"{BASE_URL}/webapi/v2/AppSettings/Website")
    settings = settings_resp.json()

    # Get page settings for timeslotUtc (not available in AppSettings)
    page_resp = session.get(f"{BASE_URL}/?GetAsJson=1&d=1")
    page_settings = page_resp.json().get("Settings", {})

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {bearer_token}",
        "X-Correlation-Id": str(uuid.uuid4()),
        "Referer": "https://www.nemlig.com/",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    }

    # Full search
    search_url = "https://webapi.prod.knl.nemlig.it/searchgateway/api/search"
    search_params = {
        "query": query,
        "take": 20,
        "skip": 0,
        "recipeCount": 0,
        "timestamp": settings.get("CombinedProductsAndSitecoreTimestamp", ""),
        "timeslotUtc": page_settings.get("TimeslotUtc", ""),
        "deliveryZoneId": page_settings.get("DeliveryZoneId", 1),
    }
    search_resp = session.get(search_url, headers=headers, params=search_params)

    return search_resp.json()
```

---

## Checkout API

### Get Credit Cards

Retrieves saved payment cards for the authenticated user.

#### Request

```http
GET https://www.nemlig.com/webapi/Checkout/GetCreditCards
```

#### Headers

Same as other authenticated requests (Authorization, X-Correlation-Id, etc.)

#### Response (Success - 200)

```json
[
  {
    "CardId": 100001,
    "ExternalId": "abc123def456ghi789jkl012mno=",
    "CardExpirationInfo": "2027-06-01T00:00:00",
    "CardExpirationMonth": "06",
    "CardExpirationYear": "27",
    "CardMask": "52340000****1234",
    "CardType": "MasterCard",
    "FeeInPercent": 0.0,
    "IsDefault": true
  },
  {
    "CardId": 100002,
    "ExternalId": "xyz789abc123def456ghi012jkl=",
    "CardExpirationInfo": "2026-03-01T00:00:00",
    "CardExpirationMonth": "03",
    "CardExpirationYear": "26",
    "CardMask": "457100******5678",
    "CardType": "Dankort",
    "FeeInPercent": 0.0,
    "IsDefault": false
  }
]
```

#### Credit Card Fields

| Field | Type | Description |
|-------|------|-------------|
| `CardId` | number | Internal card identifier |
| `ExternalId` | string | External payment provider ID |
| `CardExpirationInfo` | string | Full expiration date (ISO format) |
| `CardExpirationMonth` | string | Expiration month (MM) |
| `CardExpirationYear` | string | Expiration year (YY) |
| `CardMask` | string | Masked card number |
| `CardType` | string | Card type (MasterCard, Dankort, Visa, etc.) |
| `FeeInPercent` | number | Transaction fee percentage |
| `IsDefault` | boolean | Whether this is the default payment card |

---

### Get Card Fees

Calculates transaction fees for payment cards based on order total.

#### Request

```http
GET https://www.nemlig.com/webapi/Checkout/GetCardsFees?total=604.48&ids=100001&ids=100002
```

#### Query Parameters

| Parameter | Description |
|-----------|-------------|
| `total` | Order total amount |
| `ids` | Card IDs (repeatable for multiple cards) |

#### Response (Success - 200)

```json
[
  {
    "CardId": 100001,
    "Amount": 0.0,
    "IsFailed": false,
    "ErrorMessage": null
  },
  {
    "CardId": 100002,
    "Amount": 0.0,
    "IsFailed": false,
    "ErrorMessage": null
  }
]
```

#### Card Fee Fields

| Field | Type | Description |
|-------|------|-------------|
| `CardId` | number | Card identifier |
| `Amount` | number | Fee amount for this card |
| `IsFailed` | boolean | Whether fee calculation failed |
| `ErrorMessage` | string | Error message if calculation failed |

---

### Get Delivery Placements

Retrieves available delivery placement options (where to leave the order).

#### Request

```http
GET https://www.nemlig.com/webapi/Checkout/GetDeliveryPlacements?memberType=0
```

#### Query Parameters

| Parameter | Description |
|-----------|-------------|
| `memberType` | Member type (0 = Private) |

#### Response (Success - 200)

```json
[
  {"Key": "Frontdoor", "Value": "Foran min hoveddør"},
  {"Key": "Backdoor", "Value": "Foran bagdøren/bryggersdøren"},
  {"Key": "Carport", "Value": "I carporten"},
  {"Key": "RoofCover", "Value": "Under halvtaget"},
  {"Key": "Other", "Value": "Andet (besked påkrævet)"}
]
```

#### Placement Options

| Key | Description (Danish) |
|-----|---------------------|
| `Frontdoor` | In front of my front door |
| `Backdoor` | In front of the back door |
| `Carport` | In the carport |
| `RoofCover` | Under the roof cover |
| `Other` | Other (message required) |

---

### Get Delivery Spot (Current Order Info)

Retrieves information about the current pending order/delivery slot.

#### Request

```http
GET https://www.nemlig.com/webapi/Order/DeliverySpot
```

#### Response (Success - 200)

```json
{
  "Id": "12345678",
  "CustomerName": "Anders And",
  "OrderNumber": "1050001234",
  "State": "Reorder",
  "TimeSlot": {
    "Start": "2025-11-25T16:00:00Z",
    "End": "2025-11-25T19:00:00Z"
  },
  "EditDeadline": "2025-11-24T23:00:00Z",
  "Progress": 1.0,
  "DeliveryTime": null,
  "DeliveryInterval": {
    "Start": "0001-01-01T00:00:00Z",
    "End": "9999-12-31T22:59:59Z"
  }
}
```

#### Delivery Spot Fields

| Field | Type | Description |
|-------|------|-------------|
| `Id` | string | Order ID |
| `CustomerName` | string | Customer name |
| `OrderNumber` | string | Order number |
| `State` | string | Order state (e.g., "Reorder") |
| `TimeSlot` | object | Selected delivery time window |
| `EditDeadline` | string | Last time order can be edited |
| `Progress` | number | Order progress (0.0 to 1.0) |
| `DeliveryTime` | string | Actual delivery time (null if not delivered) |
| `DeliveryInterval` | object | Valid delivery interval range |

#### Cookies Set

| Cookie | Purpose |
|--------|---------|
| `IVCookieBasketKey` | Basket GUID identifier |
| `IVCookieBasketKeyId` | Basket numeric ID |

---

### Get Third Party Integrations

Retrieves user preferences for notifications and marketing.

#### Request

```http
GET https://www.nemlig.com/webapi/ThirdPartyIntegrations/GetIntegrations
```

#### Response (Success - 200)

```json
{
  "NewslettersAndSurveysAllowed": true,
  "RecipesAllowed": false,
  "MealboxEmails": false,
  "SmsNotificationsAllowed": false
}
```

#### Integration Fields

| Field | Type | Description |
|-------|------|-------------|
| `NewslettersAndSurveysAllowed` | boolean | User allows newsletters and surveys |
| `RecipesAllowed` | boolean | User allows recipe notifications |
| `MealboxEmails` | boolean | User allows meal box emails |
| `SmsNotificationsAllowed` | boolean | User allows SMS notifications |

---

### Place Order (Logged In)

Submits the order for a logged-in user. This is the main checkout endpoint that finalizes the order.

#### Request

```http
POST https://www.nemlig.com/webapi/Order/PlaceOrderLoggedIn
Content-Type: application/json
```

#### Headers

```
Accept: application/json, text/plain, */*
Content-Type: application/json
Authorization: Bearer <access_token>
X-XSRF-TOKEN: <xsrf-token>
X-Correlation-Id: <uuid4>
Device-Size: desktop
Platform: web
Version: 11.201.0
Referer: https://www.nemlig.com/basket
```

#### Request Body

```json
{
  "Notes": "",
  "UnattendedNotes": "please ring the bell",
  "PlacementMessage": "Frontdoor",
  "DoorCode": "",
  "Password": "<user-password>",
  "ReturnOfBottlesRequested": false,
  "TermsAndConditionsAccepted": true,
  "CheckForOrdersToMerge": true,
  "PaymentCard": 100001,
  "UseMobilePay": false,
  "EmailSubscriptions": {
    "NewslettersAllowed": true,
    "MealboxEmails": false,
    "RecipesAllowed": false,
    "SurveysAllowed": true,
    "SmsNotificationsAllowed": false
  },
  "HasNewsLetterWithOffersSubscription": false,
  "HasNewsLetterWithMealplansSubscription": false
}
```

#### Request Body Fields

| Field | Type | Description |
|-------|------|-------------|
| `Notes` | string | General delivery notes |
| `UnattendedNotes` | string | Notes for unattended delivery |
| `PlacementMessage` | string | Delivery placement key (from GetDeliveryPlacements) |
| `DoorCode` | string | Door code if applicable |
| `Password` | string | User password for verification |
| `ReturnOfBottlesRequested` | boolean | Request bottle return service |
| `TermsAndConditionsAccepted` | boolean | Must be true to place order |
| `CheckForOrdersToMerge` | boolean | Check for existing orders to merge |
| `PaymentCard` | number | Card ID from GetCreditCards |
| `UseMobilePay` | boolean | Use MobilePay instead of card |
| `EmailSubscriptions` | object | Marketing preferences |
| `HasNewsLetterWithOffersSubscription` | boolean | Newsletter with offers |
| `HasNewsLetterWithMealplansSubscription` | boolean | Newsletter with meal plans |

#### Response (Success - 200)

On success, the browser redirects to the order confirmation page with query parameters:

```
/order-confirmation?orderNumber=<order-number>&uniqueId=<basket-guid>&basketId=<basket-id>&openInApp=false
```

#### Cookies Set

| Cookie | Purpose |
|--------|---------|
| `IVCookieBasketKey` | New basket GUID (previous basket becomes the order) |
| `IVCookieBasketKeyId` | New basket ID |

---

### Register Payment Transaction

Registers a new payment transaction after placing an order. Called automatically after PlaceOrderLoggedIn.

#### Request

```http
GET https://www.nemlig.com/webapi/Checkout/RegisterNewPaymentTransaction?useMobilePay=false
```

#### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `useMobilePay` | boolean | Whether MobilePay was used |

#### Headers

Same as PlaceOrderLoggedIn.

#### Response (Success - 200)

Returns payment transaction details (response body not available in capture).

---

### Get Order Summary

Retrieves detailed summary of a completed order. Called on the order confirmation page.

#### Request

```http
GET https://www.nemlig.com/webapi/Order/GetOrderSummary?orderNumber=<order-number>&uniqueId=<unique-id>&basketId=<basket-id>
```

#### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `orderNumber` | string | Order number from confirmation |
| `uniqueId` | string | Basket GUID (becomes order unique ID) |
| `basketId` | number | Original basket ID |

#### Headers

Same as other authenticated requests.

#### Response (Success - 200)

```json
{
  "SavePaymentInfoLink": "Implement this",
  "CreditCardType": "MasterCard",
  "CreditCardNumber": "52340000****1234",
  "PaymentType": "PaymentCard",
  "OrderCreatedDate": {
    "Date": "2025-11-30T00:00:00",
    "Hours": "16",
    "Minutes": "12"
  },
  "OrderDeadlineDate": {
    "Date": "2025-12-01T00:00:00",
    "Hours": "23",
    "Minutes": "59"
  },
  "OrderDeliveryStartTime": {
    "Date": "2025-12-02T00:00:00",
    "Hours": "17",
    "Minutes": "00"
  },
  "OrderDeliveryEndTime": {
    "Date": "2025-12-02T00:00:00",
    "Hours": "20",
    "Minutes": "00"
  },
  "SelectedPaymentInfo": {
    "CardType": "MasterCard",
    "CardNumber": "52340000****1234"
  },
  "TotalVatPrice": 166.84,
  "ReturnOfBottlesRequested": false,
  "VAT": 25.0,
  "Attributes": [],
  "DeliveryType": 0,
  "BasketGuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "Id": "12345679",
  "OrderNumber": "1050001235",
  "PreviousOrderNumber": null,
  "PreviousBasketGuid": null,
  "PreviousBasketId": 0,
  "InvoiceAddress": {
    "FirstName": "Anders",
    "StreetName": "Vesterbrogade",
    "HouseNumber": 42,
    "Floor": "2.",
    "Side": "TV",
    "PostalCode": 1620,
    "PostalDistrict": "København V"
  },
  "DeliveryAddress": { ... },
  "AddressesAreEqual": false,
  "Recipes": [],
  "Lines": [
    {
      "ReplacementType": null,
      "MainGroupName": "Grønt",
      "CategoryPath": "6200000000#Frugt og grønt;6200200000#Frugt og bær",
      "ProductSubGroupNumber": "6200200002",
      "ProductSubGroupName": "Pære",
      "ItemPrice": 25.0,
      "DiscountSavings": 0.0,
      "Quantity": 1,
      "PrimaryImage": "https://www.nemlig.com/scommerce/images/...",
      "CheckoutHistoricalRecord": {
        "AvailabilityStatus": 0,
        "OrderedQuantity": 0,
        "AdjustedToQuantity": 0,
        "HasAlternativeProducts": false
      },
      "AlternativeProducts": [],
      "Id": "5060501",
      "Name": "Pærer Lucas Kæmpe",
      "Category": "Grønt",
      "Brand": "Ørskov",
      "Url": "paerer-lucas-kaempe-5060501",
      "UnitPrice": "6,25",
      "UnitPriceLabel": "kr./Kg.",
      "DiscountItem": false,
      "Description": "4 stk / Danmark / Klasse 1",
      "Price": 25.0,
      "Campaign": null,
      "Labels": null,
      "Favorite": false
    }
  ]
}
```

#### Order Summary Fields

| Field | Type | Description |
|-------|------|-------------|
| `CreditCardType` | string | Card type used for payment |
| `CreditCardNumber` | string | Masked card number |
| `PaymentType` | string | Payment method (PaymentCard, MobilePay) |
| `OrderCreatedDate` | object | When order was placed |
| `OrderDeadlineDate` | object | Last time order can be edited |
| `OrderDeliveryStartTime` | object | Delivery window start |
| `OrderDeliveryEndTime` | object | Delivery window end |
| `TotalVatPrice` | number | Total VAT amount |
| `VAT` | number | VAT percentage (25% in Denmark) |
| `DeliveryType` | number | Delivery type (0 = personal) |
| `Id` | string | Internal order ID |
| `OrderNumber` | string | Display order number |
| `Lines` | array | Order line items |

---

## Page Data API (GetAsJson)

Nemlig.com uses server-side rendering with a `GetAsJson=1` parameter to fetch page data as JSON for SPA navigation.

### Request Pattern

```http
GET https://www.nemlig.com/<page-path>?GetAsJson=1&t=<timeslotUtc>&d=1
```

#### Query Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `GetAsJson` | Flag to return JSON instead of HTML | `1` |
| `t` | Timeslot UTC identifier | `2025120216-180-1020` |
| `d` | Unknown flag (always 1) | `1` |

### Response Structure

```json
{
  "MetaData": {
    "Id": "abea41a3-f951-4fe3-a703-e4b0d7164dfe",
    "Name": "Basket",
    "TemplateName": "Basket page",
    "PageTitle": "Kurv - nemlig.com",
    "MetaDescription": "...",
    "AbsolutePath": "/basket",
    "ResponseCode": 200
  },
  "Settings": {
    "ZipCode": "1620",
    "DeliveryZoneId": 1,
    "TimeslotUtc": "2025120216-180-1020",
    "UserId": "<user-id>",
    "CombinedProductsAndSitecoreTimestamp": "j0gWvnwu-sP8MfX4u"
  },
  "content": [
    {
      "TemplateName": "productlistonerowspot",
      "Heading": "Har du husket det hele?",
      "ProductGroupId": "10040a7d-a9ed-4f0e-b1a2-0febd90427c1",
      "TotalProducts": 44
    }
  ],
  "aside": [
    {
      "TemplateName": "richtextspot",
      "Name": "Trustpilot",
      "Header": "",
      "Text": "<h2>4,6 stjerner på Trustpilot</h2>"
    }
  ]
}
```

### Common Page Paths

| Path | Description |
|------|-------------|
| `/basket` | Shopping cart page |
| `/har-du-husket` | "Have you forgotten?" upsell page |
| `/checkout` | Checkout page |

---

## Product Details API

Product details are fetched using the GetAsJson pattern with the product URL path.

### Request

```http
GET https://www.nemlig.com/<product-url>?GetAsJson=1&t=<timeslotUtc>&d=1
```

#### Example

```http
GET https://www.nemlig.com/cocio-kakaomaelk-701025?GetAsJson=1&t=2025120216-180-1020&d=1
```

### Headers

```
Accept: application/json, text/plain, */*
Authorization: Bearer <access_token>
X-XSRF-TOKEN: <xsrf-token>
X-Correlation-Id: <uuid4>
Device-Size: desktop
Platform: web
Version: 11.201.0
```

### Response

The response follows the standard GetAsJson structure with product-specific content:

```json
{
  "MetaData": {
    "Id": "3437dc67-ff8b-4c33-a875-bf34dc84c8de",
    "Name": "Cocio kakaomælk",
    "TemplateName": "Product Detail Page",
    "PageTitle": "Cocio kakaomælk - nemlig.com",
    "MetaDescription": "Køb Cocio kakaomælk her på nemlig.com...",
    "AbsolutePath": "/cocio-kakaomaelk-701025",
    "ResponseCode": 200,
    "CanonicalUrl": "https://www.nemlig.com/cocio-kakaomaelk-701025"
  },
  "Settings": {
    "ZipCode": "1620",
    "DeliveryZoneId": 1,
    "TimeslotUtc": "2025120216-180-1020",
    "UserId": "<user-id>"
  },
  "content": [
    {
      "TemplateName": "productdetailspot",
      "Id": "701025",
      "Name": "Cocio kakaomælk",
      "Brand": "Cocio",
      "Category": "Drikke",
      "SubCategory": "Kakaomælk",
      "Url": "cocio-kakaomaelk-701025",
      "Price": 23.75,
      "UnitPriceCalc": 39.58,
      "UnitPriceLabel": "kr./l.",
      "Description": "0,60 l / Classic",
      "Text": "<p>Cocio Classic er den originale og elsket af mange...</p>",
      "PrimaryImage": "https://www.nemlig.com/scommerce/images/cocio-kakaomaelk.jpg?i=ypu7z8Rf/701025",
      "Availability": {
        "IsDeliveryAvailable": true,
        "IsAvailableInStock": true,
        "DeliveryAvailabilityMessage": "",
        "StockAvailabilityMessage": ""
      },
      "DiscountItem": false,
      "Favorite": false,
      "Labels": ["Produceret i Danmark"],
      "Campaign": {
        "MinQuantity": 3,
        "MaxQuantity": 0,
        "TotalPrice": 68.0,
        "CampaignPrice": 68.0,
        "Type": "ProductCampaignMixOffer",
        "Code": "FM"
      },
      "Attributes": [
        {"Name": "Smag", "Value": "Classic"},
        {"Name": "Allergener", "Value": "Mælk"},
        {"Name": "Mærkninger", "Value": "Produceret i Danmark"},
        {"Name": "Brand", "Value": "Cocio"},
        {"Name": "Type", "Value": "Kakaomælk"}
      ],
      "Media": [
        {
          "Url": "https://www.nemlig.com/scommerce/images/cocio-kakaomaelk.jpg?i=ypu7z8Rf/701025",
          "IsPrimary": true,
          "MediaType": "image",
          "AltText": "Cocio kakaomælk"
        }
      ],
      "DeclarationLabel": "<div class=\"declaration-label\">...</div>",
      "Declarations": {
        "Ingredients": "...",
        "NutritionFacts": [
          {"Name": "Energi", "Value": "276 kJ / 65 kcal"},
          {"Name": "Fedt", "Value": "1,5 g"},
          {"Name": "Kulhydrat", "Value": "10,3 g"},
          {"Name": "Protein", "Value": "3,1 g"}
        ]
      },
      "RelatedProducts": [...],
      "AlternativeProducts": [...]
    }
  ],
  "aside": [...]
}
```

### Key Product Detail Fields

| Field | Type | Description |
|-------|------|-------------|
| `Id` | string | Product ID |
| `Name` | string | Product name |
| `Brand` | string | Brand name |
| `Text` | string | HTML product description |
| `Price` | number | Current price |
| `UnitPriceCalc` | number | Price per unit |
| `UnitPriceLabel` | string | Unit label (kr./l., kr./kg., etc.) |
| `Attributes` | array | Key-value product attributes |
| `Media` | array | Product images and videos |
| `DeclarationLabel` | string | HTML nutritional label |
| `Declarations` | object | Structured nutritional data |
| `Campaign` | object | Active campaign/offer details |
| `Availability` | object | Stock and delivery availability |
| `RelatedProducts` | array | Similar products |
| `AlternativeProducts` | array | Substitute products |

### Product Attributes

Common attribute names in the `Attributes` array:

| Attribute | Description |
|-----------|-------------|
| `Smag` | Flavor/taste variant |
| `Allergener` | Allergen information |
| `Mærkninger` | Labels/certifications |
| `Brand` | Brand name |
| `Type` | Product type |
| `Oprindelse` | Country of origin |
| `Opbevaring` | Storage instructions |

---

## Order History API

### Get Order History List

Retrieves a paginated list of previous orders.

#### Request

```http
GET https://www.nemlig.com/webapi/order/GetBasicOrderHistory?skip=0&take=10
```

#### Headers

```
Accept: application/json, text/plain, */*
Authorization: Bearer <access_token>
X-XSRF-TOKEN: <xsrf-token>
X-Correlation-Id: <uuid4>
Device-Size: desktop
Platform: web
Version: 11.201.0
```

#### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `skip` | number | Number of orders to skip (pagination offset) |
| `take` | number | Number of orders to return per page |

#### Response (Success - 200)

The response contains an `Orders` array and a `NumberOfPages` field for pagination:

```json
{
  "Orders": [
    {
      "Status": 4,
      "OrderNumber": "2024-12345678",
      "Total": 604.48,
      "SubTotal": 574.48,
      "OrderDate": "2025-11-25T06:07:18Z",
      "Id": 12345678,
      "DeliveryAddress": {
        "FirstName": "Anders",
        "MiddleName": null,
        "LastName": "And",
        "StreetName": "Vesterbrogade",
        "HouseNumber": 42,
        "HouseNumberLetter": "",
        "Floor": "2.",
        "Side": "TV",
        "Door": "",
        "PostalCode": 1620,
        "PostalDistrict": "København V",
        "CompanyName": null,
        "MobileNumber": "+4512345678",
        "PhoneNumber": null,
        "ContactPerson": null,
        "IsEmptyAddress": false,
        "Name": "Anders And"
      },
      "DeliveryTime": {
        "Start": "2025-11-27T17:00:00Z",
        "End": "2025-11-27T20:00:00Z"
      },
      "HasInvoice": true,
      "IsEditable": false,
      "CanRepeat": true,
      "IsMealBox": false
    }
  ],
  "NumberOfPages": 20
}
```

#### Order Status Values

| Status | Description |
|--------|-------------|
| `4` | Delivered |
| `2` | Processing |
| `1` | Pending |

#### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `Orders` | array | Array of order objects |
| `NumberOfPages` | number | Total pages available for pagination |

#### Order Object Fields

| Field | Type | Description |
|-------|------|-------------|
| `Id` | number | Internal order ID (use for GetOrderHistory) |
| `OrderNumber` | string | Display order number (YYYY-XXXXXXXX format) |
| `Status` | number | Order status code |
| `Total` | number | Total order amount including delivery |
| `SubTotal` | number | Order amount excluding delivery (line items total) |
| `OrderDate` | string | When order was placed (ISO 8601) |
| `DeliveryAddress` | object | Delivery address details |
| `DeliveryTime` | object | Delivery window (Start/End times) |
| `HasInvoice` | boolean | Whether invoice is available |
| `IsEditable` | boolean | Whether order can still be modified |
| `CanRepeat` | boolean | Whether order can be repeated |
| `IsMealBox` | boolean | Whether order contains meal boxes |

---

### Get Order Details

Retrieves detailed line items for a specific order.

#### Request

```http
GET https://www.nemlig.com/webapi/v2/order/GetOrderHistory/{orderId}
```

#### Example

```http
GET https://www.nemlig.com/webapi/v2/order/GetOrderHistory/12345678
```

#### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `orderId` | number | Order ID from GetBasicOrderHistory response |

#### Headers

Same as Get Order History List.

#### Response (Success - 200)

The response contains a `Lines` array with all products from the order:

```json
{
  "Lines": [
    {
      "ProductNumber": "5064654",
      "ProductName": "Black Coffee Blend Supreme",
      "Quantity": 2.0,
      "Unit": "Stk.",
      "Description": "400 g / hele bønner / Black Coffee Roasters",
      "AverageItemPrice": 90.0,
      "Amount": 180.0,
      "OriginalAmount": 199.9,
      "GroupName": "Kaffe, hele bønner",
      "MainGroupName": "Drikke",
      "ImageUrl": "https://www.nemlig.com/scommerce/images/black-coffee-blend-supreme.jpg?i=_wXk7Acc/5064654&w=150",
      "ProductUrl": "black-coffee-blend-supreme-5064654",
      "CampaignName": "Fast mixtilbud",
      "HasCampaign": true,
      "IsAdjusted": false,
      "RefundedAmount": 0.0,
      "IsMealBox": false
    },
    {
      "ProductNumber": "5070417",
      "ProductName": "Cocio kakaomælk (dåse)",
      "Quantity": 1.0,
      "Unit": "Stk.",
      "Description": "12 x 0,25 l / Classic",
      "AverageItemPrice": 119.0,
      "Amount": 119.0,
      "OriginalAmount": 119.0,
      "GroupName": "Kakaomælk",
      "MainGroupName": "Drikke",
      "ImageUrl": "https://www.nemlig.com/scommerce/images/cocio-kakaomaelk-daase.jpg?i=dbnbFqFc/5070417&w=150",
      "ProductUrl": "cocio-kakaomaelk-daase-5070417",
      "CampaignName": "",
      "HasCampaign": false,
      "IsAdjusted": false,
      "RefundedAmount": 0.0,
      "IsMealBox": false
    }
  ]
}
```

#### Line Item Fields

| Field | Type | Description |
|-------|------|-------------|
| `ProductNumber` | string | Product ID |
| `ProductName` | string | Product name |
| `Quantity` | number | Quantity ordered |
| `Unit` | string | Unit of measure (Stk., Kg., etc.) |
| `Description` | string | Product description/variant |
| `AverageItemPrice` | number | Price per item (may reflect campaign price) |
| `Amount` | number | Total line amount |
| `OriginalAmount` | number | Original price before discounts |
| `GroupName` | string | Product sub-category |
| `MainGroupName` | string | Product main category |
| `ImageUrl` | string | Product thumbnail URL |
| `ProductUrl` | string | Product page URL path |
| `CampaignName` | string | Campaign name if applicable |
| `HasCampaign` | boolean | Whether item had a campaign discount |
| `IsAdjusted` | boolean | Whether quantity was adjusted (e.g., out of stock) |
| `RefundedAmount` | number | Refund amount if item was adjusted |
| `IsMealBox` | boolean | Whether item is a meal box |

---

## Notes

- All requests go through Cloudflare
- The API uses JWT tokens from Keycloak (`keycloak.mgmt.prod.k8s.nemlig`)
- Bearer tokens expire in 5 minutes, but session cookies (`.ASPXAUTH`) last 1 year
- Always include `X-Correlation-Id` header with a UUID for request tracing
- The `Version` header value may need updating as the app version changes
