# Backend Alignment Workfile

## Current Product Direction

The backend is now centered on:

- company suspicion analysis instead of tender risk labeling
- controlled tender finalization
- paginated company-facing list APIs
- backend-owned pre-award recommendation logic

## Company Suspicion

Suspicion is stored per company in:

- `CompanySuspicionAnalysis`
- `CompanySuspicionReason`

Main scoring dimensions:

- winner price anomaly against market or budget
- failed execution after previous wins
- repeated/consecutive wins
- fake competition patterns

Main response fields exposed on company APIs:

- `suspicionScore`
- `suspicionLevel`
- `suspicionFlags`
- `total_wins`
- `failed_projects`
- `ai_summary`

## Company Registration

Preferred registration route:

- `POST /companies`

Request body:

```json
{
  "company_name": "New Company LLC",
  "username": "new-company-user",
  "password": "strongpass123",
  "email": "team@example.com",
  "first_name": "Ali",
  "last_name": "Karimov"
}
```

Behavior:

- creates `Company`
- creates `User`
- auto-creates `UserProfile`
- links `UserProfile.company`
- returns token login payload

Legacy alias still supported:

- `POST /users`

## Company APIs

- `GET /companies`
- `POST /companies`
- `GET /companies/<companyId>`
- `POST /companies/<companyId>/analyze`
- `GET /risk/stats`
- `GET /risk/flags/<companyId>`
- `POST /risk/analyze/<companyId>`

## Pagination

These list endpoints support DRF page-number pagination:

- `GET /tenders`
- `GET /applications`
- `GET /companies`

Supported query params:

- `page`
- `page_size`

Existing filters still work before pagination:

- `GET /applications?companyId=<companyId>`
- `GET /applications?tenderId=<tenderId>`

Paginated response shape:

```json
{
  "count": 42,
  "next": "http://localhost:8000/tenders?page=3&page_size=6",
  "previous": "http://localhost:8000/tenders?page=1&page_size=6",
  "results": [
    {
      "id": "T-2026-0008",
      "title": "School Computer Procurement 2026"
    }
  ]
}
```

## Tender Finalization Workflow

Backend now enforces a controlled award flow:

1. admin creates a tender with publish-time fields
2. admin may edit those fields before winner finalization
3. admin finalizes one winner
4. all other applications become `Lost` through derived status
5. after finalization, tender editing is locked
6. winner cannot be changed in normal flow

### Publish-Time Tender Fields

- `title`
- `organization`
- `category`
- `budget`
- `average_market_price`
- `deadline`

### Tender APIs

- `GET /tenders`
- `POST /tenders`
- `GET /tenders/<tenderId>`
- `PUT /tenders/<tenderId>`
- `DELETE /tenders/<tenderId>`
- `POST /tenders/<tenderId>/finalize-winner`
- `GET /tenders/<tenderId>/award-risk`

### Tender Update Rule

`PUT /tenders/<tenderId>` returns `409 Conflict` once a winner exists.

Tender responses expose:

- `winnerCompanyId`
- `winnerLocked`
- `status`

### Finalize Winner

Request:

```json
{
  "applicationId": "A-AB12CD34"
}
```

Response:

```json
{
  "tenderId": "T-2026-0008",
  "winnerCompanyId": "c-acme",
  "winnerApplicationId": "A-AB12CD34",
  "locked": true,
  "applications": [
    {
      "id": "A-AB12CD34",
      "status": "Won"
    },
    {
      "id": "A-ZZ99YY88",
      "status": "Lost"
    }
  ]
}
```

## Applications

- `GET /applications`
- `POST /applications`
- `PATCH /applications/<applicationId>/status`

Current rule for status patch:

- can only be used as a pre-finalization winner-selection alias with `status=won`
- if the tender already has a winner, backend returns `409`
- direct `lost` switching is rejected
- frontend should prefer `POST /tenders/<tenderId>/finalize-winner`

## Pre-Award Recommendation

Backend now owns pre-award recommendation logic.

Endpoint:

- `GET /tenders/<tenderId>/award-risk`

Response:

```json
{
  "tenderId": "t-2026-0008",
  "baseline": {
    "source": "average_market_price",
    "amount": "1330000.00"
  },
  "participants": [
    {
      "applicationId": "app-2026-044",
      "companyId": "c-acme",
      "companyName": "Acme Construction",
      "proposedPrice": "1840000.00",
      "priceDeltaPercent": 38,
      "companySuspicionScore": 92,
      "companySuspicionLevel": "HIGH",
      "failedProjects": 3,
      "totalWins": 7,
      "recommendation": "audit_required",
      "recommendationLabel": "Do not award without audit",
      "reasons": [
        {
          "rule": "PRICE_ANOMALY",
          "title": "Price anomaly",
          "description": "Bid is 38% above the baseline.",
          "severity": "critical",
          "points": 35
        }
      ]
    }
  ],
  "generatedAt": "2026-04-26T10:45:00Z"
}
```

### Current Recommendation Inputs

- company suspicion level
- failed projects
- previous total wins
- bid price delta versus market or budget baseline
- unrealistic low bids

### Recommendation Values

- `safe`
- `review`
- `audit_required`

## Award Guard

Winner finalization is blocked for `audit_required` applications.

Protected endpoints:

- `POST /tenders/<tenderId>/finalize-winner`
- `PATCH /applications/<applicationId>/status`

Current error:

```json
{
  "detail": "Audit approval is required before awarding this company."
}
```

There is no override endpoint yet, so this is a hard stop for now.

## Django Admin Alignment

The admin panel was updated to match the API workflow:

- company creation also collects `username` and `password`
- user profile linkage is automatic
- tender bids are read-only in admin
- participants are read-only in admin
- `winner_company`, `status`, and `final_price` are read-only
- finalized tenders lock publish-time fields

This prevents the admin panel from bypassing the same workflow rules as the API.
