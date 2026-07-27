# QP-CRM API v1 — AI Agent Instructions

This document describes how to interact with the QP-CRM REST API for managing products, categories, and brands.

## Base URL

```
http://<server-ip>:5000/api/v1
```

## Authentication

All endpoints (except `/health`) require an API key passed as a Bearer token:

```
Authorization: Bearer <api_key>
```

Get the API key from: **Admin Panel → API Key Management** (or check the server console on first startup).

---

## Endpoints

### Health Check (no auth)

```bash
GET /api/v1/health
```

**Response:**
```json
{"success": true, "message": "API v1 is running", "version": "1.0.0"}
```

---

### Products

#### List/Search Products

```bash
GET /api/v1/products?search=drill&brand=DeWalt&category=Tools&page=1&per_page=25
```

All query parameters are optional.

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "name": "Cordless Drill XR",
      "description": "20V MAX cordless drill",
      "category": "Tools",
      "brand": "DeWalt",
      "photo_path": "cordless_drill_xr.jpg",
      "photo_url": "/api/v1/products/1/photo",
      "current_price": 249.99,
      "current_discount_price": 199.99
    }
  ],
  "pagination": {
    "page": 1,
    "per_page": 25,
    "total": 1,
    "total_pages": 1
  }
}
```

#### Get Single Product

```bash
GET /api/v1/products/1
```

**Response:** Same as above, single object in `data`.

#### Get Product Photo

```bash
GET /api/v1/products/1/photo
```

Returns the image file directly (JPEG).

#### Create Product

**Using JSON (no photo or photo from URL):**
```bash
curl -X POST http://localhost:5000/api/v1/products \
  -H "Authorization: Bearer <key>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "New Product",
    "description": "Product description",
    "category": "Tools",
    "brand": "DeWalt",
    "photo_url": "https://example.com/image.jpg"
  }'
```

**Using multipart (photo file upload):**
```bash
curl -X POST http://localhost:5000/api/v1/products \
  -H "Authorization: Bearer <key>" \
  -F "name=New Product" \
  -F "description=Description" \
  -F "category=Tools" \
  -F "brand=DeWalt" \
  -F "photo=@/path/to/image.jpg"
```

Only `name` is required. Returns `201 Created`.

**Response:** `409 Conflict` if a product with the same name already exists.

#### Update Product

```bash
PUT /api/v1/products/1
```

Same fields as create. Send only the fields you want to update. All fields are optional — omitted fields keep their current values.

```bash
curl -X PUT http://localhost:5000/api/v1/products/1 \
  -H "Authorization: Bearer <key>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Updated Name", "category": "New Category"}'
```

#### Delete Product

```bash
DELETE /api/v1/products/1
```

Deletes the product, all associated prices, and the photo file.

---

### Categories

#### List Categories

```bash
GET /api/v1/categories
GET /api/v1/categories?search=tool
```

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "category": "Tools",
      "import_percent": 0.07,
      "margin_percent": 0.40,
      "domestic_transport": 50.0,
      "default_extras": 0.0,
      "warranty_percent": 0.0,
      "service_percent": 0.0,
      "instalation": 0.0,
      "traning": 0.0,
      "other": 0.0
    }
  ]
}
```

**Note:** Percentage values are stored as fractions (0.07 = 7%). When creating/updating, you can pass either `7` or `0.07` — values > 1.0 are automatically divided by 100.

#### Create/Update Category

```bash
POST /api/v1/categories
Content-Type: application/json

{
  "category": "Tools",
  "import_percent": 7,
  "margin_percent": 40,
  "domestic_transport": 50,
  "default_extras": 0,
  "warranty_percent": 2,
  "service_percent": 5,
  "instalation": 100,
  "traning": 0,
  "other": 0
}
```

Only `category` is required. All other fields default to `0`. If a category with that name already exists, it is updated (upsert behavior).

#### Delete Category

```bash
DELETE /api/v1/categories/Tools
```

Returns `409 Conflict` if any products use this category.

---

### Brands

#### List Brands

```bash
GET /api/v1/brands
GET /api/v1/brands?search=dew
```

**Response:**
```json
{
  "success": true,
  "data": ["DeWalt", "Makita", "Bosch"]
}
```

#### Create Brand

```bash
POST /api/v1/brands
Content-Type: application/json

{"name": "NewBrand"}
```

Duplicate names are silently ignored (returns 201 with the name).

#### Delete Brand

```bash
DELETE /api/v1/brands/NewBrand
```

Returns `409 Conflict` if any products use this brand.

---

### OpenAPI Spec

```bash
GET /api/v1/openapi.json
```

Returns an OpenAPI 3.0 specification that AI tools can use for function-calling/discovery.

---

## Error Responses

All errors follow this format:

```json
{
  "success": false,
  "error": "Human-readable error message"
}
```

| HTTP Status | Meaning |
|-------------|---------|
| 200 | Success |
| 201 | Created |
| 400 | Validation error (missing fields, invalid data) |
| 401 | Missing or malformed Authorization header |
| 403 | Invalid API key |
| 404 | Resource not found |
| 409 | Conflict (duplicate name, resource in use) |

---

## Common Workflows

### Create a product with photo from URL
```bash
curl -X POST http://localhost:5000/api/v1/products \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Hammer Drill", "category": "Tools", "brand": "Bosch", "photo_url": "https://example.com/drill.jpg"}'
```

### Search + update a product
```bash
# Find it
curl -H "Authorization: Bearer $API_KEY" "http://localhost:5000/api/v1/products?search=Hammer"

# Update it
curl -X PUT http://localhost:5000/api/v1/products/5 \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"description": "Updated description", "category": "Power Tools"}'
```

### Create a category with defaults
```bash
curl -X POST http://localhost:5000/api/v1/categories \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"category": "Machines", "import_percent": 5, "margin_percent": 35, "domestic_transport": 100}'
```

---

## Notes for AI Agents

1. **Search is fuzzy**: The `search` parameter on products uses SQL `LIKE '%term%'`, so partial matches work.
2. **Pagination**: Default is 25 items per page, max 500. Use `page` and `per_page` to iterate through large datasets.
3. **Photo upload**: For file uploads, use `multipart/form-data` with field name `photo`. For URL downloads, pass `photo_url` in JSON.
4. **Category/brand names in delete**: URL-encode special characters. The API auto-decodes them.
5. **Duplicate handling**: Product names are case-insensitive unique. Attempting to create a duplicate returns 409.
6. **Percentage values**: When creating categories, pass percentages as you'd naturally write them (e.g., `7` for 7%). The API handles conversion. When reading, values are returned as fractions (e.g., `0.07`).